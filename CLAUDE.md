# DentaScribe — Claude Code Master Instructions

You are working on **DentaScribe**, an AI dental scribe MVP for the **Dallas, Texas** market.
Read this file at the start of every session.

## Product objective
Trustworthy, auditable AI scribe that takes a dentist–patient conversation and produces:
1. A structured **SOAP note** (JSON conforming to `soap_schema.json`)
2. **CDT billing codes** drawn strictly from `data/cdt_allow_list.json`
3. A **second-opinion** review flagging missed dx, drug interactions, billing gaps
4. A **TSBDE 22 TAC §108.8** compliance checklist
5. Exportable PDF / DOCX / JSON for the patient chart

This is **not** an autonomous diagnostic tool. Every output must be reviewed and signed by a licensed dentist.

## Non-negotiable rules
- **No hallucinated CDT codes.** Coder agent must only return codes present in `data/cdt_allow_list.json`. The validator double-checks.
- **Grounded SOAP.** Every clinical claim in the SOAP note must include a `source_span` quoting the transcript. The validator rejects ungrounded claims above severity threshold.
- **Texas compliance.** Patient identifiers, provider license #, date of service, and informed-consent flag are required fields. See `texas_blank_soap_template.json`.
- **No PHI in logs.** Never write transcripts, patient names, or chart contents to stdout, log files, or error messages outside the SQLite chart store.
- **BYO API key.** Never hardcode keys. Read `ANTHROPIC_API_KEY` and `DEEPGRAM_API_KEY` from environment or Streamlit sidebar input.

## Tech stack (fixed — do not swap)
- Python 3.11+
- **uv** for dependency management (not pip, not poetry)
- Streamlit for UI
- Anthropic SDK (`anthropic>=0.40`) — Claude Sonnet 4.5 default (model id `claude-sonnet-4-5`)
- Deepgram SDK for live STT
- SQLite for MVP persistence (Postgres migration later)
- `jsonschema` for schema validation
- `reportlab` + `python-docx` for exports

## Repo layout (target — will be filled by batches 2–6)
```
dentascribe/
├── CLAUDE.md                      ← you are here
├── README.md
├── pyproject.toml                 ← uv-managed
├── .env.example
├── .gitignore
├── app.py                         ← Streamlit entrypoint (batch 6)
├── core/
│   ├── llm_client.py              ← Claude wrapper (batch 3)
│   ├── glossary_loader.py         ← controlled vocab injector (batch 3)
│   └── soap_validator.py          ← 4-layer validator (batch 3)
├── prompts/
│   ├── soap_prompt.py             ← scribe system prompt (batch 3)
│   └── clinical_prompts.py        ← coder + second-opinion prompts (batch 3)
├── agents/
│   ├── swarm.py                   ← orchestrator (batch 4)
│   ├── clinical_agents.py         ← Scribe + Coder (batch 4)
│   ├── second_opinion_agent.py    ← rule-based reviewer (batch 4)
│   └── compliance_agent.py        ← TSBDE checklist (batch 4)
├── streaming/
│   └── deepgram_stream.py         ← live mic (batch 5)
├── audio_pipeline/
│   └── replay.py                  ← demo-mode scripted player (batch 5)
├── exports/
│   └── soap_exporter.py           ← PDF/DOCX/JSON writers (batch 5)
├── ui/
│   └── components/
│       └── widgets.py             ← tooth chart, agent rail, KPI strip (batch 6)
├── data/
│   ├── soap_schema.json           ← (batch 2)
│   ├── texas_blank_soap_template.json   ← (batch 2)
│   ├── visit_type_templates.json  ← (batch 2)
│   ├── dental_glossary.json       ← (batch 2)
│   ├── cdt_allow_list.json        ← (batch 2)
│   ├── tooth_norm.py              ← (batch 2)
│   ├── surface_norm.py            ← (batch 2)
│   └── samples/
│       ├── case1_emergency_endo_tooth19.txt   ← (batch 5)
│       └── case2_occlusal_composite_tooth30.txt ← (batch 5)
├── tests/
│   └── test_smoke.py              ← grows each batch
└── docs/
    ├── DEMO_SCRIPT.md             ← (batch 6)
    └── CLAUDE_CODE_HANDOFF.md     ← (batch 6)
```

## Coding conventions
- Type hints everywhere. Use `from __future__ import annotations`.
- Pydantic v2 for any in-memory model that isn't a JSON-schema-validated dict.
- All Claude calls go through `core/llm_client.py` — never call `anthropic.Anthropic()` directly elsewhere.
- All prompts live in `prompts/` — never inline a system prompt in agent code.
- Every agent returns a `dict` with at least: `{"agent": str, "status": "ok"|"error", "output": ..., "trace": [...]}`.

## How to verify each batch
Each batch ZIP contains a `BATCH_N_README.md` with:
1. Files added
2. Where to put them (always: extract at repo root)
3. A verification command (e.g. `uv run python -c "import core.llm_client"`)
Do not advance to batch N+1 until batch N verification passes.

## Current batch
**Batch 1 — Foundation.** This batch establishes the repo skeleton, `pyproject.toml`, env files, and this `CLAUDE.md`. No runtime code yet.

## Two locked test cases (referenced throughout)
- **Case 1**: Emergency visit. Tooth #19 (lower-left first molar). Irreversible pulpitis. Expected procedures: D0140 (limited exam), D0220 (PA radiograph), D3330 (endo molar) recommended, D9230 (N2O) optional. Patient on lisinopril → ibuprofen interaction flag.
- **Case 2**: Routine restorative. Tooth #30 (lower-right first molar), occlusal caries. Expected: D0120 (periodic exam), D0274 (bitewings-four), D2391 (resin one-surface posterior).
