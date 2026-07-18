from __future__ import annotations

from dataclasses import dataclass

from .academy import Academy
from .reasoning_engine import TeacherReasoningEngine, TeachingDecision
from .student_analyzer import StudentAnalysis
from .teaching_plan import TeachingPlan, build_teaching_plan


@dataclass(frozen=True)
class ReasonedLesson:
    decision: TeachingDecision
    plan: TeachingPlan


class ReasoningService:
    """Coordinates academy routing and deterministic teacher reasoning."""

    def __init__(
        self,
        academy: Academy | None = None,
        engine: TeacherReasoningEngine | None = None,
    ) -> None:
        self.academy = academy or Academy()
        self.engine = engine or TeacherReasoningEngine()

    def prepare(
        self,
        analysis: StudentAnalysis,
        *,
        student_requested_final_answer: bool = False,
        lesson_has_started: bool = False,
    ) -> ReasonedLesson:
        teacher = self.academy.route(
            subject=analysis.recommended_teacher_subject or analysis.subject,
        )
        decision = self.engine.decide(
            analysis,
            teacher,
            student_requested_final_answer=student_requested_final_answer,
            lesson_has_started=lesson_has_started,
        )
        return ReasonedLesson(
            decision=decision,
            plan=build_teaching_plan(decision),
        )
