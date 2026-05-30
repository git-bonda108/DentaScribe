"""DentaScribe v2 — card-based Streamlit UX (TSBDE / Dallas defaults).

Run: streamlit run app_v2.py
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from core.config import load_config
from core.state import SwarmState
from core.db import ConsultationStore
from agents.orchestrator import Orchestrator
from ui.components import soap_block, cdt_chip, speaker_bubble
from utils.fixtures import DEMO_TRANSCRIPTS, get_demo_transcript

DATA = Path(__file__).resolve().parent / "data"

st.set_page_config(
    page_title="DentaScribe — Clinical AI Scribe",
    page_icon="🦷",
    layout="wide",
    initial_sidebar_state="expanded",
)

BRAND = {
    "primary": "#0E5C8E",
    "accent": "#22B8A6",
    "warn": "#E0A800",
    "danger": "#D64545",
    "bg": "#F6F9FC",
    "ink": "#0F1E2E",
    "muted": "#5B6B7B",
}

VISIT_TYPES = [
    ("emergency", "Emergency (Endo-capable)"),
    ("emergency_limited", "Emergency / Limited"),
    ("periodic_recall", "Periodic Recall"),
    ("restorative_direct", "Restorative (Direct)"),
    ("restorative_indirect", "Restorative (Indirect)"),
    ("endodontic", "Endodontic"),
    ("periodontal_hygiene", "Periodontal / Hygiene"),
]

st.markdown(
    f"""
<style>
.stApp {{ background:{BRAND['bg']}; color:{BRAND['ink']}; }}
.ds-card {{ background:#fff;border:1px solid #E3EAF1;border-radius:14px;
  padding:18px 20px;box-shadow:0 1px 2px rgba(15,30,46,.04);margin-bottom:14px; }}
.ds-pill {{ display:inline-block;padding:2px 10px;border-radius:999px;
  font-size:12px;font-weight:600;margin-right:6px; }}
