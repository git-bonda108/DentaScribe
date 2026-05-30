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


def _run_orchestrator(transcript_text: str) -> dict:
    """Calls Batch-4 orchestrator. Returns demo stub if not wired."""
    try:
        from agents.orchestrator import run_pipeline
        return run_pipeline(transcript_text)
    except Exception as e:
        return {"_error": str(e), "soap": None, "validation": None,
                "review": [], "audit_records": []}


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
        with st.spinner("Running 7 agents…"):
            result = _run_orchestrator(transcript_text)
            st.session_state["ds_last_run"] = result

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
