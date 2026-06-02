"""Live recording — WebRTC mic → Deepgram WebSocket → live coaching pane.

Architecture (true real-time, not chunked):

  1. `webrtc_streamer(mode=SENDONLY)` opens the mic.
  2. We poll `ctx.audio_receiver.get_frames()` every fragment tick.
  3. Each frame → 16-bit PCM bytes → pushed to a `LiveDeepgramSession`
     (one WebSocket per recording session).
  4. Deepgram pushes `interim` + `is_final` transcripts on its own thread;
     we marshal them into the session's snapshot (thread-safe).
  5. Streamlit fragments re-render the transcript + coach pane every ~0.5s
     from `session.snapshot()` — interim text shows in gray italic so the
     user sees words *as they speak them*.

Key fix vs the chunked-REST version:
  • REST returned 0 utterances for 1-sec clips. WebSocket streams interim
    transcripts as words land, so the right pane fills in immediately.
  • Same `audio_receiver` polling pattern (no AudioProcessor class) so
    Streamlit reruns don't kill the WebRTC context.
  • The fragment refresh rate dropped to 0.5s for snappier UI updates.
"""
from __future__ import annotations
import time
from typing import Optional

import streamlit as st


TURN_CHANGE_DEBOUNCE_S = 2.0
TURN_TIMEOUT_CEILING_S = 15.0
FRAGMENT_REFRESH_SECS  = "0.5s"   # 0.5s = visibly live without burning CPU


# ===========================================================================
# Top-level entry
# ===========================================================================

def render_live_recording(coach_enabled: bool = True, demo_mode: bool = True) -> None:
    """Mount WebRTC widget + two-pane Coach/Transcript view.
    Uses Deepgram WebSocket streaming for true real-time transcript.
    """
    try:
        from streamlit_webrtc import (
            webrtc_streamer, WebRtcMode, RTCConfiguration,
        )
        from audio.live_streaming import LiveDeepgramSession, frame_to_pcm16_bytes
    except ImportError as e:
        st.error(
            f"Live recording requires `streamlit-webrtc` + `deepgram-sdk`. "
            f"Install: `pip install streamlit-webrtc deepgram-sdk`. Error: {e}"
        )
        return

    # ----- session state ----------------------------------------------
    if "live_session" not in st.session_state:
        st.session_state["live_session"] = LiveDeepgramSession()
    if "live_recommendations" not in st.session_state:
        st.session_state["live_recommendations"] = []
    if "live_coach_last_fired" not in st.session_state:
        st.session_state["live_coach_last_fired"] = 0.0
    if "live_last_speaker" not in st.session_state:
        st.session_state["live_last_speaker"] = None
    if "live_started_at" not in st.session_state:
        st.session_state["live_started_at"] = 0.0
    if "live_seen_segments_count" not in st.session_state:
        st.session_state["live_seen_segments_count"] = 0

    # ----- Header ------------------------------------------------------
    st.markdown(
        '<div style="margin-bottom:14px;">'
        '<div style="font-size:13px;color:#5A6478;line-height:1.55;">'
        '<b>Click START below</b> and grant mic permission. Words appear on '
        'the right as you speak (typically <b>&lt;1 second</b> latency). The '
        'coach on the left flags safety, history gaps, and CDT codes as the '
        'conversation unfolds. Click <b>Stop &amp; finalize</b> when done — '
        'the full transcript hands off to the agent swarm for the signed SOAP.'
        '</div></div>',
        unsafe_allow_html=True,
    )

    cols = st.columns([2, 1, 1])
    if cols[1].button("🔄  Clear", use_container_width=True, key="ds_live_clear"):
        st.session_state["live_session"].reset()
        st.session_state["live_recommendations"] = []
        st.session_state["live_coach_last_fired"] = 0.0
        st.session_state["live_last_speaker"] = None
        st.session_state["live_started_at"] = 0.0
        st.session_state["live_seen_segments_count"] = 0
        st.toast("Cleared")
        st.rerun()

    session = st.session_state["live_session"]
    snap = session.snapshot()
    has_text = bool(snap.segments or snap.interim_text)
    if cols[2].button("🛑  Stop & finalize", use_container_width=True,
                       key="ds_live_finalize",
                       type="primary" if has_text else "secondary",
                       disabled=not has_text,
                       help="Close the mic and IMMEDIATELY run the agent swarm "
                            "on the recorded transcript — no tab switching."):
        session.stop()
        # Signal the parent page to kick off the swarm on the rolling text
        # right after this rerun. The parent reads (and pops) this flag
        # inside the live mic tab so the swarm runs inline.
        finalized = snap.transcript_text
        if finalized.strip():
            st.session_state["live_finalize_pending"] = finalized
            # Keep a copy for the Run-on-paste retry path
            st.session_state["live_handed_off_text"] = finalized
            st.toast("Recording stopped — running agent swarm…", icon="🎙️")
        else:
            st.toast("Nothing captured yet — speak first.", icon="⚠️")
        st.rerun()

    # ----- WebRTC widget ----------------------------------------------
    rtc_config = RTCConfiguration({"iceServers": [
        {"urls": ["stun:stun.l.google.com:19302"]}
    ]})

    ctx = webrtc_streamer(
        key="ds_live_mic",
        mode=WebRtcMode.SENDONLY,
        rtc_configuration=rtc_config,
        media_stream_constraints={"audio": True, "video": False},
        audio_receiver_size=1024,
        async_processing=False,
    )

    if ctx and ctx.state.playing and not st.session_state["live_started_at"]:
        st.session_state["live_started_at"] = time.time()
        st.toast("Recording started — speak now.", icon="🎙️")

    # If recording stopped (user pressed Stop on the WebRTC widget), close WS
    if ctx and not ctx.state.playing and session.is_running:
        session.stop()

    # ----- Audio drain + coach trigger + diagnostic strip -------------
    _audio_drain_fragment(ctx, coach_enabled=coach_enabled, demo_mode=demo_mode)

    # ----- Two-pane live view -----------------------------------------
    left, right = st.columns([1, 1], gap="medium")
    with left:
        _coach_pane_fragment(coach_enabled=coach_enabled)
    with right:
        _transcript_pane_fragment()


