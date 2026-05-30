"""Universal numbering (1-32) tooth chart SVG widget."""
from __future__ import annotations
import streamlit as st


def render_tooth_chart(highlighted=None, annotations=None) -> None:
    highlighted = highlighted or set()
    annotations = annotations or {}
    upper = list(range(1, 17))
    lower = list(range(32, 16, -1))
    w_tooth, h_tooth, gap = 26, 34, 4
    width = (w_tooth + gap) * 16 + 20
    height = (h_tooth * 2) + 36

    def tooth_rect(n, x, y):
        fill = "#4DD4AC" if n in highlighted else "#1F2A44"
        label_color = "#0B1220" if n in highlighted else "#9AA6B8"
        title = annotations.get(n, f"Tooth {n}")
        return (
            f'<g><title>{title}</title>'
            f'<rect x="{x}" y="{y}" width="{w_tooth}" height="{h_tooth}" rx="6" '
            f'fill="{fill}" stroke="#0B1220" stroke-width="1"/>'
            f'<text x="{x + w_tooth/2}" y="{y + h_tooth/2 + 4}" font-size="10" '
            f'fill="{label_color}" text-anchor="middle" font-family="monospace">{n}</text>'
            '</g>'
        )

    parts = [f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">']
    parts.append('<text x="10" y="14" font-size="10" fill="#6B7790">UPPER (1-16, R-L)</text>')
    for i, n in enumerate(upper):
        parts.append(tooth_rect(n, 10 + i * (w_tooth + gap), 18))
    parts.append(f'<text x="10" y="{18 + h_tooth + 18}" font-size="10" fill="#6B7790">LOWER (32-17, R-L)</text>')
    for i, n in enumerate(lower):
        parts.append(tooth_rect(n, 10 + i * (w_tooth + gap), 18 + h_tooth + 22))
    parts.append("</svg>")
    st.markdown(f'<div class="ds-card" style="overflow-x:auto;">{"".join(parts)}</div>',
                unsafe_allow_html=True)
