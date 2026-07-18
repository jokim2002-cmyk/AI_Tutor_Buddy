from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Tuple


class GuardianRole(str, Enum):
    PARENT = "parent"
    GUARDIAN = "guardian"


class ReportAudience(str, Enum):
    CLASS_TEACHER = "class_teacher"
    PRINCIPAL = "principal"
    GUARDIAN = "guardian"


class PrivacyLevel(str, Enum):
    GENERAL = "general"
    SENSITIVE = "sensitive"
    SAFETY_CRITICAL = "safety_critical"


@dataclass(frozen=True)
class GuardianProfile:
    guardian_id: str
    name: str
    role: GuardianRole
    child_ids: Tuple[str, ...]
    preferred_language: str = "auto"

    def validate(self) -> None:
        if not self.guardian_id.strip():
            raise ValueError("guardian_id is required")
        if not self.name.strip():
            raise ValueError("guardian name is required")
        if not self.child_ids:
            raise ValueError("guardian must be linked to at least one child")
        if len(set(self.child_ids)) != len(self.child_ids):
            raise ValueError("duplicate child link detected")


@dataclass(frozen=True)
class LearningActivity:
    subject: str
    topic: str
    duration_minutes: int
    understanding: str
    confidence: str
    strategy_used: str = ""
    completed: bool = True

    def validate(self) -> None:
        if not self.subject.strip():
            raise ValueError("activity subject is required")
        if not self.topic.strip():
            raise ValueError("activity topic is required")
        if self.duration_minutes < 0:
            raise ValueError("duration_minutes cannot be negative")


@dataclass(frozen=True)
class StudentProgressSnapshot:
    student_id: str
    student_name: str
    date_label: str
    activities: Tuple[LearningActivity, ...]
    interests: Tuple[str, ...] = ()
    strengths: Tuple[str, ...] = ()
    support_needs: Tuple[str, ...] = ()
    voluntary_questions: Tuple[str, ...] = ()
    persistence_signals: Tuple[str, ...] = ()
    preferred_learning_methods: Tuple[str, ...] = ()
    sensitive_notes: Tuple[str, ...] = ()
    safety_flags: Tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.student_id.strip():
            raise ValueError("student_id is required")
        if not self.student_name.strip():
            raise ValueError("student_name is required")
        for activity in self.activities:
            activity.validate()


@dataclass(frozen=True)
class GuardianReport:
    student_id: str
    student_name: str
    period_label: str
    learned_today: Tuple[str, ...]
    current_strengths: Tuple[str, ...]
    support_needs: Tuple[str, ...]
    interest_signals: Tuple[str, ...]
    home_support_actions: Tuple[str, ...]
    wellbeing_note: str
    privacy_notice: str
    generated_by: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FuturePathSuggestion:
    student_id: str
    exploration_areas: Tuple[str, ...]
    evidence_summary: Tuple[str, ...]
    suggested_activities: Tuple[str, ...]
    caution: str
    confidence: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GuardianConversationResponse:
    speaker_name: str
    speaker_role: str
    answer: str
    report: GuardianReport | None = None
    future_path: FuturePathSuggestion | None = None
    comparison_blocked: bool = False
    audit_tags: Tuple[str, ...] = field(default_factory=tuple)