# ===========================================================================
# Fragment 1 — audio drain (sends frames to Deepgram WS) + coach trigger
# + diagnostic strip
# ===========================================================================

@st.fragment(run_every=FRAGMENT_REFRESH_SECS)
def _audio_drain_fragment(ctx, *, coach_enabled: bool, demo_mode: bool) -> None:
    """Every 0.5s: poll WebRTC frames, push to Deepgram, maybe fire coach,
    render the diagnostic strip."""
    from audio.live_streaming import frame_to_pcm16_bytes
    session = st.session_state["live_session"]

    # --- 1. Poll WebRTC frames + stream to Deepgram --------------------
    # PyAV resampler inside `ingest_frame` normalizes whatever the browser
    # sends (48kHz stereo float, 16kHz mono, etc.) to 16-bit mono 16kHz PCM,
    # so Deepgram always sees the same format. Auto-starts on first frame.
    if ctx and ctx.state.playing and ctx.audio_receiver:
        try:
            frames = ctx.audio_receiver.get_frames(timeout=0.05)
        except Exception:
            frames = []
        for f in frames:
            session.ingest_frame(f)

    # --- 2. Maybe fire coach (only when new finalized segments arrived) -
    snap = session.snapshot()
    if coach_enabled and snap.segments:
        prev_seen = st.session_state.get("live_seen_segments_count", 0)
        new_segments = snap.segments[prev_seen:]
        st.session_state["live_seen_segments_count"] = len(snap.segments)
        if new_segments or _coach_ceiling_hit():
            _maybe_fire_coach(snap, new_segments=new_segments, demo_mode=demo_mode)

    # --- 3. Diagnostic strip ------------------------------------------
    is_playing = bool(ctx and ctx.state.playing)
    state = snap.state
    dot, label = _state_dot_and_label(state, is_playing)

    err_html = ""
    if snap.last_error:
        err_html = (
            f'<div style="font-size:11px;color:#B91C1C;background:rgba(185,28,28,0.05);'
            f'border:1px solid rgba(185,28,28,0.20);padding:6px 10px;border-radius:6px;'
            f'margin-top:6px;">⚠ {snap.last_error}</div>'
        )

    st.markdown(
        f'<div style="display:flex;align-items:center;gap:18px;padding:10px 16px;'
        f'background:#FBFCFD;border:1px solid #EEF1F5;border-radius:10px;'
        f'box-shadow:0 1px 2px rgba(11,20,38,0.04);margin:14px 0 18px;flex-wrap:wrap;">'
        f'  <div style="display:inline-flex;align-items:center;gap:8px;">'
        f'    <span style="width:8px;height:8px;border-radius:50%;background:{dot};'
        f'{"box-shadow:0 0 8px " + dot + "aa;animation:ds-pulse 1.5s infinite;" if state == "streaming" else ""}"></span>'
        f'    <span style="font-size:11px;font-weight:700;color:{dot};'
        f'                 letter-spacing:0.10em;text-transform:uppercase;">{label}</span>'
        f'  </div>'
        f'  <div style="font-size:11px;color:#5A6478;display:flex;gap:18px;'
        f'              font-family:\'JetBrains Mono\',monospace;">'
        f'    <span>frames <b style="color:#0B1426;">{snap.frames_sent}</b></span>'
        f'    <span>bytes <b style="color:#0B1426;">{snap.bytes_sent:,}</b></span>'
        f'    <span>finals <b style="color:#0B1426;">{len(snap.segments)}</b></span>'
        f'    <span>state <b style="color:#0B1426;">{snap.state}</b></span>'
        f'  </div>'
        f'</div>{err_html}',
        unsafe_allow_html=True,
    )


