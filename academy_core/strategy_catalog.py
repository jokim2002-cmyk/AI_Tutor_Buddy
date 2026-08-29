from __future__ import annotations

from typing import Dict, Tuple

from .strategy_models import StrategyDefinition, StrategyKey


STRATEGY_CATALOG: Dict[StrategyKey, StrategyDefinition] = {
    StrategyKey.STEP_BY_STEP: StrategyDefinition(
        key=StrategyKey.STEP_BY_STEP,
        title="Step-by-Step",
        description="Break the concept into one visible reasoning step at a time.",
        compatible_subjects=("*",),
        compatible_actions=(
            "check_prerequisites",
            "give_hint",
            "explain",
            "guided_practice",
            "revise",
        ),
        strengths=("reduces overload", "supports confused learners"),
    ),
    StrategyKey.WORKED_EXAMPLE: StrategyDefinition(
        key=StrategyKey.WORKED_EXAMPLE,
        title="Worked Example",
        description="Model one complete example while explaining each decision.",
        compatible_subjects=("maths", "science", "computer"),
        compatible_actions=("explain", "guided_practice", "revise"),
        strengths=("makes hidden steps visible", "supports procedural learning"),
    ),
    StrategyKey.ANALOGY: StrategyDefinition(
        key=StrategyKey.ANALOGY,
        title="Analogy",
        description="Connect the new concept to a familiar real-world idea.",
        compatible_subjects=("*",),
        compatible_actions=("explain", "give_hint", "check_prerequisites"),
        strengths=("activates prior knowledge", "improves comprehension"),
        cautions=("state where the analogy stops matching"),
    ),
    StrategyKey.SOCRATIC_QUESTIONING: StrategyDefinition(
        key=StrategyKey.SOCRATIC_QUESTIONING,
        title="Socratic Questioning",
        description="Guide the student through short questions instead of giving the result.",
        compatible_subjects=("*",),
        compatible_actions=(
            "give_hint",
            "guided_practice",
            "independent_practice",
            "extend",
        ),
        strengths=("reveals reasoning", "builds independence"),
        cautions=("avoid long interrogation chains"),
    ),
    StrategyKey.VISUAL_EXPLANATION: StrategyDefinition(
        key=StrategyKey.VISUAL_EXPLANATION,
        title="Visual Explanation",
        description="Use mental images, diagrams, spatial layouts, or symbolic grouping.",
        compatible_subjects=("maths", "science", "computer", "social_science"),
        compatible_actions=("explain", "guided_practice", "revise"),
        strengths=("supports abstract concepts", "improves structure recognition"),
    ),
    StrategyKey.STORY_BASED: StrategyDefinition(
        key=StrategyKey.STORY_BASED,
        title="Story-Based Teaching",
        description="Teach through a short narrative with a clear learning purpose.",
        compatible_subjects=("english", "hindi", "social_science", "science"),
        compatible_actions=("explain", "revise"),
        strengths=("improves recall", "adds meaningful context"),
        cautions=("keep the story short and concept-focused"),
    ),
    StrategyKey.OBSERVATION_EXPERIMENT: StrategyDefinition(
        key=StrategyKey.OBSERVATION_EXPERIMENT,
        title="Observation or Experiment",
        description="Begin with an observation, prediction, or safe mini-experiment.",
        compatible_subjects=("science",),
        compatible_actions=("explain", "guided_practice", "extend"),
        strengths=("builds scientific thinking", "connects evidence to concepts"),
        cautions=("never suggest unsafe experiments"),
    ),
    StrategyKey.RETRIEVAL_PRACTICE: StrategyDefinition(
        key=StrategyKey.RETRIEVAL_PRACTICE,
        title="Retrieval Practice",
        description="Ask the student to recall prior learning before reviewing it.",
        compatible_subjects=("*",),
        compatible_actions=("revise", "independent_practice", "extend"),
        strengths=("strengthens memory", "reveals forgotten foundations"),
    ),
    StrategyKey.ERROR_CORRECTION: StrategyDefinition(
        key=StrategyKey.ERROR_CORRECTION,
        title="Error Correction",
        description="Use the student's error as evidence and repair the exact misconception.",
        compatible_subjects=("*",),
        compatible_actions=("give_hint", "explain", "guided_practice", "revise"),
        strengths=("targets misconceptions", "prevents repeated mistakes"),
        cautions=("correct the idea, never shame the learner"),
    ),
    StrategyKey.DEBUGGING: StrategyDefinition(
        key=StrategyKey.DEBUGGING,
        title="Debugging",
        description="Trace the problem, test assumptions, isolate the fault, and repair it.",
        compatible_subjects=("computer", "maths"),
        compatible_actions=("give_hint", "guided_practice", "extend"),
        strengths=("builds logical diagnosis", "supports coding and reasoning"),
    ),
    StrategyKey.COMMUNICATION_PRACTICE: StrategyDefinition(
        key=StrategyKey.COMMUNICATION_PRACTICE,
        title="Communication Practice",
        description="Practice speaking, writing, vocabulary, grammar, or expression in context.",
        compatible_subjects=("english", "hindi"),
        compatible_actions=("guided_practice", "independent_practice", "extend"),
        strengths=("builds usable language", "supports feedback and revision"),
    ),
    StrategyKey.TIMELINE_CAUSE_EFFECT: StrategyDefinition(
        key=StrategyKey.TIMELINE_CAUSE_EFFECT,
        title="Timeline and Cause-Effect",
        description="Organize events, causes, consequences, and connections explicitly.",
        compatible_subjects=("social_science",),
        compatible_actions=("explain", "revise", "extend"),
        strengths=("improves historical reasoning", "organizes complex events"),
    ),
    StrategyKey.TRANSFER_CHALLENGE: StrategyDefinition(
        key=StrategyKey.TRANSFER_CHALLENGE,
        title="Transfer Challenge",
        description="Apply the concept in a new context after understanding is demonstrated.",
        compatible_subjects=("*",),
        compatible_actions=("extend", "independent_practice"),
        strengths=("tests real understanding", "builds flexible knowledge"),
    ),
    StrategyKey.CONFIDENCE_REBUILD: StrategyDefinition(
        key=StrategyKey.CONFIDENCE_REBUILD,
        title="Confidence Rebuild",
        description="Use an achievable first step, specific encouragement, and gradual challenge.",
        compatible_subjects=("*",),
        compatible_actions=(
            "check_prerequisites",
            "give_hint",
            "explain",
            "guided_practice",
            "revise",
        ),
        strengths=("reduces fear", "restores participation"),
        cautions=("praise effort and strategy, not fixed ability"),
    ),
}


def get_strategy(key: StrategyKey) -> StrategyDefinition:
    return STRATEGY_CATALOG[key]


def all_strategies() -> Tuple[StrategyDefinition, ...]:
    return tuple(STRATEGY_CATALOG.values())
