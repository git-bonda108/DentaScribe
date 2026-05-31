"""Record / paste an encounter, run the swarm, render full report."""
from __future__ import annotations
import json
import streamlit as st

from ui.theme import inject_global_css, hero, card_open, card_close
from ui.components.transcript_panel import render_transcript
from ui.components.agent_swarm import render_swarm
from ui.components.tooth_chart import render_tooth_chart
from ui.components.review_panel import render_review
from ui.components.validator_panel import render_validator
from ui.components.attestation import render_attestation_block
from ui.components.export_buttons import render_export_buttons


def _detect_case_id(transcript_text: str) -> tuple[str, str]:
    """Heuristically pick the matching demo fixture so Demo mode stays
    grounded. Returns (case_id, visit_type).

    The architect's two locked fixtures are 'emergency_endo' (#19, RCT)
    and 'recall_hygiene' (#30, MO composite). Anything else → emergency_endo
    fixture as a sensible default.
    """
    low = transcript_text.lower()
    recall_hits = sum(s in low for s in ("recall", "cleaning", "hygiene",
                                          "six-month", "six month", "bitewing",
                                          "tooth thirty", "#30", "tooth 30"))
    if recall_hits >= 2:
        return "recall_hygiene", "recall"
    return "emergency_endo", "emergency"


def _build_metadata() -> dict:
    """Default metadata for the demo flow. Real provider/patient identity
    would come from the auth layer (TODO P3 hardening).
    """
    return {
        "date_of_service": "2026-05-31",
        "provider": {
            "name": "Dr. A. Patel",
            "tsbde_license": "TX-12345",
            "npi": "1234567890",
            "role": "dentist",
        },
        "patient": {
            "patient_id": "P-0001",
            "dob": "1985-04-12",
            "consent_on_file": True,
            "is_minor": False,
        },
        "practice_location": {"city": "Dallas", "state": "TX"},
    }


def _adapt_review_for_ui(soap: dict | None, swarm_run) -> list[dict]:
    """Bridge the SecondOpinionAgent's output shape ({flags:[…]}) to
    review_panel's expected item shape ({category, severity, message,
    suggestion, evidence_quote, tooth_ref}).
    """
    # SecondOpinion is the LAST AgentResult in the swarm; its .output holds
    # the {flags: [...], overall_assessment, blocks_sign_off} dict.
    second = None
    for r in reversed(swarm_run.results):
        if getattr(r, "agent", "").lower() in ("second_opinion", "secondopinion", "reviewer"):
            second = r.output or {}
            break
    if not second and swarm_run.results:
        # Fallback: last result with a flags key
        last = swarm_run.results[-1].output or {}
        if "flags" in last:
            second = last
    sev_map = {"high": "high", "medium": "med", "med": "med", "low": "low"}
    flags = (second or {}).get("flags", []) or []
    out: list[dict] = []
    for f in flags:
        out.append({
            "category": f.get("category", "note"),
            "severity": sev_map.get((f.get("severity") or "low").lower(), "low"),
            "message":  f.get("summary") or f.get("detail") or "",
            "suggestion": f.get("suggested_action") or f.get("detail"),
            "evidence_quote": f.get("evidence_quote"),
            "tooth_ref": f.get("tooth_ref"),
        })
    return out


