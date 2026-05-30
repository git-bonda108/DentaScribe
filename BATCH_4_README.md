# Batch 4 — Agent Swarm + Orchestrator

## What's in this batch
| File | Purpose |
|---|---|
| `agents/base.py` | `BaseAgent` contract + `AgentResult` (status, message, output, LLM call audit, duration). |
| `agents/clinical_agents.py` | **ScribeAgent** (transcript → SOAP JSON) and **CoderAgent** (SOAP → CDT codes). Includes demo fixtures for both locked test cases and post-processors: tooth/surface normalization + composite-surface arithmetic (D2391→D2392/D2393/D2394). |
| `agents/compliance_agent.py` | **ComplianceAgent** — fully deterministic, no LLM. Fills the TSBDE checklist by inspecting the SOAP + clinic env. Knows 22 TAC §108.8 + HB 2174 PMP rule. |
| `agents/second_opinion_agent.py` | **SecondOpinionAgent** — the differentiator. Bounded peer-review across 6 categories with dismissible flags. |
| `agents/swarm.py` | **Orchestrator** + `SwarmRun`. Pipeline: Scribe → Compliance → Coder → Validator → Second-Opinion. Both blocking `run()` and `run_streaming()` iterator for the live UI panel. |
| `tests/test_batch4.py` | 8 tests: end-to-end demo for both cases, CDT correctness, composite-surface upgrade, validator score, compliance checklist, drug-interaction flag, streaming order, audit records. |

## How to install
```bash
cd dentascribe
unzip ../dentascribe_04_agents.zip
uv run pytest tests/ -v
```
Expected: **32 passed** (2 + 7 + 15 + 8).

Quick interactive smoke test:
```bash
uv run python -c "
from core.llm_client import LLMClient
from agents.swarm import Orchestrator
orch = Orchestrator(LLMClient(demo=True))
run = orch.run(transcript='Patient has pain on tooth nineteen.', visit_type='emergency',
               metadata={'date_of_service':'2026-05-31','provider':{'name':'Dr','tsbde_license':'X'},'patient':{'patient_id':'P','dob':'1990-01-01','consent_on_file':True}},
               case_id='emergency_endo')
print('Status:', run.status())
print('CDT:', [c['code'] for c in run.soap['billing']['cdt_codes']])
print('Score:', run.validation['signability_score'])
"
```

## Design notes for Claude Code

### Pipeline order is load-bearing
1. **Scribe first.** Produces grounded SOAP from transcript.
2. **Compliance second** (before Coder). The TSBDE checklist data ends up inside the SOAP and informs which fields the validator is going to police.
3. **Coder third.** Operates on the SOAP plan, never the raw transcript — this is how we keep the CDT layer dependent on documented procedures.
4. **Validator fourth.** Scores the result. Errors block sign-off.
5. **Second-Opinion last.** Sees everything: SOAP, transcript, codes. It can dismissibly flag but cannot mutate.

### Why Compliance is deterministic
The TSBDE checklist is a list of boolean facts about the chart. Asking an LLM to "check the boxes" is asking for hallucinations and audit-trail problems. We compute every box from data we already have. The provider attestation block (added in batch 6) is where the human signs off.

### Surface-code refinement after Coder
The Coder is allowed to emit `D2391` (single-surface composite) for any composite. After it returns, `_refine_composite_codes()` uses `count_surfaces()` from batch 2 to upgrade based on the actual `surfaces` array on the procedure. The recall test case proves this end-to-end (MO → 2 surfaces → D2392).

### Demo mode is a first-class citizen
Both `ScribeAgent` and `CoderAgent` pass `demo_response=` to the LLM client when `llm.demo` is true. This is why all 32 tests pass without an API key. The two case_ids — `"emergency_endo"` and `"recall_hygiene"` — are the two locked sales-demo flows.

### Audit trail
`SwarmRun.audit_records()` returns one row per agent with model, prompt-hash, tokens, latency, and status. Batch 5 wires this into SQLite; batch 6 surfaces it on the audit-trail page.

## What's intentionally NOT in this batch
- No STT (batch 5: Deepgram + diarization + ASR keyword boost).
- No persistence (batch 5: SQLite encounters + audit log + retention policy).
- No UI (batch 6: branded Streamlit, live swarm panel, attestation block, exports).

## Next batch
**Batch 5 — STT, audio pipeline, persistence.** Adds `audio/deepgram_stt.py` (live streaming + keyword boost from `asr_keywords()`), `audio/diarization.py` (provider vs patient turn assignment), `storage/db.py` (SQLite schema for encounters, transcripts, soap_notes, audit_log, attestations), and `storage/retention.py` (Texas 5-year / minor+5 enforcement).

Reply **"next"** when 32 tests pass.
