"""Batch 4 — agent swarm tests (demo mode, no API key required)."""
from __future__ import annotations
import pathlib, sys

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.llm_client import LLMClient
from agents.swarm import Orchestrator


# Tiny but grounded transcript for the endo case
ENDO_TRANSCRIPT = """Doctor: What brings you in today?
Patient: My back left tooth has been throbbing for three days, it keeps me awake at night.
Doctor: Let me take a look. I can see deep decay on the back side of nineteen reaching the nerve.
Patient: It hurts a lot, maybe nine out of ten.
Doctor: Let's get a periapical of that one. (...) Okay, the PA shows a dark spot at the root tip.
Doctor: This is irreversible pulpitis, we need to start a root canal. I'll give you a quick exam and start the root canal today.
Doctor: I'll use lidocaine two percent with epi one to one hundred thousand, one carpule, IAN block.
Doctor: For pain, take ibuprofen six hundred every six hours as needed.
Patient: I'm on lisinopril for blood pressure, is that okay?
Doctor: That's fine, we'll just keep an eye on things.
"""

RECALL_TRANSCRIPT = """Doctor: Welcome back for your six-month recall. Any concerns?
Patient: No, everything feels fine.
Doctor: Let's do your routine check-up. Let's take four bitewings today.
Doctor: I see a small cavity starting on the upper right first molar mesial occlusal.
Doctor: I'll go ahead and fill that mesial occlusal today.
Doctor: I'll use lidocaine two percent with epi one to one hundred thousand, half carpule, infiltration.
"""


META = {
    "encounter_id": "test-1",
    "date_of_service": "2026-05-31",
    "provider": {"name": "Dr Test", "tsbde_license": "TX-DDS-99999"},
    "patient": {"patient_id": "P-1", "dob": "1985-01-01", "consent_on_file": True},
    "visit_type": "emergency",
}


def test_orchestrator_runs_end_to_end_demo_endo():
    orch = Orchestrator(LLMClient(demo=True))
    run = orch.run(transcript=ENDO_TRANSCRIPT, visit_type="emergency",
                   metadata=META, case_id="emergency_endo")
    agents = [r.agent for r in run.results]
    assert agents == ["Scribe", "Compliance", "Coder", "Validator", "Second Opinion"]
    assert run.soap is not None
    assert run.validation is not None


def test_orchestrator_endo_produces_expected_cdt():
    orch = Orchestrator(LLMClient(demo=True))
    run = orch.run(transcript=ENDO_TRANSCRIPT, visit_type="emergency",
                   metadata=META, case_id="emergency_endo")
    codes = {c["code"] for c in run.soap["billing"]["cdt_codes"]}
    # D9230 was null in demo, should be dropped
    assert {"D0140", "D0220", "D3330"} <= codes
    assert None not in codes


def test_orchestrator_recall_upgrades_composite_code():
    orch = Orchestrator(LLMClient(demo=True))
    run = orch.run(transcript=RECALL_TRANSCRIPT, visit_type="recall",
                   metadata={**META, "visit_type": "recall"}, case_id="recall_hygiene")
    codes = {c["code"] for c in run.soap["billing"]["cdt_codes"]}
    # MO = 2 surfaces -> should be promoted from D2391 to D2392
    assert "D2392" in codes
    assert "D0120" in codes
    assert "D0274" in codes


def test_validator_passes_on_demo_endo():
    orch = Orchestrator(LLMClient(demo=True))
    run = orch.run(transcript=ENDO_TRANSCRIPT, visit_type="emergency",
                   metadata=META, case_id="emergency_endo")
    v = run.validation
    # Demo fixture is intentionally clean — score should be high
    assert v["signability_score"] >= 70
    assert v["counts"]["errors"] == 0


def test_compliance_checklist_populated():
    orch = Orchestrator(LLMClient(demo=True))
    run = orch.run(transcript=ENDO_TRANSCRIPT, visit_type="emergency",
                   metadata=META, case_id="emergency_endo")
    checklist = run.soap["compliance"]["tsbde_checklist"]
    for key in ["patient_identified", "consent_documented", "license_on_record",
                "date_of_service_present", "anesthetic_documented",
                "diagnoses_present", "treatment_plan_present"]:
        assert checklist[key] is True


def test_second_opinion_flags_drug_interaction():
    orch = Orchestrator(LLMClient(demo=True))
    run = orch.run(transcript=ENDO_TRANSCRIPT, visit_type="emergency",
                   metadata=META, case_id="emergency_endo")
    so = next(r for r in run.results if r.agent == "Second Opinion")
    cats = {f["category"] for f in so.output["flags"]}
    assert "drug_interaction" in cats


def test_streaming_yields_in_order():
    orch = Orchestrator(LLMClient(demo=True))
    from agents.swarm import SwarmRun
    import uuid
    run = SwarmRun(run_id=str(uuid.uuid4()), case_id="emergency_endo",
                   transcript=ENDO_TRANSCRIPT, visit_type="emergency", metadata=META)
    seen = []
    for r in orch.run_streaming(run):
        seen.append(r.agent)
    assert seen == ["Scribe", "Compliance", "Coder", "Validator", "Second Opinion"]


def test_audit_records_carry_token_counts_or_demo_status():
    orch = Orchestrator(LLMClient(demo=True))
    run = orch.run(transcript=ENDO_TRANSCRIPT, visit_type="emergency",
                   metadata=META, case_id="emergency_endo")
    rows = run.audit_records()
    llm_agents = [r for r in rows if r.get("model")]
    assert llm_agents
    for r in llm_agents:
        # demo mode -> llm_status == "demo"
        assert r["llm_status"] == "demo"
