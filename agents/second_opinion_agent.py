"""Second-Opinion agent — the differentiator.

Runs after Scribe + Coder + Validator. Flags clinically significant concerns
across 6 bounded categories. Never overrides; always dismissible.
"""
from __future__ import annotations
import time

from agents.base import BaseAgent, AgentResult
from core.llm_client import LLMClient
from prompts.clinical_prompts import (
    build_second_opinion_system_prompt, build_second_opinion_user_prompt,
)


def _demo_second_opinion_endo() -> dict:
    return {
        "flags": [
            {
                "category": "drug_interaction", "severity": "medium",
                "summary": "Ibuprofen + lisinopril",
                "detail": "Patient is on lisinopril (ACE inhibitor). NSAIDs may reduce antihypertensive effect and stress renal function with prolonged use.",
                "evidence_quote": "Hypertension on lisinopril 10 mg daily",
                "suggested_action": "Consider acetaminophen 650 mg q6h PRN as alternative, or document risk-benefit discussion.",
            },
            {
                "category": "billing_gap", "severity": "low",
                "summary": "Consider D9248 if anxiolysis discussed",
                "detail": "Patient appears anxious; if non-IV conscious sedation was used, D9248 is billable.",
                "evidence_quote": "throbbing, keeps patient awake at night",
                "suggested_action": "Confirm whether any anxiolysis was administered.",
            },
            {
                "category": "compliance_gap", "severity": "low",
                "summary": "BP elevated — document acknowledgment",
                "detail": "BP 138/86 is stage 1 hypertensive. Document that this was reviewed and treatment proceeded safely.",
                "evidence_quote": "138/86",
                "suggested_action": "Add note: 'BP reviewed, within acceptable range for outpatient endodontic care.'",
            },
        ],
        "overall_assessment": "Documentation is clinically appropriate and well-grounded. Main considerations are the NSAID/ACE-I interaction and minor billing optimization. No safety blockers.",
        "blocks_sign_off": False,
    }


def _demo_second_opinion_recall() -> dict:
    return {
        "flags": [
            {
                "category": "missing_documentation", "severity": "low",
                "summary": "Anesthetic record minimal",
                "detail": "Half carpule is documented but consider noting injection site and patient response per TSBDE record requirements.",
                "evidence_quote": "Lidocaine 2% with epi 1:100,000, half carpule, infiltration",
                "suggested_action": "Expand to: site, time given, patient reaction.",
            },
        ],
        "overall_assessment": "Routine recall well-documented. Composite scope appropriate.",
        "blocks_sign_off": False,
    }


def get_demo_second_opinion(case_id: str) -> dict:
    return _demo_second_opinion_recall() if case_id == "recall_hygiene" else _demo_second_opinion_endo()


class SecondOpinionAgent(BaseAgent):
    name = "Second Opinion"
    role = "Bounded peer review across 6 categories"
    icon = "🧠"

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def run(self, ctx: dict) -> AgentResult:
        t0 = time.time()
        soap = ctx.get("soap") or {}
        transcript = ctx.get("transcript", "")
        case_id = ctx.get("case_id", "emergency_endo")

        sys_p = build_second_opinion_system_prompt()
        user_p = build_second_opinion_user_prompt(soap, transcript)
        demo_resp = get_demo_second_opinion(case_id) if self.llm.demo else None

        result, call = self.llm.complete_json(
            agent="second_opinion", system=sys_p, user=user_p,
            max_tokens=2048, temperature=0.2, demo_response=demo_resp,
        )

        if result is None:
            return AgentResult(
                agent=self.name, status="warn",
                status_message="Second-Opinion unavailable; proceed with caution.",
                output={"flags": [], "overall_assessment": "Agent unavailable.", "blocks_sign_off": False},
                llm_call=call, duration_ms=int((time.time() - t0) * 1000),
            )

        flags = result.get("flags", [])
        highs = sum(1 for f in flags if f.get("severity") == "high")
        status = "warn" if (highs or result.get("blocks_sign_off")) else "ok"
        msg = f"{len(flags)} flag(s); {highs} high-severity." if flags else "No concerns."

        return AgentResult(
            agent=self.name, status=status, status_message=msg,
            output=result, llm_call=call,
            duration_ms=int((time.time() - t0) * 1000),
        )
