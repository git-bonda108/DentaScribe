"""Tests for audio/tts_synthesis.py — exercises the parts that don't require
a network/API call. The synthesize_dialogue() entrypoint needs a real key,
so we test the script-parsing + WAV-stitching primitives directly.
"""
from __future__ import annotations
import io
import wave

import pathlib, sys
ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np

from audio.tts_synthesis import (
    _parse_dialogue,
    _stitch_to_wav,
    _wav_to_float32,
    _resample_linear,
    TARGET_SR,
    INTER_TURN_SILENCE_S,
)


# ---------- _parse_dialogue ----------

def test_parse_dialogue_basic():
    script = (
        "Doctor: Hi, what brings you in?\n"
        "Patient: Pain on tooth 19.\n"
        "Doctor: Let me take a PA.\n"
    )
    turns = _parse_dialogue(script)
    assert turns == [
        ("doctor",  "Hi, what brings you in?"),
        ("patient", "Pain on tooth 19."),
        ("doctor",  "Let me take a PA."),
    ]


def test_parse_dialogue_handles_multiline_turns():
    script = (
        "Doctor: First sentence.\n"
        "Second sentence on the next line.\n"
        "Patient: My turn.\n"
    )
    turns = _parse_dialogue(script)
    assert len(turns) == 2
    assert turns[0][0] == "doctor"
    assert "First sentence." in turns[0][1]
    assert "Second sentence" in turns[0][1]


def test_parse_dialogue_normalizes_role_aliases():
    # 'Dr', 'Provider', 'Pt' all map to canonical doctor/patient
    script = "Dr: Hi.\nPt: Hello back.\nProvider: How are you?"
    turns = _parse_dialogue(script)
    assert turns[0][0] == "doctor"
    assert turns[1][0] == "patient"
    assert turns[2][0] == "doctor"


def test_parse_dialogue_empty():
    assert _parse_dialogue("") == []
    assert _parse_dialogue("Just narration, no roles.") == []


# ---------- _stitch_to_wav ----------

def test_stitch_to_wav_concatenates_with_silence():
    # Two 1-second sine bursts at 200Hz and 400Hz
    t = np.linspace(0, 1, TARGET_SR, endpoint=False, dtype=np.float32)
    a = 0.3 * np.sin(2 * np.pi * 200 * t)
    b = 0.3 * np.sin(2 * np.pi * 400 * t)
    wav = _stitch_to_wav([a, b])
    assert len(wav) > 0
    # Decode and verify total length = 1s + silence + 1s
    with io.BytesIO(wav) as bio, wave.open(bio, "rb") as wf:
        assert wf.getframerate() == TARGET_SR
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        frames = wf.getnframes()
    expected = int(TARGET_SR * (1.0 + INTER_TURN_SILENCE_S + 1.0))
    assert abs(frames - expected) < 50, f"got {frames} frames, expected ~{expected}"


def test_stitch_to_wav_empty_returns_empty_bytes():
    assert _stitch_to_wav([]) == b""


# ---------- _wav_to_float32 round-trip ----------

def test_wav_to_float32_roundtrip_preserves_signal():
    # Generate a known sine, encode it via _stitch_to_wav, decode it back
    t = np.linspace(0, 0.5, int(TARGET_SR * 0.5), endpoint=False, dtype=np.float32)
    sig = 0.4 * np.sin(2 * np.pi * 300 * t)
    wav = _stitch_to_wav([sig])
    decoded = _wav_to_float32(wav)
    # Decoded length should equal original (no resampling needed)
    assert abs(len(decoded) - len(sig)) < 5
    # Peak amplitude should round-trip within int16 quantization
    assert abs(np.max(np.abs(decoded)) - 0.4) < 0.001


# ---------- _resample_linear ----------

def test_resample_changes_length_proportionally():
    a = np.linspace(-1.0, 1.0, 1000, dtype=np.float32)
    b = _resample_linear(a, 16000, 24000)
    assert abs(len(b) - 1500) < 5  # 1000 * 24000/16000


def test_resample_noop_when_rates_match():
    a = np.arange(100, dtype=np.float32)
    b = _resample_linear(a, 24000, 24000)
    assert np.array_equal(a, b)
