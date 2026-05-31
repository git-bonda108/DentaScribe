"""DentaScribe design system — Arini-inspired light clinical theme.

Tone: premium + approachable. Clinical-confident without being cold. Navy
text on white surfaces. Teal accent used sparingly (CTAs and key data only).
Hairline borders. Soft layered shadows. Generous whitespace. No glow.

Targets Streamlit's actual rendered DOM via `data-testid` selectors so the
styling reliably sticks to its primitives (metrics, tabs, buttons, inputs,
chat messages, dataframes, expanders).

Design tokens (change them here, the whole app updates):

  Palette:
    surface-0…2     white → off-white → light gray (layered, NO black)
    text-0…3        deep-navy → ink → secondary → faint
    accent          teal `#0EA5A4` (slightly darker than mint so it pops on white)
    blue / amber / rose / purple   semantic states

  Type:
    Inter for body, JetBrains Mono for data/numerals
    Scale 11/12/14/15/17/22/28/34/40

  Geometry:
    Border radius 6 / 10 / 14 / 999px
    Spacing 4/8/12/16/24/32/48/64
    Soft layered shadows for depth
"""
from __future__ import annotations
import streamlit as st


# ---------- Token dictionary (mirrors the CSS variables for Python helpers) ----------

COLORS = {
    # surfaces — light, layered
    "bg":           "#FFFFFF",
    "bg_0":         "#FFFFFF",
    "bg_1":         "#FBFCFD",
    "bg_2":         "#F4F6F9",
    "bg_3":         "#EEF1F5",

    # text — deep navy → faint
    "text":         "#0B1426",
    "text_0":       "#0B1426",
    "text_1":       "#1A2238",
    "text_2":       "#5A6478",
    "text_3":       "#8A95AB",
    "text_dim":     "#5A6478",   # legacy alias
    "text_faint":   "#8A95AB",   # legacy alias

    # borders — hairlines
    "border":       "#E8ECF1",   # legacy alias
    "border_1":     "#EEF1F5",
    "border_2":     "#DDE3EC",
    "border_3":     "#C3CCD9",

    # accent
    "accent":       "#0EA5A4",   # primary teal
    "accent_strong":"#0B8786",
    "accent_soft":  "#E6F8F6",
    "accent_glow":  "rgba(14,165,164,0.18)",
    "accent_alt":   "#6FE3C2",

    # semantic
    "blue":         "#2563EB",
    "amber":        "#B45309",
    "rose":         "#B91C1C",
    "purple":       "#7C3AED",

    # legacy aliases
    "bg_card":      "#FFFFFF",
    "bg_card_alt":  "#F8FAFB",
    "warn":         "#B45309",
    "error":        "#B91C1C",
    "ok":           "#0B8786",
    "interim":      "#8A95AB",
    "provider":     "#2563EB",
    "patient":      "#B45309",
    "assistant":    "#7C3AED",
}