def _state_dot_and_label(state: str, is_playing: bool) -> tuple[str, str]:
    if state == "streaming":
        return "#0EA5A4", "● Live — words arrive as you speak"
    if state == "connecting":
        return "#B45309", "● Connecting to Deepgram…"
    if state == "error":
        return "#B91C1C", "● Error — check diagnostic"
    if is_playing and state in ("idle", "closed"):
        return "#B45309", "● Mic open — waiting for first frame"
    if state == "closed":
        return "#8A95AB", "○ Closed — clear to restart"
    return "#8A95AB", "○ Idle — click START to begin"


def _coach_ceiling_hit() -> bool:
    now = time.time()
    last = st.session_state.get("live_coach_last_fired", 0.0)
    return (now - last) >= TURN_TIMEOUT_CEILING_S and last > 0


# ===========================================================================
# Coach trigger logic — turn change OR 15s ceiling
# ===========================================================================

def _maybe_fire_coach(snap, *, new_segments: list, demo_mode: bool) -> None:
    now = time.time()
    last_fired = st.session_state["live_coach_last_fired"]
    last_speaker = st.session_state["live_last_speaker"]

    speaker_changed = False
    if new_segments:
        most_recent_speaker = new_segments[-1].speaker
        if last_speaker and most_recent_speaker != last_speaker:
            speaker_changed = True
        st.session_state["live_last_speaker"] = most_recent_speaker

    elapsed = now - last_fired
    time_ceiling_hit = elapsed >= TURN_TIMEOUT_CEILING_S and bool(snap.segments)
    first_call = last_fired == 0.0 and bool(snap.segments)

    if not (first_call or (speaker_changed and elapsed >= TURN_CHANGE_DEBOUNCE_S)
            or time_ceiling_hit):
        return

    transcript_text = snap.transcript_text
    if not transcript_text:
        return

    if "live_coach_instance" not in st.session_state:
        from core.llm_client import LLMClient
        from agents.coach_agent import DentalCoach
        st.session_state["live_coach_instance"] = DentalCoach(
            LLMClient(demo=demo_mode)
        )
    coach = st.session_state["live_coach_instance"]

    try:
        recs = coach.coach(transcript_text, visit_type="emergency")
        started_at = st.session_state.get("live_started_at") or now
        for r in recs:
            st.session_state["live_recommendations"].append({
                **r.to_dict(),
                "fired_at_sec": round(now - started_at, 1),
            })
    except Exception as e:
        st.session_state["live_session"]._set_error(f"coach: {e}")

    st.session_state["live_coach_last_fired"] = now


