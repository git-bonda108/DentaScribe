"""SwarmState — the shared object that flows between agents in the pipeline."""
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from datetime import datetime
import uuid


@dataclass
class TranscriptSegment:
    speaker: str          # "doctor" | "patient" | "unknown"
    text: str
    start: Optional[float] = None   # seconds
    end: Optional[float] = None


@dataclass
class DentalEntity:
    kind: str             # "tooth" | "condition" | "procedure" | "medication" | "anatomy" | "symptom"
    value: str
    span: Optional[str] = None      # raw matched text
    confidence: float = 0.9


@dataclass
class SoapNote:
    chief_complaint: str = ""
    subjective: str = ""
    objective: str = ""
    assessment: str = ""
    plan: str = ""
    medications: List[str] = field(default_factory=list)
    follow_up: str = ""
    dental_exam: str = ""           # findings (charting-style)
    notes_for_doctor: str = ""      # red flags / things to confirm


@dataclass
class CDTSuggestion:
    code: str
    nomenclature: str
    rationale: str
    confidence: float = 0.8


@dataclass
class QualityReport:
    warnings: List[str] = field(default_factory=list)
    unconfirmed_terms: List[str] = field(default_factory=list)
    completeness_score: float = 0.0
    schema_errors: List[str] = field(default_factory=list)
    grounding_errors: List[str] = field(default_factory=list)
    cdt_errors: List[str] = field(default_factory=list)
    signability_score: float = 0.0


@dataclass
class SwarmState:
    consultation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    patient_name: str = ""
    patient_id: str = ""
    doctor_name: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    raw_audio_path: Optional[str] = None
    raw_transcript: str = ""
    segments: List[TranscriptSegment] = field(default_factory=list)
    entities: List[DentalEntity] = field(default_factory=list)
    soap: SoapNote = field(default_factory=SoapNote)
    cdt_codes: List[CDTSuggestion] = field(default_factory=list)
    cdt_candidates: List[str] = field(default_factory=list)
    visit_type: str = "emergency_limited"
    soap_structured: Optional[Dict[str, Any]] = None
    flagged_teeth: List[int] = field(default_factory=list)
    treated_teeth: List[int] = field(default_factory=list)
    attestation: Dict[str, Any] = field(default_factory=lambda: {
        "provider_reviewed": False,
        "ai_assisted_disclosure": True,
        "signed_at_iso": None,
        "signature_method": None,
        "provider_signature": "",
    })
    qa: QualityReport = field(default_factory=QualityReport)

    agent_trace: List[Dict[str, Any]] = field(default_factory=list)

    def log(self, agent: str, message: str, level: str = "info"):
        self.agent_trace.append({
            "agent": agent,
            "message": message,
            "level": level,
            "ts": datetime.utcnow().isoformat(),
        })

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
