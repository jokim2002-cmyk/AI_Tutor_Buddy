from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Tuple
from uuid import uuid4

from .classroom_models import (
    ClassroomStepResult,
    LessonSession,
    LessonStage,
    ProgressEvent,
    SessionOutcome,
    StaffNotification,
)
from .classroom_state_machine import LessonStateMachine
from .learning_goals import LearningGoalManager
from .session_memory import ClassroomSessionMemory
from .strategy_models import TeachingStrategySelection
from .teacher_turn_manager import TeacherTurnManager
from .reasoning_engine import TeachingDecision


class LiveClassroomOrchestrator:
    def __init__(
        self,
        *,
        memory: ClassroomSessionMemory | None = None,
        state_machine: LessonStateMachine | None = None,
        turn_manager: TeacherTurnManager | None = None,
        goals: LearningGoalManager | None = None,
    ) -> None:
        self.memory = memory or ClassroomSessionMemory()
        self.state_machine = state_machine or LessonStateMachine()
        self.turn_manager = turn_manager or TeacherTurnManager()
        self.goals = goals or LearningGoalManager()

    def start_session(
        self,
        *,
        student_id: str,
        teacher_name: str,
        subject: str,
        topic: str,
        goal_id: str = "",
        strategy_key: str = "",
    ) -> LessonSession:
        now = datetime.now(timezone.utc).isoformat()
        session = LessonSession(
            session_id=f"lesson_{uuid4().hex[:12]}",
            student_id=student_id,
            teacher_name=teacher_name,
            subject=subject,
            topic=topic,
            stage=LessonStage.SESSION_START,
            outcome=SessionOutcome.IN_PROGRESS,
            goal_id=goal_id,
            started_at=now,
            last_strategy=strategy_key,
        )
        self.memory.create(session)
        return session

    def advance(
        self,
        session_id: str,
        decision: TeachingDecision,
        strategy: TeachingStrategySelection,
        *,
        understanding_confirmed: bool = False,
        homework_required: bool = True,
        mistake: str = "",
        pending_doubt: str = "",
        homework_id: str = "",
        revision_topic: str = "",
        goal_evidence_count: int = 0,
    ) -> ClassroomStepResult:
        session = self.memory.get(session_id)
        turn = self.turn_manager.choose(
            session,
            decision,
            strategy,
            understanding_confirmed=understanding_confirmed,
            homework_required=homework_required,
        )

        if session.stage == LessonStage.COMPLETE:
            return ClassroomStepResult(
                session=session,
                turn=turn,
                audit_tags=("classroom_complete",),
            )

        updated = self.state_machine.transition(session, turn.advance_to)
        updated = replace(
            updated,
            last_strategy=strategy.primary.value,
            mistakes=self._append_unique(updated.mistakes, mistake),
            pending_doubts=self._append_unique(updated.pending_doubts, pending_doubt),
            homework_ids=self._append_unique(updated.homework_ids, homework_id),
            revision_topics=self._append_unique(updated.revision_topics, revision_topic),
        )

        completed_goal_ids: Tuple[str, ...] = ()
        unlocked_goal_ids: Tuple[str, ...] = ()

        if updated.stage == LessonStage.COMPLETE:
            updated = replace(
                updated,
                completed_at=datetime.now(timezone.utc).isoformat(),
                outcome=SessionOutcome.COMPLETED,
            )
            if updated.goal_id and goal_evidence_count > 0:
                unlocked_goal_ids = self.goals.complete_goal(
                    updated.goal_id,
                    evidence_count=goal_evidence_count,
                )
                if self.goals.get(updated.goal_id).status.value == "completed":
                    completed_goal_ids = (updated.goal_id,)

        self.memory.save(updated)

        progress_events = self._progress_events(updated, turn)
        for event in progress_events:
            self.memory.add_progress(event)

        staff_notifications = self._staff_notifications(updated, turn)

        return ClassroomStepResult(
            session=updated,
            turn=turn,
            progress_events=progress_events,
            staff_notifications=staff_notifications,
            completed_goal_ids=completed_goal_ids,
            unlocked_goal_ids=unlocked_goal_ids,
            audit_tags=("classroom_step", updated.stage.value),
        )

    def audit(self, session_id: str):
        return self.memory.build_audit(session_id)

    @staticmethod
    def _append_unique(items: Tuple[str, ...], value: str) -> Tuple[str, ...]:
        value = value.strip()
        if not value or value in items:
            return items
        return items + (value,)

    @staticmethod
    def _progress_events(
        session: LessonSession,
        turn,
    ) -> Tuple[ProgressEvent, ...]:
        if not turn.should_emit_progress:
            return ()
        return (
            ProgressEvent(
                student_id=session.student_id,
                session_id=session.session_id,
                subject=session.subject,
                topic=session.topic,
                event_type=session.stage.value,
                summary=(
                    f"{session.student_id} reached {session.stage.value} "
                    f"for {session.topic}."
                ),
                stage=session.stage,
                evidence_tags=(
                    session.last_strategy,
                    session.outcome.value,
                ),
            ),
        )

    @staticmethod
    def _staff_notifications(
        session: LessonSession,
        turn,
    ) -> Tuple[StaffNotification, ...]:
        if not turn.should_notify_staff:
            return ()

        category = (
            "lesson_complete"
            if session.stage == LessonStage.COMPLETE
            else "learning_update"
        )

        return (
            StaffNotification(
                recipient_role="class_teacher",
                recipient_name="Asha Ma'am",
                category=category,
                summary=(
                    f"{session.teacher_name} updated {session.student_id}'s "
                    f"{session.subject} lesson on {session.topic}."
                ),
                student_id=session.student_id,
                session_id=session.session_id,
            ),
            StaffNotification(
                recipient_role="principal",
                recipient_name="Principal Arvind",
                category=category,
                summary=(
                    f"Classroom progress is available for {session.student_id}."
                ),
                student_id=session.student_id,
                session_id=session.session_id,
            ),
        )
