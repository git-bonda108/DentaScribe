"""Tests for the Dental Coach agent (live, tool-using clinical advisor).

We can't exercise the real Anthropic tool-use loop without API cost, so we:
  - Test each of the 6 deterministic tools directly (no LLM involved)
  - Test the demo-mode coach (no LLM) end-to-end via DentalCoach.coach()
  - Test the dedupe cache + recommendation fingerprinting
  - Test the JSON-parsing helper that strips fences

The live Claude tool-use loop is exercised by the integration test in
eval/coach_smoke.py (manual; uses budget).
"""
from __future__ import annotations
import pathlib, sys
ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from agents.coach_agent import (
    CoachTools, DentalCoach, Recommendation, _parse_json,
)


# ---------- Recommendation fingerprinting + dedupe ----------

def test_recommendation_fingerprint_is_stable():
    r1 = Recommendation(category="safety", severity="high",
                         message="Ibuprofen + lisinopril interaction",
                         suggested_action="Use acetaminophen.")
    r2 = Recommendation(category="safety", severity="high",
                         message="Ibuprofen + lisinopril interaction",
                         suggested_action="Different action wording.")
    # Same category + same message → same fingerprint (dedupe target)
    assert r1.fingerprint == r2.fingerprint


def test_recommendation_fingerprint_changes_per_tooth():
    r1 = Recommendation(category="differential", severity="medium",
                         message="Test pulp", suggested_action="cold test",
                         tooth_ref="19")
    r2 = Recommendation(category="differential", severity="medium",
                         message="Test pulp", suggested_action="cold test",
                         tooth_ref="30")
    assert r1.fingerprint != r2.fingerprint


# ---------- Tool: check_drug_interaction ----------

def test_drug_interaction_ibuprofen_lisinopril_flagged():
    tools = CoachTools()
    r = tools.check_drug_interaction("ibuprofen", "lisinopril")
    assert r["has_interaction"] is True
    assert r["severity"] in ("medium", "high")
    assert r["source"] == "glossary.drugs_common"


def test_drug_interaction_safe_pair_not_flagged():
    tools = CoachTools()
    r = tools.check_drug_interaction("acetaminophen", "amoxicillin")
    assert r["has_interaction"] is False


def test_drug_interaction_is_order_independent():
    tools = CoachTools()
    r1 = tools.check_drug_interaction("ibuprofen", "lisinopril")
    r2 = tools.check_drug_interaction("lisinopril", "ibuprofen")
    assert r1["has_interaction"] == r2["has_interaction"]


# ---------- Tool: lookup_dental_term ----------

def test_lookup_dental_term_finds_caries():
    tools = CoachTools()
    r = tools.lookup_dental_term("caries")
    assert r["found"] is True
    assert r["category"] == "conditions"
    assert "decay" in r["definition"].lower() or "demineralization" in r["definition"].lower()


def test_lookup_dental_term_unknown_returns_not_found():
    tools = CoachTools()
    r = tools.lookup_dental_term("zorglub")
    assert r["found"] is False


# ---------- Tool: cdt_candidates_for ----------

def test_cdt_candidates_for_root_canal_returns_endo_codes():
    tools = CoachTools()
    cands = tools.cdt_candidates_for("root canal molar tooth 19")
    assert len(cands) >= 1
    # At least one of D3310/D3320/D3330 should appear
    codes = [c["code"] for c in cands]
    assert any(c.startswith("D33") for c in codes), f"no endodontic codes in {codes}"


def test_cdt_candidates_for_empty_returns_empty():
    tools = CoachTools()
    assert tools.cdt_candidates_for("") == []


# ---------- Tool: assess_pulpal_status ----------

def test_pulpal_status_irreversible_signature():
    tools = CoachTools()
    r = tools.assess_pulpal_status(
        "pain throbs at night, wakes me up, lingering after cold"
    )
    assert r["likely"] == "irreversible_pulpitis"
    assert any("cold" in t.lower() for t in r["recommended_tests"])


def test_pulpal_status_reversible_signature():
    tools = CoachTools()
    r = tools.assess_pulpal_status(
        "Brief cold sensitivity that stops when the stimulus is removed."
    )
    assert r["likely"] == "reversible_pulpitis"


def test_pulpal_status_indeterminate_with_no_hints():
    tools = CoachTools()
    r = tools.assess_pulpal_status("It hurts a little.")
    assert r["likely"] == "indeterminate"


# ---------- Tool: required_objective_for ----------

