"""Base agent contract."""
from abc import ABC, abstractmethod
from typing import Optional
from core.state import SwarmState
from core.config import Config
from utils.llm import LLMClient


class Agent(ABC):
    name: str = "agent"

    def __init__(self, cfg: Config, llm: Optional[LLMClient] = None):
        self.cfg = cfg
        self.llm = llm

    @abstractmethod
    def run(self, state: SwarmState) -> SwarmState:
        ...
