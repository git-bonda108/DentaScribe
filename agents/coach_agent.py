"""Dental Coach Agent — live, tool-using clinical advisor.

Watches the rolling transcript during a recording and surfaces grounded,
actionable recommendations to the doctor BEFORE they miss something.

This is NOT a diagnostic agent. It's a *workflow* agent:
  • Safety — drug interactions, allergy contraindications, vitals concerns
  • History gaps — required questions not yet asked for this visit type
  • Differential prompts — diagnostic tests to consider given symptoms
  • Documentation — TSBDE 22 TAC §108.8 anchor fields still missing
  • Billing — likely CDT codes accumulating from what's been documented

Architecture:
  - Bounded prompt; ≤3 recs per call; every rec grounded in either a
    transcript quote OR a tool-returned fact.
  - Six pure-Python tools (no LLM-in-tool recursion) over our existing
    corpus + CDT allow-list + glossary watch-lists.
  - The agent is invoked from the live recording page on speaker-turn
    change OR after a 15-second silence ceiling — debounced server-side
    so a runaway monologue doesn't spam Claude.
  - Dedupe cache — same recommendation never fires twice for the same
    encounter.
"""
from __future__ import annotations
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from core.glossary_loader import (
    load_glossary, load_cdt_allow_list, load_visit_templates,
)


# ===========================================================================
# Recommendation shape
# ===========================================================================

CATEGORIES = ("safety", "history_gap", "differential", "documentation", "billing")
SEVERITIES = ("high", "medium", "low")


@dataclass
class Recommendation:
    """One coach recommendation. Severity-colored card in the UI."""
    category: str            # one of CATEGORIES
    severity: str            # one of SEVERITIES
    message: str             # 1-line imperative
    suggested_action: str    # one specific next step
    evidence_quote: str = "" # verbatim transcript span or tool output
    tooth_ref: str | None = None
    tool_used: str | None = None
    fingerprint: str = ""    # for dedupe across calls

    def __post_init__(self):
        if not self.fingerprint:
            h = hashlib.md5(
                f"{self.category}|{self.message[:80].lower()}|{self.tooth_ref or ''}"
                .encode()
            ).hexdigest()[:12]
            self.fingerprint = h

    def to_dict(self) -> dict:
        return {
            "category":       self.category,
            "severity":       self.severity,
            "message":        self.message,
            "suggested_action": self.suggested_action,
            "evidence_quote": self.evidence_quote,
            "tooth_ref":      self.tooth_ref,
            "tool_used":      self.tool_used,
            "fingerprint":    self.fingerprint,
        }


# ===========================================================================
# Tools — the six deterministic functions Claude may call
# ===========================================================================