.ds-pill.ok {{ background:#E6F7F2;color:#0E7C66; }}
.ds-pill.warn {{ background:#FFF5DA;color:#8A6A00; }}
.ds-pill.bad {{ background:#FDE6E6;color:#9F2A2A; }}
.ds-quote {{ border-left:3px solid {BRAND['accent']};padding:6px 10px;
  background:#F0FBF8;border-radius:6px;font-style:italic;color:{BRAND['muted']}; }}
.ds-h {{ font-size:13px;font-weight:700;color:{BRAND['primary']};
  letter-spacing:.04em;text-transform:uppercase;margin-bottom:6px; }}
div[data-testid="stSidebar"] {{ background:{BRAND['ink']}; }}
div[data-testid="stSidebar"] * {{ color:#E3EAF1 !important; }}
</style>
""",
    unsafe_allow_html=True,
)


@st.cache_resource
def boot():
    cfg = load_config()
    return cfg, Orchestrator(cfg), ConsultationStore(cfg.db_path)


cfg, swarm, store = boot()


def pill(label: str, kind: str = "ok") -> str:
    return f'<span class="ds-pill {kind}">{label}</span>'


def audit(actor: str, action: str, ref_id: str = "", before=None, after=None) -> None:
    store.append_audit(actor=actor, action=action, ref_id=ref_id, before=before, after=after)


def render_tooth_chart(flagged=None, treated=None):
    flagged = flagged or set()
    treated = treated or set()
    upper = list(range(1, 17))
    lower = list(range(32, 16, -1))
    svg = [
        '<svg viewBox="0 0 880 230" xmlns="http://www.w3.org/2000/svg" '
        'style="width:100%;max-width:880px;">'
    ]

    def row(nums, y):
        for i, n in enumerate(nums):
            x = 20 + i * 53
            fill = "#fff"
            stroke = "#9FB4C7"
            if n in treated:
                fill = "#D6F2EC"
                stroke = BRAND["accent"]
            elif n in flagged:
                fill = "#FFF1CC"
                stroke = BRAND["warn"]
            svg.append(
                f'<rect x="{x}" y="{y}" width="44" height="78" rx="10" '
                f'fill="{fill}" stroke="{stroke}"/>'
            )
            svg.append(
                f'<text x="{x + 22}" y="{y + 45}" font-size="14" '
                f'text-anchor="middle" fill="{BRAND["ink"]}">{n}</text>'
            )

    row(upper, 20)
    row(lower, 120)
    svg.append("</svg>")
    st.markdown("".join(svg), unsafe_allow_html=True)


def _provider_name() -> str:
    return st.session_state.get("provider_name") or "Provider"


def _is_attested(state: dict) -> bool:
    att = state.get("attestation") or {}
    return bool(
        att.get("provider_reviewed")
        and att.get("ai_assisted_disclosure")
        and att.get("provider_signature")
    )


def _process(
    *,
    wav_bytes: bytes | None = None,
    transcript: str | None = None,
    patient_name: str,
    doctor_name: str,
    patient_id: str,
    visit_type: str,
):
    ref = patient_id or f"DS-{uuid.uuid4().hex[:6].upper()}"
    state = SwarmState(
        patient_name=patient_name or "Walk-in",
        doctor_name=doctor_name or _provider_name(),
        patient_id=ref,
        visit_type=visit_type,
    )
    audit(_provider_name(), "open_consultation", ref)

    progress = st.progress(0, text="Initializing agent swarm…")
    log_area = st.empty()

    def push(msg: str):
        log_area.markdown(
            f'<div class="ds-card" style="padding:8px 14px;font-family:ui-monospace,'
            f'monospace;font-size:.85rem;color:{BRAND["primary"]}">▸ {msg}</div>',
            unsafe_allow_html=True,
        )

    try:
        if transcript is not None:
            state.raw_transcript = transcript
            push("Transcript ingested from text input")
            progress.progress(15, text="Transcript ready")
        else:
            push(f"Sending audio to {cfg.stt_provider.upper()}…")
            progress.progress(8, text="Transcribing audio…")
            state.raw_transcript = swarm.transcribe_audio(wav_bytes)
            push(f"Transcript ready ({len(state.raw_transcript)} chars)")
            progress.progress(20, text="Transcription complete")
    except Exception as e:
        st.error(f"Transcription failed: {e}")
        return

    pct = {
        "Diarization": 35,
        "Dental NER": 50,
        "CDT": 65,
        "SOAP": 80,
        "Validation": 92,
    }

    def on_step(msg: str):
        push(msg)
        for k, v in pct.items():
            if k.lower() in msg.lower():
                progress.progress(v, text=msg)
                break

    try:
        state = swarm.run(state, on_step=on_step)
        audit("system", "soap_drafted", ref)
    except Exception as e:
        st.error(f"Agent swarm failed: {e}")
        return

    try:
        payload = state.to_dict()
        store.upsert(payload)
        audit(_provider_name(), "persist_consultation", ref)
        push("Saved to records.")
        progress.progress(100, text="Done")
    except Exception as e:
        st.warning(f"Saved in session only (DB write failed: {e})")

    st.session_state["last_state"] = state.to_dict()
    time.sleep(0.3)
    progress.empty()


def _render_result(state: dict):
    soap = state.get("soap") or {}
    qa = state.get("qa") or {}
    cdt = state.get("cdt_codes") or []
    ref = state.get("patient_id") or state.get("consultation_id", "")[:8]
    attested = _is_attested(state)
    comp = int((qa.get("completeness_score") or 0) * 100)
    warnings = qa.get("warnings") or []
    unconf = qa.get("unconfirmed_terms") or []
    schema_errs = qa.get("schema_errors") or []
    grounding_errs = qa.get("grounding_errors") or []
    cdt_errs = qa.get("cdt_errors") or []
    blockers = (
        [w for w in warnings if w.lower().startswith("block:")]
        + [f"Schema: {e}" for e in schema_errs]
        + [f"Grounding: {e}" for e in grounding_errs]
        + [f"CDT: {e}" for e in cdt_errs]
    )
    sig_raw = qa.get("signability_score")
    sign_pct = int((sig_raw if sig_raw is not None else comp / 100) * 100)
    validation_blocked = bool(schema_errs or grounding_errs or cdt_errs)
    sign_blocked = sign_pct < 85

    top = st.columns([1.2, 1, 1, 1])
    top[0].markdown(
        f"""<div class='ds-card'><div class='ds-h'>Patient</div>
        <b>{state.get('patient_name', 'Walk-in')}</b><br>
        <span style='color:{BRAND["muted"]}'>Ref: {ref}</span></div>""",
        unsafe_allow_html=True,
    )
    vt = state.get("visit_type", "emergency_limited")
    vt_label = next((l for k, l in VISIT_TYPES if k == vt), vt)
    top[1].markdown(
        f"<div class='ds-card'><div class='ds-h'>Visit type</div><b>{vt_label}</b></div>",
        unsafe_allow_html=True,
    )
    top[2].markdown(
        f"""<div class='ds-card'><div class='ds-h'>Signability</div>
        <b style='font-size:24px;color:{BRAND["accent"]}'>{sign_pct}%</b><br>
        <span style='font-size:12px;color:{BRAND["muted"]}'>
        {len(unconf)} unverified · {len(blockers)} blockers</span></div>""",
        unsafe_allow_html=True,
    )
    status_pills = pill("Signed & locked", "ok") if attested else pill("Review required", "warn")
    top[3].markdown(
        f"<div class='ds-card'><div class='ds-h'>Status</div>"
        f"{status_pills}{pill('AI-assisted', 'warn')}</div>",
        unsafe_allow_html=True,
    )

    tabs = st.tabs([
        "📋 SOAP", "💰 CDT", "💬 Transcript", "🦷 Chart",
        "🔎 Entities", "⚠️ Quality", "🧠 Trace", "⬇️ Export & Sign",
    ])

    with tabs[0]:
        c1, c2 = st.columns([1.4, 1])
        with c1:
            if soap.get("chief_complaint"):
                st.markdown(soap_block("Chief Complaint", soap["chief_complaint"]),
                            unsafe_allow_html=True)
            st.markdown(soap_block("Subjective", soap.get("subjective", "")),
                        unsafe_allow_html=True)
            st.markdown(soap_block("Objective", soap.get("objective", "")),
                        unsafe_allow_html=True)
            st.markdown(soap_block("Assessment", soap.get("assessment", "")),
                        unsafe_allow_html=True)
            st.markdown(soap_block("Plan", soap.get("plan", "")),
                        unsafe_allow_html=True)
            if soap.get("notes_for_doctor"):
                st.markdown(
                    f'<div class="ds-card" style="border-left:4px solid {BRAND["warn"]}">'
                    f'<div class="ds-h">Notes for Doctor</div>{soap["notes_for_doctor"]}</div>',
                    unsafe_allow_html=True,
                )
        with c2:
            checklist = [
                pill("Patient ID", "ok"),
                pill("CC + findings", "ok" if soap.get("chief_complaint") else "warn"),
                pill("Dx + plan", "ok" if soap.get("assessment") and soap.get("plan") else "warn"),
                pill("Provider sig", "ok" if attested else "warn"),
            ]
            st.markdown(
                f"<div class='ds-card'><div class='ds-h'>22 TAC §108.8 checklist</div>"
                f"{''.join(checklist)}</div>",
                unsafe_allow_html=True,
            )
            grounded = state.get("soap_structured", {}).get("grounding", {}).get("transcript_spans", [])
            if grounded:
                st.markdown(
                    f"<div class='ds-card'><div class='ds-h'>Grounded fields</div>"
                    f"{len(grounded)} transcript span(s) linked.</div>",
                    unsafe_allow_html=True,
                )

    with tabs[1]:
        if not cdt:
            st.info("No CDT codes inferred.")
        else:
            st.dataframe(
                pd.DataFrame(cdt)[["code", "nomenclature", "confidence", "rationale"]],
                use_container_width=True,
                hide_index=True,
            )
            st.info("Codes constrained to visit-type allow-list + candidate set.")

    with tabs[2]:
        segs = state.get("segments") or []
        if segs:
            for i, s in enumerate(segs, 1):
                st.markdown(speaker_bubble(s["speaker"], s["text"]), unsafe_allow_html=True)
        else:
            st.code(state.get("raw_transcript", ""), language="markdown")

    with tabs[3]:
        flagged = set(state.get("flagged_teeth") or [])
        treated = set(state.get("treated_teeth") or [])
        render_tooth_chart(flagged=flagged, treated=treated)

    with tabs[4]:
        ents = state.get("entities") or []
        if ents:
            st.dataframe(pd.DataFrame(ents), use_container_width=True, hide_index=True)
        else:
            st.info("No entities extracted.")

    with tabs[5]:
        if blockers:
            st.markdown(
                f"<div class='ds-card'><b>{pill('BLOCKERS', 'bad')}</b> "
                f"{'; '.join(blockers[:8])}</div>",
                unsafe_allow_html=True,
            )
        elif validation_blocked or sign_blocked:
            st.markdown(
                f"<div class='ds-card'><b>{pill('BLOCKERS', 'bad')}</b> "
                f"Signability {sign_pct}% — review required before export.</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"<div class='ds-card'><b>{pill('BLOCKERS', 'bad')}</b> None — note is signable.</div>",
                unsafe_allow_html=True,
            )
        if schema_errs or grounding_errs or cdt_errs:
            st.markdown("**Structured validation**")
            if schema_errs:
                st.error("Schema: " + "; ".join(schema_errs[:5]))
            if grounding_errs:
                st.error("Grounding: " + "; ".join(grounding_errs[:5]))
            if cdt_errs:
                st.error("CDT allow-list: " + "; ".join(cdt_errs[:5]))
        non_block_warnings = [w for w in warnings if not w.lower().startswith("block:")]
        if non_block_warnings or unconf:
            lines = [f"• {w}" for w in non_block_warnings]
            lines += [f"• Unverified: {t}" for t in unconf[:12]]
            st.markdown(
                f"<div class='ds-card'><b>{pill('WARNINGS', 'warn')}</b><br>"
                + "<br>".join(lines) + "</div>",
                unsafe_allow_html=True,
            )
        elif not blockers:
            st.success("No quality issues detected.")

    with tabs[6]:
        for entry in state.get("agent_trace") or []:
            st.markdown(
                f"<div class='ds-card' style='padding:10px'>"
                f"<b>{entry.get('agent')}</b> · "
                f"<span style='color:{BRAND['muted']}'>{entry.get('message')}</span></div>",
                unsafe_allow_html=True,
            )

    with tabs[7]:
        from exporters.pdf_export import render_pdf
        from exporters.docx_export import render_docx

        st.markdown("#### Export & Sign")
        att1 = st.checkbox(
            "I have reviewed this AI-generated note and attest to its accuracy. (Required)",
            key=f"att_review_{ref}",
        )
        att2 = st.checkbox(
            "This note was drafted with AI assistance and reviewed by the named provider.",
            key=f"att_ai_{ref}",
            value=True,
        )
        sig = st.text_input("Type your full name to sign", key=f"sig_{ref}")

        col = st.columns(4)
        fname = f"DentaScribe_{state.get('patient_name', 'patient').replace(' ', '_')}"
        pdf_bytes = render_pdf(state)
        docx_bytes = render_docx(state)
        json_bytes = json.dumps(state, indent=2).encode()
        tmpl_path = DATA / "texas_blank_soap_template.json"
        tmpl_bytes = tmpl_path.read_text() if tmpl_path.exists() else "{}"

        export_ok = (
            att1 and att2 and sig.strip() and sig.strip() == _provider_name()
            and not validation_blocked and not sign_blocked
        )
        if not export_ok:
            st.caption(
                "PDF/DOCX/JSON export unlocks after attestation + matching signature, "
                "signability ≥ 85%, and zero schema/grounding/CDT blockers."
            )

        with col[0]:
            st.download_button(
                "⬇️ SOAP (PDF)", pdf_bytes, file_name=f"{fname}.pdf",
                mime="application/pdf", disabled=not export_ok,
            )
        with col[1]:
            st.download_button(
                "⬇️ SOAP (DOCX)", docx_bytes, file_name=f"{fname}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                disabled=not export_ok,
            )
        with col[2]:
            st.download_button(
                "⬇️ SOAP (JSON)", json_bytes, file_name=f"{fname}.json",
                mime="application/json", disabled=not export_ok,
            )
        with col[3]:
            st.download_button(
                "⬇️ Texas Blank Template", tmpl_bytes,
                file_name="texas_blank_soap_template.json",
                mime="application/json",
            )

        if st.button("🖊️ Sign & Lock Note", type="primary", disabled=not export_ok):
            att = state.setdefault("attestation", {})
            att["provider_reviewed"] = True
            att["ai_assisted_disclosure"] = True
            att["provider_signature"] = sig.strip()
            att["signed_at_iso"] = datetime.utcnow().isoformat()
            att["signature_method"] = "typed_name"
            store.upsert(state)
            audit(_provider_name(), "sign_note", ref, after=att)
            st.session_state["last_state"] = state
            st.success("Note signed and locked.")
            st.rerun()


# ---------- Sidebar ----------
with st.sidebar:
    st.markdown("### 🦷 DentaScribe")
    st.caption("Clinical AI scribe · Dallas, TX")
    page = st.radio(
        "Navigate",
        ["Live Consultation", "Templates", "Tooth Chart Lab", "Audit Trail", "About"],
        label_visibility="collapsed",
    )
    st.divider()
    st.caption("Provider")
    st.text_input("Name", value="Dr. A. Patel, DDS", key="provider_name")
    st.text_input("TSBDE License #", value="TX-DDS-#####", key="provider_lic")
    st.selectbox("Role", ["dentist", "hygienist", "specialist"], key="provider_role")
    st.divider()
    llm_label = swarm.llm_provider.upper() if swarm.llm.available else "DEMO MODE"
    st.caption(f"LLM: **{llm_label}** · Stored: **{store.count()}**")


if page == "Live Consultation":
    st.markdown("## Live Consultation")
    st.caption("Capture → Transcribe → SOAP → CDT → Validate → Sign")

    c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
    with c1:
        patient_name = st.text_input("Patient name", placeholder="e.g. Riya Sharma")
    with c2:
        doctor_name = st.text_input("Provider", value=_provider_name())
    with c3:
        visit_key = st.selectbox(
            "Visit type",
            [k for k, _ in VISIT_TYPES],
            format_func=lambda k: next(l for vk, l in VISIT_TYPES if vk == k),
        )
    with c4:
        patient_id = st.text_input("Patient ref", placeholder="de-identified")

    tab_live, tab_upload, tab_paste, tab_demo = st.tabs(
        ["🎙️ Live mic", "📁 Upload", "📝 Paste", "✨ Demo"]
    )

    with tab_live:
        wav_bytes = None
        try:
            from streamlit_mic_recorder import mic_recorder
            rec = mic_recorder(
                start_prompt="🎙️ Start recording",
                stop_prompt="⏹️ Stop recording",
                use_container_width=True,
                format="wav",
                key="ds_mic_v2",
            )
            if rec and rec.get("bytes"):
                wav_bytes = rec["bytes"]
                st.audio(wav_bytes, format="audio/wav")
        except Exception as e:
            st.warning(f"Mic unavailable: {e}")
        if wav_bytes and cfg.has_stt:
            if st.button("🧠 Transcribe & run swarm", use_container_width=True):
                _process(
                    wav_bytes=wav_bytes,
                    patient_name=patient_name,
                    doctor_name=doctor_name,
                    patient_id=patient_id,
                    visit_type=visit_key,
                )
        elif wav_bytes:
            st.error("Configure OPENAI_API_KEY or DEEPGRAM_API_KEY for STT.")

    with tab_upload:
        up = st.file_uploader("Audio", type=["wav", "mp3", "m4a", "ogg", "webm", "flac"])
        if up and cfg.has_stt and st.button("🧠 Transcribe & run swarm", key="up_v2"):
            _process(
                wav_bytes=up.read(),
                patient_name=patient_name,
                doctor_name=doctor_name,
                patient_id=patient_id,
                visit_type=visit_key,
            )

    with tab_paste:
        text = st.text_area("Transcript", height=200)
        if st.button("🧠 Run swarm", disabled=not text.strip()):
            _process(
                transcript=text,
                patient_name=patient_name,
                doctor_name=doctor_name,
                patient_id=patient_id,
                visit_type=visit_key,
            )

    with tab_demo:
        opts = {
            f"{d['patient_name']} — {d['transcript'].splitlines()[1][:50]}…": i
            for i, d in enumerate(DEMO_TRANSCRIPTS)
        }
        choice = st.selectbox("Demo", list(opts.keys()))
        if st.button("✨ Run demo"):
            sample = get_demo_transcript(opts[choice])
            _process(
                transcript=sample["transcript"],
                patient_name=sample["patient_name"],
                doctor_name=sample["doctor_name"],
                patient_id=f"DEMO-{sample['id']}",
                visit_type=sample.get("visit_type", visit_key),
            )

    if "last_state" in st.session_state:
        st.markdown("---")
        _render_result(st.session_state["last_state"])

elif page == "Templates":
    st.markdown("## SOAP Templates")
    st.caption("TSBDE 22 TAC §108.8 compliant blanks for Dallas, TX practices.")
    files = [
        ("Texas Master Blank", "texas_blank_soap_template.json",
         "All sections, Dallas defaults, TSBDE checklist."),
        ("Visit-Type Templates", "visit_type_templates.json",
         "6 constrained variants with CDT allow-lists."),
        ("JSON Schema", "soap_schema.json", "Strict LLM output contract."),
    ]
    cols = st.columns(3)
    for c, (title, fn, desc) in zip(cols, files):
        path = DATA / fn
        content = path.read_text() if path.exists() else "{}"
        with c:
            st.markdown(f"<div class='ds-card'><div class='ds-h'>{title}</div>{desc}</div>",
                        unsafe_allow_html=True)
            st.download_button(f"⬇️ {fn}", content, file_name=fn, mime="application/json")

elif page == "Tooth Chart Lab":
    st.markdown("## Tooth Chart Lab")
    a = st.multiselect("Treated (green)", list(range(1, 33)), default=[30])
    b = st.multiselect("Flagged (yellow)", list(range(1, 33)), default=[3, 14])
    render_tooth_chart(flagged=set(b), treated=set(a))

elif page == "Audit Trail":
    st.markdown("## Audit Trail")
    rows = store.list_audit(limit=100)
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No audit events yet. Run a consultation to populate.")

else:
    st.markdown("## About DentaScribe")
    st.markdown(
        """
**DentaScribe** is an AI dental scribe focused on **auditability and groundedness**.
Every SOAP field should trace to a transcript span. Built for US dental practices;
Dallas/TX defaults align with TSBDE 22 TAC §108.8.

Run the v1 UI with `streamlit run app.py` or this v2 UI with `streamlit run app_v2.py`.
"""
    )
