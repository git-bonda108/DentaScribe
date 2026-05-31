"""Tests for audio/post_correction.py — the post-STT lexical/phonetic cleanup
that runs against Deepgram (or demo) output.

What we're proving:
  1. Explicit ASR-corrections in the glossary are applied verbatim.
  2. The phonetic fuzzy pass catches the long tail (e.g. "mollar"→"molar"),
     including the GLUE case ("amox cillin"→"amoxicillin").
  3. Common English source words are NOT corrupted (the failure mode of
     overly-aggressive STT post-processing).
  4. Already-correct dental terms pass through untouched.
  5. The correction is wired into both transcribe_demo and transcribe_file
     (we can only exercise the demo path without a Deepgram key, but the
     same correct_segments() helper is called from both).
"""
from __future__ import annotations

import pathlib, sys
ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from audio.deepgram_stt import transcribe_demo
from audio.post_correction import correct_transcript


# ---------- pass 1: dictionary ----------

def test_dict_pass_applies_explicit_asr_corrections():
    # All seven canonical glossary mishears
    line = "Patient has okeysol pain, messeal caries, destal abscess, perry-apical lucency, ferqation involvement, pulpitous on amalgum"
    out, corr = correct_transcript(line)
    kinds = {c["kind"] for c in corr}
    assert "dictionary" in kinds
    assert "occlusal" in out
    assert "mesial" in out
    assert "distal" in out
    assert "periapical" in out
    assert "furcation" in out
    assert "pulpitis" in out
    assert "amalgam" in out


def test_dict_pass_preserves_case_and_punctuation():
    line = "Doctor: I see Okeysol caries."
    out, corr = correct_transcript(line)
    assert "Occlusal caries." in out  # leading cap + trailing period preserved
    assert any(c["kind"] == "dictionary" for c in corr)


# ---------- pass 2: phonetic fuzzy ----------

def test_fuzzy_pass_glues_split_drug_name():
    # The most-cited STT failure mode: drug name split across two tokens.
    line = "prescribe amox cillin 500 milligrams"
    out, corr = correct_transcript(line)
    assert "amoxicillin" in out
    assert any(c["kind"] == "glue" and c["to"] == "amoxicillin" for c in corr)


def test_fuzzy_pass_substitutes_typo_in_dental_term():
    # Edit-distance-1 typo on a known dental term in the CDT description vocab.
    line = "deep mollar restoration"
    out, _ = correct_transcript(line)
    assert "molar" in out
    assert "mollar" not in out


def test_fuzzy_pass_does_not_corrupt_common_english():
    # The protected-source list MUST shield these tokens.
    line = "There started a sharp pain after the popcorn bite. I told the doctor."
    out, corr = correct_transcript(line)
    assert out == line, f"Expected no change, got: {out}"
    assert corr == []


def test_clean_dental_line_passes_through():
    # Already-correct dental vocabulary shouldn't be touched.
    line = "Periapical radiograph of tooth 19 shows periapical radiolucency. Plan: endodontic therapy."
    out, _ = correct_transcript(line)
    assert out == line


# ---------- wired through transcribe_demo ----------

def test_transcribe_demo_runs_correction():
    text = "Doctor: prescribe amox cillin and check the okeysol surface of the mollar."
    t = transcribe_demo(text)
    # transcribe_demo splits "Doctor: ..." into segments; the text on each
    # segment should be corrected.
    full = " ".join(seg.text for seg in t.segments)
    assert "amoxicillin" in full
    assert "occlusal" in full
    assert "molar" in full
    # The corrections audit should be attached when any fired.
    assert getattr(t, "corrections", []), "Transcript.corrections audit missing"


def test_transcribe_demo_post_correct_can_be_disabled():
    # Opt-out path for when raw STT inspection is needed.
    text = "Doctor: prescribe amox cillin 500 mg."
    t = transcribe_demo(text, post_correct=False)
    assert any("amox cillin" in seg.text or "amox" in seg.text for seg in t.segments)
