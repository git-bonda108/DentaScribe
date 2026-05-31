"""Deepgram STT wrapper with three execution modes.

1. **Demo / no key**:  `transcribe_demo(text)` — synthesizes a Transcript from a
   pasted "Doctor: ... Patient: ..." block. The Streamlit UI uses this when
   `DEEPGRAM_API_KEY` is absent, so sales demos always run.

2. **File / non-streaming**: `transcribe_file(path)` — for the 2 prerecorded
   client-demo recordings. Uses Deepgram's pre-recorded REST endpoint with
   diarization + dental keyword boost.

3. **Live / streaming**:  `stream_microphone()` — async generator that yields
   interim + final `TranscriptSegment`s as Deepgram's websocket emits them.
   The Streamlit UI in batch 6 renders interim text in grey and final text in
   black for the live conversation feed.

The keyword boost list comes from `core.glossary_loader.asr_keywords()` so the
glossary is the single source of truth for dental vocabulary boosting.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import AsyncIterator

from audio.transcript_types import Transcript, TranscriptSegment
from audio.diarization import assign_roles

try:
    from deepgram import DeepgramClient, PrerecordedOptions, LiveOptions, LiveTranscriptionEvents
    _HAS_DEEPGRAM = True
except ImportError:
    DeepgramClient = None  # type: ignore
    _HAS_DEEPGRAM = False


# Boost weight applied to every keyword. Deepgram tops out at ~50 keywords per
# request with reliable boost; we cap to the most important terms.
KEYWORD_BOOST_INTENSITY = 1.5
MAX_KEYWORDS = 50


def _selected_keywords() -> list[str]:
    """Top dental keywords to boost (anatomy, procedures, drugs)."""
    try:
        from core.glossary_loader import asr_keywords
        kw = asr_keywords()
    except Exception:
        kw = []
    # Hard priority order — sliced if Deepgram quota is hit
    priority = [
        "occlusal", "mesial", "distal", "buccal", "lingual", "incisal",
        "caries", "pulpitis", "periodontitis", "gingivitis", "abscess",
        "composite", "amalgam", "endodontic", "extraction", "crown", "bridge",
        "lidocaine", "articaine", "septocaine", "mepivacaine", "epinephrine",
        "bitewing", "periapical", "ibuprofen", "amoxicillin", "chlorhexidine",
        "carpule", "bicuspid", "molar", "incisor", "canine", "premolar",
    ]
    seen, out = set(), []
    for k in priority + kw:
        if k and k.lower() not in seen:
            out.append(k)
            seen.add(k.lower())
        if len(out) >= MAX_KEYWORDS:
            break
    return out


def is_available() -> bool:
    return _HAS_DEEPGRAM and bool(os.getenv("DEEPGRAM_API_KEY"))


# ---------- 1) demo / paste mode ----------

def transcribe_demo(text: str, post_correct: bool = True) -> Transcript:
    """Build a Transcript from a pasted Doctor/Patient text block.

    `post_correct=True` (default) runs the dental glossary's ASR-corrections
    dictionary + phonetic fuzzy correction over each segment. Demo input is
    typically clean prose, but this keeps the demo path symmetric with
    the live audio path so users see corrections fire when they paste
    realistic STT mishears.
    """
    transcript = Transcript.from_plain_text(text or "")
    if post_correct and transcript.segments:
        try:
            from audio.post_correction import correct_segments
            audit = correct_segments(transcript.segments)
            if audit:
                transcript.corrections = audit  # type: ignore[attr-defined]
        except Exception:
            pass
    return transcript


# ---------- 2) file / non-streaming mode ----------

def transcribe_file(audio_path: str, model: str = "nova-2-medical",
                    preprocess: bool = True) -> Transcript:
    """Transcribe a prerecorded file with diarization + dental keyword boost.

    `preprocess=True` (default) runs the audio through `utils.audio.preprocess_wav`
    BEFORE sending to Deepgram. This is the muffled / distant / noisy-operatory
    win: high-pass @ 100 Hz, spectral-gating denoise, peak/RMS normalization,
    and a spectral-flatness quality score. The Transcript carries the
    quality report so the UI can warn on poor input.

    Falls back to a demo transcript if Deepgram is unavailable.
    """
    if not is_available():
        # No key/no SDK: return empty so the caller can fall back to demo paste.
        return Transcript(segments=[])

    with open(audio_path, "rb") as f:
        buffer = f.read()

    quality_report: dict | None = None
    if preprocess:
        try:
            from utils.audio import preprocess_wav
            res = preprocess_wav(buffer)
            buffer = res.wav_bytes
            quality_report = {
                "before": res.quality_before.to_dict(),
                "after":  res.quality_after.to_dict(),
                "stages": res.stages_applied,
            }
        except Exception:
            # Non-WAV input (webm / ogg / mp3) or scipy/noisereduce missing —
            # silently fall through. Deepgram handles those formats natively.
            pass

    client = DeepgramClient(os.getenv("DEEPGRAM_API_KEY"))
    options = PrerecordedOptions(
        model=model,
        language="en-US",
        smart_format=True,
        punctuate=True,
        diarize=True,
        utterances=True,
        keywords=[f"{k}:{KEYWORD_BOOST_INTENSITY}" for k in _selected_keywords()],
    )
    resp = client.listen.rest.v("1").transcribe_file({"buffer": buffer}, options)
    transcript = _parse_prerecorded(resp.to_dict())

    # Post-STT lexical / phonetic correction against the dental glossary.
    # Runs in-place on each segment's text; aggregated audit attached to
    # the Transcript for the trace / UI.
    try:
        from audio.post_correction import correct_segments
        correction_audit = correct_segments(transcript.segments)
        if correction_audit:
            transcript.corrections = correction_audit  # type: ignore[attr-defined]
    except Exception:
        pass

    if quality_report is not None:
        # Stash on the Transcript so callers can surface it in the UI/trace.
        transcript.audio_quality = quality_report  # type: ignore[attr-defined]
    return transcript


def _parse_prerecorded(resp: dict) -> Transcript:
    """Extract diarized utterances from Deepgram's prerecorded JSON."""
    segs: list[TranscriptSegment] = []
    utterances = (resp.get("results", {}) or {}).get("utterances") or []
    for u in utterances:
        segs.append(TranscriptSegment(
            speaker="unknown",
            text=u.get("transcript", "").strip(),
            start_s=float(u.get("start", 0.0)),
            end_s=float(u.get("end", 0.0)),
            confidence=float(u.get("confidence", 0.0)),
            is_final=True,
            speaker_label=f"spk_{u.get('speaker', 0)}",
        ))
    t = Transcript(segments=segs)
    return assign_roles(t)


