"""Batch 3 smoke tests — LLM client (demo mode), glossary loader, validator."""
from __future__ import annotations
import pathlib, sys, json

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.llm_client import LLMClient
from core.glossary_loader import (
    load_glossary, load_cdt_allow_list, load_visit_templates,
    load_blank_template, load_schema, glossary_compact, cdt_compact, asr_keywords,
)
from core.soap_validator import SOAPValidator
from prompts.soap_prompt import build_scribe_system_prompt, build_scribe_user_prompt
from prompts.clinical_prompts import (
    build_coder_system_prompt, build_coder_user_prompt,
    build_second_opinion_system_prompt, build_second_opinion_user_prompt,
)


# ---------- LLM client (demo mode) ----------

def test_llm_client_demo_mode_text():
    client = LLMClient(demo=True)
    canned = "demo output"
    out, rec = client.complete_text(
        agent="test", system="sys", user="hi", demo_response=canned,
    )
    assert out == canned
    assert rec.status == "demo"


def test_llm_client_demo_mode_json():
    client = LLMClient(demo=True)
    canned = {"hello": "world"}
    out, rec = client.complete_json(
        agent="test", system="sys", user="hi", demo_response=canned,
    )
    assert out == canned
    assert rec.status == "demo"


# ---------- Glossary loader ----------

def test_glossary_loaders():
    assert "anatomy" in load_glossary()
    assert load_cdt_allow_list()["codes"]
    assert "emergency" in load_visit_templates()
    assert "metadata" in load_blank_template()
    assert load_schema()["type"] == "object"


def test_glossary_compact_contains_key_terms():
    g = glossary_compact()
    for term in ["mesial", "occlusal", "pulpitis_irreversible", "lidocaine_2_epi_1_100k"]:
        assert term in g


def test_cdt_compact_contains_test_case_codes():
    c = cdt_compact()
    for code in ["D0140", "D0220", "D3330", "D9230", "D0120", "D0274", "D2391"]:
        assert code in c


def test_asr_keywords_nonempty():
    kw = asr_keywords()
    assert len(kw) > 10
    assert "occlusal" in kw


# ---------- Prompts build ----------

def test_scribe_prompt_builds():
    sys_p = build_scribe_system_prompt()
    assert "Scribe agent" in sys_p
    assert "Universal" in sys_p
    user_p = build_scribe_user_prompt("hello", "emergency", {"a": 1})
    assert "emergency" in user_p


def test_coder_prompt_builds():
    sys_p = build_coder_system_prompt()
    assert "Coder agent" in sys_p
    assert "D2391" in sys_p
    soap = {"plan": {"procedures_today": [{"procedure": "test"}]}, "objective": {"radiographs_taken": []}}
    user_p = build_coder_user_prompt(soap)
    assert "procedures_today" in user_p or "test" in user_p


def test_second_opinion_prompt_builds():
    sys_p = build_second_opinion_system_prompt()
    assert "Second-Opinion" in sys_p
    user_p = build_second_opinion_user_prompt({"foo": "bar"}, "transcript")
    assert "transcript" in user_p


# ---------- Validator: minimal valid note ----------

def _minimal_valid_soap(transcript_quote: str = "tooth nineteen hurts a lot") -> dict:
    return {
        "metadata": {
            "encounter_id": "enc-1",
            "date_of_service": "2026-05-31",
            "provider": {"name": "Dr Smith", "tsbde_license": "12345"},
            "patient": {"patient_id": "p1", "dob": "1990-01-01", "consent_on_file": True},
            "visit_type": "emergency",
        },
        "subjective": {"chief_complaint": "tooth pain"},
        "objective": {
            "exam_findings": [{
                "tooth": "19", "finding": "deep caries with pulpal exposure",
                "severity": "severe", "source_span": transcript_quote,
            }],
        },
        "assessment": {
            "diagnoses": [{
                "tooth": "19", "diagnosis": "irreversible pulpitis",
                "source_span": transcript_quote,
            }],
        },
        "plan": {
            "procedures_today": [{
                "procedure": "limited exam", "tooth": "19",
                "source_span": transcript_quote,
            }],
            "follow_up": "endo consult next week",
        },
        "billing": {"cdt_codes": [{
            "code": "D0140", "tooth": "19",
            "rationale": "limited oral evaluation",
            "source_span": transcript_quote,
        }]},
        "compliance": {"tsbde_checklist": {}},
        "grounding": {"transcript_excerpts": [{
            "span_id": "s1", "text": transcript_quote, "speaker": "patient",
        }]},
    }


def test_validator_accepts_minimal_valid():
    v = SOAPValidator()
    soap = _minimal_valid_soap()
    report = v.validate(soap, transcript="My tooth nineteen hurts a lot, doctor.")
    assert report.valid, [i.message for i in report.errors]
    assert report.signability_score >= 80


def test_validator_catches_hallucinated_cdt():
    v = SOAPValidator()
    soap = _minimal_valid_soap()
    soap["billing"]["cdt_codes"][0]["code"] = "D9999"  # not in allow-list
    report = v.validate(soap, transcript="My tooth nineteen hurts a lot, doctor.")
    assert not report.valid
    assert any(i.layer == "cdt" and i.severity == "error" for i in report.issues)


def test_validator_catches_ungrounded_claim():
    v = SOAPValidator()
    soap = _minimal_valid_soap("a quote NOT in the transcript")
    report = v.validate(soap, transcript="Patient says nothing useful here.")
    assert not report.valid
    assert any(i.layer == "grounding" and i.severity == "error" for i in report.issues)


def test_validator_catches_missing_texas_license():
    v = SOAPValidator()
    soap = _minimal_valid_soap()
    soap["metadata"]["provider"]["tsbde_license"] = ""
    report = v.validate(soap, transcript="My tooth nineteen hurts a lot, doctor.")
    assert any(i.layer == "texas" and "tsbde_license" in i.path for i in report.issues)


def test_signability_score_drops_with_severity():
    v = SOAPValidator()
    soap = _minimal_valid_soap()
    clean = v.validate(soap, transcript="My tooth nineteen hurts a lot, doctor.")
    soap["billing"]["cdt_codes"][0]["code"] = "D9999"
    dirty = v.validate(soap, transcript="My tooth nineteen hurts a lot, doctor.")
    assert dirty.signability_score < clean.signability_score
