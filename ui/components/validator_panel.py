"""Validator panel — signability score chip + grouped issues."""
from __future__ import annotations
import streamlit as st
from ui.theme import score_chip


def render_validator(validation) -> None:
    if not validation:
        st.info("No validation report yet.")
        return
    score = validation.get("signability_score")
    st.markdown(
        '<div style="display:flex; align-items:center; gap:14px; margin-bottom:10px;">'
        '<div style="font-size:11px; color:#9AA6B8; letter-spacing:0.1em;">SIGNABILITY</div>'
        f'{score_chip(score)}'
        '<div style="font-size:12px; color:#6B7790;">0-100 (>=85 to sign)</div>'
        '</div>',
        unsafe_allow_html=True,
    )
    issues = validation.get("issues") or []
    if not issues:
        st.success("No issues found.")
        return
    buckets = {"error": [], "warning": [], "info": []}
    for i in issues:
        buckets.setdefault(i.get("severity", "info"), []).append(i)
    for sev, label, emoji in [("error","Errors","🛑"),("warning","Warnings","⚠️"),("info","Info","ℹ️")]:
        rows = buckets.get(sev) or []
        if not rows: continue
        st.markdown(f"**{emoji} {label} ({len(rows)})**")
        for r in rows:
            path = r.get("path") or "—"
            msg = r.get("message") or ""
            st.markdown(f"- `{path}` — {msg}")
