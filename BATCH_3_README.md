# Batch 3 — LLM Core + Validator + Prompts

## What's in this batch
| File | Purpose |
|---|---|
| `core/llm_client.py` | Single canonical Claude wrapper. Demo mode + audit records + JSON-retry. **Every Claude call goes through this.** |
| `core/glossary_loader.py` | Cached loaders for glossary, CDT, visit templates, blank template, schema. Plus `glossary_compact()`, `cdt_compact()`, `asr_keywords()` for prompt injection / Deepgram boost. |
| `core/soap_validator.py` | Four-layer validator: structural (jsonschema) + grounding + CDT allow-list + Texas TSBDE soft rules. Returns `ValidationReport` with `signability_score` 0–100. |
| `prompts/soap_prompt.py` | Scribe agent system + user prompt builders. |
| `prompts/clinical_prompts.py` | Coder agent + Second-Opinion agent system + user prompt builders. |
| `tests/test_batch3.py` | 15 tests covering demo mode, loaders, prompt builds, validator (valid/hallucinated CDT/ungrounded/missing license/score drop). |

## How to install
```bash
cd dentascribe
unzip ../dentascribe_03_llm_core.zip
uv sync   # in case anthropic / jsonschema weren't fetched yet
```

## Verification
```bash
uv run pytest tests/ -v
```
Expected: **24 passed** (2 batch 1 + 7 batch 2 + 15 batch 3).

Quick interactive check (no API key needed):
```bash
uv run python -c "from prompts.soap_prompt import build_scribe_system_prompt; print(build_scribe_system_prompt()[:500])"
uv run python -c "from core.soap_validator import SOAPValidator; print(SOAPValidator().validate({}, '').as_dict())"
```

## Design notes for Claude Code

### LLM client guarantees
- **Demo mode is first-class.** If `ANTHROPIC_API_KEY` is missing, every agent should still run by passing `demo_response=` to the call. This is how the Streamlit UI in batch 6 stays runnable for sales demos without keys.
- **Audit record on every call.** `LLMCall` carries agent name, model, prompt hash, tokens, latency, status. The orchestrator in batch 4 persists this to the SQLite audit log.
- **JSON retry is built-in.** `complete_json()` retries once with temperature 0 if the first response isn't valid JSON. After that it returns `None` and the caller decides.

### Validator philosophy
- **Structural errors are hard fails.** Schema violations block sign-off.
- **Hallucinated CDT codes are hard fails.** This is the single biggest liability surface — keep it red.
- **Ungrounded clinical claims are hard fails.** Every exam finding, diagnosis, procedure, and CDT code must quote the transcript verbatim (normalized whitespace/punctuation).
- **Texas rules are mostly warnings.** A missing TSBDE license is an error; missing consent is a warning the provider must dismiss. This matches real workflow — providers fix on review.

### Prompt design choices
- **Schema injected verbatim** into the Scribe prompt. No "describe the shape in English" — the literal blank template is the target.
- **CDT list injected verbatim** into the Coder prompt with a hard "this is the COMPLETE SET" line.
- **Second-Opinion is bounded to 6 categories** (missed dx, missing docs, drug interactions, billing gaps, compliance, patient safety). Prevents drift into general medical advice.

## Next batch
**Batch 4 — Agent swarm.** Adds `agents/swarm.py` (orchestrator), `agents/clinical_agents.py` (Scribe + Coder runners), `agents/second_opinion_agent.py`, `agents/compliance_agent.py` (deterministic TSBDE checklist filler). The swarm produces an end-to-end SOAP from a transcript and runs in both Demo and Live modes.

Reply **"next"** when 24 tests pass.
