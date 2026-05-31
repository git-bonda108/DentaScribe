"""Cost telemetry tests — verifies token→USD math and demo-cost gating."""
from __future__ import annotations
import pathlib, sys
ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.cost import cost_for_call, cost_breakdown, format_usd


def test_cost_for_call_sonnet_known_math():
    # 1M input + 1M output on claude-sonnet-4-5 should be $3 + $15 = $18.00
    usd = cost_for_call("claude-sonnet-4-5", 1_000_000, 1_000_000)
    assert abs(usd - 18.0) < 1e-6


def test_cost_for_call_handles_zero_tokens():
    assert cost_for_call("claude-sonnet-4-5", 0, 0) == 0.0


def test_cost_for_call_falls_back_to_default_for_unknown_model():
    # Unknown model uses default rates ($3 in / $15 out per M)
    usd = cost_for_call("some-future-model", 500_000, 100_000)
    expected = (500_000 * 3.0 + 100_000 * 15.0) / 1_000_000
    assert abs(usd - expected) < 1e-6


def test_cost_breakdown_aggregates_across_agents():
    # Two live calls + one demo call → demo contributes 0 USD
    records = [
        {"agent": "scribe", "model": "claude-sonnet-4-5", "input_tokens": 1000, "output_tokens": 500, "llm_status": "ok"},
        {"agent": "coder",  "model": "claude-sonnet-4-5", "input_tokens": 800,  "output_tokens": 200, "llm_status": "ok"},
        {"agent": "second", "model": "claude-sonnet-4-5", "input_tokens": 0,    "output_tokens": 0,   "llm_status": "demo"},
    ]
    b = cost_breakdown(records)
    expected_live = (1000 * 3.0 + 500 * 15.0 + 800 * 3.0 + 200 * 15.0) / 1_000_000
    assert abs(b["total_usd"] - round(expected_live, 4)) < 1e-4
    assert b["total_tokens_in"] == 1800
    assert b["total_tokens_out"] == 700
    assert b["live_calls"] == 2
    assert b["demo_calls"] == 1
    assert len(b["by_agent"]) == 3
    assert b["by_agent"][2]["usd"] == 0.0  # demo row is zero-cost


def test_cost_breakdown_empty():
    b = cost_breakdown([])
    assert b["total_usd"] == 0.0
    assert b["by_agent"] == []
    assert b["live_calls"] == 0


def test_format_usd_small_and_normal():
    assert format_usd(0.0) == "$0.00"
    assert format_usd(0.005) == "$0.0050"      # sub-cent shows 4dp
    assert format_usd(0.0123) == "$0.01"       # >= 1 cent uses normal 2dp
    assert format_usd(1.234) == "$1.23"        # normal money: 2dp
