"""Ground-truth schema and metric result types.

Designed against the actual SwarmState shape so we can lift fields directly
out of a finished run and compare them to expectations. Audio-mode fields
(WER, dental_wer, audio_quality) are reserved but inactive until P3.5.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any


# ---------- ground truth (input) ----------

@dataclass
class ExpectedEntity:
    """An entity we expect the NER agent to surface.

    `kind` matches DentalEntity.kind: tooth | condition | procedure |
    medication | anatomy | symptom.

    `aliases` lets us accept multiple surface forms for the same concept —
    e.g. ["tooth 3", "upper right first molar"] are both valid for the
    same tooth. Matching is case-insensitive substring against entity.value.

    `required=False` marks a "nice to have" entity that contributes to
    precision but not recall.
    """
    kind: str
    value: str
    aliases: List[str] = field(default_factory=list)
    required: bool = True

    def all_forms(self) -> List[str]:
        return [self.value.lower(), *(a.lower() for a in self.aliases)]


@dataclass
class ExpectedCdt:
    """A CDT code we expect the coder to surface.

    `rank_within` = max acceptable rank (1-indexed) in the cdt_codes list.
    Default 8 because CdtCoderAgent caps output at 8.

    `required=False` codes are credited if present but don't hurt recall.
    """
    code: str
    rank_within: int = 8
    required: bool = True


@dataclass
class GroundTruth:
    fixture_id: str

    # entities
    expected_entities: List[ExpectedEntity] = field(default_factory=list)

    # CDT codes
    expected_cdt: List[ExpectedCdt] = field(default_factory=list)
    forbidden_cdt: List[str] = field(default_factory=list)   # adversarial: must NOT appear

    # SOAP
    required_soap_sections: List[str] = field(
        default_factory=lambda: ["chief_complaint", "subjective", "objective",
                                 "assessment", "plan"]
    )
    # Per-section substrings that should appear (case-insensitive). Tunable —
    # we keep this small so we measure presence, not phrasing.
    required_soap_keywords: Dict[str, List[str]] = field(default_factory=dict)

    # Medications (substring match against the joined `soap.medications` list)
    expected_medications: List[str] = field(default_factory=list)

    # Anti-hallucination ceiling. The validator surfaces unconfirmed terms;
    # we tolerate up to this many before flagging the fixture as failing.
    max_hallucinations: int = 0

    # Reserved for P3.5 audio fixtures (inactive in P1):
    audio_path: Optional[str] = None       # relative to eval/audio/
    expected_wer_max: Optional[float] = None
    expected_dental_wer_max: Optional[float] = None

    # Human-readable notes about why this fixture exists
    notes: str = ""


# ---------- metric results (output) ----------

@dataclass
class MetricResult:
    name: str
    score: float                # 0.0–1.0 (higher is better) OR a raw count
    is_rate: bool = True        # False → score is a raw count
    detail: Dict[str, Any] = field(default_factory=dict)
    threshold: Optional[float] = None   # pass/fail gate, if any
    passed: Optional[bool] = None


@dataclass
class FixtureResult:
    fixture_id: str
    patient_name: str
    metrics: List[MetricResult] = field(default_factory=list)
    signability_score: float = 0.0   # composite, see metrics.py
    passed: bool = False
    errors: List[str] = field(default_factory=list)
    duration_ms: int = 0

    def metric(self, name: str) -> Optional[MetricResult]:
        for m in self.metrics:
            if m.name == name:
                return m
        return None


@dataclass
class EvalReport:
    fixtures: List[FixtureResult] = field(default_factory=list)
    aggregate: Dict[str, float] = field(default_factory=dict)
    passed: bool = False
    llm_provider: str = "demo"
    git_sha: str = ""
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------- pass thresholds (the regression gate) ----------
# These are intentionally tight for clean fixtures and relaxed where the
# fixture is designed to stress a particular layer (adversarial cases will
# override these in their GroundTruth).
DEFAULT_THRESHOLDS = {
    "entity_recall":        0.80,
    "entity_precision":     0.40,   # template fallback over-extracts; relax for now, tighten in P2
    "cdt_recall_at_k":      0.80,
    "cdt_forbidden_count":  0,      # raw count, lower is better
    "soap_completeness":    1.00,
    "soap_keyword_coverage": 0.70,
    "medication_coverage":  0.80,
    "hallucination_count":  0,      # raw count, lower is better
    "signability_score":    0.75,
}
