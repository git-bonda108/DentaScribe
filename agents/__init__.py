"""DentaScribe agent swarm.

Each agent is a small, focused unit that mutates the shared SwarmState.
The Orchestrator wires them into a pipeline:

    Transcription → Diarization → DentalNER → SoapNote → CdtCoder → Validator → (Storage)

Adding a new step is just a new class with `run(state) -> state`.
"""
from .orchestrator import Orchestrator  # noqa: F401
