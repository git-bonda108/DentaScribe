# CLAUDE.md — context for Claude Code sessions

This file is read automatically when Claude Code starts in this repo. Keep it accurate; if you change something fundamental, update this file in the same commit.

---

## What this is

**DentaScribe** is an MVP AI dental scribe. A doctor and patient have a conversation; DentaScribe transcribes, labels speakers, extracts dental entities, drafts a SOAP note, and suggests CDT 2026 procedure codes. Streamlit UI, runs in a phone browser.

It's the clinical-side counterpart to the front-desk **Dentsi** project (https://github.com/git-bonda108/Dentsi) by the same author. Reuse the brand and palette; don't merge the repos.

## Tech & architecture

- Python 3.10+, Streamlit, SQLite, ReportLab (PDF), python-docx, optional `streamlit-mic-recorder` for browser mic.
- LLM: Anthropic Claude primary, OpenAI fallback. Unified client in `utils/llm.py`. Demo mode (no keys) is supported and must keep working.
- STT: OpenAI Whisper default. Deepgram Nova-3 Medical via `STT_PROVIDER=deepgram`.
- **Agent swarm** in `agents/`. Pipeline is deterministic and sequential, not a graph:

  `Transcription → Diarization → DentalNER → SoapNote → CdtCoder → Validator`

  All agents mutate a shared `SwarmState` (defined in `core/state.py`). Each step appends to `state.agent_trace` — that's user-visible in the UI, treat it as load-bearing.

## Hard rules (do not break without an explicit ask)

1. **Anti-hallucination is the product.** Three layers exist; keep all three:
   - LLM prompts say "use only facts in the transcript."
   - `DentalNERAgent` drops any LLM-returned entity whose `span` is not found verbatim in the transcript.
   - `ValidatorAgent` flags note terms not present in the transcript and surfaces them as Unverified terms.
   If you add a new agent that produces text, it must be subject to the validator's check.

2. **CDT codes are constrained.** The LLM re-ranks and rationalizes; it never invents codes. The candidate list always comes from `data/cdt_codes_2026.json` via `KEYWORD_MAP` in `agents/cdt_coder.py`. To add coverage, extend the JSON and the keyword map together.

3. **Demo mode must keep working end-to-end.** When no LLM key is set, every agent has a deterministic fallback. The three fixtures in `utils/fixtures.py` are the regression suite — if any of them stops producing a complete SOAP note, that's a bug.

4. **No PHI logging.** `state.agent_trace` is fine (counts, lengths, durations). Don't log transcript or patient name contents.

5. **CDT and dental terminology data come from ADA / cited sources.** Don't fabricate codes. New CDT additions belong in `data/cdt_codes_2026.json` with a comment citing the source. The bundled subset is representative — production must license the full ADA catalog.

## Conventions

- **Adding an agent**: subclass `agents.base.Agent`, implement `run(state) -> state`, register it in `agents/orchestrator.py`'s `self.pipeline` list at the right position. Use `state.log(self.name, "...")` liberally.
- **Adding an exporter**: new file in `exporters/`, function takes a `state: dict` and returns `bytes`. Wire into the Export tab in `app.py`.
- **Adding a UI page**: new function in `app.py` returning nothing; register in the sidebar `st.radio` and the bottom router.
- **Color palette**: never hard-code hex codes. Import from `ui.theme.COLORS`. PDF/DOCX use the same hex values — keep them in sync.
- **LLM prompts** live next to the agent that uses them. Keep them short, with `Return strict JSON` for structured outputs. Use `LLMClient.complete_json()`, which already handles fenced code blocks.

## Where things live

