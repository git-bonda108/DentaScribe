"""Reusable UI components (HTML-rendered Streamlit fragments)."""
import streamlit as st
from typing import List, Dict, Any
from ui.theme import COLORS


def hero(title: str, subtitle: str, badge: str = ""):
    badge_html = (
        f'<div class="ds-hero-badge">{badge}</div>' if badge else ""
    )
    st.markdown(
        f"""
        <div class="ds-hero">
          <div>
            <h1>{title}</h1>
            <p>{subtitle}</p>
          </div>
          {badge_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def metric_card(label: str, value, helper: str = ""):
    st.markdown(
        f"""
        <div class="ds-card ds-metric">
          <div class="ds-metric-value">{value}</div>
          <div class="ds-metric-label">{label}</div>
          {f'<div class="ds-metric-label" style="font-size:.75rem;color:{COLORS["muted"]}">{helper}</div>' if helper else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )


def badge(text: str, color: str = "primary"):
    return f'<span class="ds-badge {color}">{text}</span>'


def card(title: str, body_html: str):
    st.markdown(
        f"""<div class="ds-card"><h4>{title}</h4>{body_html}</div>""",
        unsafe_allow_html=True,
    )


def speaker_bubble(speaker: str, text: str):
    cls = "doctor" if speaker.lower() == "doctor" else "patient" \
          if speaker.lower() == "patient" else "patient"
    label = speaker.upper() if speaker.lower() in ("doctor", "patient") else speaker.upper()
    return (
        f"""<div class="ds-bubble {cls}">
          <div class="ds-bubble-speaker">{label}</div>
          <div>{text}</div>
        </div>"""
    )


def soap_block(label: str, content: str):
    if not content:
        return ""
    return f"""<div class="soap-block"><h5>{label}</h5><p>{content}</p></div>"""


def cdt_chip(code: str, nomenclature: str, confidence: float):
    pct = f"{int(confidence * 100)}%"
    return (
        f'<span class="cdt-chip"><strong>{code}</strong> · {nomenclature} '
        f'<span style="color:{COLORS["muted"]};font-size:.78rem">({pct})</span></span>'
    )