class CoachTools:
    """Deterministic tools. Pure Python; no LLM round-trips inside."""

    def __init__(self) -> None:
        self._glossary = load_glossary()
        self._cdt = load_cdt_allow_list()
        self._visits = load_visit_templates()
        self._cdt_by_code = {c["code"]: c for c in self._cdt.get("codes", [])}

    # --- 1) Drug interaction check ----------------------------------------
    # Common patient-side meds the dentist won't be prescribing but needs to
    # check against. Maps generic name → class (matched against glossary's
    # drugs_common watch lists).
    _PATIENT_DRUG_CLASS = {
        # ACE inhibitors (NSAID interaction)
        "lisinopril": "ace_inhibitor", "enalapril": "ace_inhibitor",
        "ramipril": "ace_inhibitor", "benazepril": "ace_inhibitor",
        "captopril": "ace_inhibitor",
        # Anticoagulants
        "warfarin": "anticoagulant", "coumadin": "anticoagulant",
        "apixaban": "anticoagulant", "eliquis": "anticoagulant",
        "rivaroxaban": "anticoagulant", "xarelto": "anticoagulant",
        "dabigatran": "anticoagulant", "pradaxa": "anticoagulant",
        "heparin": "anticoagulant", "clopidogrel": "anticoagulant",
        "plavix": "anticoagulant", "aspirin": "anticoagulant",
        # Mood stabilizers
        "lithium": "lithium",
        # Hepatic risk
        "alcohol": "hepatic_impairment", "methotrexate": "hepatic_impairment",
        # Penicillin family alerts
        "amoxicillin": "penicillin", "ampicillin": "penicillin",
        "augmentin": "penicillin",
    }

    def _drug_class(self, name: str) -> str | None:
        """Return drug class for either a glossary entry or a known patient drug."""
        n = (name or "").lower().strip()
        if not n:
            return None
        gloss = self._glossary.get("drugs_common", {}) or {}
        if n in gloss:
            return gloss[n].get("class")
        for k, klass in self._PATIENT_DRUG_CLASS.items():
            if k in n or n in k:
                return klass
        return None

    def check_drug_interaction(self, drug1: str, drug2: str) -> dict:
        """Returns {has_interaction, severity, mechanism, alternatives}.

        Strategy: each drug resolves to a class; we check whether either
        drug's watch list (from glossary.drugs_common) names the other's
        class. Catches the common case "ibuprofen + lisinopril" where
        lisinopril isn't in our prescribing list but IS an ACE inhibitor.
        """
        d1 = (drug1 or "").lower().strip()
        d2 = (drug2 or "").lower().strip()
        if not (d1 and d2):
            return {"has_interaction": False, "severity": "low",
                    "mechanism": "", "alternatives": []}

        gloss = self._glossary.get("drugs_common", {}) or {}
        c1 = self._drug_class(d1)
        c2 = self._drug_class(d2)

        def _watch_includes(primary_low: str, target_class: str | None,
                              target_name: str) -> tuple[bool, dict]:
            info = gloss.get(primary_low) or {}
            watch = [w.lower() for w in (info.get("watch") or [])]
            for w in watch:
                if (target_class and w == target_class.lower()) \
                        or w in target_name or target_name in w:
                    return True, info
            return False, info

        # Check both directions
        for primary, other_name, other_class in ((d1, d2, c2), (d2, d1, c1)):
            primary_low = primary
            # If primary isn't in our prescribing glossary, try its class
            if primary_low not in gloss and self._drug_class(primary_low):
                # primary is patient-side med; flip roles
                continue
            hit, info = _watch_includes(primary_low, other_class, other_name)
            if hit:
                return {
                    "has_interaction": True,
                    "severity": "medium",
                    "mechanism": (f"{primary} ({info.get('class','?')}) interacts "
                                   f"with {other_name} ({other_class or 'unknown class'})"),
                    "alternatives": info.get("alternatives") or [],
                    "source": "glossary.drugs_common",
                }
        return {"has_interaction": False, "severity": "low",
                "mechanism": "", "alternatives": []}

    # --- 2) Look up a dental term -----------------------------------------
    def lookup_dental_term(self, term: str) -> dict:
        """Returns the dictionary definition + category if in glossary."""
        t = (term or "").lower().strip()
        for cat in ("anatomy", "conditions", "procedures", "materials", "anesthetics"):
            d = self._glossary.get(cat, {}) or {}
            for k, v in d.items():
                if k.lower() == t or t in k.lower():
                    return {"found": True, "term": k, "definition": v,
                            "category": cat}
        return {"found": False, "term": term, "definition": None, "category": None}

    # --- 3) CDT candidates for a procedure --------------------------------
    def cdt_candidates_for(self, procedure_text: str) -> list[dict]:
        """Token-overlap lookup against the allow-list. Returns the top 3
        likely CDT codes with descriptions."""
        text = (procedure_text or "").lower()
        if not text.strip():
            return []
        words = set(re.findall(r"[a-z]{3,}", text))
        scored: list[tuple[int, dict]] = []
        for c in self._cdt.get("codes", []):
            desc = c.get("description", "").lower()
            desc_words = set(re.findall(r"[a-z]{3,}", desc))
            score = len(words & desc_words)
            if score:
                scored.append((score, c))
        scored.sort(key=lambda x: -x[0])
        return [{"code": c["code"], "description": c["description"],
                  "category": c.get("category"), "match_score": s}
                for s, c in scored[:3]]

    # --- 4) Pulpal status from symptoms -----------------------------------
    def assess_pulpal_status(self, symptoms: str) -> dict:
        """Heuristic: maps symptom phrasing to a pulpal differential.
        NOT a diagnosis — just suggests which tests to run.
        """
        s = (symptoms or "").lower()
        irreversible_hints = ["throb", "lingering", "spontaneous", "night",
                               "wakes", "keep me up", "constant"]
        reversible_hints   = ["cold sensitivity", "sensitive to cold",
                               "stops when", "goes away", "brief"]
        necrosis_hints     = ["no response", "no pain", "abscess", "swelling",
                               "draining", "fistula"]

        score_irr = sum(1 for w in irreversible_hints if w in s)
        score_rev = sum(1 for w in reversible_hints   if w in s)
        score_nec = sum(1 for w in necrosis_hints     if w in s)

        if score_irr >= 2:
            likely = "irreversible_pulpitis"
            tests  = ["cold test (lingering)", "percussion",
                       "periapical radiograph"]
        elif score_nec >= 1:
            likely = "pulp_necrosis"
            tests  = ["electric pulp test (no response)", "PA radiograph",
                       "palpation for abscess"]
        elif score_rev >= 1:
            likely = "reversible_pulpitis"
            tests  = ["cold test (brief response)", "bite test"]
        else:
            likely = "indeterminate"
            tests  = ["cold test", "percussion", "PA radiograph"]
        return {"likely": likely, "recommended_tests": tests,
                "rationale": (f"matches: irreversible={score_irr}, "
                              f"reversible={score_rev}, necrosis={score_nec}")}

    # --- 5) Required objective fields for visit type ----------------------
    def required_objective_for(self, visit_type: str) -> dict:
        """Returns the list of required-objective fields for this visit type
        from visit_type_templates.json, plus the CDT allow-list."""
        vt = (visit_type or "").lower().strip()
        template = self._visits.get(vt) or {}
        if not template:
            # try aliases
            for alias_pair in [("recall", "recall_exam"), ("emergency", "emergency_limited")]:
                if vt in alias_pair:
                    other = alias_pair[1] if alias_pair[0] == vt else alias_pair[0]
                    template = self._visits.get(other) or {}
                    if template: break
        return {
            "visit_type": vt or "unknown",
            "required_subjective": template.get("required_subjective") or [],
            "required_objective":  template.get("required_objective")  or [],
            "required_plan":       template.get("required_plan")       or [],
            # 'typical_cdt' is the architect's key; older code paths may use
            # 'cdt_allow_list' — surface both so callers can read either.
            "typical_cdt":      template.get("typical_cdt") or [],
            "cdt_allow_list":   template.get("typical_cdt") or template.get("cdt_allow_list") or [],
            "prompts_hint":     template.get("prompts_hint") or "",
        }

    # --- 6) TSBDE anchor block check --------------------------------------
    def check_tsbde_anchor_block(self, soap_state: dict | None) -> dict:
        """Which TSBDE 22 TAC §108.8 anchor fields are still missing?"""
        s = soap_state or {}
        meta = s.get("encounter_meta") or s.get("metadata") or {}
        prov = meta.get("provider") or {}
        pat  = meta.get("patient") or {}
        plan = s.get("plan") or {}

        missing: list[str] = []
        if not prov.get("name"): missing.append("provider name")
        if not prov.get("tsbde_license"): missing.append("TSBDE license #")
        if not meta.get("date_of_service"): missing.append("date of service")
        if not pat.get("patient_id"): missing.append("patient identification")
        if not pat.get("consent_on_file"): missing.append("informed consent flag")
        # Radiograph reference if rads were taken
        if (s.get("objective") or {}).get("radiographs_taken") and \
           not (s.get("objective") or {}).get("radiographic_findings"):
            missing.append("radiographic findings (rads taken without finding)")
        # Anesthetic record if procedures present
        if plan.get("procedures_today") and not any(
            isinstance(p, dict) and p.get("anesthesia") for p in plan["procedures_today"]
        ):
            missing.append("anesthetic record")
        return {"complete": len(missing) == 0, "missing_fields": missing}


