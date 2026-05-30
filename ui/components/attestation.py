"""Provider attestation block (expander-based "modal")."""
from __future__ import annotations
import streamlit as st
from datetime import datetime, timezone


DEFAULT_ATTESTATION_TEXT = (
    "I, the undersigned licensed dental provider, have reviewed the above SOAP "
    "note in full. I attest that it accurately reflects the clinical encounter "
    "and my professional judgment. AI assistance was used to draft this note; "
    "I take full clinical and legal responsibility for its contents."
)


def render_attestation_block(default_provider: str = "", default_license: str = "",
                             can_sign: bool = False, lock_reason=None):
    with st.expander("✍️  Provider sign-off", expanded=False):
        if not can_sign:
            st.warning(lock_reason or "Note is not yet signable. Resolve validator errors first.")
        c1, c2 = st.columns([2, 1])
        with c1:
            name = st.text_input("Provider name", value=default_provider, key="att_name")
        with c2:
            lic = st.text_input("TX License #", value=default_license, key="att_lic")
        text = st.text_area("Attestation statement", value=DEFAULT_ATTESTATION_TEXT,
                            height=120, key="att_text")
        sign_clicked = st.button("Sign and lock note", type="primary",
                                 disabled=not can_sign, key="att_sign_btn")
        if sign_clicked and name and lic:
            return {
                "provider_name": name, "provider_license": lic, "signed_text": text,
                "signed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
    return None
