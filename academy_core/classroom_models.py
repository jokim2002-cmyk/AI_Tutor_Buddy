from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Tuple


class LessonStage(str, Enum):
    SESSION_START = "session_start"
    GREETING = "greeting"
    GOAL_SETTING = "goal_setting"
    TEACHING = "teaching"
    GUIDED_PRACTICE = "guided_practice"
    INDEPENDENT_PRACTICE = "independent_practice"
    UNDERSTANDING_CHECK = "understanding_check"
    REVISION = "revision"
    HOMEWORK = "homework"
    SUMMARY = "summary"
    COMPLETE = "complete"


class TeacherTurnType(str, Enum):
    GREET = "greet"
    EXPLAIN = "explain"
    ASK_QUESTION = "ask_question"
    GIVE_HINT = "give_hint"
    ENCOURAGE = "encourage"
    REVISE = "revise"
    CHALLENGE = "challenge"
    ASSIGN_HOMEWORK = "assign_homework"
    SUMMARIZE = "summarize"
    WAIT = "wait"


class SessionOutcome(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PAUSED = "paused"
    NEEDS_REVISION = "needs_revision"
    ESCALATED = "escalated"


class GoalStatus(str, Enum):
    LOCKED = "locked"
    ACTIVE = "active"
    COMPLETED = "completed"
    NEEDS_REVISION = "needs_revision"


@dataclass(frozen=True)
class LearningGoal:
    goal_id: str
    subject: str
    topic: str
    status: GoalStatus
    prerequisite_goal_ids: Tuple[str, ...] = ()
    evidence_required: int = 1

    def validate(self) -> None:
        if not self.goal_id.strip():
            raise ValueError("goal_id is required")
        if not self.subject.strip():
            raise ValueError("goal subject is required")
        if not self.topic.strip():
            raise ValueError("goal topic is required")
        if self.evidence_required < 1:
            raise ValueError("evidence_required must be at least 1")


@dataclass(frozen=True)
class LessonSession:
    session_id: str
    student_id: str
    teacher_name: str
    subject: str
    topic: str
    stage: LessonStage
    outcome: SessionOutcome = SessionOutcome.IN_PROGRESS
    goal_id: str = ""
    started_at: str = ""
    completed_at: str = ""
    last_strategy: str = ""
    pending_doubts: Tuple[str, ...] = ()
    mistakes: Tuple[str, ...] = ()
    homework_ids: Tuple[str, ...] = ()
    revision_topics: Tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_id is required")
        if not self.student_id.strip():
            raise ValueError("student_id is required")
        if not self.teacher_name.strip():
            raise ValueError("teacher_name is required")
        if not self.subject.strip():
            raise ValueError("subject is required")
        if not self.topic.strip():
            raise ValueError("topic is required")


@dataclass(frozen=True)
class TeacherTurn:
    turn_type: TeacherTurnType
    instruction: str
    expected_student_action: str
    advance_to: LessonStage
    should_write_memory: bool = True
    should_emit_progress: bool = False
    should_notify_staff: bool = False


@dataclass(frozen=True)
class ProgressEvent:
    student_id: str
    session_id: str
    subject: str
    topic: str
    event_type: str
    summary: str
    stage: LessonStage
    evidence_tags: Tuple[str, ...] = ()


@dataclass(frozen=True)
class StaffNotification:
    recipient_role: str
    recipient_name: str
    category: str
    summary: str
    student_id: str
    session_id: str


@dataclass(frozen=True)
class SessionAuditRecord:
    session_id: str
    student_id: str
    teacher_name: str
    subject: str
    topic: str
    stages_visited: Tuple[LessonStage, ...]
    strategies_used: Tuple[str, ...]
    mistakes_observed: Tuple[str, ...]
    homework_ids: Tuple[str, ...]
    revision_topics: Tuple[str, ...]
    outcome: SessionOutcome
    summary: str

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["stages_visited"] = [item.value for item in self.stages_visited]
        data["outcome"] = self.outcome.value
        return data


@dataclass(frozen=True)
class ClassroomStepResult:
    session: LessonSession
    turn: TeacherTurn
    progress_events: Tuple[ProgressEvent, ...] = ()
    staff_notifications: Tuple[StaffNotification, ...] = ()
    completed_goal_ids: Tuple[str, ...] = ()
    unlocked_goal_ids: Tuple[str, ...] = ()
    audit_tags: Tuple[str, ...] = field(default_factory=tuple)
