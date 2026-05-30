"""Scribe + Coder agents — the two LLM-driven clinical agents."""
from __future__ import annotations

import time

from agents.base import BaseAgent, AgentResult
from core.llm_client import LLMClient
from prompts.soap_prompt import build_scribe_system_prompt, build_scribe_user_prompt
from prompts.clinical_prompts import build_coder_system_prompt, build_coder_user_prompt
from data.tooth_norm import normalize_tooth
from data.surface_norm import normalize_surfaces, count_surfaces


# ---------- demo fixtures ----------

def _demo_soap_emergency_endo() -> dict:
    """Canned SOAP for the locked emergency-endo test case (#19 irreversible pulpitis)."""
    return {
        "metadata": {
            "encounter_id": "demo-endo-1",
            "date_of_service": "2026-05-31",
            "provider": {"name": "Dr. J. Patel, DDS", "tsbde_license": "TX-DDS-29481"},
            "patient": {"patient_id": "P-1042", "dob": "1985-07-12", "consent_on_file": True},
            "visit_type": "emergency",
            "location": {"clinic": "Dallas Smiles", "city": "Dallas", "state": "TX"},
        },
        "subjective": {
            "chief_complaint": "Severe lower-left tooth pain for three days, throbbing, keeps patient awake at night.",
            "pain_scale": 9,
            "history_present_illness": "Pain began spontaneously 3 days ago, worse with hot liquids, lingering 30+ seconds.",
            "medical_history_updates": ["Hypertension on lisinopril 10 mg daily"],
            "allergies": ["NKDA"],
        },
        "objective": {
            "exam_findings": [{
                "tooth": "19", "surfaces": ["O", "D"],
                "finding": "Deep distal-occlusal caries with pulpal exposure",
                "severity": "severe",
                "source_span": "I can see deep decay on the back side of nineteen reaching the nerve",
            }],
            "radiographs_taken": [{
                "type": "PA", "tooth": "19",
                "findings": "Periapical radiolucency at apex consistent with periapical pathology",
                "source_span": "the PA shows a dark spot at the root tip",
            }],
            "vitals": {"bp": "138/86", "pulse": 78},
        },
        "assessment": {
            "diagnoses": [{
                "tooth": "19", "diagnosis": "Irreversible pulpitis with symptomatic apical periodontitis",
                "icd10": "K04.0",
                "source_span": "this is irreversible pulpitis, we need to start a root canal",
            }],
            "differential": [],
        },
        "plan": {
            "procedures_today": [{
                "procedure": "Limited oral evaluation, problem-focused", "tooth": "19",
                "anesthesia": "Lidocaine 2% with epinephrine 1:100,000, 1 carpule, IAN block",
                "source_span": "I'll give you a quick exam and start the root canal today",
            }, {
                "procedure": "Endodontic therapy, molar - initial", "tooth": "19",
                "source_span": "we need to start a root canal",
            }],
            "prescriptions": [{
                "drug": "Ibuprofen", "strength": "600 mg", "sig": "1 tab PO q6h PRN pain",
                "quantity": 20, "refills": 0,
                "source_span": "take ibuprofen six hundred every six hours as needed",
            }],
            "recommended_future": ["Complete RCT in 2 visits", "Crown #19 after obturation"],
            "follow_up": "Return in 7 days for obturation",
            "patient_instructions": "Soft diet, avoid chewing on left side, call if swelling.",
        },
        "billing": {"cdt_codes": []},
        "compliance": {"tsbde_checklist": {}},
        "grounding": {"transcript_excerpts": []},
    }


