"""Base agent contract.

Every agent in the swarm is a callable object with:
- a `name` (shown in the UI swarm panel)
- a `role` (one-line description)
- an `icon` (emoji for the UI)
- a `run(ctx) -> AgentResult` method

AgentResult carries the agent's output, the LLMCall audit record, status,
and human-readable status_message for the live swarm panel.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import time

from core.llm_client import LLMCall


@dataclass
class AgentResult:
    agent: str
    status: str                    # "pending" | "running" | "ok" | "warn" | "error" | "skipped"
    status_message: str = ""
    output: Any = None
    llm_call: LLMCall | None = None
    duration_ms: int = 0
    started_at: float = field(default_factory=time.time)


class BaseAgent:
    name: str = "base"
    role: str = "base agent"
    icon: str = "🤖"

    def run(self, ctx: dict) -> AgentResult:
        raise NotImplementedError
