# Batch 5 — STT, Audio Pipeline, Persistence

Adds the audio layer (Deepgram + offline demo) and the SQLite persistence layer
that the agent swarm and Streamlit UI need to run as a real product.

## Files in this batch

```
audio/
  transcript_types.py     # Transcript / TranscriptSegment dataclasses
  diarization.py          # provider/patient role assignment from speaker tags
  deepgram_stt.py         # demo / file / live streaming STT with dental keyword boost
storage/
  db.py                   # SQLite schema + encounter/transcript/SOAP/audit/attestation/export
  retention.py            # Texas 22 TAC §108.8 retention sweep (adult 5y, minor majority+5y)
tests/
  test_batch5.py          # 11 tests, no network or Deepgram key required
```

## Install

```bash
uv pip install deepgram-sdk
```
(Optional — everything in this batch works without the SDK in demo mode.)

## Environment

```bash
export DEEPGRAM_API_KEY=...        # only needed for real audio
```

## Wiring order for Claude Code

1. Call `storage.db.init_db()` once at app startup (idempotent).
2. On new encounter:
   - `create_encounter(...)` → `encounter_id`
   - get transcript via `audio.deepgram_stt.transcribe_demo|file|stream_microphone`
   - `save_transcript(encounter_id, transcript.to_dict(), source=...)`
3. Run the orchestrator from Batch 4 with the transcript text.
4. Persist results:
   - `save_soap_note(encounter_id, run.soap, validation=run.validation, signability_score=...)`
   - `append_audit_records(run.audit_records(), encounter_id=encounter_id)`
5. On provider sign-off → `save_attestation(...)`.
6. On export → `record_export(...)`.

## Verification

```bash
uv run pytest tests/test_batch5.py -v
```
Expected: **11 passed.**

After integrating with batches 1–4, total suite should be **43 passed**.

## What this enables

- Real diarized transcripts from prerecorded audio (2 client-demo recordings).
- Live mic streaming with interim + final segments for the live conversation panel.
- Every encounter, transcript, SOAP version, agent call, attestation, and export
  is persisted and queryable for the Audit Trail page.
- Texas retention is enforced via an admin-confirmed two-step purge (never auto-deletes).

## HIPAA note

SQLite is fine for MVP but is NOT HIPAA-compliant at rest by default. Before
handling real PHI:
- Encrypt the DB file (SQLCipher) or migrate to Postgres on a BAA-covered host.
- Require Deepgram BAA (available on their enterprise tier).
- Encrypt audio files at rest; never log raw transcripts to stdout in prod.
