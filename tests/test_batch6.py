"""Batch 6 UI smoke tests — imports + pure-render checks."""
from __future__ import annotations
import importlib, pathlib, sys

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def test_theme_imports_and_exposes_helpers():
    m = importlib.import_module("ui.theme")
    assert callable(m.inject_global_css)
    assert callable(m.hero)
    assert "ds-pill" in m.GLOBAL_CSS
    assert "ds-card" in m.GLOBAL_CSS


def test_score_chip_thresholds():
    from ui.theme import score_chip
    assert "ds-score-low" in score_chip(50)
    assert "ds-score-mid" in score_chip(75)
    chip = score_chip(92)
    assert "ds-score-low" not in chip and "ds-score-mid" not in chip


def test_components_import_cleanly():
    for mod in ["ui.components.transcript_panel",
                "ui.components.agent_swarm",
                "ui.components.tooth_chart",
                "ui.components.review_panel",
                "ui.components.validator_panel",
                "ui.components.attestation",
                "ui.components.export_buttons"]:
        importlib.import_module(mod)


def test_agent_swarm_lists_seven_named_agents():
    from ui.components.agent_swarm import AGENT_DISPLAY
    names = [n for n, _ in AGENT_DISPLAY]
    assert names == ["Triage", "Scribe", "Terminologist", "Coder",
                     "Validator", "Reviewer", "Compliance"]


def test_extract_teeth_from_soap_finds_numbers():
    from ui.pages.record_page import _extract_teeth
    soap = {
        "objective":  {"findings":   [{"tooth": 19, "note": "deep caries"}]},
        "assessment": {"diagnoses":  [{"tooth": 19, "dx": "pulpitis"}]},
        "plan":       {"procedures": [{"tooth": 19, "code": "D3330"},
                                      {"tooth": 30, "code": "D2740"}]},
    }
    teeth = _extract_teeth(soap)
    assert teeth == {19, 30}
