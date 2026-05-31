"""Live audio streaming — Deepgram WebSocket session.

Why a WebSocket (not chunked REST):
  Deepgram's REST endpoint returns transcripts only when an *utterance* is
  closed (silence boundary). A 1-second clip from WebRTC almost never
  contains an utterance, so REST returns empty results — that's why the
  previous version showed `chunks 7 · segments 0`.

  The WebSocket / Live API is the correct surface for live work:
    • Streams `interim_results` as words are spoken (no silence required).
    • Emits `is_final=true` events when an utterance closes.
    • Supports diarization across the whole conversation, not per-chunk.
    • Sub-second latency from speech to on-screen text.

Architecture:
  • `LiveDeepgramSession` owns one WS connection per recording session.
  • Audio frames from streamlit-webrtc are converted to little-endian
    int16 PCM and pushed to `session.send(bytes)`.
  • Deepgram emits `Transcript` events on its own thread; we marshal them
    into a thread-safe state (segments list + interim text) protected by
    a Lock.
  • The Streamlit fragment reads `session.snapshot()` and renders.

The legacy `LiveAudioBuffer` shape is preserved for the existing test
imports — it's now a thin pointer to the active session's snapshot.
"""
from __future__ import annotations
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# ===========================================================================
# Data shapes — small dataclasses the UI reads from
# ===========================================================================

@dataclass
class LiveSegment:
    """One finalized transcript span (an utterance Deepgram closed)."""
    speaker: str         # 'doctor' | 'patient' | 'unknown'
    text: str
    received_at: float = field(default_factory=time.time)


@dataclass
class LiveSnapshot:
    """Immutable view the UI fragment renders. Cheap to copy."""
    segments: list[LiveSegment]
    interim_text: str
    state: str           # 'idle' | 'connecting' | 'streaming' | 'closed' | 'error'
    frames_sent: int
    bytes_sent: int
    last_error: str

    @property
    def transcript_text(self) -> str:
        """Doctor: ... / Patient: ... rendering. Used by the swarm handoff."""
        return "\n".join(f"{s.speaker.title()}: {s.text}" for s in self.segments)


# ===========================================================================
# LiveDeepgramSession — wraps the Deepgram WebSocket client
# ===========================================================================

