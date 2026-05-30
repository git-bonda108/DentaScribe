"""Animated agent swarm — 7 named agents with live status pills."""
from __future__ import annotations
import streamlit as st


AGENT_DISPLAY = [
    ("Triage",        "intent + visit type"),
    ("Scribe",        "diarized SOAP draft"),
    ("Terminologist", "dental term normalization"),
    ("Coder",         "CDT code suggestion"),
    ("Validator",     "schema + grounding + Texas"),
    ("Reviewer",      "Second-Opinion (Agentic AI)"),
    ("Compliance",    "TSBDE / 22 TAC §108.8 check"),
]


def _pill(status: str) -> str:
    cls = {"idle":"ds-pill-idle","running":"ds-pill-running","ok":"ds-pill-ok",
           "warn":"ds-pill-warn","error":"ds-pill-err"}.get(status, "ds-pill-idle")
    label = {"idle":"queued","running":"running","ok":"done",
             "warn":"warn","error":"failed"}.get(status, status)
    return f'<span class="ds-pill-status {cls}">{label}</span>'


def render_swarm(audit_records) -> None:
    by_agent = {r.get("agent"): r for r in (audit_records or [])}
    cols = st.columns(len(AGENT_DISPLAY))
    for col, (name, role) in zip(cols, AGENT_DISPLAY):
        r = by_agent.get(name) or {}
        status = (r.get("status") or "idle").lower()
        if r.get("llm_status") == "demo" and status == "idle":
            status = "ok"
        toks = (r.get("input_tokens") or 0) + (r.get("output_tokens") or 0)
        latency = r.get("latency_ms") or r.get("duration_ms") or 0
        model = (r.get("model") or "—").split("/")[-1]
        with col:
            st.markdown(
                '<div class="ds-card" style="padding:12px 14px; margin-bottom:6px;">'
                f'<div style="font-weight:600; font-size:13px;">{name}</div>'
                f'<div style="font-size:11px; color:#9AA6B8; margin-bottom:8px;">{role}</div>'
                f'{_pill(status)}'
                f'<div style="font-size:10px; color:#6B7790; margin-top:8px;">'
                f'{model}<br/>{toks} tok • {latency} ms</div>'
                '</div>',
                unsafe_allow_html=True,
            )
