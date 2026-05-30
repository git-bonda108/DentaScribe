"""Unified LLM client — Anthropic primary, OpenAI fallback, deterministic demo mode."""
from __future__ import annotations
import json
from typing import Optional, Dict, Any
from core.config import Config


class LLMClient:
    """Thin wrapper that returns text/JSON from whichever provider is configured.

    Resolution order:
      1. Anthropic (Claude) if ANTHROPIC_API_KEY set.
      2. OpenAI    (GPT-4o)  if OPENAI_API_KEY set.
      3. None  → caller should fall back to deterministic logic / fixtures.
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.provider: Optional[str] = None
        self._anthropic = None
        self._openai = None

        if cfg.anthropic_api_key:
            try:
                import anthropic
                self._anthropic = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
                self.provider = "anthropic"
                return
            except Exception:
                self._anthropic = None
        if cfg.openai_api_key:
            try:
                from openai import OpenAI
                self._openai = OpenAI(api_key=cfg.openai_api_key)
                self.provider = "openai"
            except Exception:
                self._openai = None

    @property
    def available(self) -> bool:
        return self.provider is not None

    def complete(self, system: str, user: str, max_tokens: int = 1500,
                 temperature: float = 0.2) -> str:
        if self.provider == "anthropic":
            msg = self._anthropic.messages.create(
                model=self.cfg.anthropic_model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return "".join(b.text for b in msg.content if hasattr(b, "text"))
        if self.provider == "openai":
            resp = self._openai.chat.completions.create(
                model=self.cfg.openai_model,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return resp.choices[0].message.content or ""
        raise RuntimeError("No LLM provider configured")

    def complete_json(self, system: str, user: str, **kw) -> Dict[str, Any]:
        """Force-JSON variant. Robustly handles fenced code blocks."""
        raw = self.complete(system + "\n\nReturn ONLY valid minified JSON, no prose, no code fences.",
                            user, **kw)
        raw = raw.strip()
        # Strip ```json … ``` fences if present
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        # Find first { … last }
        if not raw.startswith("{"):
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                raw = raw[start:end + 1]
        try:
            return json.loads(raw)
        except Exception as e:
            raise RuntimeError(f"LLM did not return valid JSON: {e}\nRaw: {raw[:300]}")
