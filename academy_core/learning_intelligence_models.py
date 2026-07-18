from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, Tuple


class ReadinessBand(str, Enum):
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    FOUNDATION_NEEDED = "foundation_needed"
    DEVELOPING = "developing"
    APPROACHING_READY = "approaching_ready"
    READY_WITH_REVISION = "ready_with_revision"


class TrendDirection(str, Enum):
    DECLINING = "declining"
    STABLE = "stable"
    IMPROVING = "improving"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True)
class ConceptIntelligence:
    concept_id: str
    subject: str
    name: str
    mastery_score: float
    evidence_count: int
    confidence_score: float
    prerequisite_impact: float
    revision_due: bool
    priority_score: int
    reasons: Tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.concept_id.strip(): raise ValueError("concept_id is required")
        if not self.subject.strip(): raise ValueError("subject is required")
        if not 0.0 <= self.mastery_score <= 1.0: raise ValueError("mastery_score must be between 0 and 1")
        if not 0.0 <= self.confidence_score <= 1.0: raise ValueError("confidence_score must be between 0 and 1")
        if not 0.0 <= self.prerequisite_impact <= 1.0: raise ValueError("prerequisite_impact must be between 0 and 1")
        if not 0 <= self.priority_score <= 100: raise ValueError("priority_score must be between 0 and 100")


@dataclass(frozen=True)
class SubjectIntelligence:
    subject: str
    mastery_score: float
    syllabus_coverage: float
    evidence_count: int
    consistency_score: float
    learning_velocity: float
    trend: TrendDirection
    priority_concepts: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ExamReadinessReport:
    student_id: str
    readiness_score: float
    readiness_band: ReadinessBand
    evidence_confidence: float
    syllabus_coverage: float
    mastery_score: float
    consistency_score: float
    prerequisite_health: float
    revision_completion: float
    uncertainty_reasons: Tuple[str, ...]
    priority_concepts: Tuple[str, ...]
    generated_at: str

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["readiness_band"] = self.readiness_band.value
        return data


@dataclass(frozen=True)
class RevisionPlanItem:
    concept_id: str
    subject: str
    name: str
    priority: int
    reason: str
    suggested_action: str
    estimated_minutes: int
    prerequisite_first: Tuple[str, ...] = ()


@dataclass(frozen=True)
class LearningIntelligenceProfile:
    student_id: str
    concepts: Tuple[ConceptIntelligence, ...]
    subjects: Tuple[SubjectIntelligence, ...]
    exam_readiness: ExamReadinessReport
    revision_plan: Tuple[RevisionPlanItem, ...]
    learning_velocity: float
    consistency_score: float
    effort_trend: TrendDirection
    generated_at: str


@dataclass(frozen=True)
class IntelligenceSummary:
    audience: str
    student_id: str
    headline: str
    strengths: Tuple[str, ...]
    support_areas: Tuple[str, ...]
    next_actions: Tuple[str, ...]
    caution: str
