"""DentaScribe brand theme + global CSS.

Centralizes color tokens and reusable CSS classes so every page looks like it
was designed by the same person. Call `inject_global_css()` once per page.
"""
from __future__ import annotations
import streamlit as st


COLORS = {
    "bg":             "#0B1220",
    "bg_card":        "#121A2B",
    "bg_card_alt":    "#0F172A",
    "border":         "#1F2A44",
    "text":           "#E5E9F2",
    "text_dim":       "#9AA6B8",
    "text_faint":     "#6B7790",
    "accent":         "#4DD4AC",
    "accent_alt":     "#6FE3C2",
    "warn":           "#F4B860",
    "error":          "#F26D6D",
    "ok":             "#4DD4AC",
    "interim":        "#6B7790",
    "provider":       "#7FB7FF",
    "patient":        "#F0C674",
    "assistant":      "#C9A0FF",
}


GLOBAL_CSS = """
<style>
  :root {
    --ds-bg: #0B1220;
    --ds-card: #121A2B;
    --ds-border: #1F2A44;
    --ds-text: #E5E9F2;
    --ds-text-dim: #9AA6B8;
    --ds-accent: #4DD4AC;
    --ds-warn: #F4B860;
    --ds-error: #F26D6D;
  }
  .stApp { background: var(--ds-bg); color: var(--ds-text); }
  section[data-testid="stSidebar"] { background: #0F172A; }
  h1, h2, h3, h4 { color: var(--ds-text); letter-spacing: -0.01em; }

  .ds-hero {
    padding: 28px 32px; border-radius: 18px;
    background: linear-gradient(135deg, #15233F 0%, #0E1A33 100%);
    border: 1px solid var(--ds-border);
    margin-bottom: 18px;
  }
  .ds-hero h1 { font-size: 30px; margin: 0 0 6px 0; }
  .ds-hero p  { color: var(--ds-text-dim); margin: 0; font-size: 15px; }
  .ds-hero .ds-pill { display:inline-block; padding:3px 10px; border-radius:999px;
                       background:#1B2B4A; color:#4DD4AC;
                       font-size:11px; font-weight:600; letter-spacing:0.08em;
                       margin-bottom:10px; }

  .ds-card {
    background: var(--ds-card); border:1px solid var(--ds-border);
    border-radius: 14px; padding: 18px 20px; margin-bottom: 14px;
  }
  .ds-card h4 { margin: 0 0 10px 0; font-size: 14px;
                 text-transform: uppercase; letter-spacing: 0.08em;
                 color: var(--ds-text-dim); }

  .ds-pill-status {
    display:inline-flex; align-items:center; gap:6px;
    padding: 4px 10px; border-radius: 999px; font-size: 11px; font-weight: 600;
    border: 1px solid var(--ds-border);
  }
  .ds-pill-idle    { background:#1A2440; color:#9AA6B8; }
  .ds-pill-running { background:#1F2F55; color:#4DD4AC;
                      animation: ds-pulse 1.2s ease-in-out infinite; }
  .ds-pill-ok      { background:#163B30; color:#4DD4AC; }
  .ds-pill-warn    { background:#3D2E13; color:#F4B860; }
  .ds-pill-err     { background:#3B1A1A; color:#F26D6D; }
  @keyframes ds-pulse {
    0%,100% { opacity:1; } 50% { opacity:0.55; }
  }

  .ds-utt { padding:8px 12px; margin:6px 0; border-radius:10px;
             border:1px solid var(--ds-border); font-size:14px; line-height:1.45;}
  .ds-utt-provider  { background:#16223D; }
  .ds-utt-patient   { background:#1E1B12; }
  .ds-utt-assistant { background:#21183A; }
  .ds-utt-interim   { color: #6B7790; font-style: italic; }
  .ds-utt .who      { font-size:10px; letter-spacing:0.1em; text-transform:uppercase;
                       color: var(--ds-text-dim); margin-right:8px; }

  .ds-score { display:inline-block; padding:6px 12px; border-radius:10px;
               font-weight:700; font-size:20px;
               background:#0F2B23; color:#4DD4AC; }
  .ds-score-low { background:#3B1A1A; color:#F26D6D; }
  .ds-score-mid { background:#3D2E13; color:#F4B860; }

  .ds-review { border-left: 3px solid var(--ds-border); padding:10px 14px;
                background:#101A30; border-radius: 0 10px 10px 0; margin:8px 0; }
  .ds-review-high { border-left-color: #F26D6D; }
  .ds-review-med  { border-left-color: #F4B860; }
  .ds-review-low  { border-left-color: #4DD4AC; }
  .ds-review .cat { font-size:10px; letter-spacing:0.1em; text-transform:uppercase;
                     color: var(--ds-text-dim); }

  .ds-quote { border-left:3px solid #4DD4AC; padding:4px 10px;
               color: var(--ds-text-dim); font-style:italic; margin:6px 0; }
</style>
"""


def inject_global_css() -> None:
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


def hero(title: str, subtitle: str, pill: str = "DENTASCRIBE  •  DALLAS, TX") -> None:
    st.markdown(
        f'<div class="ds-hero">'
        f'<div class="ds-pill">{pill}</div>'
        f'<h1>{title}</h1><p>{subtitle}</p></div>',
        unsafe_allow_html=True,
    )


def card_open(title: str | None = None) -> None:
    st.markdown('<div class="ds-card">', unsafe_allow_html=True)
    if title:
        st.markdown(f"<h4>{title}</h4>", unsafe_allow_html=True)


def card_close() -> None:
    st.markdown('</div>', unsafe_allow_html=True)


def score_chip(score):
    if score is None:
        return '<span class="ds-score ds-score-low">—</span>'
    cls = "ds-score"
    if score < 70:
        cls += " ds-score-low"
    elif score < 85:
        cls += " ds-score-mid"
    return f'<span class="{cls}">{score}</span>'
