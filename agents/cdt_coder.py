"""CDT Coder Agent — stage 1 deterministic candidate selection.

Stage 2 (LLM re-rank + rationale) happens inside SoapNoteAgent when an LLM
is available. This agent NEVER invents codes outside the catalog.
"""
import json
import re
from pathlib import Path
from typing import List, Optional

from agents.base import Agent
from agents.knowledge import DentalKnowledge
from core.soap_schema import cdt_allow_list
from core.state import SwarmState, CDTSuggestion


DATA = Path(__file__).resolve().parent.parent / "data" / "cdt_codes_2026.json"

KEYWORD_MAP = {
    "cleaning":           ["D1110", "D1120"],
    "prophylaxis":        ["D1110", "D1120"],
    "fluoride varnish":   ["D1206"],
    "fluoride":           ["D1208", "D1206"],
    "sealant":            ["D1351"],
    "scaling and root planing": ["D4341", "D4342"],
    "scaling":            ["D4341", "D4346"],
    "root planing":       ["D4341", "D4342"],
    "periodontal maintenance": ["D4910"],
    "composite":          ["D2330", "D2331", "D2391", "D2392", "D2393", "D2394"],
    "filling":            ["D2330", "D2391"],
    "restoration":        ["D2330", "D2391"],
    "amalgam":            ["D2140", "D2150"],
    "crown":              ["D2740", "D2750"],
    "veneer":             ["D2960", "D2962"],
    "root canal":         ["D3310", "D3320", "D3330"],
    "endodontic":         ["D3310", "D3320", "D3330"],
    "pulp cap":           ["D3110"],
    "pulpotomy":          ["D3220", "D3221"],
    "extraction":         ["D7140", "D7210"],
    "wisdom tooth":       ["D7220", "D7230", "D7240"],
    "third molar":        ["D7220", "D7230", "D7240"],
    "panoramic":          ["D0330"],
    "bitewing":           ["D0274"],
    "periapical":         ["D0220", "D0230"],
    "x-ray":              ["D0220", "D0274", "D0330"],
    "radiograph":         ["D0220", "D0274", "D0330"],
    "comprehensive evaluation": ["D0150"],
    "periodic evaluation": ["D0120"],
    "limited evaluation":  ["D0140"],
    "saliva test":         ["D0426"],
    "cracked-tooth test":  ["D0461"],
    "cracked tooth test":  ["D0461"],
    "night guard":         ["D9944", "D9945"],
    "occlusal guard":      ["D9944", "D9945"],
    "palliative":          ["D9110"],
    "nitrous oxide":       ["D9230"],
}


class CdtCoderAgent(Agent):
    name = "cdt_coder"

    def __init__(self, cfg, llm=None, knowledge: Optional[DentalKnowledge] = None):
        super().__init__(cfg, llm)
        with open(DATA) as f:
            self.catalog = json.load(f)
        self.by_code = {c["code"]: c for c in self.catalog["codes"]}
        self.kb = knowledge or DentalKnowledge()

    def run(self, state: SwarmState) -> SwarmState:
        transcript_text = state.raw_transcript or "\n".join(s.text for s in state.segments)
        haystack = transcript_text + " \n " + (state.soap.plan or "") + " " + (state.soap.assessment or "")

        kb_hits = self.kb.find_cdt_candidates(haystack, top_n=14)
        candidate_codes: List[str] = [h["code"] for h in kb_hits]
        evidence: dict[str, list[str]] = {h["code"]: [f"kb_score={h['score']}"] for h in kb_hits}

        for kw, codes in KEYWORD_MAP.items():
            if re.search(r"\b" + re.escape(kw) + r"\b", haystack.lower()):
                for code in codes:
                    if code not in candidate_codes:
                        candidate_codes.append(code)
                    evidence.setdefault(code, []).append(kw)

        allow = set(cdt_allow_list(state.visit_type))
        if allow:
            filtered = [c for c in candidate_codes if c in allow]
            if filtered:
                candidate_codes = filtered
            else:
                state.log(self.name,
                          f"visit allow-list empty for {state.visit_type} — keeping all candidates",
                          level="warn")

        state.cdt_candidates = candidate_codes
        suggestions: List[CDTSuggestion] = []
        for code in candidate_codes:
            entry = self.by_code.get(code)
            if not entry:
                continue
            kws = evidence.get(code, [])
            suggestions.append(CDTSuggestion(
                code=code,
                nomenclature=entry["nomenclature"],
                rationale=f"Evidence: {', '.join(kws)}",
                confidence=0.7,
            ))

        state.log(self.name,
                  f"Stage-1 candidates: kb={len(kb_hits)}, "
                  f"visit={state.visit_type}, total={len(suggestions)}")

        # Demo / no SOAP LLM: materialize suggestions here (stage 2 skipped).
        if not (self.llm and self.llm.available):
            state.cdt_codes = suggestions[:8]
            state.log(self.name, f"Suggested {len(state.cdt_codes)} CDT codes (deterministic)")
        return state

    def candidates_to_suggestions(self, codes: List[str]) -> List[CDTSuggestion]:
        out: List[CDTSuggestion] = []
        for code in codes:
            entry = self.by_code.get(code)
            if entry:
                out.append(CDTSuggestion(
                    code=code,
                    nomenclature=entry["nomenclature"],
                    rationale="From visit-type allow-list",
                    confidence=0.75,
                ))
        return out