# ===========================================================================
# Fragment 2 — coach pane
# ===========================================================================

_CAT_META = {
    "safety":        ("🚨", "#B91C1C", "rgba(185,28,28,0.04)"),
    "history_gap":   ("📝", "#B45309", "rgba(180,83,9,0.04)"),
    "differential":  ("🩺", "#2563EB", "rgba(37,99,235,0.04)"),
    "documentation": ("📋", "#7C3AED", "rgba(124,58,237,0.04)"),
    "billing":       ("💼", "#0B8786", "rgba(14,165,164,0.05)"),
}


@st.fragment(run_every=FRAGMENT_REFRESH_SECS)
def _coach_pane_fragment(*, coach_enabled: bool) -> None:
    badge_html = (
        '<span style="font-size:10px;color:#0B8786;background:#E6F8F6;'
        'border:1px solid rgba(14,165,164,0.30);padding:3px 9px;border-radius:999px;'
        'font-weight:700;letter-spacing:0.10em;">ACTIVE</span>'
        if coach_enabled else
        '<span style="font-size:10px;color:#5A6478;background:#F4F6F9;'
        'border:1px solid #DDE3EC;padding:3px 9px;border-radius:999px;'
        'font-weight:700;letter-spacing:0.10em;">DISABLED</span>'
    )
    st.markdown(
        '<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">'
        '<span style="font-size:18px;">🩺</span>'
        '<span style="font-size:14px;font-weight:600;color:#0B1426;'
        'letter-spacing:-0.005em;">Live coaching</span>'
        + badge_html + '</div>',
        unsafe_allow_html=True,
    )

    if not coach_enabled:
        st.info("Coach mode is off. Enable it in the sidebar.")
        return

    recs = list(reversed(st.session_state.get("live_recommendations") or []))
    if not recs:
        st.markdown(
            '<div style="padding:16px 18px;border-radius:12px;background:#FBFCFD;'
            'border:1px solid #EEF1F5;color:#5A6478;font-size:13px;'
            'box-shadow:0 1px 2px rgba(11,20,38,0.04);">'
            'Recommendations will appear here as the doctor and patient speak.'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    for r in recs:
        cat = r.get("category", "documentation")
        icon, fg, bg = _CAT_META.get(cat, ("•", "#5A6478", "#FBFCFD"))
        severity = (r.get("severity") or "low").upper()
        msg = r.get("message", "")
        action = r.get("suggested_action") or ""
        quote = r.get("evidence_quote") or ""
        tool = r.get("tool_used") or ""
        fired_at = r.get("fired_at_sec")
        html = (
            f'<div style="background:#FFFFFF;border:1px solid #EEF1F5;'
            f'border-left:3px solid {fg};border-radius:10px;padding:14px 16px;'
            f'margin-bottom:10px;box-shadow:0 1px 2px rgba(11,20,38,0.04);">'
            f'  <div style="display:flex;justify-content:space-between;align-items:center;">'
            f'    <div style="font-size:10px;color:{fg};font-weight:700;'
            f'                letter-spacing:0.10em;text-transform:uppercase;">'
            f'      {icon} {cat.replace("_", " ")} · {severity}</div>'
            + (f'    <div style="font-size:10px;color:#8A95AB;font-family:'
               f'\'JetBrains Mono\',monospace;">+{fired_at}s</div>'
               if fired_at is not None else "")
            + f'  </div>'
            f'  <div style="font-size:14px;font-weight:600;color:#0B1426;'
            f'              margin:8px 0 4px;letter-spacing:-0.005em;">{msg}</div>'
            + (f'  <div style="font-size:13px;color:#5A6478;line-height:1.5;">↳ {action}</div>'
               if action else "")
            + (f'  <div style="border-left:2px solid {fg};padding:5px 10px;margin-top:10px;'
               f'              background:{bg};font-size:12px;color:#5A6478;'
               f'              font-style:italic;border-radius:0 6px 6px 0;">'
               f'    "{quote}"</div>' if quote else "")
            + (f'  <div style="font-size:10px;color:#8A95AB;margin-top:8px;'
               f'              font-family:\'JetBrains Mono\',monospace;">tool: {tool}</div>'
               if tool else "")
            + '</div>'
        )
        st.markdown(html, unsafe_allow_html=True)


# ===========================================================================
# Fragment 3 — transcript pane
# Renders finalized segments + the CURRENT interim transcript in gray italic
# so the user sees words appearing as they speak.
# ===========================================================================

@st.fragment(run_every=FRAGMENT_REFRESH_SECS)
def _transcript_pane_fragment() -> None:
    session = st.session_state.get("live_session")
    snap = session.snapshot() if session else None

    n_segments = len(snap.segments) if snap else 0
    st.markdown(
        '<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">'
        '<span style="font-size:18px;">💬</span>'
        '<span style="font-size:14px;font-weight:600;color:#0B1426;'
        'letter-spacing:-0.005em;">Live transcript</span>'
        f'<span style="font-size:10px;color:#5A6478;background:#F4F6F9;'
        f'border:1px solid #DDE3EC;padding:3px 9px;border-radius:999px;'
        f'font-weight:700;letter-spacing:0.10em;">{n_segments} TURN(S)</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    if not snap or (not snap.segments and not snap.interim_text):
        st.markdown(
            '<div style="padding:16px 18px;border-radius:12px;background:#FBFCFD;'
            'border:1px solid #EEF1F5;color:#5A6478;font-size:13px;'
            'box-shadow:0 1px 2px rgba(11,20,38,0.04);">'
            'Click <b>START</b> on the recorder above and speak. The transcript '
            'will appear here in under a second.</div>',
            unsafe_allow_html=True,
        )
        return

    # --- finalized turns (most recent 30) ---
    for seg in snap.segments[-30:]:
        who = (seg.speaker or "unknown").lower()
        if who in ("doctor", "provider", "dr"):
            avatar, role = "👨‍⚕️", "assistant"
        elif who in ("patient", "pt"):
            avatar, role = "🧑", "user"
        else:
            avatar, role = "💬", "assistant"
        with st.chat_message(role, avatar=avatar):
            st.markdown(f"**{(seg.speaker or 'Unknown').title()}**",
                         unsafe_allow_html=True)
            st.write(seg.text)

    # --- the currently-streaming interim transcript (italic, dim) ---
    # This is what makes it feel LIVE — words appear here within ~300ms of
    # being spoken, then get promoted into a real bubble when Deepgram
    # marks them is_final=True.
    if snap.interim_text:
        st.markdown(
            f'<div style="margin:8px 0;padding:14px 18px;border:1px dashed #DDE3EC;'
            f'border-radius:12px;background:#FBFCFD;color:#5A6478;font-style:italic;'
            f'font-size:14px;line-height:1.55;display:flex;gap:10px;align-items:flex-start;">'
            f'  <span style="width:8px;height:8px;border-radius:50%;background:#0EA5A4;'
            f'               margin-top:7px;animation:ds-pulse 1.2s infinite;flex-shrink:0;"></span>'
            f'  <span>{snap.interim_text}<span style="opacity:0.6;">▌</span></span>'
            f'</div>',
            unsafe_allow_html=True,
        )
