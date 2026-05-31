"""Dialogue TTS synthesis — ElevenLabs (preferred) + OpenAI TTS fallback.

Goal: convert a "Doctor: ... / Patient: ..." script into a stitched WAV that
sounds like a real two-person consultation, suitable for piping back through
the Deepgram STT path to test the full audio pipeline end-to-end.

Provider resolution:
  1. ElevenLabs if ELEVENLABS_API_KEY is set. Two distinct voices (male
     doctor / female patient by default — overridable via env vars).
  2. OpenAI TTS (`tts-1`) — same voice with role-prefixed prompt; less
     realistic but no extra API key needed.
  3. Raises RuntimeError if neither is configured.

Why two providers:
  - ElevenLabs gives genuinely different speaker timbres, which is what the
    Deepgram diarizer needs to distinguish doctor from patient.
  - OpenAI TTS is the safety net so the demo works on machines that only
    have an OpenAI key.

Output format: 16-bit PCM mono WAV at 24 kHz (Deepgram-friendly).
"""
from __future__ import annotations
import io
import os
import re
import wave
from typing import List, Tuple

import numpy as np


# Default voice IDs. Override via env: ELEVENLABS_VOICE_DOCTOR / _PATIENT.
# These ElevenLabs voice IDs are publicly listed in their default library.
ELEVENLABS_VOICE_DOCTOR_DEFAULT  = "TX3LPaxmHKxFdv7VOQHJ"   # "Liam" — calm male
ELEVENLABS_VOICE_PATIENT_DEFAULT = "EXAVITQu4vr4xnSDxMaL"   # "Bella" — neutral female
ELEVENLABS_MODEL                 = "eleven_turbo_v2_5"     # fast, English-only

# OpenAI TTS fallback voices
OPENAI_VOICE_DOCTOR  = "onyx"
OPENAI_VOICE_PATIENT = "shimmer"
OPENAI_TTS_MODEL     = "tts-1"

TARGET_SR = 24000   # mono 16-bit @ 24 kHz — Deepgram / OpenAI Whisper friendly
INTER_TURN_SILENCE_S = 0.25   # short pause between speakers, feels natural


# ---------- public API ----------

def synthesize_dialogue(script: str) -> Tuple[bytes, str]:
    """Synthesize a Doctor/Patient script into a stitched WAV.

    Returns `(wav_bytes, provider_name)`. Raises RuntimeError if no
    provider is available.
    """
    turns = _parse_dialogue(script)
    if not turns:
        raise ValueError("No 'Doctor:'/'Patient:' lines found in script.")

    if os.getenv("ELEVENLABS_API_KEY"):
        try:
            audio = _synthesize_elevenlabs(turns)
            return _stitch_to_wav(audio), "elevenlabs"
        except Exception as e:
            # Soft fall-through to OpenAI if ElevenLabs fails (404/quota/etc.)
            last_err = e
    else:
        last_err = None

    if os.getenv("OPENAI_API_KEY"):
        audio = _synthesize_openai(turns)
        return _stitch_to_wav(audio), "openai-tts"

    raise RuntimeError(
        "No TTS provider configured. Set ELEVENLABS_API_KEY or OPENAI_API_KEY."
        + (f" ElevenLabs error: {last_err}" if last_err else "")
    )


# ---------- script parsing ----------

_TURN_RE = re.compile(r"^\s*(doctor|patient|dr\.?|provider|pt)\s*[:\-]\s*(.+)$",
                       re.IGNORECASE)


def _parse_dialogue(script: str) -> List[Tuple[str, str]]:
    """Returns list of (role, text). Role normalized to 'doctor' or 'patient'."""
    out: List[Tuple[str, str]] = []
    current_role = None
    current_text: list[str] = []
    for line in (script or "").splitlines():
        m = _TURN_RE.match(line)
        if m:
            if current_role and current_text:
                out.append((current_role, " ".join(current_text).strip()))
            tag = m.group(1).lower()
            current_role = "doctor" if tag.startswith(("doctor", "dr", "prov")) else "patient"
            current_text = [m.group(2).strip()]
        elif line.strip() and current_role:
            current_text.append(line.strip())
    if current_role and current_text:
        out.append((current_role, " ".join(current_text).strip()))
    return [(r, t) for r, t in out if t]


