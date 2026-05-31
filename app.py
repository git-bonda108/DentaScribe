"""DentaScribe — Streamlit entrypoint.

Three pages:
  Record  — capture/upload/paste, run swarm, sign, export.
  Audit   — per-encounter agent call log.
  Admin   — Texas retention sweep.

Sidebar exposes a **Demo / Live** mode toggle. When Live is selected (and
`ANTHROPIC_API_KEY` is present), the agent swarm calls the real Claude model.
Demo mode runs everything against locked fixtures — useful for sales demos
and the unit tests.

Run:  streamlit run app.py
"""
from __future__ import annotations
import os
import streamlit as st

# Load .env BEFORE anything that reads env vars (LLMClient checks at import time).
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except Exception:
    pass

st.set_page_config(page_title="DentaScribe", page_icon="🦷",
                   layout="wide", initial_sidebar_state="expanded")

try:
    from storage.db import init_db
    init_db()
except Exception:
    pass

from ui.pages.record_page import render as render_record
from ui.pages.audit_page  import render as render_audit
from ui.pages.admin_page  import render as render_admin

PAGES = {"🩺  Record": render_record,
         "📜  Audit":  render_audit,
         "⚙️  Admin":  render_admin}

# ---------------- sidebar ----------------

with st.sidebar:
    st.markdown("### 🦷 DentaScribe")
    st.caption("Dallas, TX • 22 TAC §108.8 aware")
    choice = st.radio("Pages", list(PAGES.keys()), label_visibility="collapsed")
    st.divider()

    # Mode toggle. Default = Demo unless the user explicitly flips it.
    has_key = bool(os.getenv("ANTHROPIC_API_KEY"))
    if "ds_mode" not in st.session_state:
        st.session_state["ds_mode"] = "Demo"

    mode = st.radio(
        "Agent mode",
        ["Demo", "Live (Claude)"],
        index=0 if st.session_state["ds_mode"] == "Demo" else 1,
        help="Live mode calls the Anthropic API for real. Tokens are billed; "
             "cost is shown after each run.",
    )
    st.session_state["ds_mode"] = mode

    if mode == "Live (Claude)":
        if not has_key:
            st.error("ANTHROPIC_API_KEY not set — falling back to Demo.")
            st.session_state["ds_mode"] = "Demo"
        else:
            st.success("Live: claude-sonnet-4-5 ready.")
            st.caption("Pricing: $3 / Mtok input, $15 / Mtok output. "
                       "Typical consultation ≈ $0.02–$0.10.")
    else:
        st.info("Demo mode: locked fixtures, no API calls, $0 cost.")

    # Last-run cost chip (populated by record_page after each run)
    last_cost = st.session_state.get("ds_last_cost")
    if last_cost is not None:
        from core.cost import format_usd
        st.metric("Last run", format_usd(last_cost["total_usd"]),
                  f"{last_cost['total_tokens_in']+last_cost['total_tokens_out']:,} tok")

    st.divider()
    st.caption("MVP build • Demo mode if no API keys")

# ---------------- page router ----------------

PAGES[choice]()
