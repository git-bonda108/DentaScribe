"""The orchestrator: runs the agent swarm end-to-end.

Pipeline:
  Scribe  ─►  Compliance  ─►  Coder  ─►  Validator  ─►  Second-Opinion
                                                 │
                                                 └─►  ValidationReport
                                                 └─►  Audit trail (every LLMCall)

The orchestrator yields AgentResults as it goes so the Streamlit UI in batch 6
can render a live "swarm panel" with status pills.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Iterator

from core.llm_client import LLMClient
from core.soap_validator import SOAPValidator
from agents.base import AgentResult
from agents.clinical_agents import ScribeAgent, CoderAgent
from agents.compliance_agent import ComplianceAgent
from agents.second_opinion_agent import SecondOpinionAgent


@dataclass
class SwarmRun:
    run_id: str
    case_id: str
    transcript: str
    visit_type: str
    metadata: dict
    results: list[AgentResult] = field(default_factory=list)
    soap: dict | None = None
    validation: dict | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    @property
    def duration_ms(self) -> int:
        end = self.finished_at or time.time()
        return int((end - self.started_at) * 1000)

    def status(self) -> str:
        if any(r.status == "error" for r in self.results):
            return "error"
        if any(r.status == "warn" for r in self.results):
            return "warn"
        return "ok" if self.results else "pending"

    def audit_records(self) -> list[dict]:
        out = []
        for r in self.results:
            row = {
                "run_id": self.run_id, "agent": r.agent, "status": r.status,
                "status_message": r.status_message, "duration_ms": r.duration_ms,
                "started_at": r.started_at,
            }
            if r.llm_call:
                row.update({
                    "model": r.llm_call.model,
                    "input_tokens": r.llm_call.input_tokens,
                    "output_tokens": r.llm_call.output_tokens,
                    "latency_ms": r.llm_call.latency_ms,
                    "llm_status": r.llm_call.status,
                    "prompt_hash": r.llm_call.system_prompt_hash,
                })
            out.append(row)
        return out


class Orchestrator:
    def __init__(self, llm: LLMClient | None = None, clinic_env: dict | None = None):
        self.llm = llm or LLMClient(demo=True)
        self.clinic_env = clinic_env or {}
        self.validator = SOAPValidator()

    def run(
        self,
        *,
        transcript: str,
        visit_type: str = "emergency",
        metadata: dict | None = None,
        case_id: str = "emergency_endo",
    ) -> SwarmRun:
        """Run the full pipeline and return a completed SwarmRun (non-streaming)."""
        run = SwarmRun(
            run_id=str(uuid.uuid4()),
            case_id=case_id,
            transcript=transcript,
            visit_type=visit_type,
            metadata=metadata or {},
        )
        for _ in self.run_streaming(run):
            pass
        return run

    def run_streaming(self, run: SwarmRun) -> Iterator[AgentResult]:
        """Yield AgentResults as they complete. The UI uses this for the live panel."""
        ctx = {
            "transcript": run.transcript,
            "visit_type": run.visit_type,
            "metadata": run.metadata,
            "case_id": run.case_id,
            "clinic_env": self.clinic_env,
        }

        # 1) Scribe
        scribe = ScribeAgent(self.llm).run(ctx)
        run.results.append(scribe)
        yield scribe
        if scribe.status == "error":
            run.finished_at = time.time()
            return
        run.soap = scribe.output
        ctx["soap"] = run.soap

        # 2) Compliance (deterministic; fills checklist)
        compliance = ComplianceAgent().run(ctx)
        run.results.append(compliance)
        yield compliance

        # 3) Coder
        coder = CoderAgent(self.llm).run(ctx)
        run.results.append(coder)
        yield coder

        # 4) Validator (deterministic; not an LLM agent but reported in swarm)
        report = self.validator.validate(run.soap, transcript=run.transcript)
        run.validation = report.as_dict()
        validator_result = AgentResult(
            agent="Validator",
            status=("ok" if report.valid and not report.warnings else
                    "warn" if report.valid else "error"),
            status_message=(
                f"Score {report.signability_score}/100 • "
                f"{len(report.errors)} err, {len(report.warnings)} warn, {len(report.infos)} info"
            ),
            output=run.validation,
            duration_ms=0,
        )
        run.results.append(validator_result)
        yield validator_result

        # 5) Second-Opinion
        second = SecondOpinionAgent(self.llm).run(ctx)
        run.results.append(second)
        yield second

        run.finished_at = time.time()
