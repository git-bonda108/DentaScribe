"""Live + final transcript panel.

Renders TranscriptSegment dicts as styled bubbles. Interim segments
(is_final=False) appear in grey italic. Used by both the live streaming
page and the prerecorded/demo page.
"""
from __future__ import annotations
import streamlit as st


def render_transcript(segments, max_height: int = 420) -> None:
    if not segments:
        st.markdown(
            '<div class="ds-utt" style="text-align:center; color:#6B7790;">'
            'No conversation yet. Start recording or paste a transcript.</div>',
            unsafe_allow_html=True,
        )
        return

    parts = [f'<div style="max-height:{max_height}px; overflow-y:auto; padding-right:6px;">']
    for seg in segments:
        who = seg.get("speaker", "unknown")
        text = seg.get("text", "")
        final = seg.get("is_final", True)
        css = "ds-utt"
        if who == "provider":    css += " ds-utt-provider"
        elif who == "patient":   css += " ds-utt-patient"
        elif who == "assistant": css += " ds-utt-assistant"
        if not final:            css += " ds-utt-interim"
        parts.append(f'<div class="{css}"><span class="who">{who}</span>{text}</div>')
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def render_with_quotes(segments, highlight_quotes) -> None:
    parts = ['<div style="max-height:420px; overflow-y:auto; padding-right:6px;">']
    for seg in segments:
        who = seg.get("speaker", "unknown")
        text = seg.get("text", "")
        for q in highlight_quotes:
            if q and q.lower() in text.lower():
                text = text.replace(q, f'<mark style="background:#3D2E13;color:#F4B860;">{q}</mark>')
        css = "ds-utt"
        if who == "provider":  css += " ds-utt-provider"
        elif who == "patient": css += " ds-utt-patient"
        parts.append(f'<div class="{css}"><span class="who">{who}</span>{text}</div>')
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)
