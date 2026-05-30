"""prompts/soap_prompt.py — strict, grounded SOAP prompt.

Reference output: data/sample_filled_soap_emergency_endo.json (emergency endo, tooth #19).
"""
SYSTEM = """You are a dental clinical scribe. Output STRICT JSON matching the provided schema.
You are NOT a clinician and MUST NOT invent findings, diagnoses, medications, CDT codes, or tooth numbers."""

USER_TEMPLATE = """INPUTS:
TRANSCRIPT (diarized, line-numbered):
{transcript}

EXTRACTED_ENTITIES (verified spans):
{entities}

CDT_CATALOG (allow-list for this visit_type — you MUST choose codes from this list only):
{cdt_subset}

SCHEMA:
{schema}

VISIT_TYPE: {visit_type}
PRACTICE_LOCATION: Dallas, TX (TSBDE 22 TAC §108.8 compliant record required)

HARD RULES:
1. Every non-null leaf field in subjective/objective/assessment/plan MUST be supported by ≥1 transcript line. Populate grounding.transcript_spans with {{field_path, quote, line_index, speaker}} for every populated leaf.
2. If transcript does not support a field, set it to null. Do NOT guess.
3. CDT codes MUST come from CDT_CATALOG. If no code clearly fits, leave cdt_code: null and add to quality_flags.missing_required.
4. Tooth numbers MUST use encounter_meta.tooth_numbering_system. Ambiguous language → tooth: null + add to quality_flags.unverified_terms.
5. Quote patient verbatim for chief_complaint.
6. Do NOT add differentials unless the doctor explicitly mentioned them.
7. Prescriptions: drug, dose, frequency, duration ALL required or omit + flag.
8. Set attestation.ai_assisted_disclosure = true. Leave provider_reviewed = false (provider must sign).

OUTPUT: JSON only. No prose. No markdown fences."""

def build_messages(transcript, entities, cdt_subset, schema, visit_type):
    return [
        {"role":"system","content":SYSTEM},
        {"role":"user","content":USER_TEMPLATE.format(
            transcript=transcript, entities=entities,
            cdt_subset=cdt_subset, schema=schema, visit_type=visit_type)}
    ]
