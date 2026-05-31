"""DentaScribe design system — premium dark clinical theme.

Targets Streamlit's actual rendered DOM via `data-testid` selectors so the
styling reliably sticks to its primitives (metrics, tabs, buttons, inputs,
chat messages, dataframes, expanders). Anything that can't be styled via CSS
is wrapped in a thin Python helper here.

Design tokens (kept in one place — change them here, the whole app updates):

  Palette:
    bg-0…3   layered backgrounds, page → sidebar → card → raised
    text-0…3 high-emphasis → tertiary
    accent   primary mint-teal (`#4DD4AC`)
    blue / amber / rose / purple   semantic states

  Type:
    Inter for body, JetBrains Mono for data/numerals
    Scale 11/12/14/15/17/20/24/32

  Geometry:
    Border radius 8 / 12 / 16 / 999px
    Spacing 4/8/12/16/24/32/48
    Soft layered shadows for depth
"""
from __future__ import annotations
import streamlit as st


# ---------- Token dictionary (mirrors the CSS variables for Python helpers) ----------

COLORS = {
    "bg_0":         "#0A0F1C",
    "bg_1":         "#0F172A",
    "bg_2":         "#121A2D",
    "bg_3":         "#1A2440",
    "text_0":       "#FFFFFF",
    "text_1":       "#E5E9F2",
    "text_2":       "#9AA6B8",
    "text_3":       "#6B7790",
    "border_1":     "rgba(255,255,255,0.06)",
    "border_2":     "rgba(255,255,255,0.10)",
    "accent":       "#4DD4AC",
    "accent_strong":"#6FE3C2",
    "accent_glow":  "rgba(77,212,172,0.18)",
    "blue":         "#7FB7FF",
    "amber":        "#F4B860",
    "rose":         "#F26D6D",
    "purple":       "#C9A0FF",

    # Legacy aliases preserved so existing components keep working
    "bg":           "#0A0F1C",
    "bg_card":      "#121A2D",
    "bg_card_alt":  "#0F172A",
    "border":       "rgba(255,255,255,0.08)",
    "text":         "#E5E9F2",
    "text_dim":     "#9AA6B8",
    "text_faint":   "#6B7790",
    "accent_alt":   "#6FE3C2",
    "warn":         "#F4B860",
    "error":        "#F26D6D",
    "ok":           "#4DD4AC",
    "interim":      "#6B7790",
    "provider":     "#7FB7FF",
    "patient":      "#F0C674",
    "assistant":    "#C9A0FF",
}


