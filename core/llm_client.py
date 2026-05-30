"""Single canonical Claude client.

EVERY Claude call in DentaScribe MUST go through this module.
Never instantiate anthropic.Anthropic() directly elsewhere — the validator,
audit log, and demo mode all depend on this chokepoint.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

try:
    from anthropic import Anthropic
    from anthropic.types import Message
    _HAS_ANTHROPIC = True
except ImportError:  # demo mode allowed without SDK
    Anthropic = None  # type: ignore
    Message = None  # type: ignore
    _HAS_ANTHROPIC = False


DEFAULT_MODEL = os.getenv("DENTASCRIBE_MODEL", "claude-sonnet-4-5")
FALLBACK_MODEL = "claude-opus-4"


@dataclass
class LLMCall:
    """Audit record for one Claude call. Stored in the audit log."""
    agent: str
    model: str
    system_prompt_hash: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    status: str = "ok"
    error: str | None = None
    raw_response_id: str | None = None
    timestamp: float = field(default_factory=time.time)


class LLMClient:
    """Thin wrapper around the Anthropic SDK with three guarantees:

    1. **JSON-mode helper** — `complete_json()` parses Claude's text into a dict
       and retries once with a "your previous response was not valid JSON" nudge.
    2. **Demo mode** — if `demo=True` or no API key, returns a canned response
       supplied by the caller. Keeps the UI runnable with no keys.
    3. **Audit trail** — every call returns `(content, LLMCall)` so the orchestrator
       can persist a trace.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None, demo: bool = False):
        self.model = model or DEFAULT_MODEL
        self.demo = demo or not (api_key or os.getenv("ANTHROPIC_API_KEY"))
        if not self.demo and _HAS_ANTHROPIC:
            self._client = Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
        else:
            self._client = None

    # ---------- public API ----------

    def complete_text(
        self,
        *,
        agent: str,
        system: str,
        user: str,
        max_tokens: int = 2048,
        temperature: float = 0.2,
        demo_response: str | None = None,
    ) -> tuple[str, LLMCall]:
        """Plain text completion."""
        record = LLMCall(
            agent=agent,
            model=self.model,
            system_prompt_hash=_hash(system),
        )

        if self.demo:
            record.status = "demo"
            return (demo_response or "", record)

        t0 = time.time()
        try:
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            text = "".join(block.text for block in resp.content if hasattr(block, "text"))
            record.input_tokens = resp.usage.input_tokens
            record.output_tokens = resp.usage.output_tokens
            record.raw_response_id = resp.id
            record.latency_ms = int((time.time() - t0) * 1000)
            return text, record
        except Exception as e:
            record.status = "error"
            record.error = f"{type(e).__name__}: {e}"
            record.latency_ms = int((time.time() - t0) * 1000)
            return "", record

    def complete_json(
        self,
        *,
        agent: str,
        system: str,
        user: str,
        max_tokens: int = 4096,
        temperature: float = 0.1,
        demo_response: dict | None = None,
    ) -> tuple[dict | None, LLMCall]:
        """JSON-mode completion. Returns parsed dict or None on failure."""
        if self.demo:
            record = LLMCall(agent=agent, model=self.model, system_prompt_hash=_hash(system), status="demo")
            return (demo_response, record)

        # Wrap system prompt with strict JSON directive
        json_system = system + "\n\nCRITICAL: Respond with a single JSON object and nothing else. No prose, no markdown fences, no commentary."

        text, record = self.complete_text(
            agent=agent, system=json_system, user=user,
            max_tokens=max_tokens, temperature=temperature,
        )
        parsed = _safe_json_parse(text)
        if parsed is not None:
            return parsed, record

        # Retry once with a nudge
        nudge_user = (
            f"{user}\n\nYour previous response was not valid JSON. "
            "Return ONLY a valid JSON object now, with no surrounding text."
        )
        text2, record2 = self.complete_text(
            agent=agent + "_retry", system=json_system, user=nudge_user,
            max_tokens=max_tokens, temperature=0.0,
        )
        parsed2 = _safe_json_parse(text2)
        record2.status = "retry_ok" if parsed2 is not None else "retry_failed"
        return parsed2, record2


# ---------- helpers ----------

def _hash(s: str) -> str:
    import hashlib
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


def _safe_json_parse(text: str) -> dict | None:
    if not text:
        return None
    text = text.strip()
    # strip accidental markdown fences
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        # try to find the first '{' and last '}'
        start = text.find("{")
        end = text.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
        return None
