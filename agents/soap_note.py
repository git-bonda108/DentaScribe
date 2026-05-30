"""SOAP Note Agent — TSBDE schema v2 + legacy flat fallback.

LLM path: strict JSON schema (soap_schema.json), validated with jsonschema,
up to 2 retries. CDT stage-2 selection is embedded in plan.procedures_*.
Demo path: deterministic template from grounded entities.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any, List, Optional

from agents.base import Agent
from agents.knowledge import DentalKnowledge
from core.soap_schema import (
    cdt_subset_for_visit,
    extract_cdt_suggestions,
    load_schema,
    structured_to_flat,
    validate_soap,
)
from core.soap_validator import SOAPValidator
from core.state import SwarmState, SoapNote, TranscriptSegment
from prompts.soap_prompt import SYSTEM, USER_TEMPLATE
from utils.tooth_norm import normalize_tooth


def _to_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, list):
        return "; ".join(_to_str(x) for x in v if x is not None).strip()
    if isinstance(v, dict):
        parts = []
        for val in v.values():
            s = _to_str(val)
            if s:
                parts.append(s)
        return "; ".join(parts).strip()
    return str(v).strip()


def _to_str_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v.strip()] if v.strip() else []
    if isinstance(v, list):
        return [_to_str(x) for x in v if _to_str(x)]
    s = _to_str(v)
    return [s] if s else []


LEGACY_SYSTEM_PROMPT = """You are a senior dental scribe. From a doctor-patient consultation
transcript, write a SOAP note that an attending dentist could sign without edits.

Strict rules:
- Use ONLY facts that appear in the transcript. NEVER infer diagnoses, dosages,
  tooth numbers, or procedures that were not explicitly stated.
- Return strict JSON with keys:
  chief_complaint, subjective, objective, assessment, plan,
  medications (array of strings), follow_up, dental_exam, notes_for_doctor
