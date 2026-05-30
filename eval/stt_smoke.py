"""STT pipeline smoke test — TTS roundtrip.

Generates synthetic audio from a fixture transcript (via OpenAI TTS), pipes
the audio through the full STT stack (preprocess → STT → phonetic correction),
and measures how much of the original dental vocabulary survives.

This is a TRUTH-BY-CONSTRUCTION test: the input "audio" is clean, so we expect
high accuracy. It validates the wiring, not robustness to real-world muffled
audio (that's P3.5, when you record real conversations).

  CLI: python -m eval.stt_smoke
       python -m eval.stt_smoke --fixture demo-001
       python -m eval.stt_smoke --voice alloy
       python -m eval.stt_smoke --no-preprocess     # skip the audio preprocessing
"""
from __future__ import annotations
import argparse
import io
import os
import re
import sys
import wave
from pathlib import Path
from typing import List, Tuple

from core.config import load_config
from agents.orchestrator import Orchestrator
from utils.fixtures import DEMO_TRANSCRIPTS


# ---------- key dental terms we care about preserving through TTS→STT ----------

_DENTAL_TARGETS = {
    "periapical", "composite", "endodontic", "root canal", "crown", "veneer",
    "amoxicillin", "ibuprofen", "chlorhexidine", "lidocaine",
    "periodontal", "scaling", "prophylaxis", "fluoride", "varnish",
    "occlusal", "buccal", "lingual", "mesial", "distal",
    "caries", "gingivitis", "periodontitis", "calculus", "pulpitis",
    "molar", "premolar", "incisor", "canine",
    "cracked-tooth", "saliva", "operculum", "bruxism",
}


def transcript_for_tts(transcript: str) -> str:
    """Strip 'Doctor:' / 'Patient:' prefixes; TTS reads the role aloud otherwise."""
    out = []
    for line in transcript.splitlines():
        line = re.sub(r"^(Doctor|Patient|Speaker\s*\d+)\s*[:\-]\s*", "", line, flags=re.IGNORECASE)
        out.append(line.strip())
    return " ".join(s for s in out if s)


def synthesize_speech(text: str, voice: str, openai_client) -> bytes:
    """OpenAI TTS → WAV bytes."""
    resp = openai_client.audio.speech.create(
        model="tts-1",          # smaller / faster than tts-1-hd; fine for smoke
        voice=voice,
        input=text,
        response_format="wav",
    )
    # The 1.x SDK exposes .content; the streaming context isn't needed here.
    return resp.read() if hasattr(resp, "read") else resp.content


# ---------- scoring ----------

def find_terms_in(text: str, terms: List[str]) -> set:
    """Case-insensitive 'is this term mentioned in this text?' check."""
    low = text.lower()
    out = set()
    for t in terms:
        if t.lower() in low:
            out.add(t)
    return out


def word_overlap(a: str, b: str) -> float:
    """Token-overlap Jaccard. Rough proxy for transcript similarity."""
    ta = set(re.findall(r"[a-zA-Z]{3,}", a.lower()))
    tb = set(re.findall(r"[a-zA-Z]{3,}", b.lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# ---------- main ----------

def run(fixture_id: str = None, voice: str = "alloy", preprocess: bool = True,
        post_correct: bool = True) -> int:
    cfg = load_config()
    if not cfg.openai_api_key:
        print("OPENAI_API_KEY is required to synthesize speech via TTS.")
        return 2

    fixtures = [f for f in DEMO_TRANSCRIPTS if not fixture_id or f["id"] == fixture_id]
    if not fixtures:
        print(f"No fixture matched id={fixture_id!r}")
        return 2

    from openai import OpenAI
    openai_client = OpenAI(api_key=cfg.openai_api_key)
    swarm = Orchestrator(cfg)

    overall_pass = True
    print(f"\nSTT smoke (voice={voice}, preprocess={preprocess}, post_correct={post_correct})")
    print(f"STT engine: {cfg.stt_provider} ({cfg.whisper_model if cfg.stt_provider=='openai' else cfg.deepgram_model})\n")

    for f in fixtures:
        text = transcript_for_tts(f["transcript"])
        # TTS has length limits; the demo fixtures are short enough not to hit them.
        print(f"--- {f['id']}  {f['patient_name']}  ({len(text)} chars) ---")

        wav_bytes = synthesize_speech(text, voice, openai_client)
        # OpenAI's TTS WAV header reports a corrupt `nframes`; derive
        # duration from the raw byte length instead (mono 16-bit assumed).
        sr, dur = 24000, len(wav_bytes) / (24000 * 2)
        try:
            with io.BytesIO(wav_bytes) as bio, wave.open(bio, "rb") as wf:
                sr = wf.getframerate()
                bytes_per_sec = sr * wf.getsampwidth() * wf.getnchannels()
                dur = len(wav_bytes) / max(bytes_per_sec, 1)
        except Exception:
            pass
        print(f"  Synthesized  {len(wav_bytes)} bytes, ~{dur:.1f}s @ {sr} Hz")

        # Run through full STT stack
        recovered = swarm.transcribe_audio(wav_bytes)

        # Audio quality + corrections
        q = swarm.transcriber.last_quality or {}
        if "before" in q:
            qb, qa = q["before"], q["after"]
            print(f"  Audio QA     before={qb.get('label')} ({qb.get('rms_dbfs')} dBFS) "
                  f"-> after={qa.get('label')} ({qa.get('rms_dbfs')} dBFS); stages={q.get('stages')}")
        elif "error" in q:
            print(f"  Audio QA     {q['error']}")
        cr = swarm.transcriber.last_correction_report or {}
        if cr.get("count"):
            print(f"  Corrections  {cr['count']}: {[c['from']+'->'+c['to'] for c in cr['corrections'][:5]]}")

        # Score: did the dental vocabulary survive the round trip?
        original_targets = find_terms_in(text, list(_DENTAL_TARGETS))
        recovered_targets = find_terms_in(recovered, list(_DENTAL_TARGETS))
        kept = original_targets & recovered_targets
        lost = original_targets - recovered_targets
        recall = len(kept) / max(len(original_targets), 1)
        overlap = word_overlap(text, recovered)

        ok = recall >= 0.80 and overlap >= 0.40
        overall_pass = overall_pass and ok
        mark = "✓ PASS" if ok else "✗ FAIL"
        print(f"  Dental recall  {len(kept)}/{len(original_targets)} = {recall:.2f}")
        print(f"  Word overlap   {overlap:.2f}  (rough proxy for fidelity)")
        if lost:
            print(f"  Lost terms     {sorted(lost)[:8]}")
        print(f"  {mark}\n")

    print("STT smoke result:", "PASS" if overall_pass else "FAIL")
    return 0 if overall_pass else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval.stt_smoke")
    ap.add_argument("--fixture", default=None)
    ap.add_argument("--voice", default="alloy",
                    choices=["alloy", "ash", "coral", "echo", "fable", "onyx", "nova", "shimmer", "verse"])
    ap.add_argument("--no-preprocess", action="store_true")
    ap.add_argument("--no-correct", action="store_true")
    args = ap.parse_args(argv)
    return run(fixture_id=args.fixture, voice=args.voice,
               preprocess=not args.no_preprocess,
               post_correct=not args.no_correct)


if __name__ == "__main__":
    sys.exit(main())
