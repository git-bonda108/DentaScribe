"""DentaScribe — AI dental scribe (Streamlit MVP).

Run:  streamlit run app.py
"""
from __future__ import annotations
import json
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from core.config import load_config
from core.state import SwarmState
from core.db import ConsultationStore
from agents.orchestrator import Orchestrator
from ui.styles import inject_css
from ui.theme import COLORS
from ui.components import (
    hero, metric_card, card, badge,
    speaker_bubble, soap_block, cdt_chip,
)
from utils.fixtures import DEMO_TRANSCRIPTS, get_demo_transcript


# ---------- Page setup ----------
st.set_page_config(
    page_title="DentaScribe — AI Dental Scribe",
    page_icon="🦷",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(inject_css(), unsafe_allow_html=True)


# ---------- Boot once ----------
@st.cache_resource
def boot():
    cfg = load_config()
    return cfg, Orchestrator(cfg), ConsultationStore(cfg.db_path)


cfg, swarm, store = boot()


# ---------- Sidebar ----------
with st.sidebar:
    st.markdown(f"### 🦷 DentaScribe")
    st.markdown(
        f'<div style="color:#94A3B8;font-size:.85rem;margin-bottom:18px">'
        f'AI clinical scribe for dentistry</div>',
        unsafe_allow_html=True,
    )
    page = st.radio(
        "Navigation",
        ["Live Consultation", "Records", "About"],
        label_visibility="collapsed",
    )

    st.markdown("---")
    st.markdown("**System status**")
    llm_label = swarm.llm_provider.upper() if swarm.llm.available else "DEMO MODE"
    llm_color = "#0EA5A4" if swarm.llm.available else "#F59E0B"
    st.markdown(
        f'<div style="font-size:.85rem">LLM: '
        f'<span style="color:{llm_color};font-weight:600">{llm_label}</span></div>',
        unsafe_allow_html=True,
    )
    stt = (cfg.stt_provider.upper() + (" ✓" if cfg.has_stt else " (no key)"))
    st.markdown(f'<div style="font-size:.85rem">STT: <code>{stt}</code></div>',
                unsafe_allow_html=True)
    st.markdown(
        f'<div style="font-size:.85rem">Stored: <b>{store.count()}</b> consultations</div>',
        unsafe_allow_html=True,
    )

    st.markdown("---")
    st.caption("Made with ❤️ for clinicians. Notes must be reviewed before signing.")


# =====================================================================
# PAGE: Live Consultation
# =====================================================================
def render_live():
    has_llm = swarm.llm.available
    has_stt = cfg.has_stt
    badge_text = ("LIVE • " + swarm.llm_provider.upper()) if has_llm else "DEMO MODE"
    hero(
        "Live Consultation",
        "Record the doctor–patient conversation. The agent swarm transcribes, "
        "labels speakers, extracts dental entities, drafts a SOAP note, "
        "and suggests CDT 2026 codes — all reviewable before sign-off.",
        badge=badge_text,
    )

    # ---- Patient meta ----
    with st.container():
        c1, c2, c3 = st.columns([2, 2, 1])
        with c1:
            patient_name = st.text_input("Patient name", key="patient_name",
                                         placeholder="e.g. Riya Sharma")
        with c2:
            doctor_name = st.text_input("Provider", key="doctor_name",
                                        placeholder="e.g. Dr. Patel")
        with c3:
            patient_id = st.text_input("Patient ID", key="patient_id",
                                       placeholder="optional")

    # ---- Input mode ----
    st.markdown("#### How do you want to capture the consultation?")
    tab_live, tab_upload, tab_paste, tab_demo = st.tabs(
        ["🎙️ Live microphone", "📁 Upload audio", "📝 Paste transcript", "✨ Try a demo"]
    )

    # ----- Live mic -----
    with tab_live:
        st.markdown(
            '<div class="ds-card"><h4>Browser microphone</h4>'
            '<p style="margin:0;color:#475569;font-size:.9rem">Click to start, '
            'click again to stop. Works on Android Chrome, iOS Safari, and desktop '
            'browsers via the Web Media-API.</p></div>',
            unsafe_allow_html=True,
        )
        wav_bytes = None
        try:
            from streamlit_mic_recorder import mic_recorder
            rec = mic_recorder(
                start_prompt="🎙️ Start recording",
                stop_prompt="⏹️ Stop recording",
                use_container_width=True,
                format="wav",
                key="ds_mic",
            )
            if rec and rec.get("bytes"):
                wav_bytes = rec["bytes"]
                st.audio(wav_bytes, format="audio/wav")
                st.success(f"Captured {len(wav_bytes) / 1024:.1f} KB of audio.")
        except Exception as e:
            st.warning(
                "`streamlit-mic-recorder` is not available. Install with "
                "`pip install streamlit-mic-recorder` to enable browser mic capture. "
                f"Details: {e}"
            )

        if wav_bytes:
            if not has_stt:
                st.error(
                    "No STT provider configured. Set OPENAI_API_KEY or DEEPGRAM_API_KEY "
                    "in `.env`, or paste a transcript on the next tab."
                )
            else:
                if st.button("🧠 Transcribe & run swarm", key="run_live",
                             use_container_width=True):
                    _process(wav_bytes=wav_bytes,
                             patient_name=patient_name, doctor_name=doctor_name,
                             patient_id=patient_id)

    # ----- Upload -----
    with tab_upload:
        up = st.file_uploader(
            "Upload pre-recorded audio",
            type=["wav", "mp3", "m4a", "ogg", "webm", "flac"],
            help="Whisper accepts WAV/MP3/M4A/OGG/WebM/FLAC up to 25MB.",
        )
        if up is not None:
            wav_bytes = up.read()
            st.audio(wav_bytes)
            if not has_stt:
                st.error("No STT provider configured. Set OPENAI_API_KEY or "
                         "DEEPGRAM_API_KEY in `.env`.")
            elif st.button("🧠 Transcribe & run swarm", key="run_upload",
                           use_container_width=True):
                _process(wav_bytes=wav_bytes,
                         patient_name=patient_name, doctor_name=doctor_name,
                         patient_id=patient_id,
                         filename=up.name)

    # ----- Paste -----
    with tab_paste:
        st.caption("Useful for testing without audio, or for editing an "
                   "auto-transcribed pass before generating the note.")
        text = st.text_area(
            "Transcript (use `Doctor:` / `Patient:` prefixes if you have them)",
            height=240,
            placeholder=(
                "Doctor: Good morning, what brings you in today?\n"
                "Patient: I've had pain in my upper right back tooth for a week…"
            ),
        )
        if st.button("🧠 Run swarm on transcript", key="run_paste",
                     use_container_width=True, disabled=not text.strip()):
            _process(transcript=text,
                     patient_name=patient_name, doctor_name=doctor_name,
                     patient_id=patient_id)

    # ----- Demo -----
    with tab_demo:
        st.caption("Curated dental consultations grounded in real CDT 2026 "
                   "terminology — useful for showing the full flow without "
                   "any API keys.")
        opts = {f"{d['patient_name']} — "
                f"{d['transcript'].splitlines()[1][:60]}…": i
                for i, d in enumerate(DEMO_TRANSCRIPTS)}
        choice = st.selectbox("Pick a demo conversation", list(opts.keys()))
        idx = opts[choice]
        sample = get_demo_transcript(idx)
        with st.expander("Preview transcript", expanded=False):
            st.code(sample["transcript"], language="markdown")
        if st.button("✨ Run swarm on demo", key="run_demo",
                     use_container_width=True):
            _process(transcript=sample["transcript"],
                     patient_name=sample["patient_name"],
                     doctor_name=sample["doctor_name"],
                     patient_id="DEMO-" + sample["id"])

    # ---- Result panel ----
    if "last_state" in st.session_state:
        st.markdown("---")
        _render_result(st.session_state["last_state"])


# =====================================================================
# Helper: process an input through the swarm
# =====================================================================
def _process(*, wav_bytes: bytes | None = None,
             transcript: str | None = None,
             patient_name: str, doctor_name: str, patient_id: str,
             filename: str | None = None):
    state = SwarmState(
        patient_name=patient_name or "Walk-in",
        doctor_name=doctor_name or "Provider",
        patient_id=patient_id or "",
    )

    progress = st.progress(0, text="Initializing agent swarm…")
    steps = ["Transcription", "Diarization", "Dental NER",
             "SOAP note", "CDT 2026 coding", "Validation", "Persisting"]
    log_area = st.empty()

    def push(msg: str):
        log_area.markdown(
            f'<div style="background:{COLORS["primary_light"]};'
            f'padding:8px 14px;border-radius:8px;margin:4px 0;'
            f'font-family:ui-monospace,monospace;font-size:.85rem;'
            f'color:{COLORS["primary_dark"]}">▸ {msg}</div>',
            unsafe_allow_html=True,
        )

    # 1) get transcript
    try:
        if transcript is not None:
            state.raw_transcript = transcript
            push("Transcript ingested from text input")
            progress.progress(15, text="Transcript ready")
        else:
            push(f"Sending audio to {cfg.stt_provider.upper()} for transcription…")
            progress.progress(8, text="Transcribing audio…")
            state.raw_transcript = swarm.transcribe_audio(wav_bytes)
            push(f"Transcript ready ({len(state.raw_transcript)} chars)")
            progress.progress(20, text="Transcription complete")
    except Exception as e:
        st.error(f"Transcription failed: {e}")
        return

    # 2) run the pipeline
    pct = {"Diarization": 35, "Dental NER": 55,
           "SOAP note": 75, "CDT 2026 coding": 88,
           "Validation": 96}

    def on_step(msg: str):
        push(msg)
        for k, v in pct.items():
            if k.lower() in msg.lower():
                progress.progress(v, text=msg)
                break

    try:
        state = swarm.run(state, on_step=on_step)
    except Exception as e:
        st.error(f"Agent swarm failed: {e}")
        return

    # 3) persist
    try:
        store.upsert(state.to_dict())
        push("Saved to records.")
        progress.progress(100, text="Done")
    except Exception as e:
        st.warning(f"Saved in session only (DB write failed: {e})")

    st.session_state["last_state"] = state.to_dict()
    time.sleep(0.4)
    progress.empty()


# =====================================================================
# Render a finished SwarmState
# =====================================================================
def _render_result(state: dict):
    soap = state.get("soap", {})
    qa = state.get("qa", {})
    cdt = state.get("cdt_codes", []) or []

    # Top metrics
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        metric_card("Transcript length",
                    f"{len(state.get('raw_transcript', ''))} chars",
                    helper="Raw STT output")
    with c2:
        metric_card("Speaker turns",
                    len(state.get("segments", [])),
                    helper="Doctor + Patient bubbles")
    with c3:
        metric_card("Dental entities",
                    len(state.get("entities", [])),
                    helper="Teeth, conditions, procedures…")
    with c4:
        comp = qa.get("completeness_score", 0)
        metric_card("SOAP completeness",
                    f"{int(comp * 100)}%",
                    helper=f"{len(qa.get('warnings', []))} warnings")

    tabs = st.tabs(["📝 SOAP Note", "🦷 CDT Codes", "💬 Transcript",
                    "🔬 Entities", "🛡️ Quality", "🧠 Swarm Trace", "⬇️ Export"])

    # ---- SOAP ----
    with tabs[0]:
        if soap.get("chief_complaint"):
            st.markdown(soap_block("Chief Complaint", soap["chief_complaint"]),
                        unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(soap_block("Subjective", soap.get("subjective", "")),
                        unsafe_allow_html=True)
            st.markdown(soap_block("Assessment", soap.get("assessment", "")),
                        unsafe_allow_html=True)
        with col2:
            st.markdown(soap_block("Objective", soap.get("objective", "")),
                        unsafe_allow_html=True)
            st.markdown(soap_block("Plan", soap.get("plan", "")),
                        unsafe_allow_html=True)
        if soap.get("dental_exam"):
            st.markdown(soap_block("Dental Exam Findings",
                                   soap.get("dental_exam", "")),
                        unsafe_allow_html=True)
        meds = soap.get("medications") or []
        if meds:
            st.markdown("##### Medications")
            for m in meds:
                st.markdown(f"- {m}")
        if soap.get("follow_up"):
            st.markdown(soap_block("Follow-up", soap["follow_up"]),
                        unsafe_allow_html=True)
        if soap.get("notes_for_doctor"):
            st.markdown(
                f'<div class="ds-card" style="border-left:4px solid {COLORS["amber"]}">'
                f'<h4 style="color:{COLORS["amber"]}">Notes for Doctor</h4>'
                f'<p>{soap["notes_for_doctor"]}</p></div>',
                unsafe_allow_html=True,
            )

    # ---- CDT ----
    with tabs[1]:
        if not cdt:
            st.info("No CDT codes were inferred from this consultation.")
        else:
            st.markdown(
                "Codes are **suggestions** based on procedures mentioned in the "
                "transcript. Always verify against ADA CDT 2026 before billing."
            )
            chips_html = "".join(
                cdt_chip(c["code"], c["nomenclature"], c.get("confidence", 0.7))
                for c in cdt
            )
            st.markdown(f"<div>{chips_html}</div>", unsafe_allow_html=True)
            st.markdown("---")
            st.dataframe(
                pd.DataFrame(cdt)[["code", "nomenclature", "confidence", "rationale"]],
                use_container_width=True,
                hide_index=True,
            )

    # ---- Transcript ----
    with tabs[2]:
        segs = state.get("segments") or []
        if not segs:
            st.code(state.get("raw_transcript", ""), language="markdown")
        else:
            html = "".join(speaker_bubble(s["speaker"], s["text"]) for s in segs)
            st.markdown(html, unsafe_allow_html=True)

    # ---- Entities ----
    with tabs[3]:
        ents = state.get("entities") or []
        if not ents:
            st.info("No entities extracted.")
        else:
            df = pd.DataFrame(ents)
            for kind in df["kind"].unique():
                st.markdown(f"##### {kind.title()}")
                sub = df[df["kind"] == kind][["value", "span", "confidence"]]
                st.dataframe(sub, hide_index=True, use_container_width=True)

    # ---- Quality ----
    with tabs[4]:
        c1, c2 = st.columns(2)
        with c1:
            card("Completeness", f"""
                <div class="ds-metric-value">{int(qa.get('completeness_score', 0)*100)}%</div>
                <div class="ds-metric-label">SOAP sections populated</div>
            """)
        with c2:
            card("Warnings", f"""
                <div class="ds-metric-value">{len(qa.get('warnings', []))}</div>
                <div class="ds-metric-label">Issues flagged</div>
            """)
        warnings = qa.get("warnings", [])
        if warnings:
            st.markdown("##### Warnings")
            for w in warnings:
                st.markdown(
                    f'<div class="ds-card" style="border-left:4px solid {COLORS["amber"]}">'
                    f'⚠ {w}</div>',
                    unsafe_allow_html=True,
                )
        unconf = qa.get("unconfirmed_terms", [])
        if unconf:
            st.markdown("##### Unconfirmed terms (verify against transcript)")
            chips = " ".join(badge(t, "amber") for t in unconf)
            st.markdown(chips, unsafe_allow_html=True)
        if not warnings and not unconf:
            st.success("✓ No quality issues detected.")

    # ---- Trace ----
    with tabs[5]:
        trace = state.get("agent_trace") or []
        st.markdown(
            "Each agent in the swarm logs a line as it runs. Use this to "
            "audit which agent contributed what."
        )
        for entry in trace:
            level = entry.get("level", "info")
            color = (COLORS["red"] if level == "error"
                     else COLORS["amber"] if level == "warn"
                     else COLORS["primary"])
            st.markdown(
                f'<div style="display:flex;gap:10px;padding:6px 0;'
                f'border-bottom:1px solid {COLORS["border"]}">'
                f'<span style="color:{COLORS["muted"]};font-family:ui-monospace,monospace;'
                f'font-size:.78rem;width:160px">{entry["ts"][11:19]}</span>'
                f'<span style="color:{color};font-weight:600;width:130px">{entry["agent"]}</span>'
                f'<span>{entry["message"]}</span></div>',
                unsafe_allow_html=True,
            )

    # ---- Export ----
    with tabs[6]:
        from exporters.pdf_export import render_pdf
        from exporters.docx_export import render_docx
        c1, c2, c3 = st.columns(3)
        pdf_bytes = render_pdf(state)
        docx_bytes = render_docx(state)
        json_bytes = json.dumps(state, indent=2).encode()
        fname = f"DentaScribe_{state.get('patient_name','patient').replace(' ', '_')}_{state['created_at'][:10]}"
        with c1:
            st.download_button("⬇ Download PDF", pdf_bytes, file_name=f"{fname}.pdf",
                               mime="application/pdf", use_container_width=True)
        with c2:
            st.download_button("⬇ Download DOCX", docx_bytes, file_name=f"{fname}.docx",
                               mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                               use_container_width=True)
        with c3:
            st.download_button("⬇ Raw JSON", json_bytes, file_name=f"{fname}.json",
                               mime="application/json", use_container_width=True)


# =====================================================================
# PAGE: Records
# =====================================================================
def render_records():
    hero("Patient Records",
         "Search, filter and re-open past consultations.",
         badge=f"{store.count()} STORED")

    q = st.text_input("Search by patient, complaint, or provider", "")
    rows = store.list_all(q=q, limit=500)

    if not rows:
        st.info("No consultations stored yet. Run a Live Consultation to create one.")
        return

    df = pd.DataFrame([{
        "Date": r["created_at"][:19].replace("T", " "),
        "Patient": r["patient_name"],
        "Provider": r["doctor_name"],
        "Chief Complaint": (r["chief_complaint"] or "")[:80],
        "ID": r["id"],
    } for r in rows])

    st.dataframe(df.drop(columns=["ID"]), hide_index=True, use_container_width=True)

    chosen = st.selectbox(
        "Open a consultation",
        df["ID"].tolist(),
        format_func=lambda cid: next(
            f"{r['patient_name']} — {r['created_at'][:19].replace('T', ' ')}"
            for r in rows if r["id"] == cid
        ),
    )
    if chosen:
        state = store.get(chosen)
        if state:
            st.markdown("---")
            _render_result(state)
            colA, colB = st.columns([1, 1])
            with colA:
                if st.button("🗑️ Delete this consultation",
                             use_container_width=True):
                    store.delete(chosen)
                    st.success("Deleted. Refreshing…")
                    time.sleep(0.5)
                    st.rerun()


# =====================================================================
# PAGE: About
# =====================================================================
def render_about():
    hero("About DentaScribe",
         "An MVP AI scribe purpose-built for the dental industry.",
         badge="MVP")
    st.markdown("""
### Why this exists
Dentists spend a third of their day on documentation. **DentaScribe** listens
to the doctor–patient conversation, then runs it through a focused
**agent swarm** to produce a complete, sign-ready SOAP note with
suggested CDT 2026 procedure codes — in seconds.

### The agent swarm
1. **Transcription Agent** — Whisper (default) or Deepgram Nova-3 Medical (93% accuracy on medical vocabulary).
2. **Diarization Agent** — labels every line as *Doctor* or *Patient* using prefix parsing or an LLM attribution pass; upgrade path is pyannote 3.1.
3. **Dental NER Agent** — extracts teeth (Universal numbering 1–32), conditions, procedures, medications, anatomy, and symptoms. Dictionary first, then LLM enrichment that is *grounded* to the transcript.
4. **SOAP Note Agent** — produces Chief Complaint, Subjective, Objective, Assessment, Plan, Dental Exam Findings, Medications, Follow-up, and Notes-for-Doctor sections. Anti-hallucination prompt.
5. **CDT Coder Agent** — keyword-anchors to the **ADA CDT 2026** catalog (subset bundled), then LLM re-rank with rationale. Codes are constrained — no invented codes.
6. **Validator Agent** — anti-hallucination check (terms in note must be evidenced in transcript), completeness score, dose/frequency check on medications.

### Why not just one big LLM call?
A swarm gives us:
- **Auditability** — every agent logs to the trace.
- **Cheaper failure modes** — when the LLM is down, the dictionary pass still produces a usable note.
- **Composability** — swap any agent (e.g. plug pyannote in for diarization) without rewriting the rest.
- **Grounding** — the validator catches drift before the doctor signs.

### Mobile / cross-platform
The browser **Media-API** (used by `streamlit-mic-recorder`) means the same
URL works on Android Chrome, iOS Safari, and any laptop browser. No native
app required.

### Privacy / production
For real clinical use you'll want HIPAA-compliant STT (Deepgram Nova-3 Medical has a HIPAA BAA option), encrypted Postgres in place of SQLite, an authentication layer, and an audit log. The agent code is designed to be lifted into a backend service largely unchanged.
""")
    st.markdown("---")
    st.markdown(f"""
**Color palette**
{badge('#0EA5A4 primary teal', 'primary')} {badge('#6FE4D6 mint', 'mint')}
{badge('#0B2A4A navy', 'navy')} {badge('#F59E0B amber', 'amber')}
{badge('#DC2626 red', 'red')} {badge('#16A34A green', 'green')}
""", unsafe_allow_html=True)


# =====================================================================
# Router
# =====================================================================
if page == "Live Consultation":
    render_live()
elif page == "Records":
    render_records()
else:
    render_about()


st.markdown(
    '<div class="ds-footer">DentaScribe MVP · '
    'CDT codes © American Dental Association · '
    'For clinical review, not unattended use.</div>',
    unsafe_allow_html=True,
)
