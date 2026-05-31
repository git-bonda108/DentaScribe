"""DentaScribe Clinical SOAP — PDF generator.

Layout-mirrors `soap_docx_template.py` so the printable version is consistent
across DOCX and PDF. Built with reportlab Platypus for proper paginated flow.

Same JSON input → same sections in the same order. Different render layer.
"""
from __future__ import annotations
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle,
    KeepTogether,
)


# Match the DOCX palette
ACCENT      = colors.HexColor("#4DD4AC")
ACCENT_SOFT = colors.HexColor("#E6F8F1")
NAVY        = colors.HexColor("#0F172A")
INK         = colors.HexColor("#1B2233")
DIM         = colors.HexColor("#606B7F")
ROSE        = colors.HexColor("#C94D4D")
AMBER       = colors.HexColor("#B3802E")
HEADER_BG   = colors.HexColor("#F4F8FB")


def build_soap_pdf(soap: dict | None, attestation: dict | None = None,
                   validation: dict | None = None) -> bytes:
    """Return the SOAP note as a paginated PDF (bytes)."""
    soap = soap or {}
    buf = io.BytesIO()

    doc = BaseDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=18*mm, rightMargin=18*mm,
        topMargin=15*mm,  bottomMargin=15*mm,
    )
    frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height,
        showBoundary=0,
    )
    doc.addPageTemplates([
        PageTemplate(id="standard", frames=[frame],
                     onPage=lambda c, d: _draw_page_footer(c, d, validation)),
    ])

    styles = _build_styles()
    story: list[Any] = []

    _flow_header(story, styles, soap)
    _flow_encounter_block(story, styles, soap)
    _flow_subjective(story, styles, soap.get("subjective") or {})
    _flow_objective(story, styles, soap.get("objective") or {})
    _flow_assessment(story, styles, soap.get("assessment") or {})
    _flow_plan(story, styles, soap.get("plan") or {})
    _flow_billing(story, styles, soap.get("billing") or {})
    _flow_compliance(story, styles, soap.get("compliance") or {})
    _flow_attestation(story, styles, attestation or {}, soap)

    doc.build(story)
    return buf.getvalue()


# ---------- styles ----------

def _build_styles() -> dict:
    s = getSampleStyleSheet()
    out = {}
    out["body"] = ParagraphStyle("body", parent=s["BodyText"],
        fontName="Helvetica", fontSize=10, textColor=INK, leading=13,
        spaceAfter=2,
    )
    out["body_dim"] = ParagraphStyle("body_dim", parent=out["body"],
        textColor=DIM, fontSize=9,
    )
    out["label"] = ParagraphStyle("label", parent=out["body"],
        fontName="Helvetica-Bold", fontSize=7.5, textColor=DIM,
        leading=10, spaceAfter=1, alignment=TA_LEFT,
    )
    out["value"] = ParagraphStyle("value", parent=out["body"],
        fontSize=11, textColor=INK, leading=14, spaceAfter=0,
    )
    out["brand_title"] = ParagraphStyle("brand_title", parent=out["body"],
        fontName="Helvetica-Bold", fontSize=18, textColor=NAVY, leading=22,
    )
    out["brand_sub"] = ParagraphStyle("brand_sub", parent=out["body"],
        fontSize=9, textColor=DIM, leading=11, spaceAfter=0,
    )
    out["section_head"] = ParagraphStyle("section_head", parent=out["body"],
        fontName="Helvetica-Bold", fontSize=10, textColor=NAVY,
        leading=14, spaceBefore=6, spaceAfter=4, leftIndent=4,
    )
    out["chief_quote"] = ParagraphStyle("chief_quote", parent=out["body"],
        fontName="Helvetica-Oblique", fontSize=11, textColor=NAVY,
        leftIndent=8, leading=14, spaceAfter=4,
    )
    out["small_italic"] = ParagraphStyle("small_italic", parent=out["body_dim"],
        fontName="Helvetica-Oblique", fontSize=9,
    )
    out["bullet"] = ParagraphStyle("bullet", parent=out["body"],
        leftIndent=8, bulletIndent=2,
    )
    out["right"] = ParagraphStyle("right", parent=out["body_dim"],
        alignment=TA_RIGHT,
    )
    return out