def _demo_soap_recall_hygiene() -> dict:
    """Canned SOAP for the locked recall-hygiene test case (#3 MO composite)."""
    return {
        "metadata": {
            "encounter_id": "demo-recall-1",
            "date_of_service": "2026-05-31",
            "provider": {"name": "Dr. J. Patel, DDS", "tsbde_license": "TX-DDS-29481"},
            "patient": {"patient_id": "P-2087", "dob": "1992-03-04", "consent_on_file": True},
            "visit_type": "recall",
            "location": {"clinic": "Dallas Smiles", "city": "Dallas", "state": "TX"},
        },
        "subjective": {
            "chief_complaint": "Six-month recall, no complaints",
            "pain_scale": 0,
            "history_present_illness": "Asymptomatic.",
            "medical_history_updates": ["No changes"],
            "allergies": ["NKDA"],
        },
        "objective": {
            "exam_findings": [{
                "tooth": "3", "surfaces": ["M", "O"],
                "finding": "Incipient caries mesio-occlusal", "severity": "mild",
                "source_span": "I see a small cavity starting on the upper right first molar mesial occlusal",
            }],
            "radiographs_taken": [{
                "type": "BW", "tooth": None,
                "findings": "Four bitewings, interproximal caries #3 MO confirmed",
                "source_span": "let's take four bitewings today",
            }],
            "vitals": {},
        },
        "assessment": {
            "diagnoses": [{
                "tooth": "3", "diagnosis": "Dental caries, mesial-occlusal",
                "icd10": "K02.51",
                "source_span": "small cavity starting on the upper right first molar mesial occlusal",
            }],
            "differential": [],
        },
        "plan": {
            "procedures_today": [{
                "procedure": "Periodic oral evaluation", "tooth": None,
                "source_span": "let's do your routine check-up",
            }, {
                "procedure": "Composite restoration two surfaces, posterior", "tooth": "3",
                "surfaces": ["M", "O"],
                "anesthesia": "Lidocaine 2% with epi 1:100,000, half carpule, infiltration",
                "source_span": "I'll go ahead and fill that mesial occlusal today",
            }],
            "prescriptions": [],
            "recommended_future": ["Six-month recall"],
            "follow_up": "Return in 6 months",
            "patient_instructions": "Continue twice-daily brushing and flossing.",
        },
        "billing": {"cdt_codes": []},
        "compliance": {"tsbde_checklist": {}},
        "grounding": {"transcript_excerpts": []},
    }


def get_demo_soap(case_id: str) -> dict:
    if case_id == "recall_hygiene":
        return _demo_soap_recall_hygiene()
    return _demo_soap_emergency_endo()


def _demo_cdt_emergency_endo() -> dict:
    return {"cdt_codes": [
        {"code": "D0140", "description": "Limited oral evaluation, problem focused", "tooth": "19",
         "rationale": "Emergency problem-focused exam for tooth #19 pain",
         "source_span": "I'll give you a quick exam"},
        {"code": "D0220", "description": "Intraoral periapical first radiographic image", "tooth": "19",
         "rationale": "Single PA of #19 to evaluate periapical pathology",
         "source_span": "the PA shows a dark spot at the root tip"},
        {"code": "D3330", "description": "Endodontic therapy, molar (excluding final restoration)", "tooth": "19",
         "rationale": "Molar endodontic therapy initiated on #19",
         "source_span": "we need to start a root canal"},
        # No N2O sedation was documented in the transcript — the Coder agent
        # surfaces the procedure but explicitly declines to bill (code: null).
        # Layer 3 of the validator emits a WARN for this; Layer 2 skips
        # grounding when code is null. Matches the architect's intent below.
        {"code": None, "description": "Inhalation of nitrous oxide / anxiolysis, analgesia",
         "tooth": None, "rationale": None, "source_span": None,
         "code_null_reason": "No nitrous documented; provider review."},
    ], "estimated_total": None}


def _demo_cdt_recall() -> dict:
    return {"cdt_codes": [
        {"code": "D0120", "description": "Periodic oral evaluation", "tooth": None,
         "rationale": "Recall periodic exam", "source_span": "your routine check-up"},
        {"code": "D0274", "description": "Bitewings — four radiographic images", "tooth": None,
         "rationale": "Four bitewings taken", "source_span": "let's take four bitewings today"},
        {"code": "D2391", "description": "Resin-based composite — one surface, posterior", "tooth": "3",
         "rationale": "Composite restoration two surfaces M+O", "source_span": "fill that mesial occlusal"},
    ], "estimated_total": None}


def get_demo_cdt(case_id: str) -> dict:
    return _demo_cdt_recall() if case_id == "recall_hygiene" else _demo_cdt_emergency_endo()


# ---------- post-processors ----------

def _normalize_soap_inplace(soap: dict) -> dict:
    """Run tooth + surface normalizers on every clinical entry."""
    def fix(item):
        if "tooth" in item and item["tooth"]:
            t = normalize_tooth(item["tooth"])
            if t: item["tooth"] = t
        if "surfaces" in item and item["surfaces"]:
            item["surfaces"] = normalize_surfaces(item["surfaces"])
        return item

    for path in [("objective", "exam_findings"), ("assessment", "diagnoses"),
                 ("plan", "procedures_today"), ("billing", "cdt_codes")]:
        section = soap.get(path[0], {}).get(path[1]) or []
        for item in section:
            fix(item)
    return soap


