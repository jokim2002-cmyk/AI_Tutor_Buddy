from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, Tuple


class StrategyKey(str, Enum):
    STEP_BY_STEP = "step_by_step"
    WORKED_EXAMPLE = "worked_example"
    ANALOGY = "analogy"
    SOCRATIC_QUESTIONING = "socratic_questioning"
    VISUAL_EXPLANATION = "visual_explanation"
    STORY_BASED = "story_based"
    OBSERVATION_EXPERIMENT = "observation_experiment"
    RETRIEVAL_PRACTICE = "retrieval_practice"
    ERROR_CORRECTION = "error_correction"
    DEBUGGING = "debugging"
    COMMUNICATION_PRACTICE = "communication_practice"
    TIMELINE_CAUSE_EFFECT = "timeline_cause_effect"
    TRANSFER_CHALLENGE = "transfer_challenge"
    CONFIDENCE_REBUILD = "confidence_rebuild"


@dataclass(frozen=True)
class StrategyDefinition:
    key: StrategyKey
    title: str
    description: str
    compatible_subjects: Tuple[str, ...]
    compatible_actions: Tuple[str, ...]
    strengths: Tuple[str, ...]
    cautions: Tuple[str, ...] = ()

    def supports_subject(self, subject: str) -> bool:
        normalized = subject.strip().lower()
        return "*" in self.compatible_subjects or normalized in self.compatible_subjects

    def supports_action(self, action: str) -> bool:
        normalized = action.strip().lower()
        return "*" in self.compatible_actions or normalized in self.compatible_actions


@dataclass(frozen=True)
class StrategyScore:
    key: StrategyKey
    score: float
    reasons: Tuple[str, ...]

    def validate(self) -> None:
        if not 0.0 <= self.score <= 100.0:
            raise ValueError("strategy score must be between 0 and 100")
        if not self.reasons:
            raise ValueError("strategy score requires at least one reason")


@dataclass(frozen=True)
class TeachingStrategySelection:
    primary: StrategyKey
    supporting: Tuple[StrategyKey, ...]
    avoid: Tuple[StrategyKey, ...]
    scores: Tuple[StrategyScore, ...]
    student_facing_sequence: Tuple[str, ...]
    teacher_instruction: str
    selection_summary: str

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["primary"] = self.primary.value
        data["supporting"] = [item.value for item in self.supporting]
        data["avoid"] = [item.value for item in self.avoid]
        data["scores"] = [
            {
                "key": item.key.value,
                "score": item.score,
                "reasons": list(item.reasons),
            }
            for item in self.scores
        ]
        return data