```
app.py                  Streamlit entry — UI only, no business logic
core/config.py          .env → Config dataclass
core/state.py           SwarmState + nested dataclasses (SoapNote, etc.)
core/db.py              SQLite store (consultations table; payload as JSON)
agents/*.py             One agent per file. Strict pipeline contract.
data/cdt_codes_2026.json    CDT subset. Has _meta with provenance.
data/dental_terms.json      Terminology bank (teeth 1-32 + lexicons).
exporters/pdf_export.py     ReportLab — clinical-grade PDF
exporters/docx_export.py    python-docx — clinical-grade Word
ui/theme.py             Design tokens (COLORS, SPACING, RADIUS)
ui/styles.py            Custom CSS injected once at boot
ui/components.py        hero, card, metric_card, badge, speaker_bubble, soap_block, cdt_chip
utils/llm.py            Anthropic + OpenAI unified client. Resolution: anthropic → openai → demo.
utils/fixtures.py       Three curated dental transcripts. Regression suite.
.streamlit/config.toml  Theme tokens for Streamlit chrome
```

## Running & testing

```bash
pip install -r requirements.txt
cp .env.example .env       # optional — demo mode runs without keys
streamlit run app.py
```

End-to-end smoke test (no keys needed):

```python
import os; os.environ["DENTASCRIBE_DEMO_MODE"] = "true"
from core.config import load_config
from core.state import SwarmState
from agents.orchestrator import Orchestrator
from utils.fixtures import DEMO_TRANSCRIPTS
swarm = Orchestrator(load_config())
for s in DEMO_TRANSCRIPTS:
    st = SwarmState(patient_name=s["patient_name"], doctor_name=s["doctor_name"])
    st.raw_transcript = s["transcript"]
    st = swarm.run(st)
    assert st.qa.completeness_score >= 0.8, s["patient_name"]
    assert len(st.cdt_codes) >= 1
print("OK")
```

If you change any agent, run this before committing.

## Known follow-ups (in priority order)

1. **Real diarization.** Replace prefix-parse / LLM attribution with `pyannote 3.1` segmentation, then slice audio for Whisper per-speaker. Wire into `agents/diarization.py` behind a feature flag.
2. **Auth.** Streamlit Community Cloud auth or a thin OIDC layer. Doctor / hygienist / admin roles. Wire into the sidebar.
3. **Postgres.** Swap `core/db.py` to SQLAlchemy + Postgres. Keep the same `ConsultationStore` interface so the UI doesn't change.
4. **Streaming transcription.** Whisper isn't streaming-native; either chunk audio in `streamlit-mic-recorder` (~5s windows) or switch the live tab to Deepgram WebSocket. Doc the trade-off in the UI.
5. **Tooth charting widget.** A visual 1-32 dental chart (SVG) that highlights teeth named in the transcript. Live on the Consultation page above the Transcript tab.
6. **Full ADA CDT 2026 license + embedding search.** Replace `KEYWORD_MAP` with an embedding index over the full code catalog. Keep deterministic keyword fallback as a safety net.
7. **HIPAA path.** Encryption at rest, audit log on every state mutation, BAA-covered STT (Deepgram Nova-3 Medical), and a configurable de-identification pass before any LLM call.

## Things that are intentional and look like bugs

- The Transcription agent's `run()` is a near no-op. That's deliberate: audio→text happens out of band via `Orchestrator.transcribe_audio(wav_bytes)` *before* the pipeline executes. The agent only logs / validates the resulting transcript. Don't move STT into the pipeline; it would force every retry to re-bill the STT call.
- The Validator's `SAFE_BOILERPLATE` set contains scaffolding words used by the *template fallback* SoapNote generator. These are not domain terms — adding more here is fine if you find new false positives in demo mode.
- `data/cdt_codes_2026.json` is intentionally a subset, not the full ADA catalog. The `_meta.note` field documents this. Don't replace with a fabricated full list.

## Brand / palette

Anchored on Dentsi's `#1E2327` text color. Primary teal `#0EA5A4`, mint `#6FE4D6`, navy `#0B2A4A`, amber `#F59E0B`, red `#DC2626`, green `#16A34A`. Background `#F7FBFC`, surface `#FFFFFF`. All in `ui/theme.py`.

---

**When in doubt, read the README.md.** It's the user-facing complement to this file.
