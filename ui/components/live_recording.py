"""Live recording component — WebRTC mic → polled audio_receiver → Deepgram.

Architecture that actually works:

  1. `webrtc_streamer(mode=SENDONLY)` opens the mic.
  2. We poll `ctx.audio_receiver.get_frames(timeout=...)` from the Streamlit
     thread — NO processor class, NO threads. Frames go into the buffer.
  3. The transcript pane is an `@st.fragment(run_every="1s")` — Streamlit
     re-runs ONLY that pane every 1 second. The WebRTC widget itself
     stays mounted (no full-page reruns, no pale screen).
  4. Every fragment tick: poll frames → drain buffered audio → re-render.
  5. Coach agent fires on speaker-turn change OR 15-second ceiling.

Key fix vs the earlier version:
  - The old `time.sleep + st.rerun()` loop was the pale-screen culprit.
    Reruns destroyed the WebRTC context and froze the UI under the
    "running" overlay.
  - Audio-only frames arrive on `audio_receiver`, not via `recv()` on a
    processor class.
  - Smaller 1-sec window → snappier perceived latency.
"""
from __future__ import annotations
import time
from typing import Optional

import streamlit as st


TURN_CHANGE_DEBOUNCE_S = 2.0
TURN_TIMEOUT_CEILING_S = 15.0
FRAGMENT_REFRESH_SECS  = "1s"     # transcript pane auto-refresh cadence


# ===========================================================================
# Top-level entry
# ===========================================================================

def render_live_recording(coach_enabled: bool = True, demo_mode: bool = True) -> None:
    """Mount the WebRTC widget + the live two-pane view.

    The widget itself stays mounted across reruns (Streamlit caches it by
    `key="ds_live_mic"`). The transcript and coach panes auto-refresh via
    `st.fragment`, which DOESN'T re-run the WebRTC widget.
    """
    try:
        from streamlit_webrtc import webrtc_streamer, WebRtcMode, RTCConfiguration
        from audio.live_streaming import LiveAudioBuffer
    except ImportError as e:
        st.error(f"Live recording requires `streamlit-webrtc`. Install with: "
                  f"`pip install streamlit-webrtc`. Error: {e}")
        return

    # ----- session state init (idempotent) ----------------------------
    if "live_buffer" not in st.session_state:
        st.session_state["live_buffer"] = LiveAudioBuffer(window_secs=1.0)
    if "live_recommendations" not in st.session_state:
        st.session_state["live_recommendations"] = []
    if "live_coach_last_fired" not in st.session_state:
        st.session_state["live_coach_last_fired"] = 0.0
    if "live_last_speaker" not in st.session_state:
        st.session_state["live_last_speaker"] = None
    if "live_started_at" not in st.session_state:
        st.session_state["live_started_at"] = 0.0

    # ----- Header + controls ------------------------------------------
    st.markdown(
        '<div style="margin-bottom:14px;">'
        '<div style="font-size:13px;color:#5A6478;line-height:1.5;">'
        'Click <b>Start</b> below to begin recording. Audio streams to Deepgram '
        'in 1-second windows; the transcript on the right updates as you speak '
        'and the coach on the left flags anything the doctor might miss.'
        '</div></div>',
        unsafe_allow_html=True,
    )

    cols = st.columns([2, 1, 1])
    if cols[1].button("🔄  Clear", use_container_width=True, key="ds_live_clear"):
        st.session_state["live_buffer"].reset()
        st.session_state["live_recommendations"] = []
        st.session_state["live_coach_last_fired"] = 0.0
        st.session_state["live_last_speaker"] = None
        st.toast("Cleared")
        st.rerun()
    if cols[2].button("📋  Use as transcript", use_container_width=True,
                       key="ds_live_handoff",
                       disabled=not st.session_state["live_buffer"].segments,
                       help="Hand the rolling transcript to the agent swarm."):
        st.session_state["live_handed_off_text"] = \
            st.session_state["live_buffer"].total_transcript_text
        st.toast("Transcript handed off to the swarm.")

    # ----- WebRTC widget (audio_receiver pattern) ---------------------
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

    # Mark the recording start time the first time playback begins
    if ctx and ctx.state.playing and not st.session_state["live_started_at"]:
        st.session_state["live_started_at"] = time.time()
        st.toast("Recording started · speak now", icon="🎙️")

    # ----- Diagnostic strip + two-pane layout (auto-refreshing) -------
    # Both fragments re-run independently every 1s — without re-mounting
    # the WebRTC widget above. This is what fixes the pale-screen issue.
    _diag_and_drain_fragment(ctx, coach_enabled=coach_enabled, demo_mode=demo_mode)

    left, right = st.columns([1, 1], gap="medium")
    with left:
        _coach_pane_fragment(coach_enabled=coach_enabled)
    with right:
        _transcript_pane_fragment()