# ===========================================================================
# Anthropic tool-use bindings
# ===========================================================================

TOOL_SCHEMAS = [
    {
        "name": "check_drug_interaction",
        "description": ("Check whether two drugs interact. Returns severity, "
                        "mechanism, and safer alternatives if any. Call ONLY "
                        "after you've heard the doctor or patient name two "
                        "drugs in the transcript."),
        "input_schema": {
            "type": "object",
            "properties": {
                "drug1": {"type": "string"},
                "drug2": {"type": "string"},
            },
            "required": ["drug1", "drug2"],
        },
    },
    {
        "name": "lookup_dental_term",
        "description": "Get the dictionary definition of a dental term.",
        "input_schema": {
            "type": "object",
            "properties": {"term": {"type": "string"}},
            "required": ["term"],
        },
    },
    {
        "name": "cdt_candidates_for",
        "description": ("Find the top 3 CDT 2026 codes whose description "
                        "matches a procedure phrase. Codes are constrained "
                        "to the allow-list."),
        "input_schema": {
            "type": "object",
            "properties": {"procedure_text": {"type": "string"}},
            "required": ["procedure_text"],
        },
    },
    {
        "name": "assess_pulpal_status",
        "description": ("Given a free-text symptom description, return the "
                        "likely pulpal differential (reversible vs irreversible "
                        "vs necrosis) and which tests to run. NOT a diagnosis."),
        "input_schema": {
            "type": "object",
            "properties": {"symptoms": {"type": "string"}},
            "required": ["symptoms"],
        },
    },
    {
        "name": "required_objective_for",
        "description": ("Returns the required-objective fields and CDT allow-list "
                        "for a given visit type. Use this to spot history/exam "
                        "gaps the doctor hasn't covered yet."),
        "input_schema": {
            "type": "object",
            "properties": {"visit_type": {"type": "string"}},
            "required": ["visit_type"],
        },
    },
    {
        "name": "check_tsbde_anchor_block",
        "description": ("Returns which TSBDE 22 TAC §108.8 record fields are "
                        "still missing from the current SOAP draft state."),
        "input_schema": {
            "type": "object",
            "properties": {
                "soap_state": {
                    "type": "object",
                    "description": ("Current draft SOAP JSON (encounter_meta, "
                                     "objective, plan, etc.). Pass `null` if "
                                     "the swarm hasn't drafted anything yet."),
                },
            },
            "required": ["soap_state"],
        },
    },
]


