"""Dental NER Agent — extracts dental entities from the transcript.

Two-tier strategy:
  * Deterministic dictionary match (dental_terms.json) — always runs, fast, no hallucination.
  * LLM enrichment — adds context-aware extraction (tooth numbers tied to
    diagnoses, severity, surfaces) when an LLM is available.
"""
import json
import re
from pathlib import Path
from typing import List, Optional
from agents.base import Agent
from agents.knowledge import DentalKnowledge
from core.state import SwarmState, DentalEntity
from utils.transcript_normalize import normalize_transcript


DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "dental_terms.json"


class DentalNERAgent(Agent):
    name = "dental_ner"

    def __init__(self, cfg, llm=None, knowledge: Optional[DentalKnowledge] = None):
        super().__init__(cfg, llm)
        with open(DATA_PATH) as f:
            self.terms = json.load(f)
        self.kb = knowledge  # optional — used to normalize tooth words → digits

    def run(self, state: SwarmState) -> SwarmState:
        transcript = state.raw_transcript or "\n".join(s.text for s in state.segments)
        if not transcript.strip():
            state.log(self.name, "No text to analyze", level="warn")
            return state

        # Normalize "tooth number nine" → "tooth 9" via knowledge + tooth_norm.
        if self.kb:
            transcript = self.kb.tooth_words_to_numbers(transcript)
        transcript, _ = normalize_transcript(transcript)

        # ---- deterministic pass (always) ----
        ents = self._dict_match(transcript)
        state.log(self.name, f"Dictionary pass found {len(ents)} entities")

        # ---- LLM enrichment (optional) ----
        if self.llm and self.llm.available:
            try:
                ents += self._llm_enrich(transcript)
                state.log(self.name, f"After LLM enrichment: {len(ents)} entities "
                                     f"({self.llm.provider})")
            except Exception as e:
                state.log(self.name, f"LLM enrichment failed: {e}", level="warn")

        state.entities = self._dedupe(ents)
        return state

    # ------------------------------------------------------------------
    def _dict_match(self, text: str) -> List[DentalEntity]:
        out: List[DentalEntity] = []
        low = text.lower()
        # tooth numbers (Universal 1-32)
        for m in re.finditer(r"\btooth\s*(?:number|no\.?|#)?\s*(\d{1,2})\b", low):
            n = m.group(1)
            if 1 <= int(n) <= 32:
                desc = self.terms["teeth_universal"].get(n, "")
                out.append(DentalEntity(kind="tooth", value=f"Tooth {n}",
                                        span=desc, confidence=0.95))
        for kind in ("conditions", "procedures", "medications", "anatomy"):
            for term in self.terms[kind]:
                if re.search(r"\b" + re.escape(term.lower()) + r"\b", low):
                    out.append(DentalEntity(
                        kind=kind.rstrip("s"),
                        value=term,
                        span=term,
                        confidence=0.85,
                    ))
        for phrase in self.terms["symptom_phrases"]:
            if phrase.lower() in low:
                out.append(DentalEntity(kind="symptom", value=phrase,
                                        span=phrase, confidence=0.85))
        return out

    def _llm_enrich(self, transcript: str) -> List[DentalEntity]:
        system = (
            "You are a clinical NER engine specialized in dentistry. Extract entities "
            "ONLY when explicitly grounded in the transcript — do NOT infer or invent. "
            "Categories: tooth, condition, procedure, medication, anatomy, symptom."
        )
        user = (
            f"Transcript:\n```\n{transcript}\n```\n\n"
            "Return JSON: {\"entities\":[{\"kind\":\"...\",\"value\":\"...\","
            "\"span\":\"exact phrase from transcript\",\"confidence\":0.0-1.0}]}"
        )
        data = self.llm.complete_json(system, user, max_tokens=1200, temperature=0.0)
        out: List[DentalEntity] = []
        low = transcript.lower()
        for e in data.get("entities", []):
            span = (e.get("span") or "").strip()
            # Anti-hallucination guard: require the span to appear in the transcript
            if span and span.lower() in low:
                out.append(DentalEntity(
                    kind=(e.get("kind") or "unknown").lower(),
                    value=e.get("value") or span,
                    span=span,
                    confidence=float(e.get("confidence") or 0.7),
                ))
        return out

    @staticmethod
    def _dedupe(ents: List[DentalEntity]) -> List[DentalEntity]:
        seen = set()
        out: List[DentalEntity] = []
        for e in ents:
            key = (e.kind, e.value.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append(e)
        return out
