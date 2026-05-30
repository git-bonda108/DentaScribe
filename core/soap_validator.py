"""JSON Schema + grounding + CDT allow-list validator for SOAP v2 outputs.

Runs after SOAP generation (see agents/validator.py). Complements the
term-level anti-hallucination checks — does not replace them.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.soap_schema import SCHEMA_PATH, VISIT_TEMPLATES_PATH

try:
    from jsonschema import Draft202012Validator
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "jsonschema is required. Install with: pip install jsonschema"
    ) from exc


class SOAPValidationError(Exception):
    """Raised when SOAP output fails validation. .feedback is LLM-ready."""

    def __init__(self, message: str, errors: List[str], feedback: str):
        super().__init__(message)
        self.errors = errors
        self.feedback = feedback


@dataclass
class ValidationReport:
    ok: bool
    schema_errors: List[str] = field(default_factory=list)
    grounding_errors: List[str] = field(default_factory=list)
    cdt_errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    signability_score: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "schema_errors": self.schema_errors,
            "grounding_errors": self.grounding_errors,
            "cdt_errors": self.cdt_errors,
            "warnings": self.warnings,
            "signability_score": round(self.signability_score, 3),
        }

    def llm_feedback(self) -> str:
        parts = []
        if self.schema_errors:
            parts.append("SCHEMA ERRORS:\n- " + "\n- ".join(self.schema_errors))
        if self.grounding_errors:
            parts.append(
                "GROUNDING ERRORS (every populated field needs a transcript span):\n- "
                + "\n- ".join(self.grounding_errors)
            )
        if self.cdt_errors:
            parts.append(
                "CDT ERRORS (codes must come from the visit-type allow-list):\n- "
                + "\n- ".join(self.cdt_errors)
            )
        return "\n\n".join(parts) if parts else ""


_GROUNDING_REQUIRED_PATHS = [
    "subjective.chief_complaint",
    "subjective.hpi.severity_0_10",
    "subjective.hpi.character",
    "subjective.hpi.triggers",
    "subjective.medications",
    "subjective.allergies",
    "objective.diagnostic_tests.percussion",
    "objective.diagnostic_tests.cold_test",
    "objective.diagnostic_tests.ept",
    "objective.radiographic_findings",
    "objective.hard_tissue_findings",
    "assessment.primary_diagnosis",
    "plan.procedures_today",
    "plan.procedures_recommended",
    "plan.prescriptions",
]


class SOAPValidator:
    def __init__(
        self,
        schema_path: str | Path | None = None,
        visit_templates_path: str | Path | None = None,
    ) -> None:
        schema_path = schema_path or SCHEMA_PATH
        visit_templates_path = visit_templates_path or VISIT_TEMPLATES_PATH
        with open(schema_path, "r", encoding="utf-8") as f:
            self._schema = json.load(f)
        self._struct_validator = Draft202012Validator(self._schema)

        with open(visit_templates_path, "r", encoding="utf-8") as f:
            self._visit_templates = json.load(f)

    def validate(
        self,
        soap: Dict[str, Any],
        transcript_lines: Optional[List[str]] = None,
        raise_on_error: bool = True,
    ) -> ValidationReport:
        report = ValidationReport(ok=True)

        self._validate_schema(soap, report)
        self._validate_grounding(soap, transcript_lines or [], report)
        self._validate_cdt_allow_list(soap, report)
        self._validate_texas_rules(soap, report)
        self._score_signability(soap, report)

        report.ok = not (
            report.schema_errors or report.grounding_errors or report.cdt_errors
        )

        if not report.ok and raise_on_error:
            raise SOAPValidationError(
                "SOAP validation failed",
                errors=report.schema_errors + report.grounding_errors + report.cdt_errors,
                feedback=report.llm_feedback(),
            )
        return report

    def _validate_schema(self, soap: Dict[str, Any], report: ValidationReport) -> None:
        for err in sorted(self._struct_validator.iter_errors(soap), key=lambda e: list(e.path)):
            path = ".".join(str(p) for p in err.path) or "<root>"
            report.schema_errors.append(f"{path}: {err.message}")

    def _validate_grounding(
        self,
        soap: Dict[str, Any],
        transcript_lines: List[str],
        report: ValidationReport,
    ) -> None:
        spans = (soap.get("grounding") or {}).get("transcript_spans") or []
        grounded_paths = {s.get("field_path", "") for s in spans}

        for path in _GROUNDING_REQUIRED_PATHS:
            if self._field_populated(soap, path) and not self._has_span_for(path, grounded_paths):
                report.grounding_errors.append(
                    f"Field '{path}' is populated but has no entry in grounding.transcript_spans."
                )

        if transcript_lines:
            n = len(transcript_lines)
            for s in spans:
                idx = s.get("line_index")
                quote = (s.get("quote") or "").strip()
                fp = s.get("field_path", "?")
                if idx is None or not (0 <= idx < n):
                    report.warnings.append(f"Span for '{fp}' has out-of-range line_index={idx}.")
                if not quote:
                    report.warnings.append(f"Span for '{fp}' has empty quote.")

    def _validate_cdt_allow_list(self, soap: Dict[str, Any], report: ValidationReport) -> None:
        visit_type = (soap.get("encounter_meta") or {}).get("visit_type")
        if not visit_type:
            return
        template = self._visit_templates.get(visit_type) or {}
        allow = set(template.get("cdt_allow_list") or [])
        if not allow:
            return

        plan = soap.get("plan") or {}
        for bucket in ("procedures_today", "procedures_recommended"):
            for i, proc in enumerate(plan.get(bucket) or []):
                code = (proc or {}).get("cdt_code")
                if code and code not in allow:
                    report.cdt_errors.append(
                        f"plan.{bucket}[{i}].cdt_code='{code}' is not in the allow-list "
                        f"for visit_type='{visit_type}'."
                    )

    def _validate_texas_rules(self, soap: Dict[str, Any], report: ValidationReport) -> None:
        meta = soap.get("encounter_meta") or {}
        loc = meta.get("practice_location") or {}
        state_code = (
            (meta.get("provider_license_state") or loc.get("state") or "")
        ).upper()
        if state_code != "TX":
            return

        obj = soap.get("objective") or {}
        if not (obj.get("radiographic_findings") or "").strip():
            report.warnings.append(
                "TX 22 TAC §108.8: radiographic findings missing — required if rads were taken."
            )
        if not (soap.get("plan") or {}).get("informed_consent", {}).get("obtained"):
            report.warnings.append(
                "TX 22 TAC §108.8: informed consent flag not set — required for invasive procedures."
            )
        if not (soap.get("attestation") or {}).get("provider_reviewed"):
            report.warnings.append(
                "Provider attestation missing — required before billable sign-off."
            )

    def _score_signability(self, soap: Dict[str, Any], report: ValidationReport) -> None:
        score = 1.0
        score -= 0.20 * min(len(report.schema_errors), 3) / 3
        score -= 0.30 * min(len(report.grounding_errors), 5) / 5
        score -= 0.30 * min(len(report.cdt_errors), 3) / 3
        score -= 0.05 * min(len(report.warnings), 4) / 4
        report.signability_score = max(0.0, min(1.0, score))

    @staticmethod
    def _field_populated(soap: Dict[str, Any], path: str) -> bool:
        cur: Any = soap
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return False
        if cur is None:
            return False
        if isinstance(cur, (list, dict, str)) and len(cur) == 0:
            return False
        return True

    @staticmethod
    def _has_span_for(path: str, grounded_paths: set) -> bool:
        if path in grounded_paths:
            return True
        prefix = path + "."
        return any(gp.startswith(prefix) for gp in grounded_paths)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m core.soap_validator <soap.json> [transcript.txt]")
        sys.exit(1)

    with open(sys.argv[1], "r", encoding="utf-8") as f:
        soap_doc = json.load(f)

    transcript: List[str] = []
    if len(sys.argv) >= 3:
        with open(sys.argv[2], "r", encoding="utf-8") as f:
            transcript = [ln.rstrip("\n") for ln in f]

    v = SOAPValidator()
    rep = v.validate(soap_doc, transcript, raise_on_error=False)
    print(json.dumps(rep.as_dict(), indent=2))
