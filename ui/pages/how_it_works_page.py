"""How it works — workflow + functionality explainer page.

A single scrollable narrative that answers, for a dentist or buyer:
  - What does DentaScribe do?
  - What's the workflow from "patient walks in" to "signed chart"?
  - What's in the agent swarm and what does each agent do?
  - What do I get back at the end?
  - What does it cost and what about Texas compliance?

Lives below Admin in the sidebar nav. Static page — no LLM calls, no
heavy state. Acts as both onboarding for first-time users and a
sales-style overview for stakeholders.
"""
from __future__ import annotations
import streamlit as st

from ui.theme import inject_global_css, hero


def render() -> None:
    inject_global_css()

    hero(
        title="From conversation to chart in 60 seconds.",
        subtitle=(
            "DentaScribe listens to the doctor-patient consultation, drafts a "
            "Texas-compliant SOAP note with CDT 2026 billing codes, runs a "
            "second-opinion safety review, and lets the provider attest "
            "and sign — all before the patient leaves the operatory."
        ),
        eyebrow="HOW IT WORKS",
        accent_word="60 seconds.",
    )

    # ---------- 1. Workflow steps ----------
    _section_label("01 · The workflow")
    st.markdown(
        '<div style="margin-bottom:12px;color:#5A6478;font-size:14px;line-height:1.6;">'
        'Same shape as the dentist\'s existing chart workflow — but the typing '
        'and the coding happen automatically.</div>',
        unsafe_allow_html=True,
    )

    steps = [
        ("01", "Capture",
         "Paste a dictation, drop in a .wav/.mp3, or hit Live mic to record "
         "the consultation in real time. Deepgram Nova-3 Medical transcribes "
         "with dental-keyterm boost so terms like <i>periapical, "
         "irreversible pulpitis, D3330</i> land correctly the first time.",
         "🎙️"),
        ("02", "Swarm",
         "Five specialized agents run in sequence: <b>Scribe</b> writes a "
         "Texas-compliant SOAP, <b>Compliance</b> fills the TSBDE 22 TAC "
         "§108.8 checklist, <b>Coder</b> picks CDT 2026 codes (allow-list "
         "constrained — never invents), <b>Validator</b> scores grounding "
         "and structure, <b>Second-Opinion</b> flags safety + billing gaps.",
         "🤖"),
        ("03", "Coach (live)",
         "If you're recording live, a sixth agent — the <b>Dental Coach</b> — "
         "watches the rolling transcript and surfaces recommendations as the "
         "conversation unfolds: drug interactions, history gaps, diagnostic "
         "tests to consider, CDT codes accumulating.",
         "🩺"),
        ("04", "Review",
         "The note appears in 6 tabs: Conversation · SOAP · Recommendations · "
         "Second-Opinion · Tooth chart · Audit & Cost. Edits are immediate. "
         "Every claim is grounded in a transcript span — hover to see the quote.",
         "🔍"),
        ("05", "Attest & sign",
         "Signability gates sign-off: the attestation block unlocks only when "
         "every structural error is resolved and the score is ≥85. The "
         "provider types their name, the AI-assisted disclosure auto-marks, "
         "and the chart is signed.",
         "✅"),
        ("06", "Export",
         "Download as a printable <b>DOCX</b> (matches a clinic\'s house "
         "letterhead with provider sig + AI disclosure + audit footer), "
         "<b>PDF</b> for fax/email, or raw <b>JSON</b> for the PMS integration.",
         "📤"),
    ]

    for num, title, body, icon in steps:
        st.markdown(
            f'<div style="display:grid;grid-template-columns:60px 1fr 50px;'
            f'gap:18px;align-items:start;padding:18px 22px;background:#FFFFFF;'
            f'border:1px solid #EEF1F5;border-radius:14px;margin-bottom:12px;'
            f'box-shadow:0 1px 2px rgba(11,20,38,0.04);">'
            f'  <div style="font-family:\'JetBrains Mono\',monospace;'
            f'              font-size:22px;font-weight:600;color:#0EA5A4;'
            f'              letter-spacing:-0.01em;line-height:1.1;">{num}</div>'
            f'  <div>'
            f'    <div style="font-size:17px;font-weight:600;color:#0B1426;'
            f'                letter-spacing:-0.015em;margin-bottom:4px;'
            f'                font-family:\'Inter Tight\',\'Inter\',sans-serif;">'
            f'{title}</div>'
            f'    <div style="font-size:14px;color:#5A6478;line-height:1.6;">{body}</div>'
            f'  </div>'
            f'  <div style="font-size:28px;text-align:center;opacity:0.85;">{icon}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.divider()

    # ---------- 2. Agent swarm ----------
    _section_label("02 · The agent swarm")
    st.markdown(
        '<div style="margin-bottom:16px;color:#5A6478;font-size:14px;line-height:1.6;">'
        'Six bounded specialists. Each has a single job and a strict contract. '
        'No one agent owns the whole note — that\'s how we keep hallucinations out.</div>',
        unsafe_allow_html=True,
    )

    agents = [
        ("📝", "Scribe", "Claude",
         "Drafts the SOAP note. Every claim must quote a transcript span; "
         "uncertain values become `null` + flagged in <code>quality_flags</code>."),
        ("🛡️", "Compliance", "Deterministic",
         "Fills the TSBDE 22 TAC §108.8 checklist by inspecting the SOAP + "
         "clinic env. No LLM — just a structured boolean check. Keeps the "
         "audit trail bulletproof."),
        ("💼", "Coder", "Claude (constrained)",
         "Maps documented procedures to CDT 2026 codes. Restricted to the "
         "<code>cdt_allow_list.json</code> — never invents codes. Surface-count "
         "logic refines composites (D2391→D2392/3/4)."),
        ("✅", "Validator", "Deterministic",
         "Four layers: structural (JSON Schema) · grounding (every span found "
         "verbatim in transcript) · CDT allow-list · Texas TSBDE soft rules. "
         "Outputs a signability score 0–100."),
        ("🩺", "Second-Opinion", "Claude",
         "Peer-reviews the completed note. Bounded to 6 categories: missed dx, "
         "missing documentation, drug interactions, billing gaps, compliance, "
         "patient safety. Cites or stays quiet."),
        ("🩹", "Dental Coach", "Claude + 6 tools",
         "Live-recording-only. Calls deterministic tools (drug-interaction, "
         "CDT-candidates, pulpal-status, TSBDE-anchor) and surfaces "
         "recommendations to the doctor in real time."),
    ]

    cols_per_row = 3
    for i in range(0, len(agents), cols_per_row):
        cols = st.columns(cols_per_row, gap="medium")
        for col, (icon, name, kind, body) in zip(cols, agents[i:i+cols_per_row]):
            kind_color = "#0EA5A4" if "Claude" in kind else "#7C3AED"
            col.markdown(
                f'<div style="background:#FFFFFF;border:1px solid #EEF1F5;'
                f'border-radius:14px;padding:20px;box-shadow:0 1px 2px rgba(11,20,38,0.04);'
                f'height:100%;">'
                f'  <div style="display:flex;align-items:center;gap:10px;'
                f'              margin-bottom:10px;">'
                f'    <div style="font-size:22px;">{icon}</div>'
                f'    <div>'
                f'      <div style="font-weight:600;color:#0B1426;font-size:15px;'
                f'                  font-family:\'Inter Tight\',\'Inter\',sans-serif;'
                f'                  letter-spacing:-0.01em;">{name}</div>'
                f'      <div style="font-size:10px;color:{kind_color};font-weight:700;'
                f'                  letter-spacing:0.10em;text-transform:uppercase;'
                f'                  margin-top:1px;">{kind}</div>'
                f'    </div>'
                f'  </div>'
                f'  <div style="font-size:13px;color:#5A6478;line-height:1.55;">{body}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.divider()

    # ---------- 3. Outputs ----------
    _section_label("03 · What you get")
    outputs = [
        ("📄  Clinical SOAP — DOCX",
         "Printable Word document a dentist would actually sign. Brand header, "
         "encounter anchor, OPQRST history, per-tooth findings table, billing "
         "CDT table, TSBDE compliance checklist with ✓/⚠/✗ marks, "
         "attestation block with AI-disclosure, audit footer."),
        ("📑  Clinical SOAP — PDF",
         "Same layout, paginated and ready for fax/email/print. Page-footer "
         "auto-stamps generation time and signability score."),
        ("{ }  Raw SOAP JSON",
         "Internal audit format. Full structured tree with grounding spans "
         "for every populated field. Replay any prior consultation through "
         "the validator without re-running Claude."),
        ("📋  Blank template",
         "Office-ready blank DOCX you can hand to new staff or fill in by "
         "hand if the system is down."),
    ]
    cols = st.columns(2, gap="medium")
    for i, (title, body) in enumerate(outputs):
        with cols[i % 2]:
            st.markdown(
                f'<div style="background:#FFFFFF;border:1px solid #EEF1F5;'
                f'border-radius:14px;padding:20px;box-shadow:0 1px 2px rgba(11,20,38,0.04);'
                f'margin-bottom:14px;">'
                f'  <div style="font-weight:600;color:#0B1426;font-size:15px;'
                f'              margin-bottom:6px;letter-spacing:-0.01em;'
                f'              font-family:\'Inter Tight\',\'Inter\',sans-serif;">{title}</div>'
                f'  <div style="font-size:13px;color:#5A6478;line-height:1.55;">{body}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.divider()

    # ---------- 4. Cost + compliance ----------
    cols = st.columns(2, gap="large")
    with cols[0]:
        _section_label("04 · Cost transparency")
        st.markdown(
            '<div style="background:#FFFFFF;border:1px solid #EEF1F5;'
            'border-radius:14px;padding:22px;box-shadow:0 1px 2px rgba(11,20,38,0.04);">'
            '  <div style="font-size:38px;font-weight:700;color:#0B1426;'
            '              font-family:\'JetBrains Mono\',monospace;'
            '              letter-spacing:-0.02em;line-height:1.1;">$0.06</div>'
            '  <div style="font-size:11px;color:#8A95AB;letter-spacing:0.10em;'
            '              text-transform:uppercase;font-weight:600;margin-top:6px;">'
            '    Typical consultation</div>'
            '  <div style="border-top:1px solid #EEF1F5;margin-top:18px;padding-top:14px;'
            '              font-size:13px;color:#5A6478;line-height:1.7;">'
            '    Scribe + Second-Opinion = 2 Claude calls (~7k tokens)<br>'
            '    Compliance + Validator = deterministic, $0<br>'
            '    + Coach mode: ~$0.10–0.20 if live recording'
            '  </div>'
            '  <div style="font-size:12px;color:#0EA5A4;margin-top:14px;font-weight:600;">'
            '    Every call is tracked per agent in the Audit page.</div>'
            '</div>',
            unsafe_allow_html=True,
        )

    with cols[1]:
        _section_label("05 · Texas-ready")
        st.markdown(
            '<div style="background:#FFFFFF;border:1px solid #EEF1F5;'
            'border-radius:14px;padding:22px;box-shadow:0 1px 2px rgba(11,20,38,0.04);">'
            '  <div style="font-size:15px;font-weight:600;color:#0B1426;'
            '              margin-bottom:12px;font-family:\'Inter Tight\',\'Inter\',sans-serif;'
            '              letter-spacing:-0.01em;">'
            '    TSBDE 22 TAC §108.8 — every box, every chart</div>'
            '  <ul style="font-size:13px;color:#5A6478;line-height:1.8;padding-left:18px;'
            '             margin:0;">'
            '    <li>Patient identification</li>'
            '    <li>Provider name + TSBDE license #</li>'
            '    <li>Date of service</li>'
            '    <li>Chief complaint + history</li>'
            '    <li>Diagnosis + plan</li>'
            '    <li>Treatment, materials, medications</li>'
            '    <li>Informed consent flag</li>'
            '    <li>Radiograph reference (if rads taken)</li>'
            '    <li>Anesthetic record (if applicable)</li>'
            '    <li>5-year retention (adult) · age-of-majority + 5y (minor)</li>'
            '  </ul>'
            '  <div style="font-size:11px;color:#8A95AB;margin-top:14px;'
            '              border-top:1px solid #EEF1F5;padding-top:12px;">'
            '    Sign-off is blocked until structural and grounding checks pass.</div>'
            '</div>',
            unsafe_allow_html=True,
        )

    st.divider()

    # ---------- 6. Trust footer ----------
    _section_label("06 · Why DentaScribe")
    cols = st.columns(3, gap="medium")
    pillars = [
        ("Grounded",
         "Every clinical claim quotes the transcript verbatim. If it's not "
         "in the transcript, it's not in the note."),
        ("Constrained",
         "CDT codes come from a sealed allow-list. The model re-ranks; "
         "it never invents."),
        ("Reviewed",
         "Two LLMs see every note — Scribe writes, Second-Opinion peer-reviews. "
         "Disagreements surface before signing."),
    ]
    for col, (title, body) in zip(cols, pillars):
        col.markdown(
            f'<div style="background:#FFFFFF;border:1px solid #EEF1F5;'
            f'border-radius:14px;padding:22px;box-shadow:0 1px 2px rgba(11,20,38,0.04);'
            f'height:100%;">'
            f'  <div style="font-size:17px;font-weight:600;color:#0B1426;'
            f'              margin-bottom:8px;font-family:\'Inter Tight\',\'Inter\',sans-serif;'
            f'              letter-spacing:-0.015em;">{title}</div>'
            f'  <div style="font-size:13px;color:#5A6478;line-height:1.6;">{body}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown(
        '<div style="margin:40px 0 8px;text-align:center;font-size:13px;'
        'color:#8A95AB;line-height:1.6;">'
        'DentaScribe MVP · Dallas, TX · TSBDE 22 TAC §108.8 compliant<br>'
        'AI-assisted; provider-signed. Every chart is reviewed and signed by '
        'a licensed dentist before becoming part of the patient record.'
        '</div>',
        unsafe_allow_html=True,
    )


def _section_label(text: str) -> None:
    st.markdown(
        f'<div style="font-family:\'JetBrains Mono\',monospace;font-size:11px;'
        f'font-weight:600;color:#8A95AB;letter-spacing:0.14em;text-transform:uppercase;'
        f'margin:8px 0 14px;">{text}</div>',
        unsafe_allow_html=True,
    )
