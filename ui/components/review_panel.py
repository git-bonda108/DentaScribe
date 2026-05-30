"""Second-Opinion / Reviewer panel."""
from __future__ import annotations
import streamlit as st


def render_review(review_items) -> None:
    if not review_items:
        st.markdown('<div class="ds-card" style="color:#9AA6B8;">'
                    'No second-opinion findings. Note looks clean.</div>',
                    unsafe_allow_html=True)
        return
    order = {"high": 0, "med": 1, "low": 2}
    items = sorted(review_items, key=lambda r: order.get((r.get("severity") or "low").lower(), 9))
    for r in items:
        sev = (r.get("severity") or "low").lower()
        cls = {"high":"ds-review-high","med":"ds-review-med","low":"ds-review-low"}.get(sev, "ds-review-low")
        cat = r.get("category", "note")
        msg = r.get("message", "")
        sugg = r.get("suggestion")
        quote = r.get("evidence_quote")
        tooth = r.get("tooth_ref")
        body = f'<div class="cat">{cat.upper()} • severity {sev}</div>'
        body += f'<div style="font-weight:600; margin:4px 0;">{msg}</div>'
        if sugg:  body += f'<div style="font-size:13px; color:#C9D2E3;">↳ {sugg}</div>'
        if quote: body += f'<div class="ds-quote">"{quote}"</div>'
        if tooth: body += f'<div style="font-size:11px; color:#6B7790;">tooth #{tooth}</div>'
        st.markdown(f'<div class="ds-review {cls}">{body}</div>', unsafe_allow_html=True)
