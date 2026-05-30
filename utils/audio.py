"""Audio preprocessing for robust dental STT.

Stack (run in this order, before any STT engine sees the audio):

  WAV bytes
    │
    ▼ 1. Decode → numpy float32 mono @ original SR
    │
    ▼ 2. High-pass filter @ ~100 Hz  (cuts HVAC rumble, drill hum on the low end)
    │
    ▼ 3. Noise reduction              (spectral gating via noisereduce)
    │
    ▼ 4. Peak normalize → -1 dBFS     (cheap proxy for LUFS; lifts muffled audio)
    │
    ▼ 5. Quality score (RMS + flatness)  ─→ surfaced in trace + UI warning
    │
    ▼ 6. Re-encode → WAV bytes for the STT API
    │
    ▼

Goals tuned for the dental operatory:
  - Distant / muffled mic:   normalization + high-pass usually fix it.
  - Suction or HVAC noise:   stationary, noise reduction handles it well.
  - Drill / handpiece:       high-frequency, non-stationary; noise reduction
                             partly handles. Surface a quality warning.
  - Voice over the mask:     normalization lifts level.

Dependencies:
  - numpy, scipy.signal     (high-pass filter)
  - noisereduce             (spectral gating)
  - stdlib `wave` & `io`    (zero-copy WAV encode/decode)

The pipeline is *defensive*: if any stage fails, we log and pass through the
audio unchanged rather than break STT. STT is the load-bearing thing.
"""
from __future__ import annotations
import io
import wave
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np


# ---------- public types ----------

@dataclass
class AudioQuality:
    """Lightweight signal-quality report. Surfaced in the trace + UI warning."""
    rms_dbfs: float                    # loudness; <-30 dBFS = quiet/muffled
    peak_dbfs: float                   # peak level
    flatness: float                    # spectral flatness 0–1; >0.4 = noisy
    duration_sec: float
    sample_rate: int
    label: str                         # "good" | "fair" | "poor"
    warnings: list[str]

    def to_dict(self) -> dict:
        return {
            "rms_dbfs": round(self.rms_dbfs, 1),
            "peak_dbfs": round(self.peak_dbfs, 1),
            "flatness": round(self.flatness, 3),
            "duration_sec": round(self.duration_sec, 2),
            "sample_rate": self.sample_rate,
            "label": self.label,
            "warnings": self.warnings,
        }


@dataclass
class PreprocessResult:
    wav_bytes: bytes
    quality_before: AudioQuality
    quality_after: AudioQuality
    stages_applied: list[str]


# ---------- core preprocess ----------

# Tunables. Kept conservative — overzealous denoising hurts STT word-error.
HIGHPASS_HZ          = 100.0   # cut HVAC / handpiece rumble below this
NOISE_REDUCE_PROP    = 0.85    # 0–1, how aggressive (1 = full subtract — too harsh)
TARGET_PEAK_DBFS     = -1.0    # leave 1 dB headroom (avoid hard clipping)
TARGET_RMS_DBFS_MIN  = -23.0   # lift below this; pyloudnorm-ish target

# Quality thresholds
RMS_GOOD             = -23.0
RMS_FAIR             = -30.0   # below this, label "poor"
FLATNESS_NOISY       = 0.40


def preprocess_wav(wav_bytes: bytes,
                   highpass: bool = True,
                   denoise: bool = True,
                   normalize: bool = True) -> PreprocessResult:
    """Apply the preprocessing stack to a WAV blob.

    Each stage is wrapped — a failure in one stage doesn't kill the rest.
    Returns the processed WAV plus before/after quality reports.
    """
    stages: list[str] = []
    samples, sr = decode_wav(wav_bytes)
    q_before = analyze(samples, sr)

    if highpass:
        try:
            samples = highpass_filter(samples, sr, cutoff_hz=HIGHPASS_HZ)
            stages.append("highpass")
        except Exception:
            pass

    if denoise:
        try:
            samples = reduce_noise(samples, sr)
            stages.append("denoise")
        except Exception:
            pass

    if normalize:
        try:
            samples = loudness_normalize(samples)
            stages.append("normalize")
        except Exception:
            pass

    q_after = analyze(samples, sr)
    out_bytes = encode_wav(samples, sr)
    return PreprocessResult(
        wav_bytes=out_bytes,
        quality_before=q_before,
        quality_after=q_after,
        stages_applied=stages,
    )


# ---------- stages ----------

def decode_wav(wav_bytes: bytes) -> Tuple[np.ndarray, int]:
    """WAV bytes → (float32 mono samples in [-1, 1], sample_rate)."""
    with io.BytesIO(wav_bytes) as bio, wave.open(bio, "rb") as wf:
        sr = wf.getframerate()
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        frames = wf.readframes(wf.getnframes())
    # Map sample-width to dtype
    if sw == 2:
        dtype = np.int16; scale = 32768.0
    elif sw == 4:
        dtype = np.int32; scale = 2147483648.0
    elif sw == 1:
        dtype = np.int8;  scale = 128.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {sw}")
    a = np.frombuffer(frames, dtype=dtype).astype(np.float32) / scale
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    return a, sr


