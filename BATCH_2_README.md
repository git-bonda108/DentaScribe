# Batch 2 — Schema + Dental Data

## What's in this batch
| File | Purpose |
|---|---|
| `data/soap_schema.json` | JSON Schema (draft-07) defining a valid DentaScribe SOAP note. Every LLM output must conform. |
| `data/texas_blank_soap_template.json` | Pre-filled empty SOAP with TSBDE 22 TAC §108.8 anchor block. Use as the LLM's target shape. |
| `data/visit_type_templates.json` | Per-visit-type required fields + typical CDT codes (emergency, endo, restorative, perio, hygiene, extraction, new patient, recall). |
| `data/dental_glossary.json` | Controlled vocabulary: anatomy, conditions, procedures, anesthetics, drugs, ASR error corrections. |
| `data/cdt_allow_list.json` | 38-code curated CDT subset. Coder agent is restricted to this list. Covers both locked test cases. |
| `data/tooth_norm.py` | Universal numbering normalizer + FDI converter + colloquial phrase mapping. |
| `data/surface_norm.py` | Surface code normalizer (M/O/D/B/L/F/I) + surface counter for CDT selection. |
| `tests/test_batch2.py` | 7 tests covering all of the above. |

## How to install
Extract on top of your existing batch-1 repo:
```bash
cd dentascribe
unzip ../dentascribe_02_schema_and_data.zip
```

## Verification
```bash
uv run pytest tests/ -v
```
Expected: **9 passed** (2 from batch 1 + 7 new).

Quick interactive check:
```bash
uv run python -c "from data.tooth_norm import normalize_tooth; print(normalize_tooth('lower left first molar'))"
# -> 19
uv run python -c "from data.surface_norm import normalize_surfaces; print(normalize_surfaces('MOD'))"
# -> ['M', 'O', 'D']
```

## Design notes for Claude Code
- **Do not edit `data/cdt_allow_list.json`** to add codes the Coder agent "needs". If a code is missing, that's a feature gap and the Coder must return `null` for billing on that line. Adding hallucinated codes here defeats the entire safety model.
- **The `_texas_compliance_notes` block in the Texas template is load-bearing.** It self-documents the regulatory basis. Strip it ONLY at PMS export time, never in storage.
- **`tooth_norm` and `surface_norm` are pure functions** — no I/O, no LLM. They run on every Scribe output before the validator sees it.
- The glossary's `asr_corrections` dict is fed into the Deepgram `keywords` boost list in batch 5.

## Next batch
**Batch 3 — LLM core + validator.** Adds `core/llm_client.py` (single Claude wrapper), `core/glossary_loader.py` (vocab injector), `core/soap_validator.py` (4-layer validator: structural, grounding, CDT allow-list, Texas soft rules), and `prompts/soap_prompt.py` + `prompts/clinical_prompts.py`.

After batch 3 you'll be able to:
- Call Claude through one canonical client
- Validate any candidate SOAP JSON
- See exactly why a candidate fails (structural / grounding / CDT / Texas)

Reply **"next"** when batch 2 verification passes.