GLOBAL_CSS = """
<style>
  /* =========================================================
     0. Fonts + CSS variables
     ========================================================= */
  @import url('https://rsms.me/inter/inter.css');
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap');

  :root {
    --ds-bg-0: #0A0F1C;
    --ds-bg-1: #0F172A;
    --ds-bg-2: #121A2D;
    --ds-bg-3: #1A2440;

    --ds-text-0: #FFFFFF;
    --ds-text-1: #E5E9F2;
    --ds-text-2: #9AA6B8;
    --ds-text-3: #6B7790;

    --ds-border-1: rgba(255,255,255,0.06);
    --ds-border-2: rgba(255,255,255,0.10);
    --ds-border-3: rgba(255,255,255,0.16);

    --ds-accent:        #4DD4AC;
    --ds-accent-strong: #6FE3C2;
    --ds-accent-soft:   rgba(77,212,172,0.10);
    --ds-accent-glow:   rgba(77,212,172,0.25);
    --ds-blue:   #7FB7FF;
    --ds-amber:  #F4B860;
    --ds-rose:   #F26D6D;
    --ds-purple: #C9A0FF;

    --ds-shadow-1: 0 1px 2px rgba(0,0,0,0.18), 0 0 0 1px var(--ds-border-1);
    --ds-shadow-2: 0 4px 12px rgba(0,0,0,0.22), 0 0 0 1px var(--ds-border-1);
    --ds-shadow-3: 0 12px 32px rgba(0,0,0,0.32), 0 0 0 1px var(--ds-border-2);
    --ds-shadow-glow: 0 0 0 1px var(--ds-accent), 0 0 24px var(--ds-accent-glow);

    --r-sm: 8px;
    --r-md: 12px;
    --r-lg: 16px;
    --r-xl: 20px;
    --r-pill: 999px;
  }

  /* =========================================================
     1. Page chrome — body, app, blocks
     ========================================================= */
  html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    font-feature-settings: 'cv11','ss01','ss03';
    letter-spacing: -0.005em;
  }
  .stApp { background: var(--ds-bg-0); color: var(--ds-text-1); }
  .block-container { padding-top: 2rem; padding-bottom: 4rem; max-width: 1400px; }

  p, li, label, .stMarkdown { color: var(--ds-text-1); line-height: 1.55; }
  small, .ds-caption { color: var(--ds-text-2); font-size: 12px; }

  h1, h2, h3, h4, h5, h6 {
    color: var(--ds-text-0);
    font-family: 'Inter Tight', 'Inter', sans-serif;
    letter-spacing: -0.022em;
    font-weight: 700;
  }
  h1 { font-size: 32px; line-height: 1.15; }
  h2 { font-size: 24px; line-height: 1.2;  }
  h3 { font-size: 19px; line-height: 1.3;  }
  h4 { font-size: 14px; line-height: 1.3;
       text-transform: uppercase; letter-spacing: 0.10em;
       color: var(--ds-text-2); font-weight: 600; }
  h5 { font-size: 13px; color: var(--ds-text-2); font-weight: 600;
       letter-spacing: 0.04em; margin-top: 4px; }

  code, pre, .ds-mono,
  [data-testid="stMetricValue"], [data-testid="stMetricDelta"] {
    font-family: 'JetBrains Mono', 'SF Mono', Menlo, monospace;
    font-feature-settings: 'tnum' 1;
  }

  hr { border-color: var(--ds-border-1) !important; margin: 24px 0; }
  [data-testid="stHorizontalBlock"] > div { gap: 14px; }

  /* =========================================================
     2. Sidebar
     ========================================================= */
  section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0E1626 0%, #0A0F1C 100%);
    border-right: 1px solid var(--ds-border-1);
  }
  section[data-testid="stSidebar"] > div { padding: 8px 12px; }

  section[data-testid="stSidebar"] [data-testid="stRadio"] > div { gap: 4px; }
  section[data-testid="stSidebar"] [data-testid="stRadio"] label {
    padding: 8px 12px;
    border-radius: var(--r-md);
    transition: background 150ms ease;
    color: var(--ds-text-1);
    font-size: 14px;
    font-weight: 500;
  }
  section[data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
    background: var(--ds-bg-3);
  }

  /* =========================================================
     3. Hero — premium gradient + brand pill
     ========================================================= */
  .ds-hero {
    position: relative;
    padding: 32px 36px;
    border-radius: var(--r-xl);
    background:
      radial-gradient(120% 100% at 0% 0%, rgba(77,212,172,0.08) 0%, transparent 55%),
      radial-gradient(80% 120% at 100% 100%, rgba(127,183,255,0.06) 0%, transparent 55%),
      linear-gradient(135deg, #16223D 0%, #0E1A33 100%);
    border: 1px solid var(--ds-border-2);
    margin: 8px 0 24px;
    overflow: hidden;
  }
  .ds-hero::before {
    content: ""; position: absolute; inset: 0;
    background: linear-gradient(180deg, transparent 0%, rgba(0,0,0,0.06) 100%);
    pointer-events: none;
  }
  .ds-hero h1 {
    font-size: 34px; margin: 6px 0 8px; font-weight: 800;
    background: linear-gradient(180deg, #FFFFFF 0%, #C8D1E6 100%);
    -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
  }
  .ds-hero p { color: var(--ds-text-2); margin: 0; font-size: 15px; max-width: 680px; line-height: 1.55; }
  .ds-pill {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 4px 12px; border-radius: var(--r-pill);
    background: rgba(77,212,172,0.12);
    color: var(--ds-accent);
    font-size: 10.5px; font-weight: 700; letter-spacing: 0.12em;
    border: 1px solid rgba(77,212,172,0.30);
  }
  .ds-pill::before {
    content: ""; width: 6px; height: 6px; border-radius: 50%;
    background: var(--ds-accent); box-shadow: 0 0 8px var(--ds-accent-glow);
  }

  /* =========================================================
     4. Cards
     ========================================================= */
  .ds-card {
    background: var(--ds-bg-2);
    border: 1px solid var(--ds-border-1);
    border-radius: var(--r-lg);
    padding: 20px 22px;
    margin-bottom: 16px;
    box-shadow: var(--ds-shadow-2);
    transition: border 150ms ease;
  }
  .ds-card:hover { border-color: var(--ds-border-2); }
  .ds-card h4 { margin: 0 0 14px 0; }

  div[data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--ds-bg-2);
    border: 1px solid var(--ds-border-1) !important;
    border-radius: var(--r-lg) !important;
    padding: 6px 10px;
    box-shadow: var(--ds-shadow-2);
  }

  /* =========================================================
     5. Metrics — bigger numbers, polished labels
     ========================================================= */
  [data-testid="stMetric"] {
    background: linear-gradient(180deg, var(--ds-bg-2) 0%, var(--ds-bg-1) 100%);
    border: 1px solid var(--ds-border-1);
    border-radius: var(--r-lg);
    padding: 14px 18px;
    box-shadow: var(--ds-shadow-1);
    transition: transform 150ms ease, border-color 150ms ease;
  }
  [data-testid="stMetric"]:hover {
    border-color: var(--ds-border-2);
    transform: translateY(-1px);
  }
  [data-testid="stMetricLabel"] {
    text-transform: uppercase; letter-spacing: 0.10em;
    font-size: 10.5px !important; font-weight: 600;
    color: var(--ds-text-2) !important;
  }
  [data-testid="stMetricValue"] {
    font-size: 28px !important; font-weight: 700;
    color: var(--ds-text-0) !important;
    letter-spacing: -0.02em;
    margin-top: 2px;
  }
  [data-testid="stMetricDelta"] {
    font-size: 12px !important; font-weight: 500;
    color: var(--ds-text-2) !important;
  }
  [data-testid="stMetricDelta"] svg { color: var(--ds-accent) !important; stroke: var(--ds-accent) !important; }

  /* =========================================================
     6. Tabs — pill style instead of underline
     ========================================================= */
  [data-testid="stTabs"] [role="tablist"] {
    gap: 4px;
    border-bottom: 1px solid var(--ds-border-1);
    padding-bottom: 4px;
    margin-bottom: 16px;
  }
  [data-testid="stTabs"] button[role="tab"] {
    background: transparent;
    border: 1px solid transparent;
    color: var(--ds-text-2);
    padding: 8px 14px;
    border-radius: var(--r-md);
    font-size: 13.5px; font-weight: 500;
    transition: all 150ms ease;
  }
  [data-testid="stTabs"] button[role="tab"]:hover {
    color: var(--ds-text-1);
    background: var(--ds-bg-3);
  }
  [data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
    color: var(--ds-text-0) !important;
    background: var(--ds-bg-3);
    border-color: var(--ds-border-2);
    box-shadow: var(--ds-shadow-1);
  }
  [data-testid="stTabs"] [role="tablist"] [data-baseweb="tab-highlight"] { display: none !important; }

  /* =========================================================
     7. Buttons — primary glow, secondary outline
     ========================================================= */
  .stButton > button, [data-testid="stFormSubmitButton"] > button {
    border-radius: var(--r-md);
    font-weight: 600;
    font-size: 13.5px;
    padding: 8px 16px;
    transition: all 150ms ease;
    border: 1px solid var(--ds-border-2);
    background: var(--ds-bg-3);
    color: var(--ds-text-1);
  }
  .stButton > button:hover {
    border-color: var(--ds-border-3);
    background: #233056;
    transform: translateY(-1px);
  }
  .stButton > button[kind="primary"] {
    background: linear-gradient(180deg, var(--ds-accent-strong) 0%, var(--ds-accent) 100%);
    color: #062318 !important;
    border: 1px solid var(--ds-accent);
    box-shadow: 0 1px 2px rgba(0,0,0,0.2), 0 0 0 1px var(--ds-accent),
                0 8px 16px -8px var(--ds-accent-glow);
  }
  .stButton > button[kind="primary"]:hover {
    filter: brightness(1.04);
    box-shadow: 0 1px 2px rgba(0,0,0,0.2), 0 0 0 1px var(--ds-accent-strong),
                0 12px 24px -8px var(--ds-accent-glow);
  }

  [role="radio"][aria-checked="true"] > div:first-child,
  [data-testid="stCheckbox"] [data-baseweb="checkbox"] [data-testid="stTooltipHoverTarget"] {
    background: var(--ds-accent) !important;
  }

  /* =========================================================
     8. Inputs — text area, text input, file uploader
     ========================================================= */
  textarea, [data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea {
    background: var(--ds-bg-1) !important;
    color: var(--ds-text-1) !important;
    border: 1px solid var(--ds-border-2) !important;
    border-radius: var(--r-md) !important;
    font-size: 14px !important;
    padding: 10px 12px !important;
    font-family: inherit !important;
  }
  textarea:focus, [data-testid="stTextInput"] input:focus, [data-testid="stTextArea"] textarea:focus {
    outline: none !important;
    border-color: var(--ds-accent) !important;
    box-shadow: 0 0 0 3px var(--ds-accent-soft) !important;
  }
  [data-testid="stFileUploader"] section {
    background: var(--ds-bg-1) !important;
    border: 1px dashed var(--ds-border-2) !important;
    border-radius: var(--r-md) !important;
  }
  [data-testid="stFileUploader"] section:hover {
    border-color: var(--ds-accent) !important;
    background: rgba(77,212,172,0.04) !important;
  }

  /* =========================================================
     9. Chat message bubbles
     ========================================================= */
  [data-testid="stChatMessage"] {
    background: var(--ds-bg-2);
    border: 1px solid var(--ds-border-1);
    border-radius: var(--r-lg);
    padding: 14px 18px;
    margin: 6px 0;
    box-shadow: var(--ds-shadow-1);
  }
  [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {
    background: linear-gradient(180deg, rgba(127,183,255,0.06) 0%, var(--ds-bg-2) 100%);
    border-left: 3px solid var(--ds-blue);
  }
  [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
    background: linear-gradient(180deg, rgba(240,198,116,0.06) 0%, var(--ds-bg-2) 100%);
    border-left: 3px solid var(--ds-amber);
  }
  [data-testid="stChatMessage"] [data-testid="chatAvatarIcon-assistant"],
  [data-testid="stChatMessage"] [data-testid="chatAvatarIcon-user"] {
    background: var(--ds-bg-3) !important;
    border: 1px solid var(--ds-border-2);
  }

  /* =========================================================
     10. Expanders
     ========================================================= */
  [data-testid="stExpander"] {
    background: var(--ds-bg-2);
    border: 1px solid var(--ds-border-1) !important;
    border-radius: var(--r-md) !important;
    margin: 6px 0 !important;
    box-shadow: var(--ds-shadow-1);
  }
  [data-testid="stExpander"] summary {
    color: var(--ds-text-1);
    font-size: 13px; font-weight: 500;
    padding: 10px 14px !important;
  }
  [data-testid="stExpander"] summary:hover { background: var(--ds-bg-3); }
  [data-testid="stExpander"] details[open] > summary {
    border-bottom: 1px solid var(--ds-border-1);
  }

  /* =========================================================
     11. Status block / notifications
     ========================================================= */
  [data-testid="stStatusWidget"], [data-testid="stStatus"] {
    background: var(--ds-bg-2);
    border: 1px solid var(--ds-border-1) !important;
    border-radius: var(--r-md) !important;
    box-shadow: var(--ds-shadow-2);
  }
  div[data-baseweb="notification"] {
    border-radius: var(--r-md) !important;
    border: 1px solid var(--ds-border-2) !important;
    backdrop-filter: blur(8px);
  }

  /* =========================================================
     12. DataFrames
     ========================================================= */
  [data-testid="stDataFrame"] { border: 1px solid var(--ds-border-1); border-radius: var(--r-md); overflow: hidden; }
  [data-testid="stDataFrame"] [role="row"] { border-bottom: 1px solid var(--ds-border-1); }
  [data-testid="stDataFrame"] [role="columnheader"] {
    background: var(--ds-bg-1) !important;
    color: var(--ds-text-2) !important;
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em;
  }
  [data-testid="stDataFrame"] [role="row"]:hover { background: var(--ds-bg-3); }

  /* =========================================================
     13. Agent swarm — premium card with glow on success
     ========================================================= */
  .ds-agent-card {
    position: relative;
    background: linear-gradient(180deg, var(--ds-bg-2) 0%, var(--ds-bg-1) 100%);
    border: 1px solid var(--ds-border-1);
    border-radius: var(--r-md);
    padding: 14px 12px;
    text-align: center;
    transition: all 200ms ease;
    overflow: hidden;
  }
  .ds-agent-card::before {
    content: ""; position: absolute; top: 0; left: 0; right: 0; height: 2px;
    background: var(--ds-border-1);
    transition: background 200ms ease;
  }
  .ds-agent-card.ok::before    { background: var(--ds-accent); box-shadow: 0 0 12px var(--ds-accent-glow); }
  .ds-agent-card.err::before   { background: var(--ds-rose); box-shadow: 0 0 12px rgba(242,109,109,0.3); }
  .ds-agent-card.warn::before  { background: var(--ds-amber); box-shadow: 0 0 12px rgba(244,184,96,0.3); }
  .ds-agent-card.run::before {
    background: var(--ds-accent);
    animation: ds-shimmer 1.5s ease-in-out infinite;
  }
  .ds-agent-card .icon { font-size: 22px; line-height: 1; margin-bottom: 4px; }
  .ds-agent-card .name { font-size: 12px; font-weight: 600; color: var(--ds-text-1);
                          margin-top: 4px; letter-spacing: -0.005em; }
  .ds-agent-card .meta { font-size: 10.5px; color: var(--ds-text-3); margin-top: 4px;
                          font-family: 'JetBrains Mono', monospace; }
  @keyframes ds-shimmer {
    0%,100% { opacity: 0.4; } 50% { opacity: 1; }
  }

  /* =========================================================
     14. Pills + badges
     ========================================================= */
  .ds-pill-status {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 4px 10px; border-radius: var(--r-pill);
    font-size: 11px; font-weight: 600;
    border: 1px solid var(--ds-border-2);
  }
  .ds-pill-idle    { background: var(--ds-bg-3); color: var(--ds-text-2); }
  .ds-pill-running { background: rgba(77,212,172,0.12); color: var(--ds-accent);
                      animation: ds-pulse 1.5s ease-in-out infinite; }
  .ds-pill-ok      { background: rgba(77,212,172,0.10); color: var(--ds-accent);
                      border-color: rgba(77,212,172,0.30); }
  .ds-pill-warn    { background: rgba(244,184,96,0.10); color: var(--ds-amber);
                      border-color: rgba(244,184,96,0.30); }
  .ds-pill-err     { background: rgba(242,109,109,0.10); color: var(--ds-rose);
                      border-color: rgba(242,109,109,0.30); }
  @keyframes ds-pulse {
    0%,100% { box-shadow: 0 0 0 0 rgba(77,212,172,0.0); }
    50%     { box-shadow: 0 0 0 6px rgba(77,212,172,0.10); }
  }

  /* =========================================================
     15. Score chip + Second-Opinion review
     ========================================================= */
  .ds-score { display: inline-block; padding: 8px 16px; border-radius: var(--r-md);
               font-family: 'JetBrains Mono', monospace; font-weight: 700; font-size: 22px;
               background: rgba(77,212,172,0.10); color: var(--ds-accent);
               border: 1px solid rgba(77,212,172,0.25); }
  .ds-score-low { background: rgba(242,109,109,0.10); color: var(--ds-rose);
                   border-color: rgba(242,109,109,0.25); }
  .ds-score-mid { background: rgba(244,184,96,0.10); color: var(--ds-amber);
                   border-color: rgba(244,184,96,0.25); }

  .ds-review {
    border-left: 3px solid var(--ds-border-2);
    padding: 12px 16px;
    background: var(--ds-bg-2);
    border-radius: 0 var(--r-md) var(--r-md) 0;
    margin: 8px 0;
    box-shadow: var(--ds-shadow-1);
  }
  .ds-review-high { border-left-color: var(--ds-rose);
                     background: linear-gradient(90deg, rgba(242,109,109,0.06) 0%, var(--ds-bg-2) 100%); }
  .ds-review-med  { border-left-color: var(--ds-amber);
                     background: linear-gradient(90deg, rgba(244,184,96,0.06) 0%, var(--ds-bg-2) 100%); }
  .ds-review-low  { border-left-color: var(--ds-accent);
                     background: linear-gradient(90deg, rgba(77,212,172,0.06) 0%, var(--ds-bg-2) 100%); }
  .ds-review .cat { font-size: 10px; letter-spacing: 0.10em; text-transform: uppercase;
                     color: var(--ds-text-3); font-weight: 600; }

  .ds-quote {
    border-left: 2px solid var(--ds-accent);
    padding: 6px 12px; color: var(--ds-text-2);
    font-style: italic; font-size: 13px;
    margin: 8px 0; background: var(--ds-accent-soft);
    border-radius: 0 var(--r-sm) var(--r-sm) 0;
  }

  /* =========================================================
     16. Progress bar
     ========================================================= */
  [data-testid="stProgressBar"] > div > div {
    background: linear-gradient(90deg, var(--ds-accent) 0%, var(--ds-accent-strong) 100%) !important;
    border-radius: var(--r-pill);
  }

  /* =========================================================
     17. Legacy utterance bubble support (transcript_panel.py)
     ========================================================= */
  .ds-utt { padding: 10px 14px; margin: 6px 0; border-radius: var(--r-md);
             border: 1px solid var(--ds-border-1); font-size: 14px; line-height: 1.5; }
  .ds-utt-provider  { background: linear-gradient(180deg, rgba(127,183,255,0.06) 0%, var(--ds-bg-2) 100%);
                       border-left: 3px solid var(--ds-blue); }
  .ds-utt-patient   { background: linear-gradient(180deg, rgba(240,198,116,0.06) 0%, var(--ds-bg-2) 100%);
                       border-left: 3px solid var(--ds-amber); }
  .ds-utt-assistant { background: linear-gradient(180deg, rgba(201,160,255,0.06) 0%, var(--ds-bg-2) 100%);
                       border-left: 3px solid var(--ds-purple); }
  .ds-utt-interim   { color: var(--ds-text-3); font-style: italic; }
  .ds-utt .who      { font-size: 10px; letter-spacing: 0.10em; text-transform: uppercase;
                       color: var(--ds-text-3); margin-right: 8px; font-weight: 600; }

  /* =========================================================
     18. Hide Streamlit chrome
     ========================================================= */
  #MainMenu, header[data-testid="stHeader"], footer { visibility: hidden; }
  .stDeployButton { display: none; }
</style>
"""


