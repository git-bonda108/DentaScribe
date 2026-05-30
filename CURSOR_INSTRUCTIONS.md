# DentaScribe — Cursor Build Instructions

## What is in this handoff
| File | Purpose |
|---|---|
| `soap_schema.json` | Strict JSON Schema — the LLM output contract. |
| `texas_blank_soap_template.json` | Downloadable blank SOAP for Dallas/TX practices (TSBDE 22 TAC §108.8 compliant). |
| `visit_type_templates.json` | 6 visit-type variants with CDT allow-lists. |
| `tooth_norm.py` | Drop in `utils/`. Spoken form → Universal #1-32. |
| `surface_norm.py` | Drop in `utils/`. Spoken surface → M/D/O/I/B/F/L/P or combos. |
| `dental_glossary.json` | Use for STT keyword boosting + phonetic correction. |
| `prompts/soap_prompt.py` | Replace current SOAP prompt with this. |
| `app_v2.py` | New Streamlit UX — card-based, brand-aligned, with tooth chart + grounding. |

## Wiring order (do not skip)
1. **Schema first.** Load `soap_schema.json` and validate every LLM SOAP output with `jsonschema`. Reject + retry on schema failure (cap retries = 2).
2. **Normalize before NER.** In the pipeline, after STT + text correction, run `tooth_norm.normalize_tooth()` and `surface_norm.normalize_surface()` on every candidate token. Replace surface words on hard_tissue_findings.surface and tooth refs.
3. **Two-stage CDT.**
   - Stage 1 (deterministic): match entities + keywords to `cdt_codes_2026.json` to build a candidate list per procedure mention.
   - Stage 2 (LLM): pass ONLY the candidate list to the model. Use `prompts/soap_prompt.py`. Model emits {cdt_code, cdt_confidence, cdt_rationale}. Reject any code not in candidates.
4. **Texas template download.** Wire `app_v2.py` Templates page to serve `texas_blank_soap_template.json` as a download.
5. **Streamlit upgrade.** Replace current pages with `app_v2.py`. Bring over your real data wiring (transcript, entities, validator output). The CSS/component skeleton is production-ready.
6. **Attestation block.** Sign-off requires `provider_reviewed = true` AND a typed signature. Block PDF/DOCX export until attested.
7. **Audit trail.** On every state mutation (edit field, change CDT, sign, export), append a row to `audit_log` table with {ts, actor, action, ref_id, before, after}.

## What NOT to do
- Do NOT let the LLM invent CDT codes outside the candidate list.
- Do NOT use patient names in `patient_ref`. Use a de-identified id.
- Do NOT skip the radiograph reference field for emergency/endo visits — TSBDE flags this.
- Do NOT include differentials unless the doctor explicitly said them.
- Do NOT ship without the AI-assisted disclosure in attestation.

## Texas / Dallas-specific compliance the template enforces
- 22 TAC §108.8 record elements: ID, hx, CC + findings, dx + plan, treatment/materials/meds, consent, radiograph reference, provider sig.
- Adult record retention: **5 years** from last treatment.
- Minors: until age of majority + 5 years.
- PMP (Texas Prescription Monitoring Program) check required for Schedule II–V — `plan.prescriptions[].pmp_checked` boolean is included.
- Reference: https://texreg.sos.state.tx.us/public/readtac$ext.TacPage?sl=R&app=9&pg=1&ti=22&pt=5&ch=108&rl=8
- TSBDE rules: https://tsbde.texas.gov/laws-rules/dental-practice-act-tsbde-rules/

## 4-week priority order (recap)
- Week 1: Schema + normalizers + two-stage CDT + entity precision 85%+.
- Week 2: Tooth chart widget + inline grounding hover + validator severity grouping.
- Week 3: HIPAA basics — SQLCipher (or encrypted Postgres), audit log, optional PHI de-id pre-LLM, BAA-covered STT.
- Week 4: pyannote 3.1 diarization, OIDC auth, Postgres migration, streaming STT.
