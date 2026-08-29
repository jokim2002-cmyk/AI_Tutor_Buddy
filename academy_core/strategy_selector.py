from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, MutableMapping, Sequence, Tuple

from .reasoning_engine import (
    DifficultyDirection,
    StepSize,
    TeachingAction,
    TeachingDecision,
)
from .strategy_catalog import STRATEGY_CATALOG
from .strategy_models import (
    StrategyKey,
    StrategyScore,
    TeachingStrategySelection,
)
from .student_analyzer import ConfidenceLevel, StudentAnalysis, UnderstandingState


@dataclass(frozen=True)
class StrategySelectionContext:
    analysis: StudentAnalysis
    decision: TeachingDecision
    prior_strategy_keys: Tuple[StrategyKey, ...] = ()
    student_preferences: Tuple[str, ...] = ()


class TeachingStrategySelector:
    """Ranks safe teaching strategies from analysis and reasoning evidence."""

    _SUBJECT_DEFAULTS: Mapping[str, Tuple[StrategyKey, ...]] = {
        "maths": (
            StrategyKey.STEP_BY_STEP,
            StrategyKey.WORKED_EXAMPLE,
            StrategyKey.VISUAL_EXPLANATION,
        ),
        "science": (
            StrategyKey.OBSERVATION_EXPERIMENT,
            StrategyKey.VISUAL_EXPLANATION,
            StrategyKey.ANALOGY,
        ),
        "english": (
            StrategyKey.COMMUNICATION_PRACTICE,
            StrategyKey.STORY_BASED,
            StrategyKey.SOCRATIC_QUESTIONING,
        ),
        "hindi": (
            StrategyKey.COMMUNICATION_PRACTICE,
            StrategyKey.STORY_BASED,
            StrategyKey.RETRIEVAL_PRACTICE,
        ),
        "computer": (
            StrategyKey.DEBUGGING,
            StrategyKey.STEP_BY_STEP,
            StrategyKey.WORKED_EXAMPLE,
        ),
        "social_science": (
            StrategyKey.TIMELINE_CAUSE_EFFECT,
            StrategyKey.STORY_BASED,
            StrategyKey.VISUAL_EXPLANATION,
        ),
    }

    def select(
        self,
        analysis: StudentAnalysis,
        decision: TeachingDecision,
        *,
        prior_strategy_keys: Sequence[StrategyKey | str] = (),
        student_preferences: Sequence[str] = (),
    ) -> TeachingStrategySelection:
        prior = tuple(self._normalize_key(item) for item in prior_strategy_keys)
        context = StrategySelectionContext(
            analysis=analysis,
            decision=decision,
            prior_strategy_keys=prior,
            student_preferences=tuple(item.strip().lower() for item in student_preferences),
        )

        score_map: MutableMapping[StrategyKey, float] = {
            key: 0.0 for key in STRATEGY_CATALOG
        }
        reasons: Dict[StrategyKey, List[str]] = {
            key: [] for key in STRATEGY_CATALOG
        }

        self._score_compatibility(context, score_map, reasons)
        self._score_subject(context, score_map, reasons)
        self._score_action(context, score_map, reasons)
        self._score_student_state(context, score_map, reasons)
        self._score_preferences(context, score_map, reasons)
        self._score_variety(context, score_map, reasons)

        ranked = sorted(
            STRATEGY_CATALOG,
            key=lambda key: (-score_map[key], key.value),
        )

        eligible = [
            key for key in ranked
            if score_map[key] > 0 and self._is_compatible(key, context)
        ]
        if not eligible:
            eligible = [StrategyKey.STEP_BY_STEP]

        primary = eligible[0]
        supporting = tuple(
            key for key in eligible[1:4]
            if not self._conflicts(primary, key)
        )[:2]

        avoid = self._select_avoid(context, score_map)
        scores = tuple(
            StrategyScore(
                key=key,
                score=round(max(0.0, min(100.0, score_map[key] / 2.0)), 2),
                reasons=tuple(reasons[key] or ("not selected",)),
            )
            for key in ranked[:6]
        )
        for score in scores:
            score.validate()

        sequence = self._build_sequence(primary, supporting, context)
        instruction = self._build_teacher_instruction(
            primary=primary,
            supporting=supporting,
            context=context,
        )
        summary = (
            f"Primary strategy={primary.value}; supporting="
            f"{', '.join(key.value for key in supporting) or 'none'}. "
            "Selection is temporary and must be reconsidered after new evidence."
        )

        return TeachingStrategySelection(
            primary=primary,
            supporting=supporting,
            avoid=avoid,
            scores=scores,
            student_facing_sequence=sequence,
            teacher_instruction=instruction,
            selection_summary=summary,
        )

    @staticmethod
    def _normalize_key(value: StrategyKey | str) -> StrategyKey:
        if isinstance(value, StrategyKey):
            return value
        return StrategyKey(value.strip().lower())

    @staticmethod
    def _add(
        scores: MutableMapping[StrategyKey, float],
        reasons: Dict[StrategyKey, List[str]],
        key: StrategyKey,
        amount: float,
        reason: str,
    ) -> None:
        scores[key] += amount
        reasons[key].append(reason)

    def _score_compatibility(
        self,
        context: StrategySelectionContext,
        scores: MutableMapping[StrategyKey, float],
        reasons: Dict[StrategyKey, List[str]],
    ) -> None:
        subject = context.analysis.subject or context.decision.subject
        action = context.decision.action.value

        for key, definition in STRATEGY_CATALOG.items():
            if definition.supports_subject(subject):
                self._add(scores, reasons, key, 12.0, "compatible with subject")
            else:
                self._add(scores, reasons, key, -40.0, "not compatible with subject")

            if definition.supports_action(action):
                self._add(scores, reasons, key, 16.0, "compatible with teaching action")
            else:
                self._add(scores, reasons, key, -35.0, "not compatible with teaching action")

    def _score_subject(
        self,
        context: StrategySelectionContext,
        scores: MutableMapping[StrategyKey, float],
        reasons: Dict[StrategyKey, List[str]],
    ) -> None:
        subject = (context.analysis.subject or context.decision.subject).lower()
        defaults = self._SUBJECT_DEFAULTS.get(
            subject,
            (StrategyKey.STEP_BY_STEP, StrategyKey.SOCRATIC_QUESTIONING),
        )
        for index, key in enumerate(defaults):
            self._add(
                scores,
                reasons,
                key,
                120.0 - (index * 24.0),
                f"{subject or 'general'} subject pedagogy",
            )

    def _score_action(
        self,
        context: StrategySelectionContext,
        scores: MutableMapping[StrategyKey, float],
        reasons: Dict[StrategyKey, List[str]],
    ) -> None:
        action_boosts: Mapping[TeachingAction, Tuple[StrategyKey, ...]] = {
            TeachingAction.CLARIFY: (StrategyKey.SOCRATIC_QUESTIONING,),
            TeachingAction.CHECK_PREREQUISITES: (
                StrategyKey.STEP_BY_STEP,
                StrategyKey.ANALOGY,
                StrategyKey.CONFIDENCE_REBUILD,
            ),
            TeachingAction.GIVE_HINT: (
                StrategyKey.SOCRATIC_QUESTIONING,
                StrategyKey.ERROR_CORRECTION,
                StrategyKey.STEP_BY_STEP,
            ),
            TeachingAction.EXPLAIN: (
                StrategyKey.WORKED_EXAMPLE,
                StrategyKey.ANALOGY,
                StrategyKey.VISUAL_EXPLANATION,
            ),
            TeachingAction.GUIDED_PRACTICE: (
                StrategyKey.STEP_BY_STEP,
                StrategyKey.SOCRATIC_QUESTIONING,
                StrategyKey.ERROR_CORRECTION,
            ),
            TeachingAction.INDEPENDENT_PRACTICE: (
                StrategyKey.RETRIEVAL_PRACTICE,
                StrategyKey.TRANSFER_CHALLENGE,
            ),
            TeachingAction.REVISE: (
                StrategyKey.RETRIEVAL_PRACTICE,
                StrategyKey.ERROR_CORRECTION,
            ),
            TeachingAction.EXTEND: (
                StrategyKey.TRANSFER_CHALLENGE,
                StrategyKey.SOCRATIC_QUESTIONING,
            ),
        }
        for index, key in enumerate(action_boosts[context.decision.action]):
            self._add(
                scores,
                reasons,
                key,
                24.0 - (index * 4.0),
                f"supports {context.decision.action.value}",
            )

    def _score_student_state(
        self,
        context: StrategySelectionContext,
        scores: MutableMapping[StrategyKey, float],
        reasons: Dict[StrategyKey, List[str]],
    ) -> None:
        analysis = context.analysis
        decision = context.decision

        if analysis.confidence == ConfidenceLevel.LOW:
            self._add(
                scores,
                reasons,
                StrategyKey.CONFIDENCE_REBUILD,
                30.0,
                "low confidence support",
            )
            self._add(
                scores,
                reasons,
                StrategyKey.STEP_BY_STEP,
                14.0,
                "small achievable steps",
            )

        if analysis.understanding == UnderstandingState.CONFUSED:
            for key in (
                StrategyKey.STEP_BY_STEP,
                StrategyKey.WORKED_EXAMPLE,
                StrategyKey.ANALOGY,
            ):
                self._add(scores, reasons, key, 16.0, "supports confusion repair")

        if analysis.understanding == UnderstandingState.GUESSING:
            self._add(
                scores,
                reasons,
                StrategyKey.SOCRATIC_QUESTIONING,
                24.0,
                "reveals student reasoning",
            )
            self._add(
                scores,
                reasons,
                StrategyKey.ERROR_CORRECTION,
                18.0,
                "repairs misconception evidence",
            )

        if decision.step_size in {StepSize.VERY_SMALL, StepSize.SMALL}:
            self._add(
                scores,
                reasons,
                StrategyKey.STEP_BY_STEP,
                22.0,
                "matches selected step size",
            )

        if decision.difficulty_direction == DifficultyDirection.INCREASE:
            self._add(
                scores,
                reasons,
                StrategyKey.TRANSFER_CHALLENGE,
                26.0,
                "matches increased challenge",
            )

    def _score_preferences(
        self,
        context: StrategySelectionContext,
        scores: MutableMapping[StrategyKey, float],
        reasons: Dict[StrategyKey, List[str]],
    ) -> None:
        preference_map = {
            "visual": StrategyKey.VISUAL_EXPLANATION,
            "story": StrategyKey.STORY_BASED,
            "examples": StrategyKey.WORKED_EXAMPLE,
            "questions": StrategyKey.SOCRATIC_QUESTIONING,
            "practice": StrategyKey.RETRIEVAL_PRACTICE,
            "experiment": StrategyKey.OBSERVATION_EXPERIMENT,
        }
        for preference in context.student_preferences:
            key = preference_map.get(preference)
            if key is not None:
                self._add(scores, reasons, key, 12.0, f"student prefers {preference}")

    def _score_variety(
        self,
        context: StrategySelectionContext,
        scores: MutableMapping[StrategyKey, float],
        reasons: Dict[StrategyKey, List[str]],
    ) -> None:
        for key in context.prior_strategy_keys[-2:]:
            self._add(
                scores,
                reasons,
                key,
                -10.0,
                "recently used; mild variety penalty",
            )

    @staticmethod
    def _is_compatible(
        key: StrategyKey,
        context: StrategySelectionContext,
    ) -> bool:
        definition = STRATEGY_CATALOG[key]
        subject = context.analysis.subject or context.decision.subject
        return (
            definition.supports_subject(subject)
            and definition.supports_action(context.decision.action.value)
        )

    @staticmethod
    def _conflicts(primary: StrategyKey, candidate: StrategyKey) -> bool:
        # Keep the first plan focused instead of mixing too many high-level formats.
        narrative_pair = {
            StrategyKey.STORY_BASED,
            StrategyKey.OBSERVATION_EXPERIMENT,
        }
        return primary in narrative_pair and candidate in narrative_pair

    def _select_avoid(
        self,
        context: StrategySelectionContext,
        scores: Mapping[StrategyKey, float],
    ) -> Tuple[StrategyKey, ...]:
        avoid: List[StrategyKey] = []

        if context.analysis.understanding in {
            UnderstandingState.CONFUSED,
            UnderstandingState.GUESSING,
        }:
            avoid.append(StrategyKey.TRANSFER_CHALLENGE)

        if context.decision.step_size == StepSize.VERY_SMALL:
            avoid.append(StrategyKey.STORY_BASED)

        subject = context.analysis.subject or context.decision.subject
        for key, definition in STRATEGY_CATALOG.items():
            if not definition.supports_subject(subject) and scores[key] < 0:
                avoid.append(key)

        return tuple(dict.fromkeys(avoid))[:4]

    @staticmethod
    def _build_sequence(
        primary: StrategyKey,
        supporting: Tuple[StrategyKey, ...],
        context: StrategySelectionContext,
    ) -> Tuple[str, ...]:
        sequence = [
            "Acknowledge the student's current effort without judgement.",
            f"Use {primary.value.replace('_', ' ')} as the main teaching approach.",
        ]
        for key in supporting:
            sequence.append(
                f"Use {key.value.replace('_', ' ')} only as supporting help."
            )

        if context.decision.ask_understanding_check:
            sequence.append("Ask one focused understanding-check question.")
        else:
            sequence.append("Wait for the student's clarification before continuing.")

        return tuple(sequence)

    @staticmethod
    def _build_teacher_instruction(
        *,
        primary: StrategyKey,
        supporting: Tuple[StrategyKey, ...],
        context: StrategySelectionContext,
    ) -> str:
        support_text = ", ".join(key.value for key in supporting) or "none"
        return (
            f"Teach {context.analysis.topic or context.analysis.subject or 'the task'} "
            f"using {primary.value} as the primary strategy and {support_text} "
            "as optional support. Follow the reasoning engine's action, step size, "
            "difficulty, and final-answer policy. Re-evaluate after the next response."
        )
