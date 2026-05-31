"""Live audio streaming buffer for WebRTC → Deepgram → rolling transcript.

Design:
  • streamlit-webrtc delivers PyAV AudioFrames in a background thread.
  • We accumulate frames into ~`window_secs` chunks (default 2 sec).
  • Each chunk is encoded as WAV in-memory and sent to Deepgram via the
    existing `audio.deepgram_stt.transcribe_file()` path (chunked REST).
  • The buffer owns the rolling transcript; the UI just renders state.
  • Thread-safe — frames arrive on the WebRTC thread, drain happens from
    the Streamlit main thread between reruns.

Why chunked REST instead of true Deepgram WebSocket for MVP:
  • One less moving part (no aiortc/websocket bridging).
  • REST returns full-final segments with diarization already applied.
  • Cost is identical (Deepgram charges per second).
  • Latency: ~2s buffer + 0.5–1s REST round-trip = ~3s end-to-end.
    Good enough for a coaching pane; can upgrade to WebSocket in P5.
"""
from __future__ import annotations
import io
import os
import threading
import time
import wave
from dataclasses import dataclass, field
from queue import Queue, Empty
from typing import Optional

import numpy as np


@dataclass
class LiveSegment:
    """A finalized transcript segment from a single chunk."""
    speaker: str       # 'doctor' / 'patient' / 'unknown'
    text: str
    t_start_sec: float = 0.0
    t_end_sec: float = 0.0
    chunk_idx: int = 0


@dataclass
class LiveAudioBuffer:
    """Owns the rolling transcript for a recording session.

    Two operations:
      - `push_frame(frame)`  — called by the WebRTC thread; appends raw audio
      - `drain_chunks()`     — called by the UI thread; if enough audio has
                                accumulated, encodes WAV(s), sends to Deepgram,
                                appends to `segments`, and returns the new
                                segments produced this drain.

    Notes:
      - We deliberately track `last_chunk_at` so the UI / coach trigger logic
        can know when to fire (turn change vs 15s ceiling).
      - `bytes_target` is the byte count for one window at the input sample
        rate; computed lazily once we see the first frame.
    """
    window_secs: float = 2.0
    segments: list[LiveSegment] = field(default_factory=list)
    last_chunk_at: float = 0.0
    chunk_count: int = 0

    # Internal state (not user-facing)
    _frames: list[np.ndarray] = field(default_factory=list)
    _sample_rate: Optional[int] = None
    _channels: int = 1
    _bytes_in_window: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # Total chunks ever processed — used for indexing segments
    @property
    def total_seconds_buffered(self) -> float:
        if not self._sample_rate:
            return 0.0
        with self._lock:
            samples = sum(len(f) for f in self._frames)
        return samples / float(self._sample_rate)

    @property
    def total_transcript_text(self) -> str:
        return "\n".join(f"{s.speaker.title()}: {s.text}" for s in self.segments)

    # ------------------------------------------------------------------
    def push_frame(self, frame) -> None:
        """Accept one PyAV AudioFrame. Thread-safe."""
        try:
            samples = frame.to_ndarray()
            # Frame can be shape (channels, n) or (n,) depending on layout.
            # We collapse to mono float32 in [-1, 1].
            if samples.ndim == 2:
                samples = samples.mean(axis=0)
            samples = samples.astype(np.float32)
            # Common sample formats: int16 → divide by 32768; float already in range.
            if samples.dtype != np.float32 or np.max(np.abs(samples)) > 1.5:
                samples = samples.astype(np.float32) / 32768.0
            with self._lock:
                self._frames.append(samples)
                if self._sample_rate is None:
                    self._sample_rate = int(frame.sample_rate)
        except Exception:
            # Don't let one bad frame kill the recording.
            return

    def has_enough_audio(self) -> bool:
        if not self._sample_rate:
            return False
        with self._lock:
            samples = sum(len(f) for f in self._frames)
        return (samples / float(self._sample_rate)) >= self.window_secs

    # ------------------------------------------------------------------
    def drain_chunks(self) -> list[LiveSegment]:
        """If we have at least one full window, encode + transcribe + append.

        Returns the list of new LiveSegments produced this drain (may be
        empty if there's nothing buffered yet).
        """
        if not self.has_enough_audio():
            return []
        with self._lock:
            samples = np.concatenate(self._frames) if self._frames else np.array([], np.float32)
            self._frames = []
            sr = self._sample_rate

        wav_bytes = _encode_wav(samples, sr)
        new_segs = _transcribe(wav_bytes, self.chunk_count, self.last_chunk_at)
        if new_segs:
            self.segments.extend(new_segs)
            self.chunk_count += 1
            self.last_chunk_at = time.time()
        return new_segs

    def reset(self) -> None:
        with self._lock:
            self._frames = []
            self._sample_rate = None
        self.segments.clear()
        self.last_chunk_at = 0.0
        self.chunk_count = 0


# ===========================================================================
# Internals
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


def _transcribe(wav_bytes: bytes, chunk_idx: int, prev_chunk_time: float) -> list[LiveSegment]:
    """Send one WAV chunk through Deepgram + return LiveSegments."""
    if not wav_bytes:
        return []
    try:
        import tempfile
        from audio.deepgram_stt import transcribe_file, is_available
        if not is_available():
            return []
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
            f.write(wav_bytes)
            path = f.name
        try:
            transcript = transcribe_file(path, preprocess=False)
        finally:
            try: os.unlink(path)
            except Exception: pass
        out = []
        for s in transcript.segments:
            out.append(LiveSegment(
                speaker=s.speaker or "unknown",
                text=s.text,
                t_start_sec=prev_chunk_time,
                t_end_sec=time.time(),
                chunk_idx=chunk_idx,
            ))
        return out
    except Exception:
        return []


# ===========================================================================
# WebRTC audio processor — wires Streamlit-webrtc to our LiveAudioBuffer
# ===========================================================================

def make_audio_processor(buffer: LiveAudioBuffer):
    """Build a `streamlit-webrtc`-compatible AudioProcessor that pushes
    every incoming frame into the given LiveAudioBuffer.

    Returned class is unbound; pass to `webrtc_streamer(audio_processor_factory=...)`.
    """
    from streamlit_webrtc import AudioProcessorBase

    class _Processor(AudioProcessorBase):
        def recv(self, frame):
            buffer.push_frame(frame)
            return frame
    return _Processor