def encode_wav(samples: np.ndarray, sr: int) -> bytes:
    """float32 mono samples → 16-bit PCM WAV bytes (what STT APIs expect)."""
    s = np.clip(samples, -1.0, 1.0)
    pcm = (s * 32767.0).astype(np.int16).tobytes()
    bio = io.BytesIO()
    with wave.open(bio, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm)
    return bio.getvalue()


def highpass_filter(samples: np.ndarray, sr: int, cutoff_hz: float = HIGHPASS_HZ) -> np.ndarray:
    """4th-order Butterworth high-pass. Cuts rumble that masks consonants."""
    from scipy.signal import butter, sosfiltfilt
    nyq = sr / 2.0
    sos = butter(4, cutoff_hz / nyq, btype="highpass", output="sos")
    return sosfiltfilt(sos, samples).astype(np.float32)


def reduce_noise(samples: np.ndarray, sr: int) -> np.ndarray:
    """Stationary noise reduction via noisereduce (spectral gating).

    For most dental operatory recordings the noise floor is stationary
    (suction motor, HVAC). non-stationary mode handles drill bursts better
    but is slower and over-aggressive on speech — we use stationary mode.
    """
    import noisereduce as nr
    return nr.reduce_noise(
        y=samples, sr=sr,
        stationary=True,
        prop_decrease=NOISE_REDUCE_PROP,
    ).astype(np.float32)


def loudness_normalize(samples: np.ndarray) -> np.ndarray:
    """Bring the signal up so STT engines see a healthy level.

    Strategy:
      1. Peak normalize to TARGET_PEAK_DBFS (avoids clipping).
      2. If RMS is still below TARGET_RMS_DBFS_MIN, apply additional gain
         (but never push the peak past TARGET_PEAK_DBFS).
    Skips DC offsets / weirdness gracefully.
    """
    if samples.size == 0:
        return samples
    peak = float(np.max(np.abs(samples))) + 1e-12
    target_peak = 10 ** (TARGET_PEAK_DBFS / 20.0)
    gain = target_peak / peak
    samples = samples * gain

    rms = float(np.sqrt(np.mean(samples ** 2))) + 1e-12
    rms_dbfs = 20.0 * np.log10(rms)
    if rms_dbfs < TARGET_RMS_DBFS_MIN:
        deficit_db = TARGET_RMS_DBFS_MIN - rms_dbfs
        extra_gain = 10 ** (deficit_db / 20.0)
        boosted = samples * extra_gain
        # Re-check peak; if we'd clip, ratchet back.
        new_peak = float(np.max(np.abs(boosted))) + 1e-12
        if new_peak > target_peak:
            boosted = boosted * (target_peak / new_peak)
        samples = boosted
    return samples.astype(np.float32)


def analyze(samples: np.ndarray, sr: int) -> AudioQuality:
    """Compute RMS / peak / spectral flatness and a coarse label."""
    if samples.size == 0:
        return AudioQuality(0.0, 0.0, 0.0, 0.0, sr, "poor", ["empty audio"])
    rms = float(np.sqrt(np.mean(samples ** 2))) + 1e-12
    peak = float(np.max(np.abs(samples))) + 1e-12
    rms_dbfs = 20.0 * np.log10(rms)
    peak_dbfs = 20.0 * np.log10(peak)
    flat = _spectral_flatness(samples)
    duration = samples.size / float(sr) if sr else 0.0

    warnings: list[str] = []
    if rms_dbfs < RMS_FAIR:
        warnings.append(f"Low input level (RMS {rms_dbfs:.1f} dBFS). Mic may be too far or input gain too low.")
    if flat > FLATNESS_NOISY:
        warnings.append(f"High background noise (spectral flatness {flat:.2f}). Consider quieter environment or noise-canceling mic.")
    if peak_dbfs >= -0.5:
        warnings.append("Clipping detected (peak ≥ -0.5 dBFS).")
    if duration < 0.3:
        warnings.append("Very short recording.")

    if rms_dbfs >= RMS_GOOD and flat <= FLATNESS_NOISY * 0.7 and not warnings:
        label = "good"
    elif rms_dbfs >= RMS_FAIR and flat <= FLATNESS_NOISY:
        label = "fair"
    else:
        label = "poor"

    return AudioQuality(
        rms_dbfs=rms_dbfs, peak_dbfs=peak_dbfs, flatness=flat,
        duration_sec=duration, sample_rate=sr, label=label, warnings=warnings,
    )


def _spectral_flatness(samples: np.ndarray) -> float:
    """Spectral flatness ∈ [0, 1]. 0 = tonal/voice, 1 = white noise.
    Used as a noise-detection proxy.
    """
    if samples.size < 2048:
        return 0.0
    # Hann-windowed magnitude spectrum on a power-of-two chunk
    n = 2 ** int(np.log2(min(samples.size, 16384)))
    s = samples[:n] * np.hanning(n)
    mag = np.abs(np.fft.rfft(s))
    mag = mag[mag > 1e-12]
    if mag.size == 0:
        return 0.0
    geo = np.exp(np.mean(np.log(mag)))
    arith = np.mean(mag)
    return float(geo / arith) if arith > 0 else 0.0
