from __future__ import annotations

from dataclasses import replace
from typing import Mapping

from .classroom_models import LessonSession, LessonStage, SessionOutcome


class InvalidLessonTransition(ValueError):
    pass


class LessonStateMachine:
    _ALLOWED: Mapping[LessonStage, tuple[LessonStage, ...]] = {
        LessonStage.SESSION_START: (LessonStage.GREETING,),
        LessonStage.GREETING: (LessonStage.GOAL_SETTING,),
        LessonStage.GOAL_SETTING: (
            LessonStage.TEACHING,
            LessonStage.REVISION,
        ),
        LessonStage.TEACHING: (
            LessonStage.GUIDED_PRACTICE,
            LessonStage.UNDERSTANDING_CHECK,
            LessonStage.REVISION,
        ),
        LessonStage.GUIDED_PRACTICE: (
            LessonStage.INDEPENDENT_PRACTICE,
            LessonStage.UNDERSTANDING_CHECK,
            LessonStage.REVISION,
        ),
        LessonStage.INDEPENDENT_PRACTICE: (
            LessonStage.UNDERSTANDING_CHECK,
            LessonStage.REVISION,
        ),
        LessonStage.UNDERSTANDING_CHECK: (
            LessonStage.REVISION,
            LessonStage.HOMEWORK,
            LessonStage.SUMMARY,
        ),
        LessonStage.REVISION: (
            LessonStage.TEACHING,
            LessonStage.GUIDED_PRACTICE,
            LessonStage.UNDERSTANDING_CHECK,
        ),
        LessonStage.HOMEWORK: (LessonStage.SUMMARY,),
        LessonStage.SUMMARY: (LessonStage.COMPLETE,),
        LessonStage.COMPLETE: (),
    }

    def transition(
        self,
        session: LessonSession,
        target: LessonStage,
    ) -> LessonSession:
        allowed = self._ALLOWED[session.stage]
        if target not in allowed:
            raise InvalidLessonTransition(
                f"Cannot move from {session.stage.value} to {target.value}"
            )

        outcome = (
            SessionOutcome.COMPLETED
            if target == LessonStage.COMPLETE
            else session.outcome
        )
        return replace(session, stage=target, outcome=outcome)