GLOBAL_CSS = """
<style>
  /* =========================================================
     0. Fonts + CSS variables
     ========================================================= */
  @import url('https://rsms.me/inter/inter.css');
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap');

  :root {
    /* Surfaces — light, layered (page → cards → raised) */
    --ds-bg-0: #FFFFFF;
    --ds-bg-1: #FBFCFD;
    --ds-bg-2: #F4F6F9;
    --ds-bg-3: #EEF1F5;

    /* Text — deep navy → faint */
    --ds-text-0: #0B1426;
    --ds-text-1: #1A2238;
    --ds-text-2: #5A6478;
    --ds-text-3: #8A95AB;

    /* Borders — hairlines, just a touch of warmth */
    --ds-border-1: #EEF1F5;
    --ds-border-2: #DDE3EC;
    --ds-border-3: #C3CCD9;

    /* Accent — clinical teal, used sparingly */
    --ds-accent:        #0EA5A4;
    --ds-accent-strong: #0B8786;
    --ds-accent-soft:   #E6F8F6;
    --ds-accent-glow:   rgba(14,165,164,0.15);

    /* Semantic */
    --ds-blue:   #2563EB;
    --ds-amber:  #B45309;
    --ds-rose:   #B91C1C;
    --ds-purple: #7C3AED;

    /* Shadows — soft, layered, never harsh */
    --ds-shadow-1: 0 1px 2px rgba(11,20,38,0.04);
    --ds-shadow-2: 0 1px 2px rgba(11,20,38,0.04), 0 8px 16px -8px rgba(11,20,38,0.06);
    --ds-shadow-3: 0 4px 6px rgba(11,20,38,0.04), 0 24px 40px -16px rgba(11,20,38,0.10);

    /* Geometry */
    --r-sm: 6px;
    --r-md: 10px;
    --r-lg: 14px;
    --r-xl: 18px;
    --r-pill: 999px;
  }

  /* =========================================================
     1. Page chrome
     ========================================================= */
  html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    font-feature-settings: 'cv11','ss01','ss03';
    letter-spacing: -0.005em;
    -webkit-font-smoothing: antialiased;
  }
  .stApp { background: var(--ds-bg-0); color: var(--ds-text-1); }
  .block-container { padding-top: 2.5rem; padding-bottom: 4rem; max-width: 1200px; }

  p, li, label, .stMarkdown { color: var(--ds-text-1); line-height: 1.6; }
  small, .ds-caption { color: var(--ds-text-2); font-size: 12.5px; }

  /* Headings — clinical-confident, generous tracking */
  h1, h2, h3, h4, h5, h6 {
    color: var(--ds-text-0);
    font-family: 'Inter Tight', 'Inter', sans-serif;
    letter-spacing: -0.022em;
    font-weight: 700;
  }
  h1 { font-size: 40px; line-height: 1.1; font-weight: 800; }
  h2 { font-size: 28px; line-height: 1.2; }
  h3 { font-size: 20px; line-height: 1.3; }
  h4 { font-size: 12.5px; line-height: 1.3;
       text-transform: uppercase; letter-spacing: 0.09em;
       color: var(--ds-text-2); font-weight: 600; }
  h5 { font-size: 13px; color: var(--ds-text-2); font-weight: 600; letter-spacing: 0.02em; }

  /* Mono numerals */
  code, pre, .ds-mono,
  [data-testid="stMetricValue"], [data-testid="stMetricDelta"] {
    font-family: 'JetBrains Mono', 'SF Mono', Menlo, monospace;
    font-feature-settings: 'tnum' 1;
  }

  hr { border-color: var(--ds-border-1) !important; margin: 28px 0; }
  [data-testid="stHorizontalBlock"] > div { gap: 14px; }

  /* =========================================================
     2. Sidebar — light, hairlined, generous breathing room
     ========================================================= */
  section[data-testid="stSidebar"] {
    background: var(--ds-bg-1);
    border-right: 1px solid var(--ds-border-1);
  }
  section[data-testid="stSidebar"] > div { padding: 10px 14px; }

  section[data-testid="stSidebar"] [data-testid="stRadio"] > div { gap: 4px; }
  section[data-testid="stSidebar"] [data-testid="stRadio"] label {
    padding: 9px 12px;
    border-radius: var(--r-md);
    transition: background 150ms ease;
    color: var(--ds-text-1);
    font-size: 14px;
    font-weight: 500;
  }
  section[data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
    background: var(--ds-bg-2);
  }

  /* =========================================================
     3. Hero — white, generous whitespace, big clinical headline
     ========================================================= */
  .ds-hero {
    position: relative;
    padding: 44px 44px 38px;
    border-radius: var(--r-xl);
    background: var(--ds-bg-0);
    border: 1px solid var(--ds-border-1);
    margin: 8px 0 28px;
    box-shadow: var(--ds-shadow-2);
    overflow: hidden;
  }
  /* Very subtle gradient corner — restraint matters */
  .ds-hero::after {
    content: ""; position: absolute; top: 0; right: 0;
    width: 380px; height: 240px; pointer-events: none;
    background: radial-gradient(60% 80% at 80% 20%, rgba(14,165,164,0.10) 0%, transparent 70%);
  }
  .ds-hero h1 {
    font-size: 40px; margin: 10px 0 10px; font-weight: 800;
    color: var(--ds-text-0);
    max-width: 720px;
  }
  .ds-hero p {
    color: var(--ds-text-2); margin: 0;
    font-size: 16px; max-width: 640px; line-height: 1.55;
  }
  .ds-pill {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 4px 12px; border-radius: var(--r-pill);
    background: var(--ds-accent-soft);
    color: var(--ds-accent-strong);
    font-size: 10.5px; font-weight: 700; letter-spacing: 0.12em;
    border: 1px solid rgba(14,165,164,0.20);
  }
  .ds-pill::before {
    content: ""; width: 6px; height: 6px; border-radius: 50%;
    background: var(--ds-accent);
  }

  /* =========================================================
     4. Cards — white, hairline border, soft shadow
     ========================================================= */
  .ds-card {
    background: var(--ds-bg-0);
    border: 1px solid var(--ds-border-1);
    border-radius: var(--r-lg);
    padding: 24px 26px;
    margin-bottom: 16px;
    box-shadow: var(--ds-shadow-1);
    transition: border 150ms ease, box-shadow 150ms ease;
  }
  .ds-card:hover {
    border-color: var(--ds-border-2);
    box-shadow: var(--ds-shadow-2);
  }
  .ds-card h4 { margin: 0 0 16px 0; }

  /* st.container(border=True) */
  div[data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--ds-bg-0);
    border: 1px solid var(--ds-border-1) !important;
    border-radius: var(--r-lg) !important;
    padding: 6px 12px;
    box-shadow: var(--ds-shadow-1);
  }

  /* =========================================================
     5. Metrics — large numerals, uppercase labels
     ========================================================= */
  [data-testid="stMetric"] {
    background: var(--ds-bg-0);
    border: 1px solid var(--ds-border-1);
    border-radius: var(--r-lg);
    padding: 16px 20px;
    box-shadow: var(--ds-shadow-1);
    transition: transform 150ms ease, border-color 150ms ease, box-shadow 150ms ease;
  }
  [data-testid="stMetric"]:hover {
    border-color: var(--ds-border-2);
    transform: translateY(-1px);
    box-shadow: var(--ds-shadow-2);
  }
  [data-testid="stMetricLabel"] {
    text-transform: uppercase; letter-spacing: 0.10em;
    font-size: 10.5px !important; font-weight: 600;
    color: var(--ds-text-2) !important;
  }
  [data-testid="stMetricValue"] {
    font-size: 30px !important; font-weight: 700;
    color: var(--ds-text-0) !important;
    letter-spacing: -0.02em;
    margin-top: 4px;
  }
  [data-testid="stMetricDelta"] {
    font-size: 12px !important; font-weight: 500;
    color: var(--ds-text-2) !important;
  }
  [data-testid="stMetricDelta"] svg {
    color: var(--ds-accent-strong) !important; stroke: var(--ds-accent-strong) !important;
  }

  /* =========================================================
     6. Tabs — Arini-style: clean, restrained, no pill
     ========================================================= */
  [data-testid="stTabs"] [role="tablist"] {
    gap: 0;
    border-bottom: 1px solid var(--ds-border-1);
    padding-bottom: 0;
    margin-bottom: 20px;
  }
  [data-testid="stTabs"] button[role="tab"] {
    background: transparent;
    border: none;
    color: var(--ds-text-2);
    padding: 12px 16px;
    border-radius: 0;
    font-size: 14px; font-weight: 500;
    transition: all 150ms ease;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
  }
  [data-testid="stTabs"] button[role="tab"]:hover {
    color: var(--ds-text-0);
  }
  [data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
    color: var(--ds-text-0) !important;
    border-bottom-color: var(--ds-accent) !important;
    font-weight: 600;
  }
  [data-testid="stTabs"] [role="tablist"] [data-baseweb="tab-highlight"] { display: none !important; }

  /* =========================================================
     7. Buttons — Arini: solid navy primary, light outline secondary
     ========================================================= */
  .stButton > button, [data-testid="stFormSubmitButton"] > button {
    border-radius: var(--r-md);
    font-weight: 500;
    font-size: 14px;
    padding: 10px 18px;
    transition: all 150ms ease;
    border: 1px solid var(--ds-border-2);
    background: var(--ds-bg-0);
    color: var(--ds-text-1);
    box-shadow: var(--ds-shadow-1);
  }
  .stButton > button:hover {
    border-color: var(--ds-border-3);
    background: var(--ds-bg-1);
    color: var(--ds-text-0);
    box-shadow: var(--ds-shadow-2);
  }
  .stButton > button[kind="primary"] {
    background: var(--ds-text-0);
    color: #FFFFFF !important;
    border: 1px solid var(--ds-text-0);
    font-weight: 600;
    box-shadow: 0 1px 2px rgba(11,20,38,0.10), 0 8px 16px -8px rgba(11,20,38,0.18);
  }
  .stButton > button[kind="primary"]:hover {
    background: #1A2238;
    border-color: #1A2238;
    box-shadow: 0 1px 2px rgba(11,20,38,0.12), 0 12px 20px -10px rgba(11,20,38,0.20);
  }

  [role="radio"][aria-checked="true"] > div:first-child {
    background: var(--ds-accent) !important;
  }

  /* =========================================================
     8. Inputs
     ========================================================= */
  textarea, [data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea {
    background: var(--ds-bg-0) !important;
    color: var(--ds-text-0) !important;
    border: 1px solid var(--ds-border-2) !important;
    border-radius: var(--r-md) !important;
    font-size: 14px !important;
    padding: 12px 14px !important;
    font-family: inherit !important;
    box-shadow: var(--ds-shadow-1);
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
    background: var(--ds-accent-soft) !important;
  }

  /* =========================================================
     9. Chat message bubbles
     ========================================================= */
  [data-testid="stChatMessage"] {
    background: var(--ds-bg-0);
    border: 1px solid var(--ds-border-1);
    border-radius: var(--r-lg);
    padding: 14px 18px;
    margin: 6px 0;
    box-shadow: var(--ds-shadow-1);
  }
  [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {
    background: var(--ds-bg-0);
    border-left: 3px solid var(--ds-blue);
  }
  [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
    background: var(--ds-bg-0);
    border-left: 3px solid var(--ds-amber);
  }
  [data-testid="stChatMessage"] [data-testid="chatAvatarIcon-assistant"],
  [data-testid="stChatMessage"] [data-testid="chatAvatarIcon-user"] {
    background: var(--ds-bg-2) !important;
    border: 1px solid var(--ds-border-1);
  }

  /* =========================================================
     10. Expanders
     ========================================================= */
  [data-testid="stExpander"] {
    background: var(--ds-bg-0);
    border: 1px solid var(--ds-border-1) !important;
    border-radius: var(--r-md) !important;
    margin: 6px 0 !important;
    box-shadow: var(--ds-shadow-1);
  }
  [data-testid="stExpander"] summary {
    color: var(--ds-text-1);
    font-size: 13.5px; font-weight: 500;
    padding: 12px 16px !important;
  }
  [data-testid="stExpander"] summary:hover { background: var(--ds-bg-1); }
  [data-testid="stExpander"] details[open] > summary {
    border-bottom: 1px solid var(--ds-border-1);
  }

  /* =========================================================
     11. Status block / notifications
     ========================================================= */
  [data-testid="stStatusWidget"], [data-testid="stStatus"] {
    background: var(--ds-bg-0);
    border: 1px solid var(--ds-border-1) !important;
    border-radius: var(--r-md) !important;
    box-shadow: var(--ds-shadow-1);
  }
  div[data-baseweb="notification"] {
    border-radius: var(--r-md) !important;
    border: 1px solid var(--ds-border-1) !important;
  }

  /* =========================================================
     12. DataFrames
     ========================================================= */
  [data-testid="stDataFrame"] { border: 1px solid var(--ds-border-1); border-radius: var(--r-md); overflow: hidden; box-shadow: var(--ds-shadow-1); }
  [data-testid="stDataFrame"] [role="row"] { border-bottom: 1px solid var(--ds-border-1); }
  [data-testid="stDataFrame"] [role="columnheader"] {
    background: var(--ds-bg-1) !important;
    color: var(--ds-text-2) !important;
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em;
  }
  [data-testid="stDataFrame"] [role="row"]:hover { background: var(--ds-bg-1); }

  /* =========================================================
     13. Agent swarm cards — restrained, white, accent on success
     ========================================================= */
  .ds-agent-card {
    position: relative;
    background: var(--ds-bg-0);
    border: 1px solid var(--ds-border-1);
    border-radius: var(--r-md);
    padding: 16px 14px;
    text-align: center;
    transition: all 200ms ease;
    overflow: hidden;
    box-shadow: var(--ds-shadow-1);
  }
  .ds-agent-card::before {
    content: ""; position: absolute; top: 0; left: 0; right: 0; height: 2px;
    background: var(--ds-border-2);
    transition: background 200ms ease;
  }
  .ds-agent-card.ok::before    { background: var(--ds-accent); }
  .ds-agent-card.err::before   { background: var(--ds-rose); }
  .ds-agent-card.warn::before  { background: var(--ds-amber); }
  .ds-agent-card.run::before {
    background: var(--ds-accent);
    animation: ds-shimmer 1.5s ease-in-out infinite;
  }
  .ds-agent-card .icon { font-size: 22px; line-height: 1; margin-bottom: 6px; color: var(--ds-text-1); }
  .ds-agent-card .name { font-size: 12.5px; font-weight: 600; color: var(--ds-text-0);
                          margin-top: 4px; letter-spacing: -0.005em; }
  .ds-agent-card .meta { font-size: 10.5px; color: var(--ds-text-3); margin-top: 4px;
                          font-family: 'JetBrains Mono', monospace; }
  @keyframes ds-shimmer { 0%,100% { opacity: 0.4; } 50% { opacity: 1; } }

  /* =========================================================
     14. Pills + badges
     ========================================================= */
  .ds-pill-status {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 4px 10px; border-radius: var(--r-pill);
    font-size: 11px; font-weight: 600;
    border: 1px solid var(--ds-border-2);
    background: var(--ds-bg-0);
  }
  .ds-pill-idle    { background: var(--ds-bg-2); color: var(--ds-text-2); }
  .ds-pill-running { background: var(--ds-accent-soft); color: var(--ds-accent-strong);
                      animation: ds-pulse 1.5s ease-in-out infinite; }
  .ds-pill-ok      { background: var(--ds-accent-soft); color: var(--ds-accent-strong);
                      border-color: rgba(14,165,164,0.30); }
  .ds-pill-warn    { background: rgba(180,83,9,0.08); color: var(--ds-amber);
                      border-color: rgba(180,83,9,0.25); }
  .ds-pill-err     { background: rgba(185,28,28,0.08); color: var(--ds-rose);
                      border-color: rgba(185,28,28,0.25); }
  @keyframes ds-pulse {
    0%,100% { box-shadow: 0 0 0 0 rgba(14,165,164,0.0); }
    50%     { box-shadow: 0 0 0 6px rgba(14,165,164,0.10); }
  }

  /* =========================================================
     15. Score chip + Second-Opinion review
     ========================================================= */
  .ds-score { display: inline-block; padding: 8px 16px; border-radius: var(--r-md);
               font-family: 'JetBrains Mono', monospace; font-weight: 700; font-size: 22px;
               background: var(--ds-accent-soft); color: var(--ds-accent-strong);
               border: 1px solid rgba(14,165,164,0.20); }
  .ds-score-low { background: rgba(185,28,28,0.06); color: var(--ds-rose);
                   border-color: rgba(185,28,28,0.20); }
  .ds-score-mid { background: rgba(180,83,9,0.06); color: var(--ds-amber);
                   border-color: rgba(180,83,9,0.20); }

  .ds-review {
    border-left: 3px solid var(--ds-border-2);
    padding: 14px 18px;
    background: var(--ds-bg-0);
    border: 1px solid var(--ds-border-1);
    border-left-width: 3px;
    border-radius: 0 var(--r-md) var(--r-md) 0;
    margin: 8px 0;
    box-shadow: var(--ds-shadow-1);
  }
  .ds-review-high { border-left-color: var(--ds-rose);
                     background: linear-gradient(90deg, rgba(185,28,28,0.04) 0%, var(--ds-bg-0) 60%); }
  .ds-review-med  { border-left-color: var(--ds-amber);
                     background: linear-gradient(90deg, rgba(180,83,9,0.04) 0%, var(--ds-bg-0) 60%); }
  .ds-review-low  { border-left-color: var(--ds-accent);
                     background: linear-gradient(90deg, rgba(14,165,164,0.04) 0%, var(--ds-bg-0) 60%); }
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
     17. Legacy utterance bubble support
     ========================================================= */
  .ds-utt { padding: 12px 16px; margin: 6px 0; border-radius: var(--r-md);
             border: 1px solid var(--ds-border-1); font-size: 14px; line-height: 1.5;
             background: var(--ds-bg-0); }
  .ds-utt-provider  { border-left: 3px solid var(--ds-blue); }
  .ds-utt-patient   { border-left: 3px solid var(--ds-amber); }
  .ds-utt-assistant { border-left: 3px solid var(--ds-purple); }
  .ds-utt-interim   { color: var(--ds-text-3); font-style: italic; }
  .ds-utt .who      { font-size: 10px; letter-spacing: 0.10em; text-transform: uppercase;
                       color: var(--ds-text-3); margin-right: 8px; font-weight: 600; }

  /* =========================================================
     18. Hide Streamlit chrome we don't want
     ========================================================= */
  #MainMenu, header[data-testid="stHeader"], footer { visibility: hidden; }
  .stDeployButton { display: none; }

  /* =========================================================
     19. Arini-style demo audio card — the signature element
     ========================================================= */
  .ds-demo-card {
    background: var(--ds-bg-0);
    border: 1px solid var(--ds-border-1);
    border-radius: var(--r-lg);
    padding: 18px 20px;
    box-shadow: var(--ds-shadow-2);
    margin: 16px 0 0 0;
  }
  .ds-demo-card .row {
    display: flex; align-items: center; gap: 14px;
  }
  .ds-demo-card .play {
    width: 44px; height: 44px; border-radius: 50%;
    background: var(--ds-text-0); color: #FFFFFF;
    display: flex; align-items: center; justify-content: center;
    font-size: 16px; flex-shrink: 0;
    box-shadow: 0 1px 2px rgba(11,20,38,0.10), 0 8px 16px -8px rgba(11,20,38,0.18);
  }
  .ds-demo-card .title {
    font-size: 14px; font-weight: 600; color: var(--ds-text-0);
    letter-spacing: -0.005em;
  }
  .ds-demo-card .sub {
    font-size: 12px; color: var(--ds-text-2);
    margin-top: 2px;
  }
  .ds-demo-card .waveform {
    flex: 1; height: 32px;
    background: linear-gradient(90deg,
       var(--ds-accent-soft) 0%, var(--ds-accent-soft) 20%,
       var(--ds-bg-2) 20%, var(--ds-bg-2) 100%);
    border-radius: var(--r-sm);
    position: relative;
  }
  .ds-demo-card .waveform::before {
    content: ""; position: absolute; inset: 4px;
    background:
      repeating-linear-gradient(90deg,
        var(--ds-accent) 0px, var(--ds-accent) 2px,
        transparent 2px, transparent 5px) 0 50% / 22% 60% no-repeat,
      repeating-linear-gradient(90deg,
        var(--ds-border-3) 0px, var(--ds-border-3) 2px,
        transparent 2px, transparent 5px) 22% 50% / 78% 60% no-repeat;
    border-radius: 4px;
    opacity: 0.6;
  }
</style>
"""