# ===========================================================================
# Fragment 1 — diagnostic strip + audio drain + coach trigger
# ===========================================================================

@st.fragment(run_every=FRAGMENT_REFRESH_SECS)
def _diag_and_drain_fragment(ctx, *, coach_enabled: bool, demo_mode: bool) -> None:
    """Every 1 second: poll frames from audio_receiver, drain windows
    through Deepgram, fire the coach if conditions are met, and render
    a small diagnostic strip so the user can SEE the pipeline working.
    """
    buffer = st.session_state["live_buffer"]

    # --- 1. Poll frames (non-blocking-ish: 0.05s queue timeout) -------
    new_segments_this_tick = []
    if ctx and ctx.state.playing and ctx.audio_receiver:
        try:
            frames = ctx.audio_receiver.get_frames(timeout=0.05)
        except Exception:
            frames = []
        if frames:
            buffer.ingest_frames(frames)

        # Drain ALL full windows currently available (may be 0 or several)
        while buffer.has_enough_audio():
            chunk_new = buffer.drain_chunks()
            new_segments_this_tick.extend(chunk_new)
            if not chunk_new:
                break

    # --- 2. Maybe-fire coach ------------------------------------------
    if coach_enabled and buffer.segments:
        _maybe_fire_coach(buffer, demo_mode=demo_mode,
                          new_segments=new_segments_this_tick)

    # --- 3. Diagnostic strip ------------------------------------------
    is_playing = bool(ctx and ctx.state.playing)
    dot = ("#0EA5A4" if is_playing else "#8A95AB")
    dot_label = ("● RECORDING" if is_playing else "○ Idle — click Start")

    err_html = ""
    if buffer.last_error:
        err_html = (
            f'<div style="font-size:11px;color:#B91C1C;background:rgba(185,28,28,0.05);'
            f'border:1px solid rgba(185,28,28,0.20);padding:6px 10px;border-radius:6px;'
            f'margin-top:6px;">⚠ {buffer.last_error}</div>'
        )

    st.markdown(
        f'<div style="display:flex;align-items:center;gap:18px;padding:10px 16px;'
        f'background:#FBFCFD;border:1px solid #EEF1F5;border-radius:10px;'
        f'box-shadow:0 1px 2px rgba(11,20,38,0.04);margin:14px 0 18px;">'
        f'  <div style="display:inline-flex;align-items:center;gap:8px;">'
        f'    <span style="width:8px;height:8px;border-radius:50%;background:{dot};'
        f'                 {"box-shadow:0 0 8px " + dot + "aa;animation:ds-pulse 1.5s infinite;" if is_playing else ""}"></span>'
        f'    <span style="font-size:11px;font-weight:700;color:{dot};'
        f'                 letter-spacing:0.10em;">{dot_label}</span>'
        f'  </div>'
        f'  <div style="font-size:11px;color:#5A6478;display:flex;gap:18px;'
        f'              font-family:\'JetBrains Mono\',monospace;">'
        f'    <span>frames <b style="color:#0B1426;">{buffer.total_frames}</b></span>'
        f'    <span>chunks <b style="color:#0B1426;">{buffer.total_chunks}</b></span>'
        f'    <span>segments <b style="color:#0B1426;">{len(buffer.segments)}</b></span>'
        f'    <span>buffered <b style="color:#0B1426;">{buffer.total_seconds_buffered:.1f}s</b></span>'
        f'  </div>'
        f'</div>{err_html}',
        unsafe_allow_html=True,
    )


