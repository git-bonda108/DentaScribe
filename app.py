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

st.set_page_config(
    page_title="DentaScribe — Clinical AI Scribe",
    page_icon="🦷",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Inject the global design system FIRST so every page inherits it.
from ui.theme import inject_global_css, COLORS
inject_global_css()

try:
    from storage.db import init_db
    init_db()
except Exception:
    pass

from ui.pages.record_page import render as render_record
from ui.pages.audit_page  import render as render_audit
from ui.pages.admin_page  import render as render_admin


PAGES = {
    "🩺  Record":  render_record,
    "📜  Audit":   render_audit,
    "⚙️  Admin":   render_admin,
}


# ---------------- sidebar ----------------

def _sidebar_brand() -> None:
    """Branded sidebar header with a live status dot."""
    has_key = bool(os.getenv("ANTHROPIC_API_KEY"))
    mode = st.session_state.get("ds_mode", "Demo")
    dot_color = "#4DD4AC" if (mode == "Live (Claude)" and has_key) else "#9AA6B8"
    dot_label = "LIVE" if (mode == "Live (Claude)" and has_key) else "DEMO"

    st.markdown(
        f'<div style="padding:18px 12px 4px 12px;">'
        f'  <div style="display:flex;align-items:center;gap:10px;">'
        f'    <div style="font-size:26px;">🦷</div>'
        f'    <div>'
        f'      <div style="font-weight:700;color:#FFFFFF;font-size:17px;'
        f'                  letter-spacing:-0.02em;line-height:1;">DentaScribe</div>'
        f'      <div style="font-size:11px;color:#9AA6B8;letter-spacing:0.04em;'
        f'                  margin-top:3px;">Dallas, TX · 22 TAC §108.8</div>'
        f'    </div>'
        f'  </div>'
        f'  <div style="display:inline-flex;align-items:center;gap:6px;'
        f'              margin-top:14px;padding:3px 9px;'
        f'              border-radius:999px;background:rgba(77,212,172,0.06);'
        f'              border:1px solid rgba(255,255,255,0.10);">'
        f'    <span style="width:7px;height:7px;border-radius:50%;'
        f'                 background:{dot_color};box-shadow:0 0 8px {dot_color}aa;"></span>'
        f'    <span style="font-size:10px;font-weight:700;letter-spacing:0.10em;'
        f'                 color:{dot_color};">{dot_label}</span>'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _sidebar_section_label(text: str) -> None:
    st.markdown(
        f'<div style="font-size:10px;font-weight:600;letter-spacing:0.12em;'
        f'text-transform:uppercase;color:#6B7790;margin:18px 12px 8px;">{text}</div>',
        unsafe_allow_html=True,
    )


with st.sidebar:
    _sidebar_brand()

    _sidebar_section_label("Navigation")
    choice = st.radio("Pages", list(PAGES.keys()), label_visibility="collapsed")

    _sidebar_section_label("Agent mode")
    has_key = bool(os.getenv("ANTHROPIC_API_KEY"))
    if "ds_mode" not in st.session_state:
        st.session_state["ds_mode"] = "Demo"
    mode = st.radio(
        "Mode",
        ["Demo", "Live (Claude)"],
        index=0 if st.session_state["ds_mode"] == "Demo" else 1,
        label_visibility="collapsed",
        help="Live mode calls Claude. Tokens are billed; cost is shown per run.",
    )
    st.session_state["ds_mode"] = mode

    if mode == "Live (Claude)":
        if not has_key:
            st.markdown(
                '<div style="margin:6px 12px;padding:10px;border-radius:8px;'
                'background:rgba(242,109,109,0.08);border:1px solid rgba(242,109,109,0.25);'
                'font-size:12px;color:#F26D6D;">'
                '⚠ ANTHROPIC_API_KEY not set — falling back to Demo.</div>',
                unsafe_allow_html=True,
            )
            st.session_state["ds_mode"] = "Demo"
        else:
            st.markdown(
                '<div style="margin:6px 12px;font-size:11px;color:#9AA6B8;'
                'line-height:1.45;">'
                'Model · <code style="color:#E5E9F2;">claude-sonnet-4-5</code><br>'
                'Pricing · $3 / Mtok in, $15 / Mtok out<br>'
                '<span style="color:#6B7790;">≈ $0.02–$0.10 per consultation</span>'
                '</div>',
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            '<div style="margin:6px 12px;font-size:11px;color:#9AA6B8;'
            'line-height:1.45;">'
            'Locked fixtures · $0 · ~0 ms<br>'
            '<span style="color:#6B7790;">Same code path as Live, with the LLM stubbed.</span>'
            '</div>',
            unsafe_allow_html=True,
        )

    # Last-run cost chip
    last_cost = st.session_state.get("ds_last_cost")
    if last_cost is not None:
        _sidebar_section_label("Last run")
        from core.cost import format_usd
        total_tok = last_cost["total_tokens_in"] + last_cost["total_tokens_out"]
        st.markdown(
            f'<div style="margin:6px 12px 0;padding:14px;border-radius:12px;'
            f'background:linear-gradient(180deg,#121A2D 0%,#0F172A 100%);'
            f'border:1px solid rgba(255,255,255,0.08);">'
            f'  <div style="font-size:11px;color:#6B7790;letter-spacing:0.08em;'
            f'              text-transform:uppercase;font-weight:600;">Cost</div>'
            f'  <div style="font-size:24px;font-weight:700;color:#FFFFFF;'
            f'              font-family:\'JetBrains Mono\',monospace;'
            f'              margin-top:2px;">{format_usd(last_cost["total_usd"])}</div>'
            f'  <div style="font-size:11px;color:#9AA6B8;margin-top:4px;">'
            f'{total_tok:,} tokens · {last_cost.get("live_calls",0)} live · '
            f'{last_cost.get("demo_calls",0)} demo</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # Footer
    st.markdown(
        '<div style="position:absolute;bottom:18px;left:12px;right:12px;'
        'padding-top:14px;border-top:1px solid rgba(255,255,255,0.06);'
        'font-size:10.5px;color:#6B7790;line-height:1.5;">'
        'DentaScribe MVP · v0.1<br>'
        '<span style="color:#4B5468;">Clinical scribe + Texas compliance + dual-model verification</span>'
        '</div>',
        unsafe_allow_html=True,
    )

# ---------------- page router ----------------

PAGES[choice]()