def _run_orchestrator(transcript_text: str, demo_mode: bool) -> dict:
    """Run the Batch-4 agent swarm against a transcript.

    `demo_mode=True`  → LLMClient(demo=True), uses locked fixtures, $0 cost.
    `demo_mode=False` → real Claude API. Cost is tracked per call.

    Returns a flat dict the UI consumes:
        {soap, validation, review, audit_records, cost, audio_quality}
    """
    try:
        from core.llm_client import LLMClient
        from agents.swarm import Orchestrator
        from core.cost import cost_breakdown
    except Exception as e:
        return {"_error": f"Import failed: {e}", "soap": None,
                "validation": None, "review": [], "audit_records": [],
                "cost": {"total_usd": 0.0, "by_agent": [], "live_calls": 0, "demo_calls": 0}}

    case_id, visit_type = _detect_case_id(transcript_text)
    try:
        llm = LLMClient(demo=demo_mode)
        orch = Orchestrator(llm=llm)
        swarm_run = orch.run(
            transcript=transcript_text,
            visit_type=visit_type,
            metadata=_build_metadata(),
            case_id=case_id,
        )
    except Exception as e:
        return {"_error": f"Pipeline error: {e}", "soap": None,
                "validation": None, "review": [], "audit_records": [],
                "cost": {"total_usd": 0.0, "by_agent": [], "live_calls": 0, "demo_calls": 0}}

    audit = swarm_run.audit_records()
    return {
        "soap": swarm_run.soap,
        "validation": swarm_run.validation,
        "review": _adapt_review_for_ui(swarm_run.soap, swarm_run),
        "audit_records": audit,
        "cost": cost_breakdown(audit),
        "case_id": case_id,
        "visit_type": visit_type,
        "duration_ms": swarm_run.duration_ms,
    }


def _extract_teeth(soap):
    if not soap:
        return set()
    teeth = set()
    for path in ["objective.findings", "assessment.diagnoses", "plan.procedures"]:
        cur = soap
        for k in path.split("."):
            cur = (cur or {}).get(k) if isinstance(cur, dict) else None
        if isinstance(cur, list):
            for item in cur:
                t = (item or {}).get("tooth") if isinstance(item, dict) else None
                if isinstance(t, int) and 1 <= t <= 32:
                    teeth.add(t)
    return teeth


def _segments_from_text(text: str):
    from audio.transcript_types import Transcript
    return [s.to_dict() for s in Transcript.from_plain_text(text).segments]


