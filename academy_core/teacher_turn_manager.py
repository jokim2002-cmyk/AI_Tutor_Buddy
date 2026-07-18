from __future__ import annotations

from .classroom_models import (
    LessonSession,
    LessonStage,
    TeacherTurn,
    TeacherTurnType,
)
from .reasoning_engine import TeachingAction, TeachingDecision
from .strategy_models import TeachingStrategySelection


class TeacherTurnManager:
    def choose(
        self,
        session: LessonSession,
        decision: TeachingDecision,
        strategy: TeachingStrategySelection,
        *,
        understanding_confirmed: bool = False,
        homework_required: bool = True,
    ) -> TeacherTurn:
        stage = session.stage

        if stage == LessonStage.SESSION_START:
            return TeacherTurn(
                turn_type=TeacherTurnType.GREET,
                instruction="Open the lesson warmly and identify the current subject.",
                expected_student_action="Respond to the greeting.",
                advance_to=LessonStage.GREETING,
            )

        if stage == LessonStage.GREETING:
            return TeacherTurn(
                turn_type=TeacherTurnType.ASK_QUESTION,
                instruction="Set one clear, achievable lesson goal.",
                expected_student_action="Confirm or clarify the goal.",
                advance_to=LessonStage.GOAL_SETTING,
            )

        if stage == LessonStage.GOAL_SETTING:
            target = (
                LessonStage.REVISION
                if decision.action == TeachingAction.REVISE
                else LessonStage.TEACHING
            )
            return TeacherTurn(
                turn_type=(
                    TeacherTurnType.REVISE
                    if target == LessonStage.REVISION
                    else TeacherTurnType.EXPLAIN
                ),
                instruction=(
                    f"Begin with {strategy.primary.value}. "
                    "Follow the selected step size and final-answer policy."
                ),
                expected_student_action="Engage with the first teaching step.",
                advance_to=target,
            )

        if stage == LessonStage.TEACHING:
            if decision.action == TeachingAction.GIVE_HINT:
                return TeacherTurn(
                    turn_type=TeacherTurnType.GIVE_HINT,
                    instruction="Give one hint and do not reveal the final answer.",
                    expected_student_action="Attempt the next reasoning step.",
                    advance_to=LessonStage.GUIDED_PRACTICE,
                )
            return TeacherTurn(
                turn_type=TeacherTurnType.EXPLAIN,
                instruction=(
                    f"Teach using {strategy.primary.value} and one short example."
                ),
                expected_student_action="Explain the idea back or try an example.",
                advance_to=LessonStage.GUIDED_PRACTICE,
            )

        if stage == LessonStage.GUIDED_PRACTICE:
            return TeacherTurn(
                turn_type=TeacherTurnType.ASK_QUESTION,
                instruction="Guide one practice item with minimal help.",
                expected_student_action="Solve with guided support.",
                advance_to=LessonStage.INDEPENDENT_PRACTICE,
            )

        if stage == LessonStage.INDEPENDENT_PRACTICE:
            return TeacherTurn(
                turn_type=TeacherTurnType.CHALLENGE,
                instruction="Give one independent practice task at the current difficulty.",
                expected_student_action="Attempt independently.",
                advance_to=LessonStage.UNDERSTANDING_CHECK,
                should_emit_progress=True,
            )

        if stage == LessonStage.UNDERSTANDING_CHECK:
            if understanding_confirmed:
                target = (
                    LessonStage.HOMEWORK
                    if homework_required
                    else LessonStage.SUMMARY
                )
                return TeacherTurn(
                    turn_type=(
                        TeacherTurnType.ASSIGN_HOMEWORK
                        if homework_required
                        else TeacherTurnType.SUMMARIZE
                    ),
                    instruction=(
                        "Understanding is confirmed. Assign a short homework task."
                        if homework_required
                        else "Understanding is confirmed. Summarize the lesson."
                    ),
                    expected_student_action=(
                        "Acknowledge the homework."
                        if homework_required
                        else "Reflect on the lesson."
                    ),
                    advance_to=target,
                    should_emit_progress=True,
                    should_notify_staff=True,
                )

            return TeacherTurn(
                turn_type=TeacherTurnType.REVISE,
                instruction="Repair the exact gap with a smaller step.",
                expected_student_action="Retry after targeted revision.",
                advance_to=LessonStage.REVISION,
                should_emit_progress=True,
                should_notify_staff=True,
            )

        if stage == LessonStage.REVISION:
            return TeacherTurn(
                turn_type=TeacherTurnType.REVISE,
                instruction="Review the prerequisite or misconception without shame.",
                expected_student_action="Attempt a simpler check.",
                advance_to=LessonStage.TEACHING,
            )

        if stage == LessonStage.HOMEWORK:
            return TeacherTurn(
                turn_type=TeacherTurnType.SUMMARIZE,
                instruction="Summarize progress, homework, and next step.",
                expected_student_action="Confirm the plan.",
                advance_to=LessonStage.SUMMARY,
            )

        if stage == LessonStage.SUMMARY:
            return TeacherTurn(
                turn_type=TeacherTurnType.SUMMARIZE,
                instruction="Close warmly and save the session outcome.",
                expected_student_action="End the session.",
                advance_to=LessonStage.COMPLETE,
                should_emit_progress=True,
                should_notify_staff=True,
            )

        return TeacherTurn(
            turn_type=TeacherTurnType.WAIT,
            instruction="The lesson is already complete.",
            expected_student_action="Start a new lesson when ready.",
            advance_to=LessonStage.COMPLETE,
            should_write_memory=False,
        )
