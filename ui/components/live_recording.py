"""Live recording component — WebRTC mic + Coach-on-the-left, Transcript-on-the-right.

Reads frames via `streamlit-webrtc`, accumulates them in a session-scoped
`LiveAudioBuffer`, drains 2-sec chunks through Deepgram, and triggers the
`DentalCoach` agent on speaker-turn change OR after a 15-second silence
ceiling — debounced to keep Claude cost predictable.

The UI is the two-pane view the user explicitly asked for:

    ┌──────────────────────┬──────────────────────┐
    │  🩺  LIVE COACHING   │  💬  LIVE TRANSCRIPT │
    │  (left, real-time)   │  (right, rolling)    │
    └──────────────────────┴──────────────────────┘

This is rendered as a Streamlit fragment so it auto-refreshes ~every second
without re-running the entire record page.
"""
from __future__ import annotations
import time
from typing import Optional

import streamlit as st


# Trigger cadence (per user spec): turn change OR 15s ceiling
TURN_CHANGE_DEBOUNCE_S = 2.0   # min seconds between coach calls when triggered by turn change
TURN_TIMEOUT_CEILING_S = 15.0  # force-fire after this even without turn change


def render_live_recording(coach_enabled: bool = True, demo_mode: bool = True) -> None:
    """Top-level entry point for the Live mic tab. Renders the WebRTC widget
    and the two-pane Coach + Transcript layout. State persists in
    `st.session_state` so tab switches don't kill the recording.
    """
    # Late import — streamlit_webrtc is optional at install time
    try:
        from streamlit_webrtc import (
            webrtc_streamer, WebRtcMode, RTCConfiguration,
        )
        from audio.live_streaming import LiveAudioBuffer, make_audio_processor
    except ImportError as e:
        st.error(f"Live recording requires `streamlit-webrtc`. Install with: "
                  f"`pip install streamlit-webrtc`. Error: {e}")
        return

    # --- Session state ----------------------------------------------------
    if "live_buffer" not in st.session_state:
        st.session_state["live_buffer"] = LiveAudioBuffer(window_secs=2.0)
    if "live_recommendations" not in st.session_state:
        st.session_state["live_recommendations"] = []
    if "live_coach_last_fired" not in st.session_state:
        st.session_state["live_coach_last_fired"] = 0.0
    if "live_last_speaker" not in st.session_state:
        st.session_state["live_last_speaker"] = None

    buffer = st.session_state["live_buffer"]

    # --- Controls + status pill -------------------------------------------
    cols = st.columns([3, 1, 1])
    cols[0].caption(
        "🎙️ Click **Start** to begin recording. Audio streams over WebRTC, "
        "every 2 sec gets transcribed by Deepgram, and the **Coach** on the "
        "left calls out anything the doctor might miss — drug interactions, "
        "history gaps, diagnostic tests to consider, billing codes accumulating."
    )
    if cols[1].button("🔄  Clear", use_container_width=True):
        buffer.reset()
        st.session_state["live_recommendations"] = []
        st.session_state["live_coach_last_fired"] = 0.0
        st.session_state["live_last_speaker"] = None
        st.rerun()
    if cols[2].button("📋  Use as transcript", use_container_width=True,
                       help="Hand the rolling transcript to the agent swarm for the full SOAP run.",
                       disabled=not buffer.segments):
        st.session_state["live_handed_off_text"] = buffer.total_transcript_text
        st.toast("Transcript handed to the swarm. Switch to Paste tab and click Run.")

    # --- WebRTC widget ----------------------------------------------------
    # Free Google STUN — for production deployment a TURN server is needed
    # behind a corporate NAT. Document that as a P5 ops task.
    rtc_config = RTCConfiguration({"iceServers": [
        {"urls": ["stun:stun.l.google.com:19302"]}
    ]})

    ctx = webrtc_streamer(
        key="ds_live_mic",
        mode=WebRtcMode.SENDONLY,
        rtc_configuration=rtc_config,
        media_stream_constraints={"audio": True, "video": False},
        audio_processor_factory=make_audio_processor(buffer),
        async_processing=True,
    )

    # --- Drain + maybe-fire-coach (only while playing) --------------------
    # This block runs each Streamlit rerun. We drain ALL ready chunks (could
    # be 0 or several), then evaluate the coach trigger.
    new_segments = []
    if ctx and ctx.state.playing:
        # Drain all whole windows available right now
        while buffer.has_enough_audio():
            chunk_new = buffer.drain_chunks()
            new_segments.extend(chunk_new)
            if not chunk_new:
                break

    # Trigger coach
    if coach_enabled and buffer.segments:
        _maybe_fire_coach(buffer, demo_mode=demo_mode, new_segments=new_segments)

    # --- Two-pane layout --------------------------------------------------
    st.markdown("&nbsp;", unsafe_allow_html=True)
    left, right = st.columns([1, 1])

    with left:
        _render_coach_pane(coach_enabled)
    with right:
        _render_live_transcript_pane(buffer)

    # --- Footer (auto-refresh hint) ---------------------------------------
    if ctx and ctx.state.playing:
        st.caption(
            f"● Recording  ·  {len(buffer.segments)} segments  ·  "
            f"{buffer.chunk_count} chunks  ·  buffer "
            f"{buffer.total_seconds_buffered:.1f}s ahead"
        )
        # Lightweight self-rerun every ~1s to pull new audio in
        time.sleep(1.0)
        st.rerun()


