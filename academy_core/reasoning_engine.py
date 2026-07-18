from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .models import TeacherProfile
from .student_analyzer import (
    ConfidenceLevel,
    RevisionNeed,
    StudentAnalysis,
    UnderstandingState,
)


class TeachingAction(str, Enum):
    CLARIFY = "clarify"
    CHECK_PREREQUISITES = "check_prerequisites"
    GIVE_HINT = "give_hint"
    EXPLAIN = "explain"
    GUIDED_PRACTICE = "guided_practice"
    INDEPENDENT_PRACTICE = "independent_practice"
    REVISE = "revise"
    EXTEND = "extend"


class StepSize(str, Enum):
    VERY_SMALL = "very_small"
    SMALL = "small"
    NORMAL = "normal"
    LARGE = "large"


class DifficultyDirection(str, Enum):
    REDUCE = "reduce"
    HOLD = "hold"
    INCREASE = "increase"


@dataclass(frozen=True)
class ReasoningEvidence:
    signal: str
    source: str
    weight: float
    explanation: str

    def validate(self) -> None:
        if not self.signal.strip():
            raise ValueError("reasoning signal is required")
        if not self.source.strip():
            raise ValueError("reasoning source is required")
        if not 0.0 <= self.weight <= 1.0:
            raise ValueError("reasoning weight must be between 0 and 1")
        if not self.explanation.strip():
            raise ValueError("reasoning explanation is required")


