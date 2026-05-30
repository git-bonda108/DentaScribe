"""Four-layer SOAP validator.

Layer 1 — STRUCTURAL: jsonschema against data/soap_schema.json
Layer 2 — GROUNDING:  every clinical claim has a source_span found in the transcript
Layer 3 — CDT:        every billing code is in data/cdt_allow_list.json
Layer 4 — TEXAS:      soft TSBDE rules (consent, license, anesthetic record, sig block)

Result: ValidationReport with errors/warnings/info, plus signability_score (0-100).
A score >= 80 and zero blocking errors -> safe to present to provider for sign-off.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict

from jsonschema import Draft7Validator

from core.glossary_loader import load_schema, load_cdt_allow_list


# Severity levels
ERROR = "error"      # blocks sign-off
WARN = "warning"     # surface but allow
INFO = "info"        # nice-to-fix


@dataclass
class Issue:
    layer: str       # "structural" | "grounding" | "cdt" | "texas"
    severity: str    # ERROR | WARN | INFO
    path: str
    message: str
    suggestion: str = ""


@dataclass
class ValidationReport:
    valid: bool
    signability_score: int
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == WARN]

    @property
    def infos(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == INFO]

    def as_dict(self) -> dict:
        return {
            "valid": self.valid,
            "signability_score": self.signability_score,
            "issues": [asdict(i) for i in self.issues],
            "counts": {
                "errors": len(self.errors),
                "warnings": len(self.warnings),
                "infos": len(self.infos),
            },
        }


class SOAPValidator:
    def __init__(self):
        self.schema = load_schema()
        self.schema_validator = Draft7Validator(self.schema)
        self.allowed_cdt = {c["code"] for c in load_cdt_allow_list()["codes"]}

    # ---------- main entrypoint ----------
    def validate(self, soap: dict, transcript: str = "") -> ValidationReport:
        issues: list[Issue] = []
        issues.extend(self._layer1_structural(soap))
        issues.extend(self._layer2_grounding(soap, transcript))
        issues.extend(self._layer3_cdt(soap))
        issues.extend(self._layer4_texas(soap))

        score = self._signability_score(issues)
        valid = not any(i.severity == ERROR for i in issues)
        return ValidationReport(valid=valid, signability_score=score, issues=issues)

    # ---------- layer 1: structural ----------
    def _layer1_structural(self, soap: dict) -> list[Issue]:
        out = []
        for err in self.schema_validator.iter_errors(soap):
            path = "/".join(str(p) for p in err.absolute_path) or "<root>"
            out.append(Issue(
                layer="structural",
                severity=ERROR,
                path=path,
                message=err.message,
                suggestion="Conform to data/soap_schema.json",
            ))
        return out

    # ---------- layer 2: grounding ----------
    def _layer2_grounding(self, soap: dict, transcript: str) -> list[Issue]:
        out = []
        if not transcript:
            out.append(Issue(
                layer="grounding", severity=WARN, path="<root>",
                message="No transcript provided to validator; grounding checks skipped.",
                suggestion="Pass transcript to validate() to enable grounding.",
            ))
            return out

        norm_transcript = _normalize(transcript)

        def check(items, path_prefix, label, skip=None):
            for i, item in enumerate(items or []):
                # Optional per-item skip predicate. Used for CDT codes where
                # the Coder agent legitimately set code=null (no allow-listed
                # code fits) — there's no clinical claim to ground, and
                # Layer 3 already emits a WARN for the missing code.
                if skip is not None and skip(item):
                    continue
                span = (item.get("source_span") or "").strip()
                p = f"{path_prefix}[{i}].source_span"
                if not span:
                    out.append(Issue(
                        layer="grounding", severity=ERROR, path=p,
                        message=f"{label} missing source_span",
                        suggestion="Add a verbatim transcript quote.",
                    ))
                    continue
                if _normalize(span) not in norm_transcript:
                    out.append(Issue(
                        layer="grounding", severity=ERROR, path=p,
                        message=f"{label} source_span not found in transcript: {span[:80]!r}",
                        suggestion="Either quote exactly or remove this item.",
                    ))

        check(soap.get("objective", {}).get("exam_findings"), "objective.exam_findings", "Exam finding")
        check(soap.get("assessment", {}).get("diagnoses"), "assessment.diagnoses", "Diagnosis")
        check(soap.get("plan", {}).get("procedures_today"), "plan.procedures_today", "Procedure")
        check(soap.get("billing", {}).get("cdt_codes"), "billing.cdt_codes", "CDT code",
              skip=lambda c: c.get("code") is None)
        return out

    # ---------- layer 3: CDT ----------
    def _layer3_cdt(self, soap: dict) -> list[Issue]:
        out = []
        for i, item in enumerate(soap.get("billing", {}).get("cdt_codes") or []):
            code = item.get("code")
            if code is None:
                out.append(Issue(
                    layer="cdt", severity=WARN, path=f"billing.cdt_codes[{i}].code",
                    message="No CDT code assigned (procedure documented but uncoded)",
                    suggestion="Provider review: add code or remove procedure.",
                ))
                continue
            if not re.fullmatch(r"D[0-9]{4}", code):
                out.append(Issue(
                    layer="cdt", severity=ERROR, path=f"billing.cdt_codes[{i}].code",
                    message=f"Malformed CDT code: {code!r}",
                    suggestion="Format must be D followed by 4 digits.",
                ))
            elif code not in self.allowed_cdt:
                out.append(Issue(
                    layer="cdt", severity=ERROR, path=f"billing.cdt_codes[{i}].code",
                    message=f"CDT code {code} is not in the allow-list (likely hallucinated).",
                    suggestion="Use a code from data/cdt_allow_list.json or return null.",
                ))
        return out

    # ---------- layer 4: Texas / TSBDE ----------
    def _layer4_texas(self, soap: dict) -> list[Issue]:
        out = []
        meta = soap.get("metadata", {})
        provider = meta.get("provider", {})
        patient = meta.get("patient", {})

        if not provider.get("tsbde_license"):
            out.append(Issue(
                layer="texas", severity=ERROR, path="metadata.provider.tsbde_license",
                message="Texas TSBDE provider license is required.",
                suggestion="Set CLINIC env var or fill the provider block.",
            ))
        if not meta.get("date_of_service"):
            out.append(Issue(
                layer="texas", severity=ERROR, path="metadata.date_of_service",
                message="Date of service required per 22 TAC §108.8.",
                suggestion="Default to encounter date.",
            ))
        if not patient.get("consent_on_file"):
            out.append(Issue(
                layer="texas", severity=WARN, path="metadata.patient.consent_on_file",
                message="Informed consent not marked on file.",
                suggestion="Provider must attest consent before procedure.",
            ))

        # Anesthetic documentation
        had_anesthesia = any(
            (p.get("anesthesia") or "").strip()
            for p in soap.get("plan", {}).get("procedures_today") or []
        )
        anes_flag = soap.get("compliance", {}).get("tsbde_checklist", {}).get("anesthetic_documented")
        if had_anesthesia and not anes_flag:
            out.append(Issue(
                layer="texas", severity=WARN, path="compliance.tsbde_checklist.anesthetic_documented",
                message="Anesthetic given but compliance checklist not marked.",
                suggestion="Confirm type, amount, and time documented.",
            ))

        # Radiograph justification
        rads = soap.get("objective", {}).get("radiographs_taken") or []
        rad_flag = soap.get("compliance", {}).get("tsbde_checklist", {}).get("radiographs_justified")
        if rads and not rad_flag:
            out.append(Issue(
                layer="texas", severity=INFO, path="compliance.tsbde_checklist.radiographs_justified",
                message="Radiographs taken; ensure justification is documented.",
                suggestion="Tick the radiographs_justified box in the checklist.",
            ))

        # Controlled substance reminder
        for i, rx in enumerate(soap.get("plan", {}).get("prescriptions") or []):
            drug = (rx.get("drug") or "").lower()
            if any(c in drug for c in ["oxycodone", "hydrocodone", "tramadol", "codeine"]):
                out.append(Issue(
                    layer="texas", severity=WARN, path=f"plan.prescriptions[{i}]",
                    message=f"Controlled substance prescribed ({drug}). Texas PMP check required (HB 2174).",
                    suggestion="Document PMP check in patient_instructions.",
                ))

        return out

    # ---------- scoring ----------
    def _signability_score(self, issues: list[Issue]) -> int:
        score = 100
        for i in issues:
            if i.severity == ERROR:
                score -= 25
            elif i.severity == WARN:
                score -= 5
            else:
                score -= 1
        return max(0, score)


def _normalize(text: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation for grounding match."""
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