# ---------- Python helpers (Streamlit-aware wrappers) ----------

def inject_global_css() -> None:
    """Inject the design system once per page. Idempotent."""
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


def hero(title: str, subtitle: str, pill: str = "DENTASCRIBE  •  DALLAS, TX") -> None:
    """Branded hero header. Big clinical headline, restrained gradient corner."""
    st.markdown(
        f'<div class="ds-hero">'
        f'<div class="ds-pill">{pill}</div>'
        f'<h1>{title}</h1>'
        f'<p>{subtitle}</p>'
        f'</div>',
        unsafe_allow_html=True,
    )


def hero_with_demo(title: str, subtitle: str,
                   demo_title: str = "Hear the swarm in action",
                   demo_sub: str = "30-sec sample of a real dental consultation",
                   pill: str = "DENTASCRIBE  •  DALLAS, TX") -> None:
    """Arini-style hero — headline + subtitle on the left, demo audio card
    on the right. Visual signature element."""
    st.markdown(
        f'<div class="ds-hero">'
        f'  <div style="display:grid;grid-template-columns:1.4fr 1fr;gap:32px;align-items:center;">'
        f'    <div>'
        f'      <div class="ds-pill">{pill}</div>'
        f'      <h1 style="margin-top:14px;">{title}</h1>'
        f'      <p>{subtitle}</p>'
        f'    </div>'
        f'    <div class="ds-demo-card">'
        f'      <div class="row">'
        f'        <div class="play">▶</div>'
        f'        <div style="flex:1;">'
        f'          <div class="title">{demo_title}</div>'
        f'          <div class="sub">{demo_sub}</div>'
        f'        </div>'
        f'      </div>'
        f'      <div style="margin-top:14px;" class="waveform"></div>'
        f'    </div>'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def card_open(title: str | None = None) -> None:
    """Open a styled card."""
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