# ===========================================================================
# Coach agent — the orchestrator
# ===========================================================================

SYSTEM_PROMPT = """You are the **Dental Coach** — a live, bounded clinical-workflow advisor.

You watch a transcript of a doctor-patient consultation as it unfolds and
surface short, actionable recommendations to keep the doctor on a safe,
complete, billable trajectory.

You are NOT a diagnostician. You do NOT speak to the patient. You do NOT
write the SOAP note (a separate Scribe agent does that). Your only output
is JSON recommendations.

## What you may flag (exactly one of these categories per recommendation):
- "safety"        — drug interactions, allergy contraindications, vitals
- "history_gap"   — required intake question the doctor hasn't asked yet
- "differential"  — diagnostic test to consider given symptoms
- "documentation" — TSBDE 22 TAC §108.8 anchor field still missing
- "billing"       — likely CDT code accumulating from documented work

## Hard rules:
1. **Cite — do not invent.** Every recommendation MUST include either a
   verbatim `evidence_quote` from the transcript OR a `tool_used` name.
2. **Use tools.** When unsure (drug interactions, CDT lookups, pulpal
   tests), call the appropriate tool BEFORE recommending.
3. **At most 3 recommendations per call.** Newest most-actionable first.
   If nothing new since the last call, return `{"recommendations": []}`.
4. **Severity is honest.** "high" for safety/compliance issues that
   should block sign-off. "medium" for things the doctor should address
   soon. "low" for nice-to-haves.
5. **No clinical opinions.** Say "consider asking about X" or "test for Y",
   not "the patient has Z".

## Output schema (strict JSON):
```
{
  "recommendations": [
    {
      "category": "safety|history_gap|differential|documentation|billing",
      "severity": "high|medium|low",
      "message":  "Short imperative for the doctor.",
      "suggested_action": "One specific next step.",
      "evidence_quote": "verbatim transcript span (or empty if tool-based)",
      "tooth_ref": "tooth number if applicable, else null"
    }
  ]
}
```
"""


