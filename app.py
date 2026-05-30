"""DentaScribe — Streamlit entrypoint.

Three pages:
  Record  — capture/upload/paste, run swarm, sign, export.
  Audit   — per-encounter agent call log.
  Admin   — Texas retention sweep.

Run:  streamlit run app.py
"""
from __future__ import annotations
import streamlit as st

st.set_page_config(page_title="DentaScribe", page_icon="🦷",
                   layout="wide", initial_sidebar_state="expanded")

try:
    from storage.db import init_db
    init_db()
except Exception:
    pass

from ui.pages.record_page import render as render_record
from ui.pages.audit_page  import render as render_audit
from ui.pages.admin_page  import render as render_admin

PAGES = {"🩺  Record": render_record,
         "📜  Audit":  render_audit,
         "⚙️  Admin":  render_admin}

with st.sidebar:
    st.markdown("### 🦷 DentaScribe")
    st.caption("Dallas, TX • 22 TAC §108.8 aware")
    choice = st.radio("Pages", list(PAGES.keys()), label_visibility="collapsed")
    st.divider()
    st.caption("MVP build • Demo mode if no API keys")

PAGES[choice]()
