"""Streamlit Cloud entrypoint shim — defers to app.py.

Streamlit Cloud auto-discovers entrypoints in this priority order:
  1. The file named in the deploy form
  2. streamlit_app.py
  3. app.py (alphabetical fallback)

This file exists so deploys that left the entrypoint field blank still
land on the correct app. It's a one-line re-export.
"""
import runpy
runpy.run_path("app.py", run_name="__main__")
