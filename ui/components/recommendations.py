"""Live clinical Recommendations panel.

Separate from Second-Opinion (which is *peer-review flags*). This panel is
the **doctor-facing clinical summary** distilled from the SOAP assessment +
plan: working diagnosis, procedures today, prescriptions, follow-up.

Used during and after the swarm run. Color-coded by clinical urgency.
"""
from __future__ import annotations
from typing import Any
import streamlit as st


URGENCY_BADGE = {
    "high":    ("🚨 URGENT",    "#F26D6D", "#3B1A1A"),
    "medium":  ("⚠️ Important", "#F4B860", "#3D2E13"),
    "low":     ("• Routine",    "#4DD4AC", "#163B30"),
}


def _badge(urgency: str) -> str:
    label, fg, bg = URGENCY_BADGE.get(urgency, URGENCY_BADGE["low"])
    return (f'<span style="display:inline-block;padding:2px 8px;border-radius:999px;'
            f'background:{bg};color:{fg};font-size:10px;font-weight:600;'
            f'letter-spacing:0.06em;text-transform:uppercase;">{label}</span>')


def _classify_diagnosis(diagnosis: str) -> str:
    """Quick heuristic for clinical urgency from a diagnosis string."""
    d = (diagnosis or "").lower()
    if any(k in d for k in ("abscess", "irreversible pulpitis", "cellulitis",
                              "fracture", "avulsion", "uncontrolled bleeding")):
        return "high"
    if any(k in d for k in ("caries", "decay", "pulpitis", "periodontitis",
                              "infection", "lesion")):
        return "medium"
    return "low"


def render_recommendations(soap: dict | None, review: list[dict] | None = None) -> None:
    """Render a live, doctor-facing recommendations panel.

    Pulls from:
      - assessment.diagnoses         → clinical findings
      - plan.procedures_today        → what to do now
      - plan.prescriptions           → drugs + sigs
      - plan.recommended_future      → follow-up
      - plan.patient_instructions    → home-care
      - Second-Opinion (review)      → safety / drug interaction flags hoisted up
    """
    if not soap:
        st.info("Run the swarm to see clinical recommendations here.")
        return

    assess = soap.get("assessment") or {}
    plan = soap.get("plan") or {}
    diagnoses = assess.get("diagnoses") or []
    procedures = plan.get("procedures_today") or []
    rx = plan.get("prescriptions") or []
    future = plan.get("recommended_future") or []
    instructions = plan.get("patient_instructions") or ""
    follow_up = plan.get("follow_up") or ""

    # 1) Hoist high-severity Second-Opinion flags to the TOP (safety first)
    high_flags = [r for r in (review or [])
                  if (r.get("severity") or "").lower() in ("high", "med", "medium")]
    if high_flags:
        st.markdown("##### 🛡️ Safety alerts (from Second-Opinion)")
        for f in high_flags[:3]:
            sev = (f.get("severity") or "low").lower()
            sev = "high" if sev == "high" else "medium"
            msg = f.get("message") or "—"
            sugg = f.get("suggestion") or ""
            st.markdown(
                f'{_badge(sev)} &nbsp; **{msg}**'
                + (f'<br><span style="color:#9AA6B8;font-size:13px;">↳ {sugg}</span>' if sugg else ""),
                unsafe_allow_html=True,
            )
        st.divider()

    # 2) Working diagnosis (color-coded by urgency)
    if diagnoses:
        st.markdown("##### 🩺 Working diagnosis")
        for dx in diagnoses[:5]:
            label = dx.get("diagnosis", "—") if isinstance(dx, dict) else str(dx)
            tooth = dx.get("tooth", "") if isinstance(dx, dict) else ""
            urg = _classify_diagnosis(label)
            tooth_str = f" · tooth #{tooth}" if tooth else ""
            st.markdown(
                f'{_badge(urg)} &nbsp; **{label}**'
                + f'<span style="color:#9AA6B8;font-size:13px;">{tooth_str}</span>',
                unsafe_allow_html=True,
            )

    # 3) Procedures today
    if procedures:
        st.markdown("##### 🦷 Procedures today")
        rows = []
        for p in procedures:
            if not isinstance(p, dict): continue
            tooth = p.get("tooth") or "—"
            surfaces = ",".join(p.get("surfaces") or []) or "—"
            rows.append({
                "Tooth": tooth, "Surfaces": surfaces,
                "Procedure": p.get("procedure", "—"),
                "Anesthesia": p.get("anesthesia") or "—",
            })
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)

    # 4) Prescriptions — these are the highest-liability items
    if rx:
        st.markdown("##### 💊 Prescriptions")
        for r in rx:
            if not isinstance(r, dict): continue
            drug = r.get("drug", "—")
            strength = r.get("strength") or ""
            sig = r.get("sig") or ""
            qty = r.get("quantity")
            refills = r.get("refills")
            checked = "✓" if r.get("interaction_checked") else "⚠ INTERACTION CHECK PENDING"
            interaction_color = "#4DD4AC" if r.get("interaction_checked") else "#F4B860"
            st.markdown(
                f"**{drug}** {strength}  &nbsp; <span style='color:#9AA6B8;font-size:13px;'>{sig}</span>"
                + (f"  &nbsp;·&nbsp; Qty {qty}" if qty else "")
                + (f"  &nbsp;·&nbsp; Refills {refills}" if refills is not None else "")
                + f"<br><span style='color:{interaction_color};font-size:12px;'>{checked}</span>",
                unsafe_allow_html=True,
            )

    # 5) Follow-up / future
    if future or follow_up:
        st.markdown("##### 📅 Follow-up")
        if follow_up:
            st.write(follow_up)
        for item in future:
            if isinstance(item, str):
                st.markdown(f"• {item}")
            elif isinstance(item, dict):
                proc = item.get("procedure") or item.get("description") or "—"
                tooth = item.get("tooth")
                when = item.get("when") or item.get("timing") or ""
                st.markdown(
                    f"• **{proc}**"
                    + (f" · tooth #{tooth}" if tooth else "")
                    + (f"  <span style='color:#9AA6B8;font-size:13px;'>· {when}</span>" if when else ""),
                    unsafe_allow_html=True,
                )

    # 6) Patient instructions
    if instructions:
        st.markdown("##### 🏠 Home-care instructions")
        st.info(instructions)
