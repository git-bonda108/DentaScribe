"""DentaScribe — Streamlit entrypoint.

Three pages:
  Record  — capture/upload/paste, run swarm, sign, export.
  Audit   — per-encounter agent call log.
  Admin   — Texas retention sweep.

Sidebar exposes:
  - Page navigation
  - Agent mode (Demo / Live Claude)
  - Coach mode (live recording recommendations on/off)
  - Last-run cost chip
  - Brand footer

Visual language: Arini-inspired light clinical theme. Navy on white, teal
accent used sparingly, generous whitespace.

Run:  streamlit run app.py
"""
from __future__ import annotations
import os
import streamlit as st

# Load .env BEFORE anything that reads env vars
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


# ---------------- sidebar helpers ----------------

def _sidebar_brand() -> None:
    """Branded sidebar header with a live status dot. Light theme palette."""
    has_key = bool(os.getenv("ANTHROPIC_API_KEY"))
    mode = st.session_state.get("ds_mode", "Demo")
    is_live = mode == "Live (Claude)" and has_key
    dot_color = "#0EA5A4" if is_live else "#8A95AB"
    dot_label = "LIVE" if is_live else "DEMO"
    dot_bg    = "rgba(14,165,164,0.10)" if is_live else "rgba(138,149,171,0.10)"
    dot_brdr  = "rgba(14,165,164,0.25)" if is_live else "rgba(138,149,171,0.25)"

    st.markdown(
        f'<div style="padding:18px 12px 4px 12px;">'
        f'  <div style="display:flex;align-items:center;gap:12px;">'
        f'    <div style="font-size:28px;line-height:1;">🦷</div>'
        f'    <div>'
        f'      <div style="font-weight:700;color:#0B1426;font-size:18px;'
        f'                  letter-spacing:-0.02em;line-height:1;font-family:'
        f"'Inter Tight','Inter',sans-serif;\">DentaScribe</div>"
        f'      <div style="font-size:11px;color:#5A6478;letter-spacing:0.04em;'
        f'                  margin-top:3px;">Dallas, TX · 22 TAC §108.8</div>'
        f'    </div>'
        f'  </div>'
        f'  <div style="display:inline-flex;align-items:center;gap:6px;'
        f'              margin-top:16px;padding:3px 10px;'
        f'              border-radius:999px;background:{dot_bg};'
        f'              border:1px solid {dot_brdr};">'
        f'    <span style="width:7px;height:7px;border-radius:50%;'
        f'                 background:{dot_color};"></span>'
        f'    <span style="font-size:10px;font-weight:700;letter-spacing:0.10em;'
        f'                 color:{dot_color};">{dot_label}</span>'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _sidebar_section_label(text: str) -> None:
    st.markdown(
        f'<div style="font-size:10px;font-weight:600;letter-spacing:0.12em;'
        f'text-transform:uppercase;color:#8A95AB;margin:20px 12px 8px;">{text}</div>',
        unsafe_allow_html=True,
    )


# ---------------- sidebar build ----------------

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
        help="Live mode calls the Anthropic API for real. Cost is shown per run.",
    )
    st.session_state["ds_mode"] = mode

    if mode == "Live (Claude)":
        if not has_key:
            st.markdown(
                '<div style="margin:6px 12px;padding:10px 12px;border-radius:10px;'
                'background:rgba(185,28,28,0.05);border:1px solid rgba(185,28,28,0.20);'
                'font-size:12px;color:#B91C1C;">'
                '⚠ ANTHROPIC_API_KEY not set — falling back to Demo.</div>',
                unsafe_allow_html=True,
            )
            st.session_state["ds_mode"] = "Demo"
        else:
            st.markdown(
                '<div style="margin:6px 12px;font-size:11px;color:#5A6478;line-height:1.5;">'
                'Model · <code style="color:#0B1426;background:#F4F6F9;padding:1px 5px;border-radius:4px;">'
                'claude-sonnet-4-5</code><br>'
                'Pricing · $3 / Mtok in, $15 / Mtok out<br>'
                '<span style="color:#8A95AB;">≈ $0.02–$0.10 per consultation</span>'
                '</div>',
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            '<div style="margin:6px 12px;font-size:11px;color:#5A6478;line-height:1.5;">'
            'Locked fixtures · $0 · ~0 ms<br>'
            '<span style="color:#8A95AB;">Same code path as Live, with the LLM stubbed.</span>'
            '</div>',
            unsafe_allow_html=True,
        )

    # Coach mode toggle — live recording recommendations
    _sidebar_section_label("Coaching")
    coach_on = st.toggle(
        "🩺  Coach mode",
        value=st.session_state.get("ds_coach_enabled", True),
        help=("Surfaces drug interactions, history gaps, diagnostic tests, "
              "documentation misses, and CDT codes accumulating — live, "
              "during the recording."),
    )
    st.session_state["ds_coach_enabled"] = coach_on
    if coach_on:
        st.markdown(
            '<div style="margin:6px 12px;font-size:11px;color:#5A6478;line-height:1.5;">'
            'Trigger · speaker change OR every 15s<br>'
            'Tools · drug-interaction · CDT · pulpal · TSBDE-anchor · glossary<br>'
            '<span style="color:#8A95AB;">≈ +$0.10–0.20 per consultation in Live mode</span>'
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div style="margin:6px 12px;font-size:11px;color:#8A95AB;line-height:1.5;">'
            'Coach is silent. Recording + transcript still work; just no '
            'live recommendations.</div>',
            unsafe_allow_html=True,
        )

    # Last-run cost chip
    last_cost = st.session_state.get("ds_last_cost")
    if last_cost is not None:
        _sidebar_section_label("Last run")
        from core.cost import format_usd
        total_tok = last_cost["total_tokens_in"] + last_cost["total_tokens_out"]
        st.markdown(
            f'<div style="margin:6px 12px 0;padding:14px 16px;border-radius:12px;'
            f'background:#FFFFFF;border:1px solid #EEF1F5;'
            f'box-shadow:0 1px 2px rgba(11,20,38,0.04);">'
            f'  <div style="font-size:10px;color:#8A95AB;letter-spacing:0.08em;'
            f'              text-transform:uppercase;font-weight:600;">Cost</div>'
            f'  <div style="font-size:24px;font-weight:700;color:#0B1426;'
            f'              font-family:\'JetBrains Mono\',monospace;'
            f'              margin-top:3px;letter-spacing:-0.01em;">{format_usd(last_cost["total_usd"])}</div>'
            f'  <div style="font-size:11px;color:#5A6478;margin-top:4px;">'
            f'{total_tok:,} tokens · {last_cost.get("live_calls",0)} live · '
            f'{last_cost.get("demo_calls",0)} demo</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # Footer
    st.markdown(
        '<div style="position:absolute;bottom:18px;left:12px;right:12px;'
        'padding-top:16px;border-top:1px solid #EEF1F5;'
        'font-size:10.5px;color:#8A95AB;line-height:1.55;">'
        'DentaScribe MVP · v0.1<br>'
        '<span style="color:#A4ADC0;">Clinical scribe + Texas compliance + dual-model verification</span>'
        '</div>',
        unsafe_allow_html=True,
    )

# ---------------- page router ----------------

PAGES[choice]()
