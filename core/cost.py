"""Token-usage → USD cost computation for the agent swarm.

Why this module exists:
  Marketplace launch needs a defensible per-consultation cost. The
  LLMClient already records `input_tokens` / `output_tokens` on every
  call (`core.llm_client.LLMCall`). This module turns those into dollars
  and exposes a clean per-agent + total breakdown the UI can show.

Pricing source:
  Anthropic API list price for `claude-sonnet-4-5` as of 2025-Q4.
  Update PRICES_USD_PER_M_TOKENS if Anthropic adjusts pricing or you
  switch the default model. Cached models (input/cache_read) and batch
  pricing are not modeled here — those are minor optimizations once we
  have real volume.

Cost in DEMO mode is always $0.00 (no API call made).
"""
from __future__ import annotations
from typing import Iterable, Dict, List


# USD per 1M tokens. {model_id: (input_rate, output_rate)}
# Anthropic published rates; keep this in sync if you change models.
PRICES_USD_PER_M_TOKENS: Dict[str, tuple[float, float]] = {
    "claude-sonnet-4-5":  (3.00, 15.00),
    "claude-sonnet-4-6":  (3.00, 15.00),
    "claude-opus-4":      (15.00, 75.00),
    "claude-haiku-4-5":   (1.00,  5.00),
    # Fallback for unknown model ids
    "_default":           (3.00, 15.00),
}


def cost_for_call(model: str, input_tokens: int, output_tokens: int) -> float:
    """USD cost for one LLM call. Returns 0.0 for demo / unknown / 0-token."""
    if not model or (not input_tokens and not output_tokens):
        return 0.0
    in_rate, out_rate = PRICES_USD_PER_M_TOKENS.get(
        model, PRICES_USD_PER_M_TOKENS["_default"]
    )
    return round(
        (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000,
        6,  # six decimal places — single calls can be a fraction of a cent
    )


def cost_breakdown(audit_records: Iterable[dict]) -> Dict[str, object]:
    """Aggregate cost across all agents in a SwarmRun's audit_records.

    Each row in audit_records is expected to have (at minimum):
       agent, model, input_tokens, output_tokens, llm_status

    Returns:
       {
         "total_usd":       float,
         "total_tokens_in":  int,
         "total_tokens_out": int,
         "by_agent": [
             {agent, model, input_tokens, output_tokens, usd, demo: bool},
             ...
         ],
         "live_calls":  int,
         "demo_calls":  int,
       }
    """
    by_agent: List[dict] = []
    total = 0.0
    tot_in = tot_out = 0
    live = demo = 0
    for r in audit_records or []:
        model = r.get("model") or ""
        in_tok = int(r.get("input_tokens") or 0)
        out_tok = int(r.get("output_tokens") or 0)
        is_demo = (r.get("llm_status") == "demo") or (in_tok == 0 and out_tok == 0)
        usd = 0.0 if is_demo else cost_for_call(model, in_tok, out_tok)
        by_agent.append({
            "agent": r.get("agent", "?"),
            "model": model,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "usd": usd,
            "demo": is_demo,
        })
        total += usd
        tot_in += in_tok
        tot_out += out_tok
        live += 0 if is_demo else 1
        demo += 1 if is_demo else 0
    return {
        "total_usd": round(total, 4),
        "total_tokens_in": tot_in,
        "total_tokens_out": tot_out,
        "by_agent": by_agent,
        "live_calls": live,
        "demo_calls": demo,
    }


def format_usd(amount: float) -> str:
    """User-friendly money formatter: $0.0123 for small, $0.12 for usual."""
    if amount <= 0:
        return "$0.00"
    if amount < 0.01:
        return f"${amount:.4f}"
    return f"${amount:.2f}"
