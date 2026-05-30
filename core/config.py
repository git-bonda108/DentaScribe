"""Centralized configuration. Reads .env, exposes typed accessors."""
import os
from dataclasses import dataclass
from typing import Optional

try:
    from dotenv import load_dotenv
    # override=True so .env is authoritative in dev. Any inherited empty env
    # var (e.g. from a prior shell or parent process) would otherwise shadow
    # the real value — that bit us once when ANTHROPIC_API_KEY was set blank
    # at session start and silently overrode the .env file.
    # In production, ship without a .env and rely on real OS env vars instead.
    load_dotenv(override=True)
except Exception:
    pass


@dataclass
class Config:
    anthropic_api_key: Optional[str]
    anthropic_model: str
    openai_api_key: Optional[str]
    openai_model: str
    stt_provider: str           # "openai" | "deepgram"
    whisper_model: str
    deepgram_api_key: Optional[str]
    deepgram_model: str
    demo_mode: str              # "auto" | "true" | "false"
    db_path: str

    @property
    def has_llm(self) -> bool:
        return bool(self.anthropic_api_key or self.openai_api_key)

    @property
    def has_stt(self) -> bool:
        if self.stt_provider == "deepgram":
            return bool(self.deepgram_api_key)
        return bool(self.openai_api_key)

    @property
    def effective_demo_mode(self) -> bool:
        if self.demo_mode == "true":
            return True
        if self.demo_mode == "false":
            return False
        # auto: demo if no LLM keys at all
        return not self.has_llm


def load_config() -> Config:
    return Config(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        stt_provider=os.getenv("STT_PROVIDER", "openai").lower(),
        whisper_model=os.getenv("WHISPER_MODEL", "whisper-1"),
        deepgram_api_key=os.getenv("DEEPGRAM_API_KEY") or None,
        deepgram_model=os.getenv("DEEPGRAM_MODEL", "nova-3-medical"),
        demo_mode=os.getenv("DENTASCRIBE_DEMO_MODE", "auto").lower(),
        db_path=os.getenv("DENTASCRIBE_DB_PATH", "dentascribe.db"),
    )