# ===========================================================================
# Coach trigger logic — turn change OR 15s ceiling
# ===========================================================================

def _maybe_fire_coach(buffer, *, demo_mode: bool, new_segments: list) -> None:
    """Decide whether to invoke the coach this tick."""
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
    time_ceiling_hit = elapsed >= TURN_TIMEOUT_CEILING_S and bool(buffer.segments)
    first_call = last_fired == 0.0 and bool(buffer.segments)

    if not (first_call or (speaker_changed and elapsed >= TURN_CHANGE_DEBOUNCE_S)
            or time_ceiling_hit):
        return

    transcript_text = buffer.total_transcript_text
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
        # Surface coach failures into the diagnostic strip via buffer.last_error
        st.session_state["live_buffer"].last_error = f"coach: {e}"[:160]

    st.session_state["live_coach_last_fired"] = now


# ===========================================================================
# Fragment 2 — coach pane (auto-refreshing)
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
    """Left pane — live coaching cards. Re-renders every 1s without
    touching the WebRTC widget."""
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
        '<span style="font-size:14px;font-weight:600;color:#0B1426;letter-spacing:-0.005em;">'
        'Live coaching</span>'
        + badge_html + '</div>',
        unsafe_allow_html=True,
    )

    if not coach_enabled:
        st.info("Coach mode is off. Enable it in the sidebar to see live "
                 "recommendations as the conversation unfolds.")
        return

    recs = list(reversed(st.session_state.get("live_recommendations") or []))
    if not recs:
        st.markdown(
            '<div style="padding:16px 18px;border-radius:12px;background:#FBFCFD;'
            'border:1px solid #EEF1F5;color:#5A6478;font-size:13px;'
            'box-shadow:0 1px 2px rgba(11,20,38,0.04);">'
            'Waiting for transcript… recommendations will appear here as the '
            'doctor and patient speak.</div>',
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
# Fragment 3 — transcript pane (auto-refreshing)
# ===========================================================================

@st.fragment(run_every=FRAGMENT_REFRESH_SECS)
def _transcript_pane_fragment() -> None:
    """Right pane — rolling transcript bubbles. Auto-refreshes."""
    buffer = st.session_state.get("live_buffer")
    st.markdown(
        '<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">'
        '<span style="font-size:18px;">💬</span>'
        '<span style="font-size:14px;font-weight:600;color:#0B1426;letter-spacing:-0.005em;">'
        'Live transcript</span>'
        '<span style="font-size:10px;color:#5A6478;background:#F4F6F9;'
        'border:1px solid #DDE3EC;padding:3px 9px;border-radius:999px;'
        f'font-weight:700;letter-spacing:0.10em;">{len(buffer.segments) if buffer else 0} TURN(S)</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    if not buffer or not buffer.segments:
        st.markdown(
            '<div style="padding:16px 18px;border-radius:12px;background:#FBFCFD;'
            'border:1px solid #EEF1F5;color:#5A6478;font-size:13px;'
            'box-shadow:0 1px 2px rgba(11,20,38,0.04);">'
            'No speech captured yet. Click <b>Start</b> on the recorder above and '
            'speak — the transcript will update here within ~1.5 seconds.</div>',
            unsafe_allow_html=True,
        )
        return

    for seg in buffer.segments[-30:]:
        who = (seg.speaker or "unknown").lower()
        if who in ("doctor", "provider", "dr"):
            avatar, role = "👨‍⚕️", "assistant"
        elif who in ("patient", "pt"):
            avatar, role = "🧑", "user"
        else:
            avatar, role = "💬", "assistant"
        with st.chat_message(role, avatar=avatar):
            st.markdown(
                f"**{(seg.speaker or 'Unknown').title()}**  "
                f"<span style='font-size:10px;color:#8A95AB;font-family:"
                f"\"JetBrains Mono\",monospace;'>chunk #{seg.chunk_idx}</span>",
                unsafe_allow_html=True,
            )
            st.write(seg.text)