def _refine_composite_codes(soap: dict) -> dict:
    """If Coder returned D2391 but procedure has 2 surfaces, upgrade to D2392, etc."""
    procs = {(p.get("tooth"), tuple(p.get("surfaces") or [])): p
             for p in soap.get("plan", {}).get("procedures_today") or []}
    surface_map = {
        1: "D2391", 2: "D2392", 3: "D2393", 4: "D2394",
    }
    for code in soap.get("billing", {}).get("cdt_codes") or []:
        if code.get("code") not in {"D2391", "D2392", "D2393", "D2394"}:
            continue
        tooth = code.get("tooth")
        # find matching procedure for this tooth with surfaces
        for (t, surfs), p in procs.items():
            if t == tooth and surfs:
                n = count_surfaces(list(surfs))
                if n in surface_map:
                    code["code"] = surface_map[n]
                    code["surfaces"] = list(surfs)
                break
    return soap


# ---------- Scribe agent ----------

class ScribeAgent(BaseAgent):
    name = "Scribe"
    role = "Extracts structured SOAP from the transcript"
    icon = "🦷"

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def run(self, ctx: dict) -> AgentResult:
        t0 = time.time()
        transcript = ctx.get("transcript", "")
        visit_type = ctx.get("visit_type", "emergency")
        metadata = ctx.get("metadata", {})
        case_id = ctx.get("case_id", "emergency_endo")

        sys_p = build_scribe_system_prompt()
        user_p = build_scribe_user_prompt(transcript, visit_type, metadata)

        demo_resp = get_demo_soap(case_id) if self.llm.demo else None
        soap, call = self.llm.complete_json(
            agent="scribe", system=sys_p, user=user_p,
            max_tokens=4096, temperature=0.1, demo_response=demo_resp,
        )

        if soap is None:
            return AgentResult(
                agent=self.name, status="error",
                status_message="Scribe returned non-JSON twice; aborting.",
                llm_call=call, duration_ms=int((time.time() - t0) * 1000),
            )

        # Stamp metadata if Scribe omitted it (demo mode keeps it; live needs backfill)
        soap.setdefault("metadata", {}).update(
            {k: v for k, v in metadata.items() if k not in soap["metadata"]}
        )
        _normalize_soap_inplace(soap)

        return AgentResult(
            agent=self.name, status="ok",
            status_message=f"SOAP draft produced ({len(soap.get('objective', {}).get('exam_findings', []))} findings).",
            output=soap, llm_call=call,
            duration_ms=int((time.time() - t0) * 1000),
        )


# ---------- Coder agent ----------

class CoderAgent(BaseAgent):
    name = "Coder"
    role = "Assigns CDT billing codes (allow-list only)"
    icon = "🏷️"

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def run(self, ctx: dict) -> AgentResult:
        t0 = time.time()
        soap = ctx.get("soap") or {}
        case_id = ctx.get("case_id", "emergency_endo")
        if not soap.get("plan", {}).get("procedures_today"):
            return AgentResult(
                agent=self.name, status="skipped",
                status_message="No procedures documented; skipping CDT coding.",
                duration_ms=int((time.time() - t0) * 1000),
            )

        sys_p = build_coder_system_prompt()
        user_p = build_coder_user_prompt(soap)

        demo_resp = get_demo_cdt(case_id) if self.llm.demo else None
        result, call = self.llm.complete_json(
            agent="coder", system=sys_p, user=user_p,
            max_tokens=2048, temperature=0.0, demo_response=demo_resp,
        )

        if result is None or "cdt_codes" not in result:
            return AgentResult(
                agent=self.name, status="error",
                status_message="Coder failed to return valid CDT JSON.",
                llm_call=call, duration_ms=int((time.time() - t0) * 1000),
            )

        # Drop null-code rows so they don't pollute billing (validator warns separately)
        codes = [c for c in result["cdt_codes"] if c.get("code")]
        soap.setdefault("billing", {})["cdt_codes"] = codes
        _refine_composite_codes(soap)

        return AgentResult(
            agent=self.name, status="ok",
            status_message=f"{len(codes)} CDT codes assigned.",
            output={"cdt_codes": codes}, llm_call=call,
            duration_ms=int((time.time() - t0) * 1000),
        )