# ===========================================================================
# Coach trigger logic — turn change OR 15s ceiling
# ===========================================================================

def _maybe_fire_coach(buffer, *, demo_mode: bool, new_segments: list) -> None:
    """Decide whether to invoke the coach this rerun, and if so, do it."""
    now = time.time()
    last_fired = st.session_state["live_coach_last_fired"]
    last_speaker = st.session_state["live_last_speaker"]

    # Speaker-turn change detector: did the last segment add come from a
    # speaker different from the previous one?
    speaker_changed = False
    if new_segments:
        most_recent_speaker = new_segments[-1].speaker
        if last_speaker and most_recent_speaker != last_speaker:
            speaker_changed = True
        st.session_state["live_last_speaker"] = most_recent_speaker

    # Time ceiling: if no fire in the last 15s and we have ANY transcript,
    # call the coach anyway (catches long monologues).
    elapsed = now - last_fired
    time_ceiling_hit = elapsed >= TURN_TIMEOUT_CEILING_S and bool(buffer.segments)

    # First-call rule: if we've never fired and we have any transcript, fire.
    first_call = last_fired == 0.0 and bool(buffer.segments)

    should_fire = first_call or (speaker_changed and elapsed >= TURN_CHANGE_DEBOUNCE_S) \
                   or time_ceiling_hit
    if not should_fire:
        return

    transcript_text = buffer.total_transcript_text
    if not transcript_text:
        return

    # Build the coach (cached across reruns)
    if "live_coach_instance" not in st.session_state:
        from core.llm_client import LLMClient
        from agents.coach_agent import DentalCoach
        st.session_state["live_coach_instance"] = DentalCoach(
            LLMClient(demo=demo_mode)
        )
    coach = st.session_state["live_coach_instance"]

    try:
        recs = coach.coach(transcript_text, visit_type="emergency")
        for r in recs:
            st.session_state["live_recommendations"].append({
                **r.to_dict(),
                "fired_at_sec": round(now - (st.session_state.get("live_started_at") or now), 1),
            })
        if recs:
            st.toast(f"🩺 Coach: {len(recs)} new recommendation(s)", icon="🩺")
    except Exception as e:
        st.warning(f"Coach call failed: {e}")

    st.session_state["live_coach_last_fired"] = now


# ===========================================================================
# Left pane — live coaching recommendations
# ===========================================================================

# Per-category icon + tint to make the pane visually scannable
_CAT_META = {
    "safety":        ("🚨", "#F26D6D", "rgba(242,109,109,0.06)"),
    "history_gap":   ("📝", "#F4B860", "rgba(244,184,96,0.06)"),
    "differential":  ("🩺", "#7FB7FF", "rgba(127,183,255,0.06)"),
    "documentation": ("📋", "#C9A0FF", "rgba(201,160,255,0.06)"),
    "billing":       ("💼", "#4DD4AC", "rgba(77,212,172,0.06)"),
}