class LiveDeepgramSession:
    """Owns ONE Deepgram WebSocket connection. Thread-safe.

    Lifecycle:
      session = LiveDeepgramSession()
      session.start(sample_rate=48000)         # opens WS
      session.send(raw_pcm16_bytes)            # for every audio chunk
      snap = session.snapshot()                # read for UI
      session.stop()                           # closes WS

    All transcript state is protected by `_lock`. Deepgram's callback fires
    on its own thread; we copy values out under the lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._segments: list[LiveSegment] = []
        self._interim_text: str = ""
        self._state: str = "idle"
        self._frames_sent: int = 0
        self._bytes_sent: int = 0
        self._last_error: str = ""
        self._live = None
        self._started_at: float = 0.0
        self._sample_rate: Optional[int] = None

    # ---- public API ----------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._state == "streaming"

    def snapshot(self) -> LiveSnapshot:
        """Thread-safe immutable view."""
        with self._lock:
            return LiveSnapshot(
                segments=list(self._segments),
                interim_text=self._interim_text,
                state=self._state,
                frames_sent=self._frames_sent,
                bytes_sent=self._bytes_sent,
                last_error=self._last_error,
            )

    def start(self, sample_rate: int = 48000) -> bool:
        """Open the WebSocket. Returns True on success.
        Safe to call only when state is idle/closed/error.
        """
        if self._state == "streaming":
            return True
        api_key = os.getenv("DEEPGRAM_API_KEY")
        if not api_key:
            self._set_error("DEEPGRAM_API_KEY not set")
            return False
        try:
            from deepgram import (
                DeepgramClient, DeepgramClientOptions,
                LiveOptions, LiveTranscriptionEvents,
            )
        except ImportError as e:
            self._set_error(f"deepgram-sdk import failed: {e}")
            return False

        try:
            self._set_state("connecting")
            # Keepalive helps avoid timeouts during long silences
            client = DeepgramClient(api_key, DeepgramClientOptions(
                options={"keepalive": "true"},
            ))
            live = client.listen.websocket.v("1")

            # ----- event handlers -----
            def _on_open(_self, *args, **kwargs):
                self._set_state("streaming")

            def _on_transcript(_self, result, **kwargs):
                self._handle_transcript(result)

            def _on_speech_started(_self, *args, **kwargs):
                # could update a UI hint; not currently used
                pass

            def _on_utterance_end(_self, *args, **kwargs):
                # diarization may finalize on utterance_end
                pass

            def _on_close(_self, *args, **kwargs):
                if self._state == "streaming":
                    self._set_state("closed")

            def _on_error(_self, error, **kwargs):
                self._set_error(f"deepgram WS: {error}")

            live.on(LiveTranscriptionEvents.Open, _on_open)
            live.on(LiveTranscriptionEvents.Transcript, _on_transcript)
            live.on(LiveTranscriptionEvents.SpeechStarted, _on_speech_started)
            live.on(LiveTranscriptionEvents.UtteranceEnd, _on_utterance_end)
            live.on(LiveTranscriptionEvents.Close, _on_close)
            live.on(LiveTranscriptionEvents.Error, _on_error)

            options = LiveOptions(
                model=os.getenv("DEEPGRAM_MODEL", "nova-3-medical"),
                language="en-US",
                # Snap on word boundaries; emit interims so the UI feels live.
                interim_results=True,
                smart_format=True,
                punctuate=True,
                # Diarize across the whole session (NOT per chunk).
                diarize=True,
                utterance_end_ms="1000",
                vad_events=True,
                # Tell Deepgram what we're sending — raw PCM 16-bit mono.
                encoding="linear16",
                sample_rate=int(sample_rate),
                channels=1,
            )

            # Dental keyterm boost — same list as the chunked path
            try:
                from audio.deepgram_stt import _selected_keywords
                kws = _selected_keywords()
                if kws:
                    options.keywords = kws
            except Exception:
                pass

            ok = live.start(options)
            if not ok:
                self._set_error("live.start() returned False")
                return False
            self._live = live
            self._sample_rate = int(sample_rate)
            self._started_at = time.time()
            return True

        except Exception as e:
            self._set_error(f"start failed: {type(e).__name__}: {e}")
            return False

    def send(self, pcm16_bytes: bytes) -> None:
        """Push raw 16-bit PCM audio bytes. No-op if not streaming."""
        if not pcm16_bytes:
            return
        if self._state != "streaming" or self._live is None:
            return
        try:
            self._live.send(pcm16_bytes)
            with self._lock:
                self._frames_sent += 1
                self._bytes_sent += len(pcm16_bytes)
        except Exception as e:
            self._set_error(f"send failed: {type(e).__name__}: {e}")

    def stop(self) -> None:
        """Close the WebSocket gracefully."""
        live = self._live
        self._live = None
        if live is not None:
            try:
                live.finish()
            except Exception:
                pass
        self._set_state("closed")

    def reset(self) -> None:
        """Wipe transcript state (call between encounters)."""
        self.stop()
        with self._lock:
            self._segments.clear()
            self._interim_text = ""
            self._state = "idle"
            self._frames_sent = 0
            self._bytes_sent = 0
            self._last_error = ""

    # ---- private --------------------------------------------------------

    def _set_state(self, s: str) -> None:
        with self._lock:
            self._state = s

    def _set_error(self, msg: str) -> None:
        with self._lock:
            self._last_error = msg[:240]
            self._state = "error" if self._state != "streaming" else self._state

    def _handle_transcript(self, result) -> None:
        """Marshal one Deepgram Transcript event into our state."""
        try:
            channel = getattr(result, "channel", None) or {}
            alternatives = getattr(channel, "alternatives", None) or []
            if not alternatives:
                return
            alt = alternatives[0]
            transcript = (getattr(alt, "transcript", "") or "").strip()
            if not transcript:
                return

            is_final = bool(getattr(result, "is_final", False))

            # Speaker — Deepgram puts speaker on each Word. Use the speaker
            # of the first word in this alternative.
            speaker = "unknown"
            words = getattr(alt, "words", None) or []
            if words:
                spk = getattr(words[0], "speaker", None)
                if spk is not None:
                    # Heuristic: speaker 0 = doctor (opens conversation),
                    # speaker 1 = patient. Diarization agent re-attributes
                    # later if needed.
                    speaker = "doctor" if int(spk) == 0 else "patient"

            with self._lock:
                if is_final:
                    self._segments.append(LiveSegment(
                        speaker=speaker, text=transcript,
                    ))
                    self._interim_text = ""
                else:
                    # Interim — replace the rolling text
                    self._interim_text = transcript
        except Exception as e:
            self._set_error(f"transcript handler: {type(e).__name__}: {e}")


# ===========================================================================
# PyAV frame → 16-bit PCM bytes
# ===========================================================================

def frame_to_pcm16_bytes(frame) -> tuple[bytes, int]:
    """Convert one PyAV AudioFrame to mono 16-bit PCM bytes (little-endian).

    Returns (pcm_bytes, sample_rate). On failure returns (b"", 0).
    """
    try:
        samples = frame.to_ndarray()
        if samples.ndim == 2:
            # multi-channel → mono mix-down
            samples = samples.mean(axis=0)

        if samples.dtype == np.int16:
            pcm = samples
        elif samples.dtype == np.int32:
            pcm = (samples >> 16).astype(np.int16)
        elif np.issubdtype(samples.dtype, np.floating):
            # float in [-1, 1] → int16
            pcm = np.clip(samples, -1.0, 1.0)
            pcm = (pcm * 32767.0).astype(np.int16)
        else:
            # Coerce via float
            f = samples.astype(np.float32)
            mx = float(np.max(np.abs(f))) or 1.0
            pcm = (np.clip(f / mx, -1.0, 1.0) * 32767.0).astype(np.int16)

        return pcm.tobytes(), int(frame.sample_rate)
    except Exception:
        return b"", 0


# ===========================================================================
# Legacy LiveAudioBuffer — kept as a thin adapter for code that hasn't
# been migrated yet (some tests / earlier UI imports referenced it).
# Prefer LiveDeepgramSession directly.
# ===========================================================================

@dataclass
class LiveAudioBuffer:
    """Adapter that exposes the old field names but is backed by a
    LiveDeepgramSession when one is provided.
    """
    window_secs: float = 1.0
    session: Optional[LiveDeepgramSession] = None

    @property
    def segments(self):
        snap = self.session.snapshot() if self.session else None
        return snap.segments if snap else []

    @property
    def total_frames(self):
        snap = self.session.snapshot() if self.session else None
        return snap.frames_sent if snap else 0

    @property
    def total_chunks(self):
        # In WS mode "chunks" doesn't apply; use frames sent / 50 as a proxy.
        snap = self.session.snapshot() if self.session else None
        return (snap.frames_sent // 50) if snap else 0

    @property
    def total_seconds_buffered(self):
        return 0.0    # no buffering in WS mode

    @property
    def last_error(self):
        snap = self.session.snapshot() if self.session else None
        return snap.last_error if snap else ""

    @property
    def total_transcript_text(self):
        snap = self.session.snapshot() if self.session else None
        return snap.transcript_text if snap else ""

    def reset(self) -> None:
        if self.session:
            self.session.reset()

    # Kept for source compatibility with the previous draft code; in WS
    # mode there's nothing to drain — Deepgram pushes us results.
    def has_enough_audio(self) -> bool: return False
    def drain_chunks(self) -> list: return []
    def ingest_frames(self, frames) -> None:
        if not self.session:
            return
        for f in frames or []:
            pcm, sr = frame_to_pcm16_bytes(f)
            if pcm and self.session._state == "streaming":
                self.session.send(pcm)
            elif pcm and self.session._state == "idle":
                # Lazy-start on the first real frame so we know the sample rate
                if self.session.start(sample_rate=sr or 48000):
                    self.session.send(pcm)
