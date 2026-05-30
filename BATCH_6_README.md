# Batch 6 — Streamlit Showroom UI

Demo-able front-end. Drops onto batches 1–5 with no edits to them.

## Files

```
app.py                                # Streamlit entrypoint, 3 pages
ui/theme.py                           # brand tokens + global CSS
ui/components/
  transcript_panel.py                 # final + interim bubbles, quote highlight
  agent_swarm.py                      # 7 named agents w/ status pills
  tooth_chart.py                      # SVG universal-numbering chart
  review_panel.py                     # Second-Opinion findings, color-coded
  validator_panel.py                  # signability chip + grouped issues
  attestation.py                      # provider sign-off block
  export_buttons.py                   # populated JSON+DOCX + blank template
ui/pages/
  record_page.py                      # main flow
  audit_page.py                       # per-encounter agent audit log
  admin_page.py                       # 22 TAC §108.8 retention sweep
tests/test_batch6.py                  # 5 smoke tests
```

## Install + run

```bash
uv pip install streamlit python-docx
streamlit run app.py
```

## What Claude Code should wire

1. **Orchestrator hookup** — `ui/pages/record_page.py:_run_orchestrator()` imports
   `agents.orchestrator.run_pipeline` from Batch 4. If the signature differs,
   adapt only that one function — the rest of the UI consumes a plain dict:
   `{soap, validation, review, audit_records}`.
2. **Persistence on sign** — inside `if att:` in `record_page.py`, call
   `storage.db.save_attestation(...)` with the `encounter_id` and `soap_id`
   returned earlier by `save_soap_note`.
3. **Live mic** — wire `streamlit-mic-recorder` or `streamlit-webrtc` into the
   "Live mic" branch and feed bytes into `audio.deepgram_stt.stream_microphone`.
4. **Audio file upload** — call `audio.deepgram_stt.transcribe_file()` on the
   uploaded path; persist via `storage.db.save_transcript(..., source="deepgram_file")`.

## Verification

```bash
uv run pytest tests/test_batch6.py -v
```
Expected: **5 passed.**

Full suite after batches 1–6: **48 passed**.

## What this batch delivers visually

- Branded **DentaScribe / Dallas, TX** hero on every page.
- **Animated 7-agent swarm** — pulse on running, green on done, red on fail.
- **Conversation panel** with provider/patient bubble colors + interim-grey for live.
- **Tooth chart** with referenced teeth lit up in mint.
- **Second-Opinion panel** color-coded by severity.
- **Validator panel** with signability score chip and grouped errors/warnings.
- **Attestation block** locked until score ≥ 85 and zero errors.
- **Export row** with populated JSON, populated DOCX, and blank Texas template.
- **Audit page** with per-encounter call log.
- **Admin page** with two-step Texas retention purge.
