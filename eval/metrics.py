"""Metric implementations.

Each function takes a finished SwarmState + a GroundTruth and returns a
MetricResult. Pure functions, no side effects. The runner stitches them
together and writes the report.

Design notes:
  * Entity matching is case-insensitive substring against value+aliases —
    we do not require exact string equality because the LLM/template will
    paraphrase ("Tooth 3" vs "tooth number 3" vs "upper right first molar").
  * CDT matching is exact code equality; rank within the top-N of
    state.cdt_codes is honored.
  * Hallucination_count is the raw len() of qa.unconfirmed_terms. Validator
    already does the work of finding them; we just measure.
"""
from __future__ import annotations
from typing import List
from core.state import SwarmState, DentalEntity, CDTSuggestion
from eval.schema import (
    GroundTruth, MetricResult, ExpectedEntity, ExpectedCdt, DEFAULT_THRESHOLDS,
)


# ---------------- entity metrics ----------------

def _entity_matches(found: List[DentalEntity], expected: ExpectedEntity) -> bool:
    """True if any found entity (of the right kind) matches any expected form."""
    forms = expected.all_forms()
    for ent in found:
        if ent.kind.lower() != expected.kind.lower():
            continue
        val = (ent.value or "").lower()
        span = (ent.span or "").lower()
        for form in forms:
            if form in val or form in span or val in form:
                return True
    return False


def entity_recall(state: SwarmState, gt: GroundTruth) -> MetricResult:
    required = [e for e in gt.expected_entities if e.required]
    if not required:
        return MetricResult("entity_recall", 1.0, threshold=DEFAULT_THRESHOLDS["entity_recall"],
                            detail={"required": 0}, passed=True)
    hits, misses = [], []
    for exp in required:
        if _entity_matches(state.entities, exp):
            hits.append(f"{exp.kind}:{exp.value}")
        else:
            misses.append(f"{exp.kind}:{exp.value}")
    score = len(hits) / len(required)
    thr = DEFAULT_THRESHOLDS["entity_recall"]
    return MetricResult(
        "entity_recall", round(score, 3),
        detail={"hits": hits, "misses": misses,
                "found_total": len(state.entities), "required_total": len(required)},
        threshold=thr, passed=score >= thr,
    )


def entity_precision(state: SwarmState, gt: GroundTruth) -> MetricResult:
    """Fraction of found entities that are accounted for in expected (required or not).

    Anti-noise check: too many entities = the agent is being sloppy. We
    keep the threshold loose because the dictionary pass is intentionally
    eager. Tighten in P2 when LLM enrichment is gated by RAG.
    """
    if not state.entities:
        return MetricResult("entity_precision", 0.0,
                            detail={"reason": "no entities extracted"},
                            threshold=DEFAULT_THRESHOLDS["entity_precision"], passed=False)
    accounted, unaccounted = [], []
    for ent in state.entities:
        matched = any(_entity_matches([ent], exp) for exp in gt.expected_entities)
        (accounted if matched else unaccounted).append(f"{ent.kind}:{ent.value}")
    score = len(accounted) / len(state.entities)
    thr = DEFAULT_THRESHOLDS["entity_precision"]
    return MetricResult(
        "entity_precision", round(score, 3),
        detail={"accounted": len(accounted), "unaccounted": unaccounted[:10],
                "unaccounted_count": len(unaccounted)},
        threshold=thr, passed=score >= thr,
    )


# ---------------- CDT metrics ----------------

def cdt_recall_at_k(state: SwarmState, gt: GroundTruth) -> MetricResult:
    """For each required expected code, was it surfaced within its rank_within?"""
    required = [c for c in gt.expected_cdt if c.required]
    if not required:
        return MetricResult("cdt_recall_at_k", 1.0,
                            threshold=DEFAULT_THRESHOLDS["cdt_recall_at_k"],
                            detail={"required": 0}, passed=True)
    found_codes = [c.code for c in state.cdt_codes]
    hits, misses = [], []
    for exp in required:
        # 1-indexed rank
        pos = next((i + 1 for i, c in enumerate(found_codes) if c == exp.code), None)
        if pos is not None and pos <= exp.rank_within:
            hits.append(f"{exp.code}@{pos}")
        else:
            misses.append(exp.code)
    score = len(hits) / len(required)
    thr = DEFAULT_THRESHOLDS["cdt_recall_at_k"]
    return MetricResult(
        "cdt_recall_at_k", round(score, 3),
        detail={"hits": hits, "misses": misses, "found": found_codes},
        threshold=thr, passed=score >= thr,
    )


def cdt_forbidden_count(state: SwarmState, gt: GroundTruth) -> MetricResult:
    """Count of forbidden codes that nevertheless appeared. Lower is better."""
    found = {c.code for c in state.cdt_codes}
    violations = [code for code in gt.forbidden_cdt if code in found]
    thr = DEFAULT_THRESHOLDS["cdt_forbidden_count"]
    return MetricResult(
        "cdt_forbidden_count", float(len(violations)), is_rate=False,
        detail={"violations": violations},
        threshold=thr, passed=len(violations) <= thr,
    )


# ---------------- SOAP metrics ----------------

def soap_completeness(state: SwarmState, gt: GroundTruth) -> MetricResult:
    present, missing = [], []
    for sec in gt.required_soap_sections:
        if getattr(state.soap, sec, "").strip():
            present.append(sec)
        else:
            missing.append(sec)
    score = len(present) / max(len(gt.required_soap_sections), 1)
    thr = DEFAULT_THRESHOLDS["soap_completeness"]
    return MetricResult(
        "soap_completeness", round(score, 3),
        detail={"present": present, "missing": missing,
                "validator_score": state.qa.completeness_score},
        threshold=thr, passed=score >= thr,
    )