def _safe(value: Any) -> str:
    if value in (None, "", []):
        return "—"
    if isinstance(value, list):
        return ", ".join(_safe(v) for v in value)
    if isinstance(value, dict):
        return ", ".join(f"{k}: {_safe(v)}" for k, v in value.items())
    return str(value).strip() or "—"


def _section_head(story, styles, label: str) -> None:
    """Section divider — left mint bar + label."""
    t = Table(
        [[" ", label.upper()]],
        colWidths=[2*mm, 168*mm], rowHeights=[7*mm],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), ACCENT),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",(1, 0), (1, 0), 8),
        ("FONT",       (1, 0), (1, 0), "Helvetica-Bold", 10),
        ("TEXTCOLOR",  (1, 0), (1, 0), NAVY),
        ("BOX",        (0, 0), (-1, -1), 0, colors.transparent),
    ]))
    story.append(Spacer(1, 4*mm))
    story.append(t)
    story.append(Spacer(1, 2*mm))


def _kv_pair(label: str, value: str, styles) -> Table:
    """Inline label-then-value paragraph styled tightly."""
    label_p = Paragraph(label, styles["label"])
    value_p = Paragraph(_safe(value), styles["value"])
    t = Table([[label_p, value_p]], colWidths=[35*mm, 135*mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return t


def _data_table(rows: list[list[str]], headers: list[str], col_widths_mm: list[float]) -> Table:
    """Clinical-table look: mint header + thin row dividers."""
    data = [headers] + rows
    t = Table(data, colWidths=[w*mm for w in col_widths_mm])
    style = TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0), ACCENT_SOFT),
        ("LINEBELOW",   (0, 0), (-1, 0), 0.8, ACCENT),
        ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, 0), 8),
        ("TEXTCOLOR",   (0, 0), (-1, 0), NAVY),
        ("FONTSIZE",    (0, 1), (-1, -1), 9),
        ("TEXTCOLOR",   (0, 1), (-1, -1), INK),
        ("VALIGN",      (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",(0, 0), (-1, -1), 4),
        ("TOPPADDING",  (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
        ("LINEBELOW",   (0, 1), (-1, -2), 0.3, colors.HexColor("#DDDDDD")),
    ])
    t.setStyle(style)
    return t


# ---------- flows ----------

def _flow_header(story, styles, soap: dict) -> None:
    meta = soap.get("encounter_meta") or soap.get("metadata") or {}
    loc = meta.get("practice_location") or {}
    loc_str = f"{loc.get('city', 'Dallas')}, {loc.get('state', 'TX')}"

    title_p = Paragraph("🦷&nbsp;&nbsp;<b>DentaScribe</b>", styles["brand_title"])
    sub_p   = Paragraph("Clinical SOAP Record", styles["brand_sub"])
    right_p = Paragraph(f"{loc_str}<br/>TSBDE 22 TAC §108.8 compliant", styles["right"])
    t = Table([[title_p, right_p],
                [sub_p,    ""]],
              colWidths=[110*mm, 64*mm])
    t.setStyle(TableStyle([
        ("VALIGN",      (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",(0, 0), (-1, -1), 0),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
    ]))
    story.append(t)
    # Thin mint divider
    story.append(Spacer(1, 2))
    rule = Table([[" "]], colWidths=[174*mm], rowHeights=[0.6*mm])
    rule.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), ACCENT)]))
    story.append(rule)


