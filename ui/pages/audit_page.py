"""Audit trail page."""
from __future__ import annotations
import streamlit as st
from ui.theme import inject_global_css, hero, card_open, card_close


def render() -> None:
    inject_global_css()
    hero("Audit trail",
         "Every agent invocation is logged: model, tokens, latency, prompt hash. "
         "Filter by encounter to investigate a specific note.",
         pill="DENTASCRIBE  •  AUDIT")
    try:
        from storage.db import list_encounters, audit_log_for_encounter
        encs = list_encounters()
    except Exception as e:
        st.error(f"Storage not initialized: {e}")
        return
    if not encs:
        st.info("No encounters yet. Record one on the Record page.")
        return
    options = {f"{e['date_of_service']}  •  {e['visit_type']}  •  {e['patient_id']}": e["encounter_id"]
               for e in encs}
    pick = st.selectbox("Encounter", list(options.keys()))
    rows = audit_log_for_encounter(options[pick])
    card_open(f"Calls — {len(rows)} entries")
    if not rows:
        st.caption("No audit entries.")
    else:
        st.dataframe(
            [{"agent": r["agent"], "model": r["model"], "status": r["status"],
              "llm": r["llm_status"], "in": r["input_tokens"], "out": r["output_tokens"],
              "latency_ms": r["latency_ms"], "at": r["created_at"],
              "prompt_hash": (r["prompt_hash"] or "")[:10]} for r in rows],
            use_container_width=True, hide_index=True,
        )
    card_close()
