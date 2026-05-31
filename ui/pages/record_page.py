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


def render() -> None:
    inject_global_css()
    hero("Record an encounter",
         "Stream live from the mic, drop in a recording, or paste a transcript. "
         "The agent swarm drafts a Texas-compliant SOAP, the Reviewer gives a second opinion, "
         "and you sign off when you're ready.")

    src = st.radio("Input source", ["Paste transcript (demo)", "Upload audio file", "Live mic"],
                   horizontal=True)
    transcript_text = ""
    if src == "Paste transcript (demo)":
        transcript_text = st.text_area(
            "Paste Doctor:/Patient: dialogue",
            value=("Doctor: Let me take a look at tooth nineteen. The PA shows a dark spot near the pulp.\n"
                   "Patient: It's been throbbing for three days, especially at night.\n"
                   "Doctor: That's consistent with irreversible pulpitis. I'd recommend a root canal today, "
                   "then a crown in two weeks."),
            height=180,
        )
    elif src == "Upload audio file":
        st.file_uploader("Drop a .wav/.mp3 from the demo recordings", type=["wav", "mp3", "m4a"])
        st.caption("Wire to audio.deepgram_stt.transcribe_file() in app.py.")
    else:
        st.caption("Live mic: wire audio.deepgram_stt.stream_microphone() to streamlit-mic-recorder or webrtc.")

    run = st.button("▶  Run agent swarm", type="primary")
    result = st.session_state.get("ds_last_run")
    if run and transcript_text.strip():
        # Read the mode from the sidebar toggle. Defaults to Demo if absent.
        demo_mode = st.session_state.get("ds_mode", "Demo") == "Demo"
        spinner_msg = "Running 5 agents (demo fixtures)…" if demo_mode \
                      else "Running 5 agents on live Claude API…"
        with st.spinner(spinner_msg):
            result = _run_orchestrator(transcript_text, demo_mode=demo_mode)
            st.session_state["ds_last_run"] = result
            # Cache cost for the sidebar metric.
            if result.get("cost"):
                st.session_state["ds_last_cost"] = result["cost"]

    if not result:
        st.info("Paste a transcript above and click Run to see the swarm light up.")
        return
    if result.get("_error"):
        st.error(f"Pipeline error: {result['_error']}")
        return

    soap = result.get("soap") or {}
    validation = result.get("validation")
    review = result.get("review") or []
    audit = result.get("audit_records") or []

    st.markdown("### Agent swarm")
    render_swarm(audit)

    left, right = st.columns([1.2, 1])
    with left:
        card_open("Conversation")
        segs = soap.get("metadata", {}).get("transcript_segments") or _segments_from_text(transcript_text)
        render_transcript(segs)
        card_close()

        card_open("Tooth chart — referenced teeth")
        render_tooth_chart(highlighted=_extract_teeth(soap))
        card_close()

    with right:
        card_open("Second-Opinion (Agentic AI)")
        render_review(review)
        card_close()

        card_open("Validator")
        render_validator(validation)
        card_close()

        # Cost telemetry — visible per consultation. Demo mode = $0.
        cost = result.get("cost") or {}
        if cost:
            from core.cost import format_usd
            card_open("Cost & tokens")
            cols = st.columns(3)
            cols[0].metric("Total", format_usd(cost.get("total_usd", 0.0)))
            cols[1].metric("Input tok", f"{cost.get('total_tokens_in', 0):,}")
            cols[2].metric("Output tok", f"{cost.get('total_tokens_out', 0):,}")
            mode_caption = (f"Demo ({cost.get('demo_calls', 0)} fixture calls, $0)"
                            if cost.get("live_calls", 0) == 0
                            else f"Live ({cost.get('live_calls', 0)} Claude calls)")
            st.caption(mode_caption + f" · run {result.get('duration_ms', 0)} ms · case {result.get('case_id','?')}")
            with st.expander("Per-agent breakdown", expanded=False):
                rows = cost.get("by_agent", []) or []
                if rows:
                    import pandas as pd
                    df = pd.DataFrame(rows)
                    df["usd"] = df["usd"].map(format_usd)
                    st.dataframe(df[["agent", "model", "input_tokens", "output_tokens", "usd", "demo"]],
                                 use_container_width=True, hide_index=True)
            card_close()

    score = (validation or {}).get("signability_score") or 0
    has_errors = any((i.get("severity") == "error") for i in (validation or {}).get("issues", []))
    can_sign = score >= 85 and not has_errors
    lock_reason = None if can_sign else "Resolve all validator errors and reach signability >= 85."
    att = render_attestation_block(can_sign=can_sign, lock_reason=lock_reason)

    blank_template = _load_blank_template()
    card_open("Export")
    render_export_buttons(soap if soap else None, att, blank_template)
    card_close()

    if att:
        st.success(f"Signed by {att['provider_name']} at {att['signed_at']}")
