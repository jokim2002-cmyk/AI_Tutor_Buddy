from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Tuple

from .reasoning_service import ReasonedLesson, ReasoningService
from .strategy_models import StrategyKey, TeachingStrategySelection
from .strategy_selector import TeachingStrategySelector
from .student_analyzer import StudentAnalysis


@dataclass(frozen=True)
class StrategicLesson:
    reasoned_lesson: ReasonedLesson
    strategy: TeachingStrategySelection


class TeachingStrategyService:
    """Combines teacher reasoning and strategy selection without generating text."""

    def __init__(
        self,
        reasoning_service: ReasoningService | None = None,
        selector: TeachingStrategySelector | None = None,
    ) -> None:
        self.reasoning_service = reasoning_service or ReasoningService()
        self.selector = selector or TeachingStrategySelector()

    def prepare(
        self,
        analysis: StudentAnalysis,
        *,
        prior_strategy_keys: Sequence[StrategyKey | str] = (),
        student_preferences: Sequence[str] = (),
        student_requested_final_answer: bool = False,
        lesson_has_started: bool = False,
    ) -> StrategicLesson:
        reasoned = self.reasoning_service.prepare(
            analysis,
            student_requested_final_answer=student_requested_final_answer,
            lesson_has_started=lesson_has_started,
        )
        strategy = self.selector.select(
            analysis,
            reasoned.decision,
            prior_strategy_keys=prior_strategy_keys,
            student_preferences=student_preferences,
        )
        return StrategicLesson(
            reasoned_lesson=reasoned,
            strategy=strategy,
        )
