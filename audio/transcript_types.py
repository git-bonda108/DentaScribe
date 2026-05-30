"""Shared transcript types.

A TranscriptSegment is one diarized, timestamped utterance.
A Transcript is the ordered list. Both Deepgram and the offline fallback
emit these so the rest of the system never cares about the STT vendor.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Literal


Speaker = Literal["provider", "patient", "assistant", "unknown"]


@dataclass
class TranscriptSegment:
    speaker: Speaker
    text: str
    start_s: float
    end_s: float
    confidence: float = 1.0
    is_final: bool = True
    speaker_label: str | None = None    # raw Deepgram speaker tag (e.g. "spk_0")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Transcript:
    segments: list[TranscriptSegment] = field(default_factory=list)

    def plain_text(self) -> str:
        return "\n".join(f"{s.speaker.title()}: {s.text}" for s in self.segments)

    def to_dict(self) -> dict:
        return {"segments": [s.to_dict() for s in self.segments]}

    @classmethod
    def from_plain_text(cls, text: str) -> "Transcript":
        """Parse a 'Doctor: ...\nPatient: ...' block back into segments.

        Used by the demo audio loader and the Streamlit 'paste transcript' input.
        """
        segs = []
        t = 0.0
        for line in (text or "").splitlines():
            line = line.strip()
            if not line:
                continue
            speaker: Speaker = "unknown"
            spoken = line
            for prefix, who in [
                ("doctor:", "provider"), ("dr.:", "provider"), ("dentist:", "provider"),
                ("provider:", "provider"), ("hygienist:", "assistant"),
                ("assistant:", "assistant"), ("patient:", "patient"), ("pt:", "patient"),
            ]:
                if line.lower().startswith(prefix):
                    speaker = who   # type: ignore
                    spoken = line[len(prefix):].strip()
                    break
            dur = max(1.5, len(spoken) / 16.0)
            segs.append(TranscriptSegment(
                speaker=speaker, text=spoken, start_s=t, end_s=t + dur,
                confidence=0.95, is_final=True,
            ))
            t += dur + 0.4
        return cls(segments=segs)