def soap_keyword_coverage(state: SwarmState, gt: GroundTruth) -> MetricResult:
    """For each required section, are the expected keywords present?"""
    if not gt.required_soap_keywords:
        return MetricResult("soap_keyword_coverage", 1.0,
                            threshold=DEFAULT_THRESHOLDS["soap_keyword_coverage"],
                            detail={"sections": 0}, passed=True)
    total, hits = 0, 0
    misses = []
    for section, kws in gt.required_soap_keywords.items():
        body = (getattr(state.soap, section, "") or "").lower()
        for kw in kws:
            total += 1
            if kw.lower() in body:
                hits += 1
            else:
                misses.append(f"{section}:'{kw}'")
    score = hits / total if total else 1.0
    thr = DEFAULT_THRESHOLDS["soap_keyword_coverage"]
    return MetricResult(
        "soap_keyword_coverage", round(score, 3),
        detail={"hits": hits, "total": total, "misses": misses},
        threshold=thr, passed=score >= thr,
    )


# ---------------- medications ----------------

def medication_coverage(state: SwarmState, gt: GroundTruth) -> MetricResult:
    if not gt.expected_medications:
        return MetricResult("medication_coverage", 1.0,
                            threshold=DEFAULT_THRESHOLDS["medication_coverage"],
                            detail={"expected": 0}, passed=True)
    joined = " ".join(state.soap.medications).lower()
    # also accept mentions inside notes_for_doctor — meds without dose end up there
    joined += " " + (state.soap.notes_for_doctor or "").lower()
    # and the entities list (NER may have captured the med name)
    joined += " " + " ".join(
        e.value.lower() for e in state.entities if e.kind == "medication"
    )
    hits, misses = [], []
    for med in gt.expected_medications:
        if med.lower() in joined:
            hits.append(med)
        else:
            misses.append(med)
    score = len(hits) / len(gt.expected_medications)
    thr = DEFAULT_THRESHOLDS["medication_coverage"]
    return MetricResult(
        "medication_coverage", round(score, 3),
        detail={"hits": hits, "misses": misses},
        threshold=thr, passed=score >= thr,
    )


# ---------------- hallucinations ----------------

def hallucination_count(state: SwarmState, gt: GroundTruth) -> MetricResult:
    """Raw count of unconfirmed terms the validator surfaced. Lower is better.

    Threshold comes from the fixture's max_hallucinations (per-fixture
    tolerance) rather than the global default, because adversarial fixtures
    legitimately expect some hallucinations to be caught.
    """
    n = len(state.qa.unconfirmed_terms)
    return MetricResult(
        "hallucination_count", float(n), is_rate=False,
        detail={"terms": state.qa.unconfirmed_terms[:15]},
        threshold=float(gt.max_hallucinations),
        passed=n <= gt.max_hallucinations,
    )


# ---------------- composite signability ----------------

# Weights chosen so that the composite reflects "could a dentist sign this?"
# Hallucinations and CDT correctness dominate; entity precision is informational.
_SIGNABILITY_WEIGHTS = {
    "entity_recall":          0.15,
    "entity_precision":       0.05,
    "cdt_recall_at_k":        0.25,
    "cdt_forbidden_penalty":  0.10,   # synthesized from cdt_forbidden_count
    "soap_completeness":      0.15,
    "soap_keyword_coverage":  0.10,
    "medication_coverage":    0.05,
    "hallucination_penalty":  0.15,   # synthesized from hallucination_count
}


def signability_score(metrics: List[MetricResult], gt: GroundTruth) -> float:
    by_name = {m.name: m for m in metrics}
    def rate(name: str) -> float:
        m = by_name.get(name)
        return float(m.score) if m else 0.0

    # convert raw counts to 0–1 penalties (1.0 = no violations, 0.0 = many)
    forbidden_pen = 1.0 if rate("cdt_forbidden_count") == 0 else max(
        0.0, 1.0 - 0.5 * rate("cdt_forbidden_count")
    )
    halluc_count = rate("hallucination_count")
    halluc_tol = max(gt.max_hallucinations, 1)
    halluc_pen = max(0.0, 1.0 - (halluc_count / (halluc_tol * 4)))

    components = {
        "entity_recall":          rate("entity_recall"),
        "entity_precision":       rate("entity_precision"),
        "cdt_recall_at_k":        rate("cdt_recall_at_k"),
        "cdt_forbidden_penalty":  forbidden_pen,
        "soap_completeness":      rate("soap_completeness"),
        "soap_keyword_coverage":  rate("soap_keyword_coverage"),
        "medication_coverage":    rate("medication_coverage"),
        "hallucination_penalty":  halluc_pen,
    }
    total_w = sum(_SIGNABILITY_WEIGHTS.values())
    score = sum(_SIGNABILITY_WEIGHTS[k] * components[k] for k in components) / total_w
    return round(score, 3)


# ---------------- public API ----------------

ALL_METRICS = (
    entity_recall,
    entity_precision,
    cdt_recall_at_k,
    cdt_forbidden_count,
    soap_completeness,
    soap_keyword_coverage,
    medication_coverage,
    hallucination_count,
)


def run_all(state: SwarmState, gt: GroundTruth) -> List[MetricResult]:
    return [fn(state, gt) for fn in ALL_METRICS]