@dataclass(frozen=True)
class TeachingDecision:
    teacher_id: str
    teacher_name: str
    subject: str
    action: TeachingAction
    step_size: StepSize
    difficulty_direction: DifficultyDirection
    selected_methods: Tuple[str, ...]
    ask_understanding_check: bool
    reveal_final_answer_immediately: bool
    prerequisite_check_required: bool
    revision_required: bool
    confidence_support_required: bool
    rationale: str
    evidence: Tuple[ReasoningEvidence, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["action"] = self.action.value
        data["step_size"] = self.step_size.value
        data["difficulty_direction"] = self.difficulty_direction.value
        data["evidence"] = [asdict(item) for item in self.evidence]
        return data


class TeacherReasoningEngine:
    """Turns StudentAnalysis into a deterministic, explainable teaching decision."""

    def decide(
        self,
        analysis: StudentAnalysis,
        teacher: TeacherProfile,
        *,
        student_requested_final_answer: bool = False,
        lesson_has_started: bool = False,
    ) -> TeachingDecision:
        evidence: List[ReasoningEvidence] = []

        action = self._select_action(
            analysis=analysis,
            lesson_has_started=lesson_has_started,
            evidence=evidence,
        )
        step_size = self._select_step_size(analysis, evidence)
        difficulty = self._select_difficulty(analysis, evidence)

        methods = self._select_methods(
            analysis=analysis,
            teacher=teacher,
            action=action,
            step_size=step_size,
        )

        reveal_final = self._should_reveal_final_answer(
            analysis=analysis,
            action=action,
            student_requested_final_answer=student_requested_final_answer,
            evidence=evidence,
        )

        ask_check = action not in {
            TeachingAction.CLARIFY,
            TeachingAction.CHECK_PREREQUISITES,
        }

        prerequisite_required = (
            analysis.needs_prerequisite_check
            or action == TeachingAction.CHECK_PREREQUISITES
        )
        revision_required = (
            analysis.revision_need != RevisionNeed.NONE
            or action == TeachingAction.REVISE
        )
        confidence_support = analysis.confidence == ConfidenceLevel.LOW

        rationale = self._build_rationale(
            action=action,
            step_size=step_size,
            difficulty=difficulty,
            analysis=analysis,
        )

        for item in evidence:
            item.validate()

        return TeachingDecision(
            teacher_id=teacher.teacher_id,
            teacher_name=teacher.name,
            subject=analysis.subject or teacher.subject,
            action=action,
            step_size=step_size,
            difficulty_direction=difficulty,
            selected_methods=methods,
            ask_understanding_check=ask_check,
            reveal_final_answer_immediately=reveal_final,
            prerequisite_check_required=prerequisite_required,
            revision_required=revision_required,
            confidence_support_required=confidence_support,
            rationale=rationale,
            evidence=tuple(evidence),
        )

    def _select_action(
        self,
        *,
        analysis: StudentAnalysis,
        lesson_has_started: bool,
        evidence: List[ReasoningEvidence],
    ) -> TeachingAction:
        if analysis.should_ask_clarifying_question:
            evidence.append(ReasoningEvidence(
                signal="missing_context",
                source="student_analysis",
                weight=0.95,
                explanation="Subject or topic context is insufficient for a safe teaching decision.",
            ))
            return TeachingAction.CLARIFY

        if analysis.needs_prerequisite_check:
            evidence.append(ReasoningEvidence(
                signal="foundation_gap_possible",
                source="student_analysis",
                weight=0.90,
                explanation="Current evidence suggests checking prerequisite understanding first.",
            ))
            return TeachingAction.CHECK_PREREQUISITES

        if analysis.revision_need == RevisionNeed.URGENT:
            evidence.append(ReasoningEvidence(
                signal="urgent_revision",
                source="student_analysis",
                weight=0.90,
                explanation="Revision is urgent because mastery or practice-gap evidence is weak.",
            ))
            return TeachingAction.REVISE

        if analysis.understanding == UnderstandingState.CONFUSED:
            evidence.append(ReasoningEvidence(
                signal="confusion",
                source="student_analysis",
                weight=0.90,
                explanation="The student appears confused and needs a fresh explanation.",
            ))
            return TeachingAction.EXPLAIN

        if analysis.understanding == UnderstandingState.GUESSING:
            evidence.append(ReasoningEvidence(
                signal="guessing",
                source="student_analysis",
                weight=0.80,
                explanation="The student should explain reasoning before receiving the answer.",
            ))
            return TeachingAction.GIVE_HINT

        if analysis.understanding == UnderstandingState.DEVELOPING:
            evidence.append(ReasoningEvidence(
                signal="developing_understanding",
                source="student_analysis",
                weight=0.75,
                explanation="The student benefits from guided practice with feedback.",
            ))
            return TeachingAction.GUIDED_PRACTICE

        if analysis.understanding == UnderstandingState.UNDERSTOOD:
            if lesson_has_started:
                evidence.append(ReasoningEvidence(
                    signal="understanding_demonstrated",
                    source="student_analysis",
                    weight=0.80,
                    explanation="Understanding is demonstrated; use transfer or extension practice.",
                ))
                return TeachingAction.EXTEND

            evidence.append(ReasoningEvidence(
                signal="ready_for_independent_work",
                source="student_analysis",
                weight=0.75,
                explanation="The student appears ready for independent practice.",
            ))
            return TeachingAction.INDEPENDENT_PRACTICE

        if analysis.revision_need == RevisionNeed.SOON:
            evidence.append(ReasoningEvidence(
                signal="revision_due",
                source="student_analysis",
                weight=0.70,
                explanation="The topic should be reinforced before moving too far ahead.",
            ))
            return TeachingAction.REVISE

        evidence.append(ReasoningEvidence(
            signal="insufficient_learning_signal",
            source="student_analysis",
            weight=0.60,
            explanation="Use a brief guided example and gather more evidence.",
        ))
        return TeachingAction.EXPLAIN

    def _select_step_size(
        self,
        analysis: StudentAnalysis,
        evidence: List[ReasoningEvidence],
    ) -> StepSize:
        if (
            analysis.confidence == ConfidenceLevel.LOW
            and analysis.understanding == UnderstandingState.CONFUSED
        ):
            evidence.append(ReasoningEvidence(
                signal="low_confidence_and_confusion",
                source="student_analysis",
                weight=0.90,
                explanation="Use very small steps to reduce overload and rebuild confidence.",
            ))
            return StepSize.VERY_SMALL

        if (
            analysis.confidence == ConfidenceLevel.LOW
            or analysis.understanding in {
                UnderstandingState.CONFUSED,
                UnderstandingState.GUESSING,
            }
        ):
            return StepSize.SMALL

        if analysis.understanding == UnderstandingState.UNDERSTOOD:
            return StepSize.LARGE

        return StepSize.NORMAL

    def _select_difficulty(
        self,
        analysis: StudentAnalysis,
        evidence: List[ReasoningEvidence],
    ) -> DifficultyDirection:
        if (
            analysis.needs_prerequisite_check
            or analysis.understanding == UnderstandingState.CONFUSED
            or analysis.confidence == ConfidenceLevel.LOW
        ):
            evidence.append(ReasoningEvidence(
                signal="reduce_cognitive_load",
                source="student_analysis",
                weight=0.80,
                explanation="Reduce difficulty until the missing foundation or confusion is resolved.",
            ))
            return DifficultyDirection.REDUCE

        if (
            analysis.understanding == UnderstandingState.UNDERSTOOD
            and analysis.confidence == ConfidenceLevel.HIGH
            and analysis.revision_need == RevisionNeed.NONE
        ):
            evidence.append(ReasoningEvidence(
                signal="ready_for_challenge",
                source="student_analysis",
                weight=0.80,
                explanation="Evidence supports increasing challenge gradually.",
            ))
            return DifficultyDirection.INCREASE

        return DifficultyDirection.HOLD

    def _select_methods(
        self,
        *,
        analysis: StudentAnalysis,
        teacher: TeacherProfile,
        action: TeachingAction,
        step_size: StepSize,
    ) -> Tuple[str, ...]:
        methods: List[str] = list(analysis.recommended_methods)

        action_methods: Mapping[TeachingAction, Tuple[str, ...]] = {
            TeachingAction.CLARIFY: ("clarifying_question",),
            TeachingAction.CHECK_PREREQUISITES: (
                "prerequisite_question",
                "foundation_example",
            ),
            TeachingAction.GIVE_HINT: ("progressive_hint", "reasoning_prompt"),
            TeachingAction.EXPLAIN: ("concept_explanation", "worked_example"),
            TeachingAction.GUIDED_PRACTICE: ("guided_practice", "immediate_feedback"),
            TeachingAction.INDEPENDENT_PRACTICE: (
                "independent_practice",
                "delayed_feedback",
            ),
            TeachingAction.REVISE: ("retrieval_practice", "spaced_revision"),
            TeachingAction.EXTEND: ("transfer_question", "challenge_problem"),
        }
        methods.extend(action_methods[action])

        if step_size in {StepSize.VERY_SMALL, StepSize.SMALL}:
            methods.append("one_step_at_a_time")

        # Preserve teacher personality without overriding safety decisions.
        methods.extend(teacher.teaching_methods[:2])

        return tuple(dict.fromkeys(methods))

    def _should_reveal_final_answer(
        self,
        *,
        analysis: StudentAnalysis,
        action: TeachingAction,
        student_requested_final_answer: bool,
        evidence: List[ReasoningEvidence],
    ) -> bool:
        if action in {
            TeachingAction.CLARIFY,
            TeachingAction.CHECK_PREREQUISITES,
            TeachingAction.GIVE_HINT,
        }:
            evidence.append(ReasoningEvidence(
                signal="reasoning_before_answer",
                source="academy_constitution",
                weight=1.0,
                explanation="Clarification, foundations, or reasoning should come before the final answer.",
            ))
            return False

        if analysis.understanding in {
            UnderstandingState.CONFUSED,
            UnderstandingState.GUESSING,
        }:
            return False

        if student_requested_final_answer and action in {
            TeachingAction.INDEPENDENT_PRACTICE,
            TeachingAction.EXTEND,
        }:
            return True

        return False

    @staticmethod
    def _build_rationale(
        *,
        action: TeachingAction,
        step_size: StepSize,
        difficulty: DifficultyDirection,
        analysis: StudentAnalysis,
    ) -> str:
        target = analysis.topic or analysis.subject or "the current task"
        return (
            f"For {target}, choose action={action.value}, "
            f"step_size={step_size.value}, difficulty={difficulty.value}. "
            "This decision is based on temporary learning evidence and must be "
            "re-evaluated after the student's next response."
        )
