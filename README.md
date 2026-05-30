# DentaScribe

AI dental scribe MVP for the Dallas, Texas market. Built for licensed dentists; not an autonomous diagnostic tool.

## Quick start

```bash
# 1. Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Sync dependencies
uv sync

# 3. Copy env template and fill in keys (or use sidebar BYO key in the app)
cp .env.example .env

# 4. Run the app (available after batch 6)
uv run streamlit run app.py
```

## Modes
- **Demo mode** — no keys required. Plays scripted transcripts through the full pipeline. Use for sales demos.
- **Live mode** — requires `ANTHROPIC_API_KEY` (and `DEEPGRAM_API_KEY` for mic). Real STT + real Claude.

## What's in the box
- 5-agent swarm: Scribe, Coder, SecondOpinion, Compliance, Validator
- Claude Sonnet 4.5 for clinical reasoning (Scribe + Coder)
- Deterministic rule engines for everything else (no hallucination surface)
- Texas TSBDE 22 TAC §108.8 compliance checklist baked into every note
- PDF / DOCX / JSON export

## Build status
This repo is being assembled in 6 batches. See `CLAUDE.md` for the master plan.
- [x] Batch 1 — Foundation
- [ ] Batch 2 — Schema + dental data
- [ ] Batch 3 — LLM core + validator
- [ ] Batch 4 — Agent swarm
- [ ] Batch 5 — Audio + export
- [ ] Batch 6 — UI + demo

## License & disclaimers
For pilot/evaluation use only. Not FDA-cleared. Not a substitute for clinical judgment. Provider must review and sign every note.
