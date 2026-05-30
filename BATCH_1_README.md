# Batch 1 — Foundation

## What's in this batch
| File | Purpose |
|---|---|
| `CLAUDE.md` | Master instruction file Claude Code reads every session. **Do not delete or rename.** |
| `README.md` | Human-facing project intro |
| `pyproject.toml` | uv-managed dependency manifest |
| `.env.example` | Template for API keys + clinic identity |
| `.gitignore` | Includes PHI-safety patterns |
| `tests/test_smoke.py` | Skeleton smoke test |
| Empty folders (`core/`, `prompts/`, `agents/`, `streaming/`, `audio_pipeline/`, `exports/`, `ui/components/`, `data/samples/`, `docs/`) | Filled in by later batches |

## How to install
1. Extract this ZIP at the root of your new repo:
   ```bash
   mkdir dentascribe && cd dentascribe
   unzip ../dentascribe_01_foundation.zip
   ```
2. Install uv if you don't have it:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
3. Sync dependencies:
   ```bash
   uv sync
   ```
4. Copy env template:
   ```bash
   cp .env.example .env
   ```

## Verification
Run the batch-1 smoke test:
```bash
uv run pytest tests/test_smoke.py -v
```
Expected: **2 passed**.

Also verify Claude Code can see the master file:
```bash
head -20 CLAUDE.md
```
Should print the title `# DentaScribe — Claude Code Master Instructions`.

## What's NOT in this batch (do not panic)
- No `app.py` yet — comes in batch 6
- No schema or glossary — comes in batch 2
- No agents — comes in batch 4
- `uv sync` will install all deps, including ones not used until later batches. That's intentional so you don't re-sync 5 times.

## Next batch
**Batch 2 — Schema + dental data.** Will add `data/soap_schema.json`, `data/texas_blank_soap_template.json`, `data/visit_type_templates.json`, `data/dental_glossary.json`, `data/cdt_allow_list.json`, `data/tooth_norm.py`, `data/surface_norm.py`. After batch 2 you'll be able to import the glossary and normalize tooth numbers, but no LLM calls yet.

Reply **"next"** to me when batch 1 verification passes and you're ready for batch 2.