"""


class SoapNoteAgent(Agent):
    name = "soap_note"
    MAX_SCHEMA_RETRIES = 2

    def __init__(self, cfg, llm=None, knowledge: Optional[DentalKnowledge] = None):
        super().__init__(cfg, llm)
        self.kb = knowledge
        self._schema = load_schema()
        self._soap_validator = SOAPValidator()

    def run(self, state: SwarmState) -> SwarmState:
        transcript = state.raw_transcript or self._segments_to_text(state.segments)
        if not transcript.strip():
            state.log(self.name, "No transcript — skipping", level="warn")
            return state

        self._sync_teeth_from_entities(state)

        if self.llm and self.llm.available:
            try:
                structured = self._generate_schema_llm(state, transcript)
                state.soap_structured = structured
                state.soap = structured_to_flat(structured)
                state.cdt_codes = extract_cdt_suggestions(structured)[:8]
                if not state.cdt_codes and state.cdt_candidates:
                    from agents.cdt_coder import CdtCoderAgent
                    coder = CdtCoderAgent(self.cfg, self.llm, self.kb)
                    state.cdt_codes = coder.candidates_to_suggestions(state.cdt_candidates)[:8]
                state.log(self.name,
                          f"SOAP schema v2 via {self.llm.provider} "
                          f"({len(state.cdt_codes)} CDT)")
                return state
            except Exception as e:
                state.log(self.name, f"Schema SOAP failed, trying legacy: {e}",
                          level="warn")
                try:
                    state.soap = self._generate_legacy_llm(transcript)
                    state.log(self.name, f"SOAP legacy flat via {self.llm.provider}")
                    return state
                except Exception as e2:
                    state.log(self.name, f"Legacy SOAP failed, template: {e2}",
                              level="warn")

        state.soap = self._generate_template(state)
        state.log(self.name, "SOAP generated via template fallback")
        return state

    def _sync_teeth_from_entities(self, state: SwarmState) -> None:
        nums = set()
        for ent in state.entities:
            if ent.kind == "tooth":
                n = normalize_tooth(ent.value or ent.span or "")
                if n:
                    nums.add(n)
        if nums:
            state.flagged_teeth = sorted(nums)

    def _segments_to_text(self, segs: List[TranscriptSegment]) -> str:
        return "\n".join(f"{s.speaker.capitalize()}: {s.text}" for s in segs)

    def _line_numbered_transcript(self, state: SwarmState) -> str:
        if state.segments:
            lines = []
            for i, seg in enumerate(state.segments, 1):
                lines.append(f"{i}|{seg.speaker}: {seg.text}")
            return "\n".join(lines)
        raw = state.raw_transcript or ""
        out = []
        for i, line in enumerate(raw.splitlines(), 1):
            if line.strip():
                out.append(f"{i}|{line.strip()}")
        return "\n".join(out)

    def _entities_json(self, state: SwarmState) -> str:
        payload = [
            {"kind": e.kind, "value": e.value, "span": e.span, "confidence": e.confidence}
            for e in state.entities
        ]
        return json.dumps(payload, indent=2)

    def _generate_schema_llm(self, state: SwarmState, transcript: str) -> dict:
        numbered = self._line_numbered_transcript(state)
        cdt_subset = cdt_subset_for_visit(state.visit_type, state.cdt_candidates)
        user = USER_TEMPLATE.format(
            transcript=numbered,
            entities=self._entities_json(state),
            cdt_subset=json.dumps(cdt_subset, indent=2),
            schema=json.dumps(self._schema, indent=2),
            visit_type=state.visit_type,
        )
        last_err = "unknown"
        lines = [ln.strip() for ln in numbered.splitlines() if ln.strip()]
        for attempt in range(self.MAX_SCHEMA_RETRIES + 1):
            data = self.llm.complete_json(
                SYSTEM,
                user if attempt == 0 else user + f"\n\nFIX THESE ISSUES:\n{last_err}",
                max_tokens=3500,
                temperature=0.1,
            )
            self._ensure_encounter_meta(state, data)
            ok, err = validate_soap(data)
            if ok:
                vrep = self._soap_validator.validate(data, lines, raise_on_error=False)
                if vrep.ok:
                    self._strip_invalid_cdt(data, state.cdt_candidates)
                    return data
                last_err = vrep.llm_feedback() or "SOAP validation failed"
            else:
                last_err = err or "schema validation failed"
            state.log(self.name, f"Schema validation failed (attempt {attempt + 1}): {last_err}",
                      level="warn")
        raise RuntimeError(last_err)

    def _ensure_encounter_meta(self, state: SwarmState, data: dict) -> None:
        meta = data.setdefault("encounter_meta", {})
        meta.setdefault("patient_ref", state.patient_id or f"DS-{state.consultation_id[:8].upper()}")
        meta.setdefault("date_iso", date.today().isoformat())
        meta.setdefault("visit_type", state.visit_type)
        meta.setdefault("tooth_numbering_system", "Universal")
        meta.setdefault("practice_location", {
            "city": "Dallas", "state": "TX", "name": "DentaScribe Demo Practice",
        })
        meta.setdefault("provider", {
            "name": state.doctor_name or "Provider",
            "license_number": "TX-DDS-#####",
            "npi": "",
            "role": "dentist",
        })
        att = data.setdefault("attestation", {})
        att.setdefault("provider_reviewed", False)
        att.setdefault("ai_assisted_disclosure", True)
        qf = data.setdefault("quality_flags", {})
        qf.setdefault("unverified_terms", [])
        qf.setdefault("missing_required", [])
        gr = data.setdefault("grounding", {})
        gr.setdefault("transcript_spans", [])

    def _strip_invalid_cdt(self, data: dict, candidates: List[str]) -> None:
        allow = set(candidates)
        plan = data.get("plan") or {}
        for bucket in ("procedures_today", "procedures_recommended"):
            for proc in plan.get(bucket) or []:
                if not isinstance(proc, dict):
                    continue
                code = proc.get("cdt_code")
                if code and allow and code not in allow:
                    proc["cdt_code"] = None
                    proc["cdt_rationale"] = (proc.get("cdt_rationale") or "") + " [rejected: not in candidate list]"

    def _generate_legacy_llm(self, transcript: str) -> SoapNote:
        ref = ""
        if self.kb:
            hits = self.kb.search(transcript, k=4)
            if hits:
                ref = "\n".join(f"- [{h['category']}] {h['text']}" for h in hits)
        user = f"Consultation transcript:\n```\n{transcript}\n```"
        if ref:
            user += f"\n\nReference:\n{ref}"
        data = self.llm.complete_json(LEGACY_SYSTEM_PROMPT, user, max_tokens=1600,
                                        temperature=0.15)
        return SoapNote(
            chief_complaint=_to_str(data.get("chief_complaint")),
            subjective=_to_str(data.get("subjective")),
            objective=_to_str(data.get("objective")),
            assessment=_to_str(data.get("assessment")),
            plan=_to_str(data.get("plan")),
            medications=_to_str_list(data.get("medications")),
            follow_up=_to_str(data.get("follow_up")),
            dental_exam=_to_str(data.get("dental_exam")),
            notes_for_doctor=_to_str(data.get("notes_for_doctor")),
        )

    def _generate_template(self, state: SwarmState) -> SoapNote:
        patient_lines = [s.text for s in state.segments if s.speaker == "patient"]
        doctor_lines = [s.text for s in state.segments if s.speaker == "doctor"]

        symptoms = [e.value for e in state.entities if e.kind == "symptom"]
        conditions = [e.value for e in state.entities if e.kind == "condition"]
        procedures = [e.value for e in state.entities if e.kind == "procedure"]
        meds = [e.value for e in state.entities if e.kind == "medication"]
        teeth = [e.value for e in state.entities if e.kind == "tooth"]

        cc = (patient_lines[0] if patient_lines else "").strip()
        if len(cc) > 220:
            cc = cc[:217] + "…"

        subj = " ".join(patient_lines)[:900] or "No patient narrative captured."
        obj = (
            ("Examination noted involvement of " + ", ".join(teeth) + ". ") if teeth else ""
        ) + (
            ("Clinical findings: " + ", ".join(conditions) + ". ") if conditions else ""
        ) + (
            ("Doctor remarks: " + " ".join(doctor_lines)[:500] + ".") if doctor_lines else ""
        )
        obj = obj.strip() or "No objective examination findings captured."

        assess = (
            "Working impression based on stated findings: "
            + (", ".join(conditions) or "to be determined")
            + "."
        )
        plan = (
            "Planned interventions discussed: "
            + (", ".join(procedures) or "pending further evaluation")
            + "."
        )

        med_lines: List[str] = []
        for m in meds:
            med_lines.append(
                f"{m} — dose/frequency/route to be confirmed with prescribing doctor."
            )

        unconfirmed = []
        if meds and not any("mg" in (l or "").lower() for l in (doctor_lines + patient_lines)):
            unconfirmed.append("Confirm exact dose/frequency of mentioned medications.")
        if not teeth and conditions:
            unconfirmed.append("Confirm tooth number(s) involved.")
        notes_for_doc = " ".join(unconfirmed)

        return SoapNote(
            chief_complaint=cc,
            subjective=subj,
            objective=obj,
            assessment=assess,
            plan=plan,
            medications=med_lines,
            follow_up="Follow-up appointment timing per doctor instruction (see transcript).",
            dental_exam=("Findings: " + ", ".join(conditions + teeth)) if (conditions or teeth) else "",
            notes_for_doctor=notes_for_doc,
        )