class DentalCoach:
    """Live coaching agent. One instance per recording session.

    Maintains a dedupe cache so the same recommendation doesn't fire twice
    for the same encounter. Caller is responsible for the trigger cadence
    (we recommend: speaker-turn change OR 15-second silence ceiling).
    """

    def __init__(self, llm_client, max_recs_per_call: int = 3) -> None:
        self.llm = llm_client
        self.tools = CoachTools()
        self.max_recs_per_call = max_recs_per_call
        self._seen_fingerprints: set[str] = set()
        self._last_invoked_at: float = 0.0
        # For audit + cost tracking
        self.audit: list[dict] = []

    @property
    def total_recommendations(self) -> int:
        return len(self._seen_fingerprints)

    def reset(self) -> None:
        """Clear cache (call between encounters)."""
        self._seen_fingerprints.clear()
        self._last_invoked_at = 0.0
        self.audit.clear()

    # ------------------------------------------------------------------
    def coach(self, transcript_so_far: str, *, visit_type: str = "emergency",
              soap_draft: dict | None = None) -> list[Recommendation]:
        """One coaching pass. Returns NEW recommendations (deduped)."""
        if not transcript_so_far or not transcript_so_far.strip():
            return []

        if self.llm and getattr(self.llm, "demo", False):
            # Demo path — deterministic fixture recommendations
            return self._demo_recs(transcript_so_far, soap_draft)

        t0 = time.time()
        raw = self._call_claude_with_tools(transcript_so_far, visit_type, soap_draft)
        duration_ms = int((time.time() - t0) * 1000)

        recs = []
        for item in raw.get("recommendations", [])[:self.max_recs_per_call]:
            try:
                rec = Recommendation(
                    category=item.get("category", "documentation"),
                    severity=item.get("severity", "low"),
                    message=item.get("message", "").strip(),
                    suggested_action=item.get("suggested_action", "").strip(),
                    evidence_quote=item.get("evidence_quote", ""),
                    tooth_ref=item.get("tooth_ref"),
                    tool_used=item.get("tool_used"),
                )
            except Exception:
                continue
            if not rec.message:
                continue
            if rec.fingerprint in self._seen_fingerprints:
                continue
            self._seen_fingerprints.add(rec.fingerprint)
            recs.append(rec)

        self.audit.append({
            "duration_ms": duration_ms,
            "recommendations_new": len(recs),
            "transcript_len": len(transcript_so_far),
        })
        return recs

    # ------------------------------------------------------------------
    def _dispatch_tool(self, name: str, args: dict) -> Any:
        """Map a tool name to a CoachTools method. Defensive."""
        fn = getattr(self.tools, name, None)
        if not callable(fn):
            return {"error": f"unknown tool {name!r}"}
        try:
            return fn(**(args or {}))
        except TypeError as e:
            return {"error": f"bad args for {name}: {e}"}
        except Exception as e:
            return {"error": f"{name} failed: {e}"}

    def _call_claude_with_tools(self, transcript: str, visit_type: str,
                                  soap_draft: dict | None) -> dict:
        """Anthropic tool-use loop. Returns parsed `{"recommendations": [...]}`."""
        import anthropic
        client = self.llm._anthropic if hasattr(self.llm, "_anthropic") and self.llm._anthropic \
                 else anthropic.Anthropic()
        model = getattr(self.llm, "model", "claude-sonnet-4-5")
        previous = sorted(self._seen_fingerprints)[-12:]
        user_msg = (
            f"Visit type: {visit_type}\n\n"
            f"Transcript so far:\n```\n{transcript}\n```\n\n"
            f"Current SOAP draft (may be partial):\n```\n"
            f"{json.dumps(soap_draft or {}, indent=2)[:2000]}\n```\n\n"
            f"Previously emitted recommendation fingerprints (skip duplicates):\n"
            f"{previous}\n\n"
            "Produce at most 3 NEW recommendations. Return JSON only."
        )
        messages = [{"role": "user", "content": user_msg}]
        # Run the tool-use loop up to 5 turns (safety bound)
        for _turn in range(5):
            resp = client.messages.create(
                model=model, max_tokens=1500,
                system=SYSTEM_PROMPT,
                tools=TOOL_SCHEMAS,
                messages=messages,
            )
            if resp.stop_reason == "tool_use":
                tool_results = []
                assistant_blocks = []
                for block in resp.content:
                    if block.type == "tool_use":
                        result = self._dispatch_tool(block.name, block.input or {})
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        })
                        assistant_blocks.append(block)
                    else:
                        assistant_blocks.append(block)
                messages.append({"role": "assistant", "content": assistant_blocks})
                messages.append({"role": "user", "content": tool_results})
                continue
            # end_turn — parse final text content
            for block in resp.content:
                if block.type == "text":
                    return _parse_json(block.text)
            break
        return {"recommendations": []}

    # ------------------------------------------------------------------
    def _demo_recs(self, transcript: str, soap_draft: dict | None) -> list[Recommendation]:
        """Deterministic demo recommendations driven by transcript keywords.
        Lets the live-coach pane look populated even without an API key."""
        t = transcript.lower()
        out: list[Recommendation] = []

        # Drug interaction sniff
        if "lisinopril" in t and ("ibuprofen" in t or "advil" in t or "nsaid" in t):
            r = Recommendation(
                category="safety", severity="high",
                message="Ibuprofen + lisinopril interaction",
                suggested_action="Use acetaminophen 650 mg q6h PRN instead, or document risk discussion.",
                evidence_quote="I am on lisinopril",
                tool_used="check_drug_interaction",
            )
            if r.fingerprint not in self._seen_fingerprints:
                self._seen_fingerprints.add(r.fingerprint); out.append(r)

        # Pulpal differential sniff
        if any(k in t for k in ("throb", "wakes", "night", "lingering")) and not any(
            k in t for k in ("cold test", "ept", "percussion")
        ):
            r = Recommendation(
                category="differential", severity="medium",
                message="Lingering nocturnal pain → suspect irreversible pulpitis",
                suggested_action="Run cold test (look for lingering >10s) and percussion before committing to RCT.",
                evidence_quote="throbs at night",
                tool_used="assess_pulpal_status",
            )
            if r.fingerprint not in self._seen_fingerprints:
                self._seen_fingerprints.add(r.fingerprint); out.append(r)

        # History gap sniff
        if "allerg" not in t and ("amox" in t or "pen" in t or "ibuprofen" in t):
            r = Recommendation(
                category="history_gap", severity="medium",
                message="Medication mentioned but no allergy review documented",
                suggested_action="Ask: known drug allergies, specifically to penicillin or NSAIDs.",
                evidence_quote=("ibuprofen" if "ibuprofen" in t else "amox"),
                tool_used="required_objective_for",
            )
            if r.fingerprint not in self._seen_fingerprints:
                self._seen_fingerprints.add(r.fingerprint); out.append(r)

        return out[:self.max_recs_per_call]


# ===========================================================================
# Helpers
# ===========================================================================

def _parse_json(text: str) -> dict:
    """Best-effort JSON parse — handles fenced blocks and stray prose."""
    text = (text or "").strip()
    # Strip ```json fences
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    # Trim to outermost JSON object
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "recommendations" in data:
            return data
    except Exception:
        pass
    return {"recommendations": []}
