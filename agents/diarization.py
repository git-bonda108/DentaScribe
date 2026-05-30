"""Diarization Agent — labels each transcript line as Doctor or Patient.

Strategy (MVP):
  1. If the transcript already contains "Doctor:" / "Patient:" prefixes, parse those.
  2. Else, if "Speaker 0/1" prefixes (Deepgram output), use LLM to map to roles.
  3. Else, send to LLM for full attribution.
  4. Demo fallback: alternate Doctor/Patient by line.

Upgrade path: swap in pyannote 3.1 segmentation + use timestamps to slice
Whisper output for ground-truth speaker turns.
"""
import re
from typing import List
from agents.base import Agent
from core.state import SwarmState, TranscriptSegment


SPEAKER_LINE = re.compile(r"^\s*(doctor|dr\.?|dentist|patient|speaker\s*\d+)\s*[:\-]\s*(.+)$",
                          re.IGNORECASE)


class DiarizationAgent(Agent):
    name = "diarization"

    def run(self, state: SwarmState) -> SwarmState:
        if not state.raw_transcript.strip():
            state.log(self.name, "Empty transcript — nothing to diarize", level="warn")
            return state

        # 1) prefix-based parse
        prefix_segments = self._parse_prefixes(state.raw_transcript)
        if prefix_segments and self._is_well_labeled(prefix_segments):
            state.segments = prefix_segments
            state.log(self.name, f"Parsed {len(prefix_segments)} prefix-labelled lines")
            return state

        # 2) LLM-attributed (if available)
        if self.llm and self.llm.available:
            try:
                attributed = self._llm_attribute(state.raw_transcript)
                if attributed:
                    state.segments = attributed
                    state.log(self.name, f"LLM attributed {len(attributed)} turns "
                                         f"via {self.llm.provider}")
                    return state
            except Exception as e:
                state.log(self.name, f"LLM attribution failed: {e}", level="warn")

        # 3) deterministic fallback — alternate by paragraph
        chunks = [c.strip() for c in re.split(r"\n+", state.raw_transcript) if c.strip()]
        segments = []
        for i, chunk in enumerate(chunks):
            spk = "doctor" if i % 2 == 0 else "patient"
            segments.append(TranscriptSegment(speaker=spk, text=chunk))
        state.segments = segments
        state.log(self.name, f"Deterministic fallback over {len(segments)} chunks",
                  level="warn")
        return state

    # ------------------------------------------------------------------
    def _parse_prefixes(self, text: str) -> List[TranscriptSegment]:
        segments: List[TranscriptSegment] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            m = SPEAKER_LINE.match(line)
            if not m:
                # continuation of previous turn
                if segments:
                    segments[-1].text += " " + line
                continue
            label, content = m.group(1).lower(), m.group(2).strip()
            if "patient" in label:
                spk = "patient"
            elif "doctor" in label or "dentist" in label or label.startswith("dr"):
                spk = "doctor"
            else:
                spk = label.replace(" ", "_")  # e.g. "speaker_0"
            segments.append(TranscriptSegment(speaker=spk, text=content))
        return segments

    def _is_well_labeled(self, segs: List[TranscriptSegment]) -> bool:
        labels = {s.speaker for s in segs}
        return ("doctor" in labels and "patient" in labels) and len(segs) >= 2

    def _llm_attribute(self, transcript: str) -> List[TranscriptSegment]:
        system = (
            "You are a clinical transcription editor. Given a dental consultation "
            "transcript that may have ambiguous or numeric speaker labels, attribute "
            "each turn to either 'doctor' or 'patient' based on linguistic cues "
            "(clinical terminology, examination commands, complaints, etc.). "
            "Preserve the original wording verbatim. Output strict JSON."
        )
        user = (
            f"Transcript:\n```\n{transcript}\n```\n\n"
            "Return JSON of the form: "
            "{\"turns\":[{\"speaker\":\"doctor|patient\",\"text\":\"...\"}, ...]}"
        )
        data = self.llm.complete_json(system, user, max_tokens=2000, temperature=0.1)
        out: List[TranscriptSegment] = []
        for t in data.get("turns", []):
            spk = (t.get("speaker") or "").lower()
            if spk not in ("doctor", "patient"):
                spk = "unknown"
            out.append(TranscriptSegment(speaker=spk, text=t.get("text", "").strip()))
        return out
