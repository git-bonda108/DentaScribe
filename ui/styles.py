"""Inject custom CSS — applied once at app boot."""
from ui.theme import COLORS, RADIUS


def inject_css() -> str:
    c = COLORS
    return f"""
    <style>
    /* ---------- Global ---------- */
    .main .block-container {{
        padding-top: 1.25rem;
        padding-bottom: 2rem;
        max-width: 1280px;
    }}
    html, body, [class*="css"] {{
        color: {c['text']};
    }}
    h1, h2, h3, h4 {{
        color: {c['navy']};
        font-weight: 700;
        letter-spacing: -0.01em;
    }}

    /* ---------- Header / hero ---------- */
    .ds-hero {{
        background: linear-gradient(135deg, {c['primary']} 0%, {c['navy']} 100%);
        color: white;
        padding: 22px 26px;
        border-radius: {RADIUS['lg']};
        margin-bottom: 18px;
        display: flex; align-items: center; justify-content: space-between;
        box-shadow: 0 6px 20px rgba(11, 42, 74, 0.15);
    }}
    .ds-hero h1 {{ color: white; margin: 0; font-size: 1.7rem; }}
    .ds-hero p  {{ color: rgba(255,255,255,.85); margin: 6px 0 0; }}
    .ds-hero-badge {{
        background: rgba(255,255,255,.15);
        padding: 6px 12px; border-radius: {RADIUS['pill']};
        font-size: 0.78rem; font-weight: 600; letter-spacing: .04em;
    }}

    /* ---------- Cards / surfaces ---------- */
    .ds-card {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: {RADIUS['lg']};
        padding: 18px 20px;
        margin-bottom: 14px;
        box-shadow: 0 1px 2px rgba(15, 23, 42, .04);
    }}
    .ds-card h4 {{
        margin: 0 0 10px 0; font-size: 0.95rem;
        text-transform: uppercase; letter-spacing: 0.08em;
        color: {c['muted']};
    }}
    .ds-metric {{
        display: flex; flex-direction: column; gap: 4px;
    }}
    .ds-metric-value {{
        font-size: 1.75rem; font-weight: 700; color: {c['navy']};
    }}
    .ds-metric-label {{
        color: {c['muted']}; font-size: 0.85rem;
    }}

    /* ---------- Badges ---------- */
    .ds-badge {{
        display: inline-block;
        padding: 3px 10px;
        border-radius: {RADIUS['pill']};
        font-size: 0.72rem;
        font-weight: 600;
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }}
    .ds-badge.primary {{ background: {c['primary_light']}; color: {c['primary_dark']}; }}
    .ds-badge.mint    {{ background: #E6FBF8;             color: #047867; }}
    .ds-badge.amber   {{ background: #FEF3C7;             color: #B45309; }}
    .ds-badge.red     {{ background: #FEE2E2;             color: #B91C1C; }}
    .ds-badge.green   {{ background: #DCFCE7;             color: #15803D; }}
    .ds-badge.navy    {{ background: #DBEAFE;             color: {c['navy']}; }}
    .ds-badge.muted   {{ background: #F1F5F9;             color: {c['muted']}; }}

    /* ---------- Transcript / speaker bubbles ---------- */
    .ds-bubble {{
        padding: 10px 14px; border-radius: {RADIUS['md']};
        margin-bottom: 8px; line-height: 1.45;
    }}
    .ds-bubble.doctor  {{ background: {c['primary_light']}; border-left: 3px solid {c['primary']}; }}
    .ds-bubble.patient {{ background: #F1F5F9;              border-left: 3px solid {c['navy']}; }}
    .ds-bubble-speaker {{
        font-size: 0.74rem; font-weight: 700; text-transform: uppercase;
        letter-spacing: 0.06em; color: {c['muted']}; margin-bottom: 4px;
    }}

    /* ---------- Sidebar ---------- */
    section[data-testid="stSidebar"] {{
        background: linear-gradient(180deg, {c['navy']} 0%, #0F1F35 100%);
    }}
    section[data-testid="stSidebar"] * {{ color: #E2E8F0 !important; }}
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {{ color: white !important; }}
    section[data-testid="stSidebar"] label {{ color: #94A3B8 !important; }}

    /* ---------- Buttons ---------- */
    .stButton > button {{
        background: {c['primary']};
        color: white !important;
        border: none;
        border-radius: {RADIUS['md']};
        font-weight: 600;
        padding: 8px 18px;
        transition: all .15s;
    }}
    .stButton > button:hover {{
        background: {c['primary_dark']};
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(14, 165, 164, .25);
    }}
    .stDownloadButton > button {{
        background: {c['navy']}; color: white !important;
        border: none; border-radius: {RADIUS['md']}; font-weight: 600;
    }}

    /* ---------- Tabs ---------- */
    .stTabs [data-baseweb="tab-list"] {{ gap: 4px; }}
    .stTabs [data-baseweb="tab"] {{
        background: transparent;
        color: {c['muted']};
        font-weight: 600;
        border-radius: {RADIUS['md']} {RADIUS['md']} 0 0;
        padding: 8px 14px;
    }}
    .stTabs [aria-selected="true"] {{
        color: {c['primary_dark']} !important;
        background: {c['primary_light']};
    }}

    /* ---------- SOAP block ---------- */
    .soap-block {{
        background: {c['surface']};
        border-left: 4px solid {c['primary']};
        padding: 12px 16px;
        margin-bottom: 12px;
        border-radius: 0 {RADIUS['md']} {RADIUS['md']} 0;
    }}
    .soap-block h5 {{
        margin: 0 0 6px 0; color: {c['primary_dark']};
        font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.08em;
    }}
    .soap-block p {{ margin: 0; color: {c['text']}; }}

    /* ---------- CDT code chip ---------- */
    .cdt-chip {{
        display: inline-flex; align-items: center; gap: 6px;
        background: #F0FDFA; border: 1px solid #99F6E4;
        padding: 6px 10px; border-radius: {RADIUS['md']};
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
        font-size: 0.85rem;
        margin: 2px 4px 2px 0;
        color: {c['navy']};
    }}
    .cdt-chip strong {{ color: {c['primary_dark']}; }}

    /* ---------- Footer ---------- */
    .ds-footer {{
        text-align: center; color: {c['muted']};
        font-size: 0.78rem; padding: 12px 0; margin-top: 24px;
        border-top: 1px solid {c['border']};
    }}
    </style>
    """
