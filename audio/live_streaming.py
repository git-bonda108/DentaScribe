"""Live audio streaming — buffer + Deepgram chunked-REST transcription.

Pattern (the working one):

  • streamlit-webrtc exposes an `audio_receiver` queue we poll from the
    Streamlit thread — NO processor class, NO threading. We pull frames in
    batches inside a `st.fragment(run_every=...)` so the WebRTC widget
    stays mounted across refreshes.
  • Frames accumulate into ~`window_secs` windows (default 1.0s).
  • Each window is encoded as WAV in-memory and sent to Deepgram via
    `audio.deepgram_stt.transcribe_file()`.
  • Buffer state lives in `st.session_state`; UI fragments read & render.

This replaces the old `recv()`-based audio processor — that hook is
unreliable for audio-only WebRTC and runs in a separate thread that doesn't
share state cleanly with Streamlit.
"""
from __future__ import annotations
import io
import os
import time
import wave
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass
class LiveSegment:
    """A finalized transcript segment from a single chunk."""
    speaker: str          # 'doctor' / 'patient' / 'unknown'
    text: str
    chunk_idx: int = 0
    received_at: float = field(default_factory=time.time)


@dataclass
class LiveAudioBuffer:
    """Owns the rolling transcript for a recording session.

    Operations (all called from the Streamlit main thread — no locks needed):
      - `ingest_frames(frames)` — push a batch of PyAV AudioFrames in.
      - `drain_chunks()`        — if a window has accumulated, encode WAV,
                                   send to Deepgram, append segments,
                                   return what was newly produced.

    Diagnostic fields are public so the UI can show "X frames received,
    Y chunks processed" so you can SEE the pipeline working.
    """
    window_secs: float = 1.0
    segments: list[LiveSegment] = field(default_factory=list)

    # Diagnostics — surfaced in the UI strip
    total_frames: int = 0
    total_chunks: int = 0
    last_chunk_at: float = 0.0
    last_error: str = ""

    # Internal frame buffer
    _frames: list[np.ndarray] = field(default_factory=list)
    _sample_rate: Optional[int] = None

    # ------------------------------------------------------------------
    @property
    def total_seconds_buffered(self) -> float:
        if not self._sample_rate:
            return 0.0
        samples = sum(len(f) for f in self._frames)
        return samples / float(self._sample_rate)

    @property
    def total_transcript_text(self) -> str:
        return "\n".join(f"{s.speaker.title()}: {s.text}" for s in self.segments)

    # ------------------------------------------------------------------
    def ingest_frames(self, frames) -> None:
        """Accept a batch of PyAV AudioFrames. Tolerant of empty / bad frames."""
        for frame in frames or []:
            try:
                samples = frame.to_ndarray()
                if samples.ndim == 2:
                    samples = samples.mean(axis=0)
                samples = samples.astype(np.float32)
                # int16 values exceed [-1, 1] — normalize
                if np.max(np.abs(samples)) > 1.5:
                    samples = samples / 32768.0
                self._frames.append(samples)
                self.total_frames += 1
                if self._sample_rate is None:
                    self._sample_rate = int(frame.sample_rate)
            except Exception:
                # Don't let one bad frame kill the stream.
                continue

    def has_enough_audio(self) -> bool:
        if not self._sample_rate:
            return False
        samples = sum(len(f) for f in self._frames)
        return (samples / float(self._sample_rate)) >= self.window_secs

    def drain_chunks(self) -> list[LiveSegment]:
        """If a full window is buffered, encode + transcribe + append.

        Returns the new LiveSegments produced this call (may be empty).
        """
        if not self.has_enough_audio():
            return []
        samples = np.concatenate(self._frames)
        self._frames = []
        sr = self._sample_rate

        wav_bytes = _encode_wav(samples, sr)
        new_segs, err = _transcribe(wav_bytes, self.total_chunks)
        if err:
            self.last_error = err
        if new_segs:
            self.segments.extend(new_segs)
        self.total_chunks += 1
        self.last_chunk_at = time.time()
        return new_segs

    def reset(self) -> None:
        self._frames = []
        self._sample_rate = None
        self.segments.clear()
        self.total_frames = 0
        self.total_chunks = 0
        self.last_chunk_at = 0.0
        self.last_error = ""


# ===========================================================================
# Encoding + STT helpers
# ===========================================================================

def _encode_wav(samples: np.ndarray, sr: int) -> bytes:
    """Encode mono float32 samples as 16-bit PCM WAV."""
    if samples.size == 0 or not sr:
        return b""
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype(np.int16).tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm)
    return buf.getvalue()


def _transcribe(wav_bytes: bytes, chunk_idx: int) -> tuple[list[LiveSegment], str]:
    """Send one WAV chunk through Deepgram + return (segments, error).

    `error` is an empty string on success, otherwise a short message.
    """
    if not wav_bytes:
        return [], "empty wav"
    try:
        import tempfile
        from audio.deepgram_stt import transcribe_file, is_available
        if not is_available():
            return [], "Deepgram not available (key missing or SDK incompatible)"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
            f.write(wav_bytes)
            path = f.name
        try:
            transcript = transcribe_file(path, preprocess=False)
        finally:
            try: os.unlink(path)
            except Exception: pass
        out: list[LiveSegment] = []
        for s in transcript.segments:
            txt = (s.text or "").strip()
            if not txt:
                continue
            out.append(LiveSegment(
                speaker=s.speaker or "unknown",
                text=txt,
                chunk_idx=chunk_idx,
            ))
        return out, ""
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"[:160]
