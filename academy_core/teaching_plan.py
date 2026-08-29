from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .reasoning_engine import TeachingAction, TeachingDecision


@dataclass(frozen=True)
class TeachingPlan:
    opening_instruction: str
    teaching_instruction: str
    closing_instruction: str
    prohibited_behaviors: Tuple[str, ...]


def build_teaching_plan(decision: TeachingDecision) -> TeachingPlan:
    openings = {
        TeachingAction.CLARIFY: "Ask one short clarifying question.",
        TeachingAction.CHECK_PREREQUISITES: "Start with one prerequisite check.",
        TeachingAction.GIVE_HINT: "Acknowledge the attempt and give the smallest useful hint.",
        TeachingAction.EXPLAIN: "Begin with a simple concept explanation.",
        TeachingAction.GUIDED_PRACTICE: "Solve the next step together with the student.",
        TeachingAction.INDEPENDENT_PRACTICE: "Give one independent practice question.",
        TeachingAction.REVISE: "Begin with a short retrieval question from prior learning.",
        TeachingAction.EXTEND: "Give a transfer question that applies the concept in a new way.",
    }

    method_text = ", ".join(decision.selected_methods)
    teaching_instruction = (
        f"Use these methods where appropriate: {method_text}. "
        f"Use {decision.step_size.value.replace('_', ' ')} steps and "
        f"{decision.difficulty_direction.value} the current difficulty."
    )

    closing = (
        "Check understanding with one focused question."
        if decision.ask_understanding_check
        else "Wait for the student's clarification before teaching further."
    )

    return TeachingPlan(
        opening_instruction=openings[decision.action],
        teaching_instruction=teaching_instruction,
        closing_instruction=closing,
        prohibited_behaviors=(
            "Do not shame or label the student.",
            "Do not invent mastery evidence.",
            "Do not reveal hidden internal reasoning.",
            "Do not skip prerequisite gaps merely to finish quickly.",
            "Do not provide the final answer immediately when guided reasoning is required.",
        ),
    )
