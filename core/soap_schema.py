"""Load and validate TSBDE SOAP schema (soap_schema.json)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.state import CDTSuggestion, SoapNote

DATA = Path(__file__).resolve().parent.parent / "data"
SCHEMA_PATH = DATA / "soap_schema.json"
VISIT_TEMPLATES_PATH = DATA / "visit_type_templates.json"
CDT_PATH = DATA / "cdt_codes_2026.json"


@lru_cache(maxsize=1)
def load_schema() -> dict:
    with open(SCHEMA_PATH) as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_visit_templates() -> dict:
    with open(VISIT_TEMPLATES_PATH) as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_cdt_catalog() -> dict:
    with open(CDT_PATH) as f:
        return json.load(f)


def cdt_allow_list(visit_type: str) -> List[str]:
    tmpl = load_visit_templates().get(visit_type, {})
    return list(tmpl.get("cdt_allow_list") or [])


def cdt_subset_for_visit(visit_type: str, candidates: List[str]) -> List[dict]:
    """Intersect deterministic candidates with visit-type allow-list."""
    allow = set(cdt_allow_list(visit_type))
    by_code = {c["code"]: c for c in load_cdt_catalog()["codes"]}
    if allow:
        codes = [c for c in candidates if c in allow]
    else:
        codes = list(candidates)
    out = []
    for code in codes:
        entry = by_code.get(code)
        if entry:
            out.append({"code": code, "nomenclature": entry["nomenclature"]})
    return out


def validate_soap(data: dict) -> Tuple[bool, Optional[str]]:
    try:
        import jsonschema
        jsonschema.validate(instance=data, schema=load_schema())
        return True, None
    except ImportError:
        required = load_schema().get("required", [])
        missing = [k for k in required if k not in data]
        if missing:
            return False, f"missing keys: {missing}"
        return True, None
    except Exception as e:
        return False, str(e)


def _join_parts(parts: List[str]) -> str:
    return "; ".join(p for p in parts if p).strip()


def structured_to_flat(soap: dict) -> SoapNote:
    """Map schema v2 JSON → legacy SoapNote for eval + PDF exporters."""
    subj = soap.get("subjective") or {}
    obj = soap.get("objective") or {}
    assess = soap.get("assessment") or {}
    plan = soap.get("plan") or {}

    cc = subj.get("chief_complaint") or ""
    hpi = subj.get("hpi") or {}
    hpi_bits = []
    for k in ("onset", "duration", "character", "functional_impact"):
        v = hpi.get(k)
        if v:
            hpi_bits.append(f"{k}: {v}")
    sev = hpi.get("severity_0_10")
    if sev is not None:
        hpi_bits.append(f"severity: {sev}/10")
    triggers = hpi.get("triggers") or []
    if triggers:
        hpi_bits.append("triggers: " + ", ".join(triggers))
    subjective = _join_parts(hpi_bits)
    if subj.get("dental_history"):
        subjective = _join_parts([subjective, subj["dental_history"]])

    obj_bits = []
    if obj.get("extraoral"):
        eo = obj["extraoral"]
        if isinstance(eo, dict):
            obj_bits.append("EO: " + _join_parts([str(v) for v in eo.values() if v]))
        else:
            obj_bits.append(f"EO: {eo}")
    if obj.get("intraoral_soft_tissue"):
        obj_bits.append(f"IO ST: {obj['intraoral_soft_tissue']}")
    perio = obj.get("periodontal") or {}
    if perio:
        obj_bits.append("Perio: " + _join_parts([f"{k}={v}" for k, v in perio.items() if v]))
    for ht in obj.get("hard_tissue_findings") or []:
        if isinstance(ht, dict):
            tooth = ht.get("tooth")
            finding = ht.get("finding") or ht.get("condition") or ""
            surf = ht.get("surface")
            line = f"#{tooth}" if tooth else ""
            if surf:
                line += f" ({surf})"
            if finding:
                line += f": {finding}"
            if line:
                obj_bits.append(line.strip(": "))
    if obj.get("radiographic_findings"):
        obj_bits.append(f"Radiographs: {obj['radiographic_findings']}")
    tests = obj.get("diagnostic_tests") or {}
    if tests:
        obj_bits.append("Tests: " + _join_parts([f"{k}={v}" for k, v in tests.items() if v]))

    primary = assess.get("primary_diagnosis") or []
    assess_lines = []
    for dx in primary:
        if isinstance(dx, dict):
            tooth = dx.get("tooth")
            label = dx.get("diagnosis") or dx.get("label") or ""
            icd = dx.get("icd10")
            line = f"#{tooth} — {label}" if tooth else label
            if icd:
                line += f" ({icd})"
            assess_lines.append(line)
        elif dx:
            assess_lines.append(str(dx))
    assessment = _join_parts(assess_lines)

    plan_lines = []
    for proc in plan.get("procedures_today") or []:
        if not isinstance(proc, dict):
            continue
        code = proc.get("cdt_code") or ""
        name = proc.get("procedure") or ""
        tooth = proc.get("tooth")
        prefix = f"Today: {name}"
        if tooth:
            prefix += f" (#{tooth})"
        if code:
            prefix += f" · {code}"
        plan_lines.append(prefix)
    for proc in plan.get("procedures_recommended") or []:
        if isinstance(proc, dict):
            code = proc.get("cdt_code") or ""
            name = proc.get("procedure") or ""
            tooth = proc.get("tooth")
            line = f"Recommended: {name}"
            if tooth:
                line += f" (#{tooth})"
            if code:
                line += f" · {code}"
            plan_lines.append(line)
    rx_lines = []
    for rx in plan.get("prescriptions") or []:
        if isinstance(rx, dict):
            parts = [rx.get("drug"), rx.get("dose"), rx.get("frequency"), rx.get("duration")]
            rx_lines.append(" ".join(p for p in parts if p))
    if rx_lines:
        plan_lines.append("Rx: " + "; ".join(rx_lines))
    consent = plan.get("informed_consent") or {}
    if consent.get("obtained"):
        plan_lines.append("Consent: obtained")
    follow = plan.get("follow_up") or {}
    follow_up = ""
    if isinstance(follow, dict):
        follow_up = follow.get("instructions") or follow.get("timing") or ""
    elif follow:
        follow_up = str(follow)

    meds = []
    for m in subj.get("medications") or []:
        meds.append(str(m))
    meds.extend(rx_lines)

    dental_exam = _join_parts(obj_bits[:6])
    notes = _join_parts(
        (soap.get("quality_flags") or {}).get("unverified_terms") or []
    )

    return SoapNote(
        chief_complaint=str(cc or ""),
        subjective=subjective or str(cc or ""),
        objective=_join_parts(obj_bits) or "",
        assessment=assessment,
        plan=_join_parts(plan_lines),
        medications=meds,
        follow_up=str(follow_up or ""),
        dental_exam=dental_exam,
        notes_for_doctor=notes,
    )


def extract_cdt_suggestions(soap: dict) -> List[CDTSuggestion]:
    """Pull CDT codes embedded in structured plan sections."""
    by_code = {c["code"]: c for c in load_cdt_catalog()["codes"]}
    out: List[CDTSuggestion] = []
    seen = set()
    plan = soap.get("plan") or {}
    for bucket in ("procedures_today", "procedures_recommended"):
        for proc in plan.get(bucket) or []:
            if not isinstance(proc, dict):
                continue
            code = proc.get("cdt_code")
            if not code or code in seen or code not in by_code:
                continue
            seen.add(code)
            entry = by_code[code]
            out.append(CDTSuggestion(
                code=code,
                nomenclature=entry["nomenclature"],
                rationale=str(proc.get("cdt_rationale") or proc.get("procedure") or ""),
                confidence=float(proc.get("cdt_confidence") or 0.85),
            ))
    out.sort(key=lambda s: -s.confidence)
    return out
