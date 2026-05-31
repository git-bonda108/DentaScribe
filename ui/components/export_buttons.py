"""Export buttons — clinical SOAP downloads.

Surfaces the populated SOAP as the FIRST-CLASS deliverables:
  • DOCX  — printable, signable, formatted (provider can drop into the chart)
  • PDF   — same layout, paginated, ready for fax/email/print
And keeps:
  • Raw JSON  — audit-only, for replay/regression
  • Blank Word template — handed out to new staff for orientation

Validation parameter is passed through so the audit footer carries the
signability score.
"""
from __future__ import annotations
import json
import streamlit as st


def render_export_buttons(soap, attestation, blank_template=None,
                          validation: dict | None = None) -> None:
    """4-column export row. The first two are the clinical artifacts; the
    second two are the audit/orientation artifacts."""
    c1, c2, c3, c4 = st.columns(4)

    # 1) DOCX — the primary deliverable
    with c1:
        if soap:
            try:
                from exports.soap_docx_template import build_soap_docx
                data = build_soap_docx(soap, attestation, validation)
                st.download_button(
                    "📄  Clinical SOAP (DOCX)",
                    data=data, file_name="dentascribe_soap.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True, type="primary",
                )
            except Exception as e:
                st.button("📄  Clinical SOAP (DOCX)", disabled=True,
                          use_container_width=True, help=f"Generator failed: {e}")
        else:
            st.button("📄  Clinical SOAP (DOCX)", disabled=True, use_container_width=True)

    # 2) PDF — paginated print version
    with c2:
        if soap:
            try:
                from exports.soap_pdf_template import build_soap_pdf
                data = build_soap_pdf(soap, attestation, validation)
                st.download_button(
                    "📑  Clinical SOAP (PDF)",
                    data=data, file_name="dentascribe_soap.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
            except Exception as e:
                st.button("📑  Clinical SOAP (PDF)", disabled=True,
                          use_container_width=True, help=f"Generator failed: {e}")
        else:
            st.button("📑  Clinical SOAP (PDF)", disabled=True, use_container_width=True)

    # 3) Raw JSON — audit only
    with c3:
        if soap:
            st.download_button(
                "{ }  Raw SOAP JSON",
                data=json.dumps(soap, indent=2).encode("utf-8"),
                file_name="soap_raw.json", mime="application/json",
                use_container_width=True,
                help="Internal audit format; not a substitute for the signed DOCX/PDF.",
            )
        else:
            st.button("{ }  Raw SOAP JSON", disabled=True, use_container_width=True)

    # 4) Blank template (for new-staff orientation)
    with c4:
        try:
            from exports.soap_docx_template import build_soap_docx
            blank_data = build_soap_docx({}, None, None)
            st.download_button(
                "📋  Blank Template (DOCX)",
                data=blank_data,
                file_name="dentascribe_blank_template.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
        except Exception:
            # Fall back to the legacy JSON template if generator unavailable
            if blank_template:
                st.download_button(
                    "📋  Blank Template (JSON)",
                    data=json.dumps(blank_template, indent=2).encode("utf-8"),
                    file_name="texas_blank_soap_template.json",
                    mime="application/json",
                    use_container_width=True,
                )
            else:
                st.button("📋  Blank Template", disabled=True, use_container_width=True)
