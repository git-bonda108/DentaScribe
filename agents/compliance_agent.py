"""Compliance agent — fully deterministic TSBDE checklist filler.

This agent does NOT call the LLM. It reads the SOAP note + clinic env config
and ticks the TSBDE checklist boxes that can be confirmed mechanically.
The provider remains responsible for attestation.
"""
from __future__ import annotations
import time
import os

from agents.base import BaseAgent, AgentResult


REQUIRED_TSBDE_FIELDS = [
    "patient_identified",
    "consent_documented",
    "license_on_record",
    "date_of_service_present",
    "anesthetic_documented",
    "radiographs_justified",
    "diagnoses_present",
    "treatment_plan_present",
    "pmp_check_if_controlled",
]


class ComplianceAgent(BaseAgent):
    name = "Compliance"
    role = "Deterministic TSBDE checklist (22 TAC §108.8)"
    icon = "📋"

    def run(self, ctx: dict) -> AgentResult:
        t0 = time.time()
        soap = ctx.get("soap") or {}
        clinic_env = ctx.get("clinic_env") or {}

        meta = soap.get("metadata", {})
        provider = meta.get("provider", {})
        patient = meta.get("patient", {})

        checklist = {
            "patient_identified": bool(patient.get("patient_id")),
            "consent_documented": bool(patient.get("consent_on_file")),
            "license_on_record": bool(provider.get("tsbde_license") or clinic_env.get("CLINIC_LICENSE")),
            "date_of_service_present": bool(meta.get("date_of_service")),
            "anesthetic_documented": _anesthetic_ok(soap),
            "radiographs_justified": _radiographs_ok(soap),
            "diagnoses_present": bool(soap.get("assessment", {}).get("diagnoses")),
            "treatment_plan_present": bool(
                soap.get("plan", {}).get("procedures_today") or soap.get("plan", {}).get("recommended_future")
            ),
            "pmp_check_if_controlled": _pmp_ok(soap),
        }

        soap.setdefault("compliance", {})["tsbde_checklist"] = checklist
        soap["compliance"]["regulatory_citation"] = "22 TAC §108.8 (Records of the Dental Patient)"
        soap["compliance"]["retention_policy"] = "5 years adult / age of majority + 5 years for minors"

        missing = [k for k, v in checklist.items() if not v]
        status = "ok" if not missing else ("warn" if len(missing) <= 2 else "error")
        msg = "TSBDE checklist complete." if not missing else f"{len(missing)} item(s) need provider attention: {', '.join(missing)}"

        return AgentResult(
            agent=self.name, status=status, status_message=msg,
            output={"checklist": checklist, "missing": missing},
            duration_ms=int((time.time() - t0) * 1000),
        )


def _anesthetic_ok(soap: dict) -> bool:
    procs = soap.get("plan", {}).get("procedures_today") or []
    needs = any(_likely_needs_anesthesia(p.get("procedure", "")) for p in procs)
    if not needs:
        return True  # vacuously satisfied
    return any((p.get("anesthesia") or "").strip() for p in procs)


def _likely_needs_anesthesia(procedure: str) -> bool:
    proc = (procedure or "").lower()
    keywords = ["composite", "restoration", "extraction", "endodontic", "root canal",
                "crown", "biopsy", "incision", "surgical"]
    return any(k in proc for k in keywords)


def _radiographs_ok(soap: dict) -> bool:
    rads = soap.get("objective", {}).get("radiographs_taken") or []
    if not rads:
        return True
    return all((r.get("findings") or "").strip() for r in rads)


def _pmp_ok(soap: dict) -> bool:
    """Texas HB 2174 — PMP query required for CII–CV prescriptions."""
    rxs = soap.get("plan", {}).get("prescriptions") or []
    controlled = ["oxycodone", "hydrocodone", "tramadol", "codeine", "morphine", "fentanyl"]
    has_controlled = any(any(c in (rx.get("drug", "").lower()) for c in controlled) for rx in rxs)
    if not has_controlled:
        return True
    notes = (soap.get("plan", {}).get("patient_instructions") or "").lower()
    return "pmp" in notes or "prescription monitoring" in notes
