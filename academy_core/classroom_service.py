from __future__ import annotations

from dataclasses import dataclass

from .classroom_models import ClassroomStepResult, LessonSession
from .classroom_orchestrator import LiveClassroomOrchestrator
from .reasoning_service import ReasonedLesson
from .strategy_models import TeachingStrategySelection


@dataclass(frozen=True)
class ClassroomPreparation:
    session: LessonSession
    reasoned_lesson: ReasonedLesson
    strategy: TeachingStrategySelection


class ClassroomService:
    """Thin integration boundary for reasoning, strategy, and lesson execution."""

    def __init__(self, orchestrator: LiveClassroomOrchestrator | None = None) -> None:
        self.orchestrator = orchestrator or LiveClassroomOrchestrator()

    def prepare(
        self,
        *,
        student_id: str,
        teacher_name: str,
        subject: str,
        topic: str,
        reasoned_lesson: ReasonedLesson,
        strategy: TeachingStrategySelection,
        goal_id: str = "",
    ) -> ClassroomPreparation:
        session = self.orchestrator.start_session(
            student_id=student_id,
            teacher_name=teacher_name,
            subject=subject,
            topic=topic,
            goal_id=goal_id,
            strategy_key=strategy.primary.value,
        )
        return ClassroomPreparation(
            session=session,
            reasoned_lesson=reasoned_lesson,
            strategy=strategy,
        )

    def advance(
        self,
        preparation: ClassroomPreparation,
        **kwargs,
    ) -> ClassroomStepResult:
        return self.orchestrator.advance(
            preparation.session.session_id,
            preparation.reasoned_lesson.decision,
            preparation.strategy,
            **kwargs,
        )
