"""Batch 2 smoke tests — schema, templates, normalizers."""
from __future__ import annotations
import json, pathlib, sys

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from data.tooth_norm import normalize_tooth, describe_tooth
from data.surface_norm import normalize_surfaces, surface_count


def _load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def test_schema_loads_and_has_required_top_level():
    schema = _load("data/soap_schema.json")
    assert schema["type"] == "object"
    for k in ["metadata", "subjective", "objective", "assessment", "plan", "billing", "compliance", "grounding"]:
        assert k in schema["required"], f"schema missing required: {k}"


def test_texas_blank_template_complies_with_schema_shape():
    tpl = _load("data/texas_blank_soap_template.json")
    # required top-level keys exist
    for k in ["metadata", "subjective", "objective", "assessment", "plan", "billing", "compliance", "grounding"]:
        assert k in tpl
    # Texas regulatory anchor present
    assert "_texas_compliance_notes" in tpl
    assert "22 TAC" in tpl["_texas_compliance_notes"]["regulatory_basis"]


def test_visit_types_cover_core_workflows():
    vt = _load("data/visit_type_templates.json")
    for must in ["emergency", "restorative", "endo", "new_patient_exam", "recall_exam"]:
        assert must in vt


def test_cdt_allow_list_format():
    cdt = _load("data/cdt_allow_list.json")
    codes = {c["code"] for c in cdt["codes"]}
    # codes used by the two locked test cases
    for required in ["D0140", "D0220", "D3330", "D9230",  # case 1 emergency endo
                     "D0120", "D0274", "D2391"]:          # case 2 occlusal composite
        assert required in codes, f"CDT allow-list missing {required}"


def test_glossary_loads():
    gl = _load("data/dental_glossary.json")
    for cat in ["anatomy", "conditions", "procedures", "anesthetics", "drugs_common", "asr_corrections"]:
        assert cat in gl


def test_tooth_norm():
    assert normalize_tooth("19") == "19"
    assert normalize_tooth("#19") == "19"
    assert normalize_tooth("tooth 19") == "19"
    assert normalize_tooth("lower left first molar") == "19"
    assert normalize_tooth("lower right first molar") == "30"
    assert normalize_tooth("garbage") is None
    assert "lower left" in describe_tooth(19)


def test_surface_norm():
    assert normalize_surfaces("MOD") == ["M", "O", "D"]
    assert normalize_surfaces("mesial occlusal") == ["M", "O"]
    assert normalize_surfaces(["mesial", "occlusal"]) == ["M", "O"]
    assert surface_count("MOD") == 3
    assert normalize_surfaces("junk") == []