# ---------- 3) live / streaming mode ----------

async def stream_microphone(audio_iter, model: str = "nova-2-medical") -> AsyncIterator[TranscriptSegment]:
    """Stream from a mic / browser audio iterator and yield TranscriptSegments.

    `audio_iter` is any async iterator yielding raw PCM bytes (16k/16-bit mono).
    The Streamlit UI provides this via `streamlit-mic-recorder` or webrtc.

    Yields interim segments (is_final=False) and final segments (is_final=True).
    Final segments carry diarized speaker tags Deepgram emits.
    """
    if not is_available():
        return

    client = DeepgramClient(os.getenv("DEEPGRAM_API_KEY"))
    connection = client.listen.asynclive.v("1")
    queue: asyncio.Queue[TranscriptSegment | None] = asyncio.Queue()

    async def _on_message(_, result, **__):
        try:
            alt = result.channel.alternatives[0]
            text = (alt.transcript or "").strip()
            if not text:
                return
            speaker_idx = None
            if alt.words:
                speaker_idx = getattr(alt.words[0], "speaker", None)
            seg = TranscriptSegment(
                speaker="unknown", text=text,
                start_s=float(result.start), end_s=float(result.start + result.duration),
                confidence=float(alt.confidence or 0.0),
                is_final=bool(result.is_final),
                speaker_label=f"spk_{speaker_idx}" if speaker_idx is not None else None,
            )
            await queue.put(seg)
        except Exception:
            return

    async def _on_close(*_, **__):
        await queue.put(None)

    connection.on(LiveTranscriptionEvents.Transcript, _on_message)
    connection.on(LiveTranscriptionEvents.Close, _on_close)

    options = LiveOptions(
        model=model, language="en-US",
        smart_format=True, punctuate=True,
        diarize=True, interim_results=True,
        encoding="linear16", sample_rate=16000, channels=1,
        keywords=[f"{k}:{KEYWORD_BOOST_INTENSITY}" for k in _selected_keywords()],
    )
    await connection.start(options)

    async def _pump():
        async for chunk in audio_iter:
            await connection.send(chunk)
        await connection.finish()

    pump_task = asyncio.create_task(_pump())
    try:
        while True:
            seg = await queue.get()
            if seg is None:
                break
            yield seg
    finally:
        pump_task.cancel()