def _load_blank_template():
    try:
        with open("texas_blank_soap_template.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


SAMPLE_TRANSCRIPT = (
    "Doctor: Hi. What brings you in today?\n"
    "Patient: I have severe pain on my lower left back tooth — tooth number nineteen.\n"
    "Doctor: How long?\n"
    "Patient: Three days. It throbs at night, can't sleep on that side.\n"
    "Doctor: Let me take a periapical X-ray. The PA shows a dark spot near the apex.\n"
    "Doctor: That's consistent with irreversible pulpitis. I'd recommend starting a "
    "root canal today and following up with a crown in two weeks.\n"
    "Patient: I'm on lisinopril for blood pressure. Is that okay?\n"
    "Doctor: Noted. For pain, take ibuprofen 400 mg every six hours as needed."
)


# ============================================================
# KPI strip — top-of-page metric cards
# ============================================================

def _render_kpi_strip(result: dict | None, demo_mode: bool) -> None:
    """4-card row showing the most important numbers at a glance."""
    validation = (result or {}).get("validation") or {}
    cost = (result or {}).get("cost") or {}
    soap = (result or {}).get("soap") or {}
    from core.cost import format_usd

    score = validation.get("signability_score")
    counts = validation.get("counts") or {}
    n_errors = counts.get("errors", 0)
    n_warns  = counts.get("warnings", 0)
    cdt_count = len((soap.get("billing") or {}).get("cdt_codes") or [])
    total_cost = cost.get("total_usd", 0.0)

    c1, c2, c3, c4, c5 = st.columns(5)
    score_delta = None
    if score is not None:
        if score >= 85:  score_delta = "↑ sign-ready"
        elif score >= 70: score_delta = "↑ near sign-ready"
        else:            score_delta = "⚠ needs review"
    c1.metric("Signability", f"{score}" if score is not None else "—", score_delta)
    c2.metric("Errors", n_errors, f"{n_warns} warnings")
    c3.metric("CDT codes", cdt_count)
    c4.metric("Cost", format_usd(total_cost), f"{cost.get('total_tokens_in',0)+cost.get('total_tokens_out',0):,} tok")
    c5.metric("Mode", "Demo" if demo_mode else "Live (Claude)",
              f"run {(result or {}).get('duration_ms', 0)/1000:.1f}s" if result else "—")


# ============================================================
# Conversation panel — st.chat_message bubbles
# ============================================================

def _render_chat_conversation(transcript_text: str, soap: dict | None) -> None:
    """Pretty per-speaker bubbles. Uses st.chat_message which handles the
    avatar+styling natively — far cleaner than the raw markdown bubbles.
    """
    if not transcript_text or not transcript_text.strip():
        st.info("No conversation captured yet.")
        return

    # Parse plain "Speaker: text" lines into segments
    from audio.transcript_types import Transcript
    segs = Transcript.from_plain_text(transcript_text).segments
    if not segs:
        st.info("No conversation captured yet.")
        return

    # Show the audio quality report if we have one (from the STT path)
    aq = st.session_state.get("ds_audio_quality")
    if aq:
        with st.expander("🎙️ Audio quality", expanded=False):
            qa = aq.get("after") or aq.get("before") or {}
            cols = st.columns(4)
            cols[0].metric("Quality", (qa.get("label") or "—").upper())
            cols[1].metric("RMS", f"{qa.get('rms_dbfs', 0):.1f} dBFS")
            cols[2].metric("Peak", f"{qa.get('peak_dbfs', 0):.1f} dBFS")
            cols[3].metric("Duration", f"{qa.get('duration_sec', 0):.1f}s")
            for w in qa.get("warnings", []) or []:
                st.warning(w)
            if aq.get("stages"):
                st.caption("Stages applied: " + ", ".join(aq["stages"]))

    # Show correction audit if any
    corrections = st.session_state.get("ds_corrections") or []
    if corrections:
        with st.expander(f"✍️ Post-STT corrections ({len(corrections)})", expanded=False):
            for c in corrections[:20]:
                st.markdown(f"`{c.get('from')}` → **{c.get('to')}**  "
                            f"<span style='color:#9AA6B8;font-size:11px'>{c.get('kind')}</span>",
                            unsafe_allow_html=True)

    # Bubbles
    for seg in segs:
        who = (seg.speaker or "unknown").lower()
        if who in ("doctor", "provider", "dr"):
            avatar = "👨‍⚕️"; role = "assistant"
        elif who in ("patient", "pt"):
            avatar = "🧑"; role = "user"
        else:
            avatar = "💬"; role = "assistant"
        with st.chat_message(role, avatar=avatar):
            label = (seg.speaker or "Unknown").title()
            st.markdown(f"**{label}**")
            st.write(seg.text)


# ============================================================
# SOAP rendering — proper structured view
# ============================================================

def _render_soap_view(soap: dict | None) -> None:
    if not soap:
        st.info("Run the swarm to populate the SOAP note.")
        return

    tab_s, tab_o, tab_a, tab_p, tab_b, tab_c = st.tabs(
        ["Subjective", "Objective", "Assessment", "Plan", "Billing", "Compliance"]
    )
    with tab_s:
        s = soap.get("subjective") or {}
        if s.get("chief_complaint"):
            st.markdown(f"**Chief complaint** — {s['chief_complaint']}")
        if s.get("history_of_present_illness"):
            st.markdown(f"**HPI** — {s['history_of_present_illness']}")
        meds = s.get("medications") or []
        if meds:
            st.markdown("**Medications:** " + ", ".join(str(m) for m in meds))
        allergies = s.get("allergies") or []
        if allergies:
            st.warning("**Allergies:** " + ", ".join(str(a) for a in allergies))
        if s.get("medical_history_updates"):
            mhu = s["medical_history_updates"]
            st.markdown(f"**Medical history updates** — {mhu if isinstance(mhu, str) else ', '.join(mhu)}")
        if not (s.get("chief_complaint") or s.get("history_of_present_illness") or meds or allergies):
            st.caption("No subjective content captured.")

    with tab_o:
        o = soap.get("objective") or {}
        if o.get("vitals"):
            st.markdown("**Vitals** — " + ", ".join(f"{k}: {v}" for k,v in o["vitals"].items()))
        if o.get("intra_oral"):
            st.markdown(f"**Intraoral** — {o['intra_oral']}")
        if o.get("extra_oral"):
            st.markdown(f"**Extraoral** — {o['extra_oral']}")
        rads = o.get("radiographs_taken") or []
        if rads:
            st.markdown("**Radiographs**")
            for r in rads:
                if isinstance(r, dict):
                    parts = [r.get("type",""), f"tooth #{r['tooth']}" if r.get("tooth") else None, r.get("findings","")]
                    st.markdown("• " + " — ".join(p for p in parts if p))
                else:
                    st.markdown(f"• {r}")
        findings = o.get("exam_findings") or []
        if findings:
            st.markdown("**Exam findings**")
            for f in findings:
                if isinstance(f, dict):
                    line = f"tooth #{f.get('tooth','?')}"
                    if f.get('surfaces'): line += f" ({','.join(f['surfaces'])})"
                    line += f" — {f.get('finding','')}"
                    if f.get("severity"): line += f"  *[{f['severity']}]*"
                    st.markdown(f"• {line}")

    with tab_a:
        a = soap.get("assessment") or {}
        for dx in (a.get("diagnoses") or []):
            if isinstance(dx, dict):
                tooth_str = f" (tooth #{dx['tooth']})" if dx.get("tooth") else ""
                st.markdown(f"• **{dx.get('diagnosis','—')}**{tooth_str}")
                if dx.get("severity"): st.caption(f"Severity: {dx['severity']}")
            else:
                st.markdown(f"• {dx}")

    with tab_p:
        p = soap.get("plan") or {}
        if p.get("procedures_today"):
            st.markdown("**Procedures today**")
            for proc in p["procedures_today"]:
                if isinstance(proc, dict):
                    tooth = f"tooth #{proc['tooth']}" if proc.get("tooth") else ""
                    surfaces = f" ({','.join(proc['surfaces'])})" if proc.get("surfaces") else ""
                    st.markdown(f"• **{proc.get('procedure','—')}** — {tooth}{surfaces}")
        if p.get("prescriptions"):
            st.markdown("**Prescriptions**")
            for rx in p["prescriptions"]:
                if isinstance(rx, dict):
                    st.markdown(f"• **{rx.get('drug','—')}** {rx.get('strength','')} — {rx.get('sig','')}")
        if p.get("follow_up"):
            st.markdown(f"**Follow-up** — {p['follow_up']}")
        if p.get("patient_instructions"):
            st.info(p['patient_instructions'])

    with tab_b:
        codes = (soap.get("billing") or {}).get("cdt_codes") or []
        if not codes:
            st.caption("No CDT codes assigned.")
        else:
            rows = []
            for c in codes:
                rows.append({
                    "Code": c.get("code") or "—",
                    "Description": c.get("description") or "—",
                    "Tooth": c.get("tooth") or "",
                    "Surfaces": ",".join(c.get("surfaces") or []),
                    "Rationale": c.get("rationale") or c.get("code_null_reason") or "—",
                })
            st.dataframe(rows, use_container_width=True, hide_index=True)

    with tab_c:
        checklist = (soap.get("compliance") or {}).get("tsbde_checklist") or {}
        if not checklist:
            st.caption("No compliance data.")
        else:
            ok = sum(1 for v in checklist.values() if v is True)
            total = len(checklist)
            st.progress(ok/total if total else 0, text=f"TSBDE 22 TAC §108.8 — {ok}/{total} boxes")
            cols = st.columns(2)
            i = 0
            for key, val in checklist.items():
                target = cols[i % 2]
                mark = "✅" if val is True else ("⚠️" if val is None else "❌")
                target.markdown(f"{mark} {key.replace('_', ' ').title()}")
                i += 1


# ============================================================
# Audit + cost tab
# ============================================================

def _render_audit_view(result: dict) -> None:
    cost = result.get("cost") or {}
    audit = result.get("audit_records") or []
    from core.cost import format_usd

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total cost", format_usd(cost.get("total_usd", 0.0)))
    c2.metric("Input tokens", f"{cost.get('total_tokens_in', 0):,}")
    c3.metric("Output tokens", f"{cost.get('total_tokens_out', 0):,}")
    c4.metric("API calls", f"{cost.get('live_calls', 0)} live · {cost.get('demo_calls', 0)} demo")

    st.markdown("##### Per-agent breakdown")
    rows = cost.get("by_agent") or []
    if rows:
        import pandas as pd
        df = pd.DataFrame(rows)
        df["usd"] = df["usd"].map(format_usd)
        st.dataframe(df[["agent", "model", "input_tokens", "output_tokens", "usd", "demo"]],
                     use_container_width=True, hide_index=True)

    if audit:
        st.markdown("##### Agent trace")
        for r in audit:
            status = (r.get("status") or "idle").lower()
            icon = {"ok":"✅", "error":"❌", "warn":"⚠️"}.get(status, "•")
            cols = st.columns([1, 2, 4])
            cols[0].markdown(f"{icon} **{r.get('agent','?')}**")
            cols[1].caption(f"{r.get('duration_ms', 0)} ms · {r.get('model','—').split('-')[-1] if r.get('model') else 'demo'}")
            cols[2].caption(r.get("status_message", "") or "—")


# ============================================================
# Live agent swarm with st.status
# ============================================================

def _render_live_swarm_status(audit: list[dict]) -> None:
    """Per-agent status pills using st.status for the executed run.
    During execution we'd swap to a true streaming version (P3 task).
    For now this gives an at-a-glance scoreboard with timings.
    """
    if not audit:
        return
    cols = st.columns(len(audit))
    for col, r in zip(cols, audit):
        status = (r.get("status") or "idle").lower()
        agent = (r.get("agent") or "?").replace("_", " ").title()
        toks = (r.get("input_tokens") or 0) + (r.get("output_tokens") or 0)
        dur = r.get("duration_ms", 0)
        icon = {"ok":"✅", "error":"❌", "warn":"⚠️", "demo":"🎯"}.get(status, "•")
        col.markdown(
            f"<div style='border:1px solid #1F2A44;border-radius:10px;padding:10px;"
            f"background:#121A2B;text-align:center;'>"
            f"<div style='font-size:18px;'>{icon}</div>"
            f"<div style='font-size:12px;font-weight:600;color:#E5E9F2;margin-top:2px;'>{agent}</div>"
            f"<div style='font-size:10px;color:#9AA6B8;margin-top:2px;'>{dur} ms · {toks} tok</div>"
            f"</div>",
            unsafe_allow_html=True,
        )


# ============================================================
# Main render()
# ============================================================

def render() -> None:
    inject_global_css()
    hero("Record an encounter",
         "Paste a transcript, drop in audio, or synthesize a sample. The agent "
         "swarm drafts a Texas-compliant SOAP, the Reviewer gives a second opinion, "
         "and you sign off when you're ready.")

    result = st.session_state.get("ds_last_run")
    demo_mode = st.session_state.get("ds_mode", "Demo") == "Demo"

    # ---- KPI strip (always visible — placeholders before first run) ----
    _render_kpi_strip(result, demo_mode)

    # ---- Input section ----
    with st.container(border=True):
        st.markdown("##### 🎙️  Capture transcript")
        tab_paste, tab_upload, tab_mic, tab_tts = st.tabs(
            ["📝  Paste", "📁  Upload audio", "🎤  Live mic", "🔊  Synthesize sample"]
        )
        transcript_text = ""
        with tab_paste:
            transcript_text = st.text_area(
                "Doctor / Patient dialogue", value=SAMPLE_TRANSCRIPT,
                height=180, label_visibility="collapsed",
            )
        with tab_upload:
            up = st.file_uploader("Drop .wav/.mp3/.m4a", type=["wav", "mp3", "m4a"],
                                  label_visibility="collapsed")
            if up is not None:
                transcript_text = _transcribe_uploaded_audio(up)
        with tab_mic:
            st.caption("Live mic streaming — coming in P3 (Deepgram WebSocket + "
                       "`streamlit-mic-recorder`).")
        with tab_tts:
            transcript_text = _render_tts_synthesis_tab() or transcript_text

        c_run, c_clear, _ = st.columns([1, 1, 4])
        run = c_run.button("▶  Run agent swarm", type="primary", use_container_width=True)
        clear = c_clear.button("Clear", use_container_width=True)
        if clear:
            for k in ("ds_last_run", "ds_last_cost", "ds_audio_quality", "ds_corrections"):
                st.session_state.pop(k, None)
            st.rerun()

    # ---- Execute the run ----
    if run and transcript_text.strip():
        with st.status(
            "Demo mode — booting agent swarm…" if demo_mode
            else "Live (Claude) mode — booting agent swarm…",
            expanded=True,
        ) as status:
            status.write("📋  Scribe writing SOAP note…")
            status.write("✅  Compliance running TSBDE checklist…")
            status.write("💼  Coder selecting CDT codes (allow-list constrained)…")
            status.write("🔍  Validator: structural + grounding + CDT + Texas…")
            status.write("🩺  Second-Opinion reviewing for safety + billing gaps…")
            result = _run_orchestrator(transcript_text, demo_mode=demo_mode)
            st.session_state["ds_last_run"] = result
            if result.get("cost"):
                st.session_state["ds_last_cost"] = result["cost"]
            ok = not result.get("_error") and (result.get("validation") or {}).get("counts", {}).get("errors", 0) == 0
            status.update(
                label=("✅ Swarm complete — sign-ready" if ok
                       else "⚠️ Swarm complete — needs review"),
                state="complete" if ok else "error",
                expanded=False,
            )
        st.toast("Agent swarm complete!", icon="🎉")
        st.rerun()  # refresh KPI strip with new numbers

    if not result:
        st.info("👆  Paste a transcript or pick **Synthesize sample**, then click **Run agent swarm**.")
        return
    if result.get("_error"):
        st.error(f"Pipeline error: {result['_error']}")
        return

    soap = result.get("soap") or {}
    validation = result.get("validation")
    review = result.get("review") or []
    audit = result.get("audit_records") or []

    # ---- Agent swarm scoreboard ----
    st.markdown("##### Agent swarm")
    _render_live_swarm_status(audit)

    # ---- Main result tabs ----
    tabs = st.tabs([
        "💬  Conversation", "📋  SOAP note", "🩺  Recommendations",
        "🔍  Second-Opinion", "🦷  Tooth chart", "📊  Audit & Cost",
    ])
    with tabs[0]:
        _render_chat_conversation(transcript_text or _sample_transcript_from_soap(soap), soap)
    with tabs[1]:
        _render_soap_view(soap)
    with tabs[2]:
        from ui.components.recommendations import render_recommendations
        render_recommendations(soap, review)
    with tabs[3]:
        render_review(review)
        if validation:
            st.divider()
            render_validator(validation)
    with tabs[4]:
        render_tooth_chart(highlighted=_extract_teeth(soap))
    with tabs[5]:
        _render_audit_view(result)

    # ---- Attestation + export ----
    st.divider()
    score = (validation or {}).get("signability_score") or 0
    has_errors = any((i.get("severity") == "error") for i in (validation or {}).get("issues", []))
    can_sign = score >= 85 and not has_errors
    lock_reason = None if can_sign else "Resolve all validator errors and reach signability ≥ 85."
    att = render_attestation_block(can_sign=can_sign, lock_reason=lock_reason)

    blank_template = _load_blank_template()
    with st.container(border=True):
        st.markdown("##### 📤  Export")
        render_export_buttons(soap if soap else None, att, blank_template)

    if att:
        st.success(f"Signed by {att['provider_name']} at {att['signed_at']}")


# ============================================================
# Helpers used by the new render()
# ============================================================

def _sample_transcript_from_soap(soap: dict | None) -> str:
    """If session lost the transcript_text variable, reconstruct from SOAP."""
    if not soap:
        return ""
    meta = soap.get("metadata") or {}
    segs = meta.get("transcript_segments") or []
    if segs:
        return "\n".join(f"{s.get('speaker','?').title()}: {s.get('text','')}" for s in segs)
    return ""


def _transcribe_uploaded_audio(uploaded_file) -> str:
    """Run an uploaded audio file through the full STT stack (preprocess →
    Deepgram → phonetic correction). Stashes audio quality + corrections in
    session state so the Conversation tab can surface them.
    """
    import tempfile, os
    suffix = "." + (uploaded_file.name.rsplit(".", 1)[-1] if "." in uploaded_file.name else "wav")
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        f.write(uploaded_file.read())
        path = f.name
    try:
        from audio.deepgram_stt import transcribe_file, is_available
        if not is_available():
            st.warning("DEEPGRAM_API_KEY not set — falling back to demo passthrough.")
            return ""
        transcript = transcribe_file(path)
        if getattr(transcript, "audio_quality", None):
            st.session_state["ds_audio_quality"] = transcript.audio_quality
        if getattr(transcript, "corrections", None):
            st.session_state["ds_corrections"] = transcript.corrections
        return "\n".join(f"{s.speaker.title()}: {s.text}" for s in transcript.segments)
    finally:
        try: os.unlink(path)
        except Exception: pass


def _render_tts_synthesis_tab() -> str:
    """Synthesize a doctor/patient conversation via ElevenLabs (or OpenAI TTS
    fallback), play it back, optionally run it through the STT pipeline.
    Returns the transcript text used for synthesis so the caller can hand it
    to the swarm without a STT roundtrip (cleaner demo).
    """
    st.caption(
        "Generate a realistic doctor/patient audio clip and pipe it through the "
        "full STT → swarm pipeline. ElevenLabs preferred (two-voice). "
        "Falls back to OpenAI TTS if no ElevenLabs key is set."
    )
    script = st.text_area(
        "Script to synthesize", value=SAMPLE_TRANSCRIPT, height=160,
        key="ds_tts_script",
    )
    cols = st.columns([1, 1, 2])
    do_synth = cols[0].button("🔊  Synthesize", key="ds_tts_synth_btn")
    do_pipeline = cols[1].checkbox("Run STT roundtrip", value=False,
                                    help="Synthesize → STT → use STT output as transcript")

    if do_synth:
        with st.spinner("Synthesizing audio…"):
            try:
                from audio.tts_synthesis import synthesize_dialogue
                wav_bytes, provider = synthesize_dialogue(script)
                st.session_state["ds_tts_wav"] = wav_bytes
                st.session_state["ds_tts_provider"] = provider
                st.toast(f"Synthesized via {provider}", icon="🔊")
            except Exception as e:
                st.error(f"TTS failed: {e}")

    wav_bytes = st.session_state.get("ds_tts_wav")
    if wav_bytes:
        st.audio(wav_bytes, format="audio/wav")
        st.caption(f"~{len(wav_bytes)/(24000*2):.1f}s · {len(wav_bytes):,} bytes · via {st.session_state.get('ds_tts_provider','—')}")
        if do_pipeline:
            with st.spinner("Running STT roundtrip (preprocess → Deepgram → correction)…"):
                try:
                    import tempfile, os
                    from audio.deepgram_stt import transcribe_file, is_available
                    if not is_available():
                        st.warning("DEEPGRAM_API_KEY missing — using script text instead.")
                        return script
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                        f.write(wav_bytes); path = f.name
                    try:
                        t = transcribe_file(path)
                        if getattr(t, "audio_quality", None):
                            st.session_state["ds_audio_quality"] = t.audio_quality
                        if getattr(t, "corrections", None):
                            st.session_state["ds_corrections"] = t.corrections
                        return "\n".join(f"{s.speaker.title()}: {s.text}" for s in t.segments) or script
                    finally:
                        try: os.unlink(path)
                        except Exception: pass
                except Exception as e:
                    st.error(f"STT roundtrip failed: {e}")
                    return script
    return script