def test_required_objective_for_emergency_visit():
    tools = CoachTools()
    r = tools.required_objective_for("emergency")
    assert "required_objective" in r
    # The architect's emergency template requires exam findings + rads
    required = " ".join(r["required_objective"]).lower()
    assert "exam_findings" in required
    assert "radiograph" in required
    # And the CDT allow-list should contain emergency exam + endo codes
    allow = r["cdt_allow_list"]
    assert any(c == "D0140" for c in allow), f"expected D0140 in {allow}"


def test_required_objective_for_unknown_visit_returns_empty_safely():
    tools = CoachTools()
    r = tools.required_objective_for("ufo_consult")
    assert r["required_objective"] == []
    assert r["cdt_allow_list"] == []


# ---------- Tool: check_tsbde_anchor_block ----------

def test_tsbde_anchor_complete_record():
    tools = CoachTools()
    r = tools.check_tsbde_anchor_block({
        "encounter_meta": {
            "date_of_service": "2026-05-31",
            "provider": {"name": "Dr A", "tsbde_license": "TX-1"},
            "patient": {"patient_id": "P1", "consent_on_file": True},
        },
    })
    assert r["complete"] is True
    assert r["missing_fields"] == []


def test_tsbde_anchor_flags_missing_license_and_consent():
    tools = CoachTools()
    r = tools.check_tsbde_anchor_block({
        "encounter_meta": {
            "date_of_service": "2026-05-31",
            "provider": {"name": "Dr A"},        # missing license
            "patient": {"patient_id": "P1"},     # missing consent
        },
    })
    assert r["complete"] is False
    missing = " ".join(r["missing_fields"]).lower()
    assert "tsbde" in missing or "license" in missing
    assert "consent" in missing


# ---------- Coach end-to-end (demo mode, no LLM) ----------

class _DemoLLM:
    """Minimal stub matching the LLMClient.demo interface."""
    demo = True
    model = "claude-sonnet-4-5"
    _anthropic = None


def test_coach_demo_flags_drug_interaction_when_both_drugs_mentioned():
    coach = DentalCoach(_DemoLLM())
    transcript = (
        "Doctor: Hi, what brings you in?\n"
        "Patient: Severe tooth pain. I am on lisinopril for blood pressure.\n"
        "Doctor: For pain, take ibuprofen 400 mg every six hours."
    )
    recs = coach.coach(transcript, visit_type="emergency")
    categories = [r.category for r in recs]
    assert "safety" in categories, f"got {categories}"
    safety = next(r for r in recs if r.category == "safety")
    assert safety.severity == "high"
    assert "lisinopril" in safety.evidence_quote.lower()


def test_coach_dedupes_within_session():
    coach = DentalCoach(_DemoLLM())
    transcript = "Patient: I am on lisinopril.\nDoctor: Take ibuprofen 400 mg."
    first = coach.coach(transcript, visit_type="emergency")
    assert len(first) >= 1
    # Run again with same content — should not re-emit
    second = coach.coach(transcript, visit_type="emergency")
    fingerprints_first = {r.fingerprint for r in first}
    fingerprints_second = {r.fingerprint for r in second}
    assert fingerprints_first.isdisjoint(fingerprints_second), \
        "demo coach re-emitted the same recommendation"


def test_coach_caps_at_max_recs_per_call():
    coach = DentalCoach(_DemoLLM(), max_recs_per_call=2)
    transcript = (
        "Patient: I am on lisinopril.\n"
        "Doctor: For pain take ibuprofen.\n"
        "Patient: It throbs at night, wakes me up, lingering after cold."
    )
    recs = coach.coach(transcript, visit_type="emergency")
    assert len(recs) <= 2


def test_coach_reset_clears_fingerprints():
    coach = DentalCoach(_DemoLLM())
    transcript = "Patient: lisinopril.\nDoctor: ibuprofen."
    coach.coach(transcript)
    assert coach.total_recommendations >= 1
    coach.reset()
    assert coach.total_recommendations == 0
    # Now the same input should re-emit
    new = coach.coach(transcript)
    assert len(new) >= 1


# ---------- JSON parsing helper ----------

def test_parse_json_strips_fenced_block():
    raw = '```json\n{"recommendations": [{"category":"safety","severity":"high","message":"x","suggested_action":"y"}]}\n```'
    data = _parse_json(raw)
    assert data["recommendations"][0]["category"] == "safety"


def test_parse_json_handles_prose_around_json():
    raw = 'Here is the output:\n{"recommendations": []}\nLet me know if you need more.'
    data = _parse_json(raw)
    assert data == {"recommendations": []}


def test_parse_json_returns_empty_on_garbage():
    assert _parse_json("not json at all") == {"recommendations": []}