# ---------- Python helpers (Streamlit-aware wrappers) ----------

def inject_global_css() -> None:
    """Inject the design system once per page. Idempotent."""
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


def hero(title: str, subtitle: str, pill: str = "DENTASCRIBE  •  DALLAS, TX") -> None:
    """Branded hero header. Title gets a subtle gradient + tracking."""
    st.markdown(
        f'<div class="ds-hero">'
        f'<div class="ds-pill">{pill}</div>'
        f'<h1>{title}</h1>'
        f'<p>{subtitle}</p>'
        f'</div>',
        unsafe_allow_html=True,
    )


def card_open(title: str | None = None) -> None:
    """Open a styled card. Use card_close() to close. Prefer
    `st.container(border=True)` where you can — this is the legacy escape hatch.
    """
    st.markdown('<div class="ds-card">', unsafe_allow_html=True)
    if title:
        st.markdown(f"<h4>{title}</h4>", unsafe_allow_html=True)


def card_close() -> None:
    st.markdown('</div>', unsafe_allow_html=True)


def score_chip(score) -> str:
    """Return HTML for a signability score chip, colored by threshold."""
    if score is None:
        return '<span class="ds-score ds-score-low">—</span>'
    cls = "ds-score"
    if score < 70:
        cls += " ds-score-low"
    elif score < 85:
        cls += " ds-score-mid"
    return f'<span class="{cls}">{score}</span>'


def status_pill(label: str, kind: str = "idle") -> str:
    """Return HTML for a pill-style status badge.
    kind ∈ {idle, running, ok, warn, err}"""
    return f'<span class="ds-pill-status ds-pill-{kind}">{label}</span>'


def agent_card_html(agent: str, status: str, tokens: int = 0,
                    duration_ms: int = 0, icon: str = "•") -> str:
    """Return HTML for one animated agent status card in the swarm strip."""
    status = (status or "idle").lower()
    cls = {"ok":"ok", "error":"err", "warn":"warn", "running":"run"}.get(status, "")
    name = agent.replace("_", " ").title()
    return (
        f'<div class="ds-agent-card {cls}">'
        f'<div class="icon">{icon}</div>'
        f'<div class="name">{name}</div>'
        f'<div class="meta">{duration_ms} ms · {tokens:,} tok</div>'
        f'</div>'
    )