def _flow_encounter_block(story, styles, soap: dict) -> None:
    meta = soap.get("encounter_meta") or soap.get("metadata") or {}
    patient = meta.get("patient") or {}
    provider = meta.get("provider") or {}

    story.append(Spacer(1, 3*mm))
    def _slot(label, value):
        return [Paragraph(label.upper(), styles["label"]),
                Paragraph(_safe(value), styles["value"])]

    rows = [
        [_slot("Encounter date", meta.get("date_of_service", "—")),
         _slot("Visit type", (meta.get("visit_type") or "—").replace("_", " ")),
         _slot("Patient ID", patient.get("patient_id", "—")),
         _slot("Patient DOB", patient.get("dob", "—"))],
        [_slot("Provider", provider.get("name", "—")),
         _slot("TSBDE license", provider.get("tsbde_license", "—")),
         _slot("NPI", provider.get("npi", "—")),
         _slot("Role", provider.get("role", "—"))],
    ]

    for row in rows:
        # build a 4-col Table where each cell contains a label+value stack
        cells = []
        for slot in row:
            inner = Table([[slot[0]], [slot[1]]], colWidths=[42*mm])
            inner.setStyle(TableStyle([
                ("LEFTPADDING",  (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING",   (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
            ]))
            cells.append(inner)
        t = Table([cells], colWidths=[43*mm, 43*mm, 43*mm, 43*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND",  (0, 0), (-1, -1), HEADER_BG),
            ("VALIGN",      (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING",(0, 0), (-1, -1), 0),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
        ]))
        story.append(t)
        story.append(Spacer(1, 1*mm))


def _flow_subjective(story, styles, s: dict) -> None:
    _section_head(story, styles, "Subjective")

    cc = s.get("chief_complaint")
    if cc:
        story.append(_kv_pair("Chief complaint:", "", styles))
        story.append(Paragraph(f"&ldquo;{cc}&rdquo;", styles["chief_quote"]))
    else:
        story.append(_kv_pair("Chief complaint:", "—", styles))

    hpi = s.get("hpi") or s.get("history_of_present_illness")
    if isinstance(hpi, dict):
        story.append(_kv_pair("HPI (OPQRST):", "", styles))
        for key, label in [
            ("onset", "Onset"),
            ("provocation", "Provocation"),
            ("quality", "Quality"),
            ("region", "Region / radiation"),
            ("severity_0_10", "Severity (0–10)"),
            ("timing", "Timing"),
            ("triggers", "Triggers"),
            ("character", "Character"),
        ]:
            if key in hpi and hpi[key] not in (None, "", []):
                story.append(_kv_pair(label, _safe(hpi[key]), styles))
    elif hpi:
        story.append(_kv_pair("HPI:", _safe(hpi), styles))

    story.append(_kv_pair("Medical history",  _safe(s.get("medical_history_updates")), styles))
    story.append(_kv_pair("Medications",       _safe(s.get("medications")), styles))
    story.append(_kv_pair("Allergies",         _safe(s.get("allergies")), styles))
    if s.get("social_history"):
        story.append(_kv_pair("Social history", _safe(s.get("social_history")), styles))


def _flow_objective(story, styles, o: dict) -> None:
    _section_head(story, styles, "Objective")

    vitals = o.get("vitals") or {}
    if vitals:
        parts = []
        for k in ("bp", "hr", "rr", "temp", "spo2", "weight", "height", "bmi"):
            if k in vitals: parts.append(f"{k.upper()} {vitals[k]}")
        if parts:
            story.append(_kv_pair("Vitals:", "  ·  ".join(parts), styles))

    if o.get("extra_oral"):
        story.append(_kv_pair("Extra-oral exam:", _safe(o["extra_oral"]), styles))
    if o.get("intra_oral"):
        story.append(_kv_pair("Intra-oral exam:", _safe(o["intra_oral"]), styles))

    findings = o.get("exam_findings") or []
    if findings:
        story.append(_kv_pair("Hard-tissue findings:", "", styles))
        rows = []
        for f in findings:
            if not isinstance(f, dict): continue
            rows.append([
                _safe(f.get("tooth")),
                ",".join(f.get("surfaces") or []) or "—",
                _safe(f.get("finding")),
                _safe(f.get("severity")),
                _safe(f.get("source_span"))[:80],
            ])
        if rows:
            story.append(_data_table(rows,
                ["Tooth", "Surfaces", "Finding", "Severity", "Source"],
                [16, 24, 50, 22, 58],
            ))
            story.append(Spacer(1, 2*mm))

    perio = o.get("perio_summary") or o.get("periodontal_summary")
    if perio:
        story.append(_kv_pair("Periodontal:", _safe(perio), styles))

    rads = o.get("radiographs_taken") or []
    if rads:
        story.append(_kv_pair("Radiographs:", "", styles))
        for r in rads:
            if isinstance(r, dict):
                parts = [r.get("type", ""), f"#{r['tooth']}" if r.get("tooth") else None, r.get("findings", "")]
                story.append(Paragraph("• " + " — ".join(p for p in parts if p), styles["bullet"]))
            elif r:
                story.append(Paragraph("• " + str(r), styles["bullet"]))


def _flow_assessment(story, styles, a: dict) -> None:
    _section_head(story, styles, "Assessment")
    diagnoses = a.get("diagnoses") or a.get("primary_diagnosis")
    if isinstance(diagnoses, list) and diagnoses:
        for dx in diagnoses:
            if isinstance(dx, dict):
                tooth = dx.get("tooth")
                sev = dx.get("severity")
                tag = ""
                if tooth: tag += f"  ·  tooth #{tooth}"
                if sev:   tag += f"  ·  {sev}"
                story.append(Paragraph(f"• <b>{_safe(dx.get('diagnosis'))}</b>{tag}", styles["bullet"]))
            else:
                story.append(Paragraph(f"• {_safe(dx)}", styles["bullet"]))
    elif diagnoses:
        story.append(Paragraph(_safe(diagnoses), styles["body"]))
    else:
        story.append(Paragraph("—", styles["body_dim"]))

    differentials = a.get("differentials") or a.get("differential_diagnoses")
    if differentials:
        story.append(_kv_pair("Differential:", _safe(differentials), styles))


def _flow_plan(story, styles, p: dict) -> None:
    _section_head(story, styles, "Plan")

    procs = p.get("procedures_today") or []
    if procs:
        story.append(_kv_pair("Procedures today:", "", styles))
        rows = []
        for proc in procs:
            if not isinstance(proc, dict): continue
            rows.append([
                _safe(proc.get("tooth")),
                ",".join(proc.get("surfaces") or []) or "—",
                _safe(proc.get("procedure")),
                _safe(proc.get("anesthesia")),
                _safe(proc.get("cdt_code")),
            ])
        if rows:
            story.append(_data_table(rows,
                ["Tooth", "Surfaces", "Procedure", "Anesthesia", "CDT"],
                [16, 22, 70, 32, 30],
            ))
            story.append(Spacer(1, 2*mm))

    rxs = p.get("prescriptions") or []
    if rxs:
        story.append(_kv_pair("Prescriptions:", "", styles))
        for rx in rxs:
            if not isinstance(rx, dict): continue
            drug   = rx.get("drug", "—")
            stren  = rx.get("strength") or ""
            sig    = rx.get("sig") or ""
            qty    = rx.get("quantity")
            refill = rx.get("refills")
            ok     = rx.get("interaction_checked")
            line = f"• <b>{drug}</b> {stren}  ·  {sig}"
            if qty is not None:    line += f"  ·  Qty {qty}"
            if refill is not None: line += f"  ·  Refills {refill}"
            color = "#4DD4AC" if ok else "#B3802E"
            label = "✓ interaction checked" if ok else "⚠ interaction check pending"
            line += f'  <font color="{color}" size="8">{label}</font>'
            story.append(Paragraph(line, styles["bullet"]))

    if p.get("follow_up"):
        story.append(_kv_pair("Follow-up:", _safe(p["follow_up"]), styles))
    if p.get("patient_instructions"):
        story.append(_kv_pair("Patient instructions:", _safe(p["patient_instructions"]), styles))

    rec = p.get("recommended_future") or []
    if rec:
        story.append(_kv_pair("Recommended (future):", "", styles))
        for item in rec:
            if isinstance(item, dict):
                story.append(Paragraph(f"• {_safe(item.get('procedure'))} — {_safe(item.get('when'))}", styles["bullet"]))
            else:
                story.append(Paragraph(f"• {_safe(item)}", styles["bullet"]))


def _flow_billing(story, styles, b: dict) -> None:
    _section_head(story, styles, "Billing (CDT 2026)")
    codes = b.get("cdt_codes") or []
    if not codes:
        story.append(Paragraph("No CDT codes assigned.", styles["body_dim"]))
        return
    rows = []
    for c in codes:
        if not isinstance(c, dict): continue
        rows.append([
            _safe(c.get("code")),
            _safe(c.get("description"))[:60],
            _safe(c.get("tooth")),
            ",".join(c.get("surfaces") or []) or "—",
            _safe(c.get("rationale") or c.get("code_null_reason"))[:80],
        ])
    if rows:
        story.append(_data_table(rows,
            ["Code", "Description", "Tooth", "Surfaces", "Rationale"],
            [16, 60, 16, 22, 56],
        ))
        story.append(Spacer(1, 2*mm))
    est = b.get("estimated_total")
    if est is not None:
        s = f"${est:,.2f}" if isinstance(est, (int, float)) else _safe(est)
        story.append(_kv_pair("Estimated total:", s, styles))


def _flow_compliance(story, styles, c: dict) -> None:
    _section_head(story, styles, "Compliance — TSBDE 22 TAC §108.8")
    checklist = c.get("tsbde_checklist") or {}
    if not checklist:
        story.append(Paragraph("No compliance data computed.", styles["body_dim"]))
        return
    # Two-column layout of check items
    pairs = []
    items = list(checklist.items())
    for i in range(0, len(items), 2):
        l = items[i] if i < len(items) else None
        r = items[i+1] if i+1 < len(items) else None
        pairs.append([_fmt_compliance_cell(l), _fmt_compliance_cell(r)])
    t = Table(pairs, colWidths=[85*mm, 85*mm])
    t.setStyle(TableStyle([
        ("VALIGN",      (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",(0, 0), (-1, -1), 4),
        ("TOPPADDING",  (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 2),
    ]))
    story.append(t)


def _fmt_compliance_cell(item) -> str:
    if item is None:
        return ""
    key, val = item
    mark = "✓" if val is True else ("⚠" if val is None else "✗")
    color = "#4DD4AC" if val is True else ("#B3802E" if val is None else "#C94D4D")
    label = key.replace("_", " ").title()
    return Paragraph(
        f'<font color="{color}" size="11"><b>{mark}</b></font>&nbsp;&nbsp;<font size="10">{label}</font>',
        ParagraphStyle("compliance_item", parent=getSampleStyleSheet()["BodyText"],
                        fontSize=10, textColor=INK, leading=14),
    )


def _flow_attestation(story, styles, att: dict, soap: dict) -> None:
    _section_head(story, styles, "Attestation")
    soap_att = soap.get("attestation") or {}

    story.append(Paragraph(
        "<i>This SOAP note was drafted by DentaScribe (an AI-assisted clinical scribe) "
        "and reviewed by the signing provider before signature. The provider takes "
        "clinical responsibility for the content of this record.</i>",
        styles["small_italic"],
    ))
    story.append(Spacer(1, 3*mm))

    provider_name = att.get("provider_name") or soap_att.get("signed_by") or "—"
    signed_at     = att.get("signed_at") or soap_att.get("signed_at") or "Not signed"
    is_disclosed  = soap_att.get("ai_assisted_disclosure", True)

    left = [
        Paragraph("PROVIDER SIGNATURE", styles["label"]),
        Paragraph(provider_name, styles["value"]),
    ]
    right = [
        Paragraph("DATE / TIME", styles["label"]),
        Paragraph(signed_at, styles["value"]),
    ]
    t = Table([[left, right]], colWidths=[85*mm, 85*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, -1), HEADER_BG),
        ("VALIGN",      (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",(0, 0), (-1, -1), 6),
        ("TOPPADDING",  (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Spacer(1, 2*mm))

    disc_color = "#4DD4AC" if is_disclosed else "#C94D4D"
    disc_text  = "✓ Acknowledged" if is_disclosed else "⚠ NOT ACKNOWLEDGED"
    story.append(Paragraph(
        f'<b>AI-assisted disclosure</b>&nbsp;&nbsp;<font color="{disc_color}">{disc_text}</font>',
        styles["body_dim"],
    ))


def _draw_page_footer(canvas, doc_, validation: dict | None) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(DIM)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    score = ((validation or {}).get("signability_score"))
    score_str = f"  ·  Signability score: {score}/100" if score is not None else ""
    footer = (f"Generated {ts}{score_str}  ·  DentaScribe MVP v0.1  "
               f"·  AI-assisted; provider-signed.  ·  Page {doc_.page}")
    canvas.drawString(18*mm, 10*mm, footer)
    canvas.restoreState()


# ---------- self-test ----------

if __name__ == "__main__":
    sample = Path(__file__).resolve().parent.parent / "data" / "sample_filled_soap_emergency_endo.json"
    if sample.exists():
        soap = json.loads(sample.read_text())
        out = Path("/tmp/dentascribe_sample.pdf")
        out.write_bytes(build_soap_pdf(soap))
        print(f"✓ wrote {out} ({out.stat().st_size:,} bytes)")
    else:
        out = Path("/tmp/dentascribe_blank.pdf")
        out.write_bytes(build_soap_pdf({}))
        print(f"✓ wrote blank PDF {out} ({out.stat().st_size:,} bytes)")