# ---------- ElevenLabs ----------

def _synthesize_elevenlabs(turns: List[Tuple[str, str]]) -> List[np.ndarray]:
    """Return a list of float32 mono @ TARGET_SR audio chunks, one per turn."""
    import requests
    api_key = os.environ["ELEVENLABS_API_KEY"]
    voice_doctor  = os.getenv("ELEVENLABS_VOICE_DOCTOR",  ELEVENLABS_VOICE_DOCTOR_DEFAULT)
    voice_patient = os.getenv("ELEVENLABS_VOICE_PATIENT", ELEVENLABS_VOICE_PATIENT_DEFAULT)

    chunks: List[np.ndarray] = []
    for role, text in turns:
        voice = voice_doctor if role == "doctor" else voice_patient
        # PCM 16-bit @ 24kHz mono → directly compatible with our pipeline.
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
        params = {"output_format": "pcm_24000"}
        body = {
            "text": text,
            "model_id": ELEVENLABS_MODEL,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }
        headers = {"xi-api-key": api_key, "Accept": "audio/pcm", "Content-Type": "application/json"}
        r = requests.post(url, params=params, json=body, headers=headers, timeout=60)
        r.raise_for_status()
        pcm = np.frombuffer(r.content, dtype=np.int16).astype(np.float32) / 32768.0
        chunks.append(pcm)
    return chunks


# ---------- OpenAI TTS fallback ----------

def _synthesize_openai(turns: List[Tuple[str, str]]) -> List[np.ndarray]:
    """OpenAI TTS returns WAV; decode each turn into float32 @ TARGET_SR."""
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    chunks: List[np.ndarray] = []
    for role, text in turns:
        voice = OPENAI_VOICE_DOCTOR if role == "doctor" else OPENAI_VOICE_PATIENT
        resp = client.audio.speech.create(
            model=OPENAI_TTS_MODEL, voice=voice, input=text,
            response_format="wav",
        )
        wav_bytes = resp.read() if hasattr(resp, "read") else resp.content
        chunks.append(_wav_to_float32(wav_bytes))
    return chunks


# ---------- WAV utilities ----------

def _wav_to_float32(wav_bytes: bytes) -> np.ndarray:
    """Decode WAV → mono float32 @ TARGET_SR. Resamples crudely if needed."""
    with io.BytesIO(wav_bytes) as bio, wave.open(bio, "rb") as wf:
        sr = wf.getframerate()
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        frames = wf.readframes(wf.getnframes())
    if sw == 2:
        a = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif sw == 4:
        a = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif sw == 1:
        a = np.frombuffer(frames, dtype=np.int8).astype(np.float32) / 128.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {sw}")
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    if sr != TARGET_SR:
        a = _resample_linear(a, sr, TARGET_SR)
    return a


def _resample_linear(a: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    """Crude linear resampler. Good enough for TTS audio piped into STT."""
    if src_sr == dst_sr or a.size == 0:
        return a
    ratio = dst_sr / src_sr
    new_n = int(round(a.size * ratio))
    x_old = np.linspace(0, 1, a.size, endpoint=False)
    x_new = np.linspace(0, 1, new_n, endpoint=False)
    return np.interp(x_new, x_old, a).astype(np.float32)


def _stitch_to_wav(chunks: List[np.ndarray]) -> bytes:
    """Concatenate per-turn audio with short silent gaps; encode 16-bit WAV."""
    if not chunks:
        return b""
    silence = np.zeros(int(TARGET_SR * INTER_TURN_SILENCE_S), dtype=np.float32)
    pieces: list[np.ndarray] = []
    for i, c in enumerate(chunks):
        pieces.append(c)
        if i < len(chunks) - 1:
            pieces.append(silence)
    sig = np.concatenate(pieces)
    sig = np.clip(sig, -1.0, 1.0)
    pcm = (sig * 32767.0).astype(np.int16).tobytes()

    bio = io.BytesIO()
    with wave.open(bio, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(TARGET_SR)
        wf.writeframes(pcm)
    return bio.getvalue()
