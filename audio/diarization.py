"""Provider vs patient labeling from raw diarized speaker tags.

Deepgram returns speaker tags like spk_0, spk_1. We map them to provider/patient
using two heuristics layered together:

1. **Provider lexicon match** — speakers whose utterances contain dentist-y phrases
   ("let me take a look", "I'll use lidocaine", "the PA shows") score higher as provider.
2. **Question/imperative ratio** — providers ask more questions and give more directives.

The speaker with the higher provider-score is labeled `provider`, the other `patient`.
Additional speakers (hygienist, parent) are labeled `assistant`.
"""
from __future__ import annotations
import re
from collections import defaultdict
from audio.transcript_types import Transcript, TranscriptSegment


PROVIDER_PHRASES = [
    r"\blet me\b", r"\bwe('| )ll\b", r"\bI('| )ll\b",
    r"\btake a look\b", r"\blook at\b", r"\bthe PA\b", r"\bx[- ]?ray\b",
    r"\bbitewing\b", r"\blidocaine\b", r"\bcarpule\b", r"\bcomposite\b",
    r"\bcrown\b", r"\bcaries\b", r"\bocclusal\b", r"\bmesial\b", r"\bdistal\b",
    r"\bpulp\b", r"\broot canal\b", r"\bendo(dontic)?\b", r"\bgingiv",
    r"\btooth (number )?\b\d+", r"\bthe (upper|lower)\b",
    r"\bplan is\b", r"\brecommend\b", r"\bopen wide\b", r"\bdoes that hurt\b",
]
PATIENT_PHRASES = [
    r"\bit hurts\b", r"\bI feel\b", r"\bmy tooth\b", r"\bI('| )?ve had\b",
    r"\bthrobbing\b", r"\bsore\b", r"\bouch\b", r"\bsensitive\b",
    r"\byes\b", r"\bno\b", r"\bokay\b", r"\bI take\b", r"\bI('| )?m on\b",
]


def _score(text: str, patterns: list[str]) -> int:
    t = text.lower()
    return sum(1 for p in patterns if re.search(p, t))


def assign_roles(transcript: Transcript) -> Transcript:
    """Mutates segment.speaker in place based on speaker_label clustering."""
    if not transcript.segments:
        return transcript

    # If speakers are already labelled provider/patient (e.g. from_plain_text), keep them.
    already = {s.speaker for s in transcript.segments}
    if already and already.issubset({"provider", "patient", "assistant"}):
        return transcript

    # Group by speaker_label or fallback to raw speaker field
    groups: dict[str, list[TranscriptSegment]] = defaultdict(list)
    for seg in transcript.segments:
        key = seg.speaker_label or seg.speaker or "unknown"
        groups[key].append(seg)

    scored: dict[str, dict[str, int]] = {}
    for key, segs in groups.items():
        joined = " ".join(s.text for s in segs)
        scored[key] = {
            "provider": _score(joined, PROVIDER_PHRASES),
            "patient": _score(joined, PATIENT_PHRASES),
            "question_count": joined.count("?"),
            "n_segs": len(segs),
        }

    # Pick the top-2 most-talkative groups as provider/patient candidates
    ranked = sorted(groups.keys(), key=lambda k: scored[k]["n_segs"], reverse=True)
    top_two = ranked[:2]

    if len(top_two) == 2:
        a, b = top_two
        a_score = scored[a]["provider"] - scored[a]["patient"] + scored[a]["question_count"]
        b_score = scored[b]["provider"] - scored[b]["patient"] + scored[b]["question_count"]
        if a_score >= b_score:
            role_for = {a: "provider", b: "patient"}
        else:
            role_for = {a: "patient", b: "provider"}
    elif len(top_two) == 1:
        role_for = {top_two[0]: "provider"}
    else:
        role_for = {}

    for seg in transcript.segments:
        key = seg.speaker_label or seg.speaker or "unknown"
        seg.speaker = role_for.get(key, "assistant")  # type: ignore
    return transcript
