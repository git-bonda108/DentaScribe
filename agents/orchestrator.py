"""Orchestrator — wires the agent swarm into a deterministic pipeline.

Pipeline (after STT + transcript normalization):
  Diarization → DentalNER → CdtCoder (stage-1 candidates) → SoapNote → Validator

The Transcription step is split into two interfaces:
  * `transcribe_audio(bytes)` — turns audio into text BEFORE the pipeline runs.
  * The pipeline itself assumes `state.raw_transcript` is populated (either
    from STT, an uploaded text, or a fixture).
"""
from typing import Optional, Callable
from core.config import Config
from core.state import SwarmState
from utils.llm import LLMClient

from .transcription import TranscriptionAgent
from .diarization import DiarizationAgent
from .dental_ner import DentalNERAgent
from .soap_note import SoapNoteAgent
from .cdt_coder import CdtCoderAgent
from .validator import ValidatorAgent
from utils.transcript_normalize import normalize_transcript
from .knowledge import DentalKnowledge


class Orchestrator:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.llm = LLMClient(cfg)
        # Single shared knowledge instance — chunks/embeddings load once.
        # We pass the LLM's underlying OpenAI client into the retriever so
        # embedding search is enabled when a key is available; otherwise
        # token-overlap retrieval is used.
        openai_client = getattr(self.llm, "_openai", None)
        self.knowledge = DentalKnowledge(openai_client=openai_client)
        self.transcriber = TranscriptionAgent(cfg, self.llm, knowledge=self.knowledge)
        self.pipeline = [
            DiarizationAgent(cfg, self.llm),
            DentalNERAgent(cfg, self.llm, knowledge=self.knowledge),
            CdtCoderAgent(cfg, self.llm, knowledge=self.knowledge),
            SoapNoteAgent(cfg, self.llm, knowledge=self.knowledge),
            ValidatorAgent(cfg, self.llm, knowledge=self.knowledge),
        ]

    @property
    def llm_provider(self) -> str:
        return self.llm.provider or "demo"

    # --------------------- audio entry point ---------------------
    def transcribe_audio(self, wav_bytes: bytes, language: Optional[str] = None) -> str:
        return self.transcriber.transcribe_bytes(wav_bytes, language)

    # --------------------- run the pipeline ---------------------
    def run(self, state: SwarmState, on_step: Optional[Callable[[str], None]] = None) -> SwarmState:
        # Normalize tooth/surface references before NER (post-STT correction).
        if state.raw_transcript.strip():
            normalized, norm_log = normalize_transcript(state.raw_transcript)
            if norm_log:
                state.raw_transcript = normalized
                state.log("normalization",
                          f"normalized {len(norm_log)} tooth/surface refs")
        # Always log the transcription as the first step in trace.
        state.log("transcription",
                  f"transcript ingested ({len(state.raw_transcript)} chars)")
        if on_step:
            on_step("Transcription complete")
        for agent in self.pipeline:
            if on_step:
                on_step(f"Running {agent.name} …")
            state = agent.run(state)
        if on_step:
            on_step("Done")
        return state