def _render_coach_pane(coach_enabled: bool) -> None:
    st.markdown(
        '<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">'
        '<span style="font-size:18px;">🩺</span>'
        '<span style="font-size:13px;font-weight:600;color:#E5E9F2;letter-spacing:-0.005em;">'
        'Live coaching</span>'
        + ('<span style="font-size:10px;color:#4DD4AC;background:rgba(77,212,172,0.10);'
            'border:1px solid rgba(77,212,172,0.30);padding:2px 8px;border-radius:999px;'
            'font-weight:600;letter-spacing:0.06em;">ACTIVE</span>' if coach_enabled
           else '<span style="font-size:10px;color:#9AA6B8;background:rgba(255,255,255,0.04);'
                 'border:1px solid rgba(255,255,255,0.10);padding:2px 8px;border-radius:999px;'
                 'font-weight:600;letter-spacing:0.06em;">DISABLED</span>')
        + '</div>',
        unsafe_allow_html=True,
    )

    if not coach_enabled:
        st.info("Coach mode is off. Enable it in the sidebar to see live "
                 "recommendations as the conversation unfolds.")
        return

    recs = list(reversed(st.session_state.get("live_recommendations") or []))
    if not recs:
        st.markdown(
            '<div style="padding:14px;border-radius:12px;background:rgba(255,255,255,0.02);'
            'border:1px solid rgba(255,255,255,0.06);color:#9AA6B8;font-size:13px;">'
            'Waiting for transcript… recommendations will appear here as the doctor '
            'and patient speak.</div>',
            unsafe_allow_html=True,
        )
        return

    for r in recs:
        cat = r.get("category", "documentation")
        icon, fg, bg = _CAT_META.get(cat, ("•", "#9AA6B8", "rgba(255,255,255,0.02)"))
        severity = (r.get("severity") or "low").upper()
        msg = r.get("message", "")
        action = r.get("suggested_action") or ""
        quote = r.get("evidence_quote") or ""
        tool = r.get("tool_used") or ""
        fired_at = r.get("fired_at_sec")

        html = (
            f'<div style="background:{bg};border:1px solid rgba(255,255,255,0.08);'
            f'border-left:3px solid {fg};border-radius:12px;padding:14px 16px;'
            f'margin-bottom:10px;">'
            f'  <div style="display:flex;justify-content:space-between;align-items:center;">'
            f'    <div style="font-size:10px;color:{fg};font-weight:700;'
            f'                letter-spacing:0.10em;text-transform:uppercase;">'
            f'      {icon} {cat.replace("_", " ")} · {severity}</div>'
            + (f'    <div style="font-size:10px;color:#6B7790;font-family:'
               f'\'JetBrains Mono\',monospace;">+{fired_at}s</div>'
               if fired_at is not None else "")
            + f'  </div>'
            f'  <div style="font-size:14px;font-weight:600;color:#E5E9F2;'
            f'              margin:6px 0 4px;">{msg}</div>'
            + (f'  <div style="font-size:13px;color:#9AA6B8;line-height:1.45;">↳ {action}</div>'
               if action else "")
            + (f'  <div style="border-left:2px solid {fg};padding:4px 10px;margin-top:8px;'
               f'              background:rgba(255,255,255,0.03);font-size:12px;'
               f'              color:#9AA6B8;font-style:italic;border-radius:0 6px 6px 0;">'
               f'    "{quote}"</div>' if quote else "")
            + (f'  <div style="font-size:10px;color:#6B7790;margin-top:6px;'
               f'              font-family:\'JetBrains Mono\',monospace;">tool: {tool}</div>'
               if tool else "")
            + '</div>'
        )
        st.markdown(html, unsafe_allow_html=True)


# ===========================================================================
# Right pane — rolling live transcript
# ===========================================================================

def _render_live_transcript_pane(buffer) -> None:
    st.markdown(
        '<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">'
        '<span style="font-size:18px;">💬</span>'
        '<span style="font-size:13px;font-weight:600;color:#E5E9F2;letter-spacing:-0.005em;">'
        'Live transcript</span>'
        '<span style="font-size:10px;color:#9AA6B8;background:rgba(255,255,255,0.04);'
        'border:1px solid rgba(255,255,255,0.10);padding:2px 8px;border-radius:999px;'
        f'font-weight:600;letter-spacing:0.06em;">{len(buffer.segments)} TURN(S)</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    if not buffer.segments:
        st.markdown(
            '<div style="padding:14px;border-radius:12px;background:rgba(255,255,255,0.02);'
            'border:1px solid rgba(255,255,255,0.06);color:#9AA6B8;font-size:13px;">'
            'No speech captured yet. Click <b>Start</b> on the recorder above and '
            'speak — every 2 seconds the transcript will update here.</div>',
            unsafe_allow_html=True,
        )
        return

    # Render the rolling transcript inside a scrollable container that
    # always shows the most recent turn at the bottom (autoscroll).
    for seg in buffer.segments[-30:]:   # cap at last 30 turns so DOM stays light
        who = (seg.speaker or "unknown").lower()
        if who in ("doctor", "provider", "dr"):
            avatar, role = "👨‍⚕️", "assistant"
        elif who in ("patient", "pt"):
            avatar, role = "🧑", "user"
        else:
            avatar, role = "💬", "assistant"
        with st.chat_message(role, avatar=avatar):
            st.markdown(f"**{(seg.speaker or 'Unknown').title()}**  "
                         f"<span style='font-size:10px;color:#6B7790;font-family:"
                         f"\"JetBrains Mono\",monospace;'>chunk #{seg.chunk_idx}</span>",
                         unsafe_allow_html=True)
            st.write(seg.text)
