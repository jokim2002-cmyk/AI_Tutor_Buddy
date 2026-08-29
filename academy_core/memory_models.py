from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Tuple


class MasteryLevel(str, Enum):
    UNKNOWN = "unknown"
    INTRODUCED = "introduced"
    DEVELOPING = "developing"
    PROFICIENT = "proficient"
    MASTERED = "mastered"
    NEEDS_REVISION = "needs_revision"


class MemoryEventType(str, Enum):
    LESSON = "lesson"
    PRACTICE = "practice"
    ASSESSMENT = "assessment"
    MISCONCEPTION = "misconception"
    REVISION = "revision"
    GOAL_COMPLETION = "goal_completion"


class MemoryVisibility(str, Enum):
    STUDENT = "student"
    TEACHER = "teacher"
    CLASS_TEACHER = "class_teacher"
    PRINCIPAL = "principal"
    GUARDIAN_SUMMARY = "guardian_summary"
    RESTRICTED = "restricted"


@dataclass(frozen=True)
class ConceptNode:
    concept_id: str
    subject: str
    name: str
    prerequisite_ids: Tuple[str, ...] = ()
    mastery: MasteryLevel = MasteryLevel.UNKNOWN
    confidence_score: float = 0.0
    evidence_count: int = 0
    last_evidence_at: str = ""
    next_revision_at: str = ""
    misconception_ids: Tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.concept_id.strip():
            raise ValueError("concept_id is required")
        if not self.subject.strip():
            raise ValueError("subject is required")
        if not self.name.strip():
            raise ValueError("concept name is required")
        if not 0.0 <= self.confidence_score <= 1.0:
            raise ValueError("confidence_score must be between 0 and 1")
        if self.evidence_count < 0:
            raise ValueError("evidence_count cannot be negative")


@dataclass(frozen=True)
class MisconceptionRecord:
    misconception_id: str
    student_id: str
    concept_id: str
    description: str
    first_seen_at: str
    last_seen_at: str
    occurrence_count: int = 1
    resolved: bool = False
    resolution_evidence: Tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.misconception_id.strip():
            raise ValueError("misconception_id is required")
        if not self.student_id.strip():
            raise ValueError("student_id is required")
        if not self.concept_id.strip():
            raise ValueError("concept_id is required")
        if not self.description.strip():
            raise ValueError("description is required")
        if self.occurrence_count < 1:
            raise ValueError("occurrence_count must be at least 1")


@dataclass(frozen=True)
class LearningMemoryEvent:
    event_id: str
    student_id: str
    concept_id: str
    event_type: MemoryEventType
    timestamp: str
    summary: str
    evidence_score: float
    visibility: MemoryVisibility = MemoryVisibility.TEACHER
    source_session_id: str = ""
    tags: Tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id is required")
        if not self.student_id.strip():
            raise ValueError("student_id is required")
        if not self.concept_id.strip():
            raise ValueError("concept_id is required")
        if not self.summary.strip():
            raise ValueError("summary is required")
        if not 0.0 <= self.evidence_score <= 1.0:
            raise ValueError("evidence_score must be between 0 and 1")


@dataclass(frozen=True)
class StudentMemoryProfile:
    student_id: str
    concept_ids: Tuple[str, ...] = ()
    event_ids: Tuple[str, ...] = ()
    misconception_ids: Tuple[str, ...] = ()
    revision_queue: Tuple[str, ...] = ()
    updated_at: str = ""

    def validate(self) -> None:
        if not self.student_id.strip():
            raise ValueError("student_id is required")


@dataclass(frozen=True)
class RevisionRecommendation:
    student_id: str
    concept_id: str
    reason: str
    priority: int
    due_at: str
    suggested_strategy: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KnowledgeGraphSnapshot:
    student_id: str
    nodes: Tuple[ConceptNode, ...]
    edges: Tuple[Tuple[str, str], ...]
    blocked_concepts: Tuple[str, ...]
    revision_due: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["nodes"] = [
            {**asdict(node), "mastery": node.mastery.value}
            for node in self.nodes
        ]
        return data
