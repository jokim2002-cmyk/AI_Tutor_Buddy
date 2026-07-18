from __future__ import annotations

from dataclasses import replace
from typing import Dict, Iterable, Mapping, Sequence, Tuple

from .classroom_models import GoalStatus, LearningGoal


class LearningGoalManager:
    def __init__(self, goals: Sequence[LearningGoal] = ()) -> None:
        self._goals: Dict[str, LearningGoal] = {}
        for goal in goals:
            self.register(goal)

    def register(self, goal: LearningGoal) -> None:
        goal.validate()
        if goal.goal_id in self._goals:
            raise ValueError(f"duplicate goal_id: {goal.goal_id}")
        self._goals[goal.goal_id] = goal

    def get(self, goal_id: str) -> LearningGoal:
        return self._goals[goal_id]

    def all(self) -> Tuple[LearningGoal, ...]:
        return tuple(self._goals.values())

    def activate_available_goals(self) -> Tuple[str, ...]:
        changed = []
        for goal_id, goal in list(self._goals.items()):
            if goal.status != GoalStatus.LOCKED:
                continue
            if all(
                self._goals[item].status == GoalStatus.COMPLETED
                for item in goal.prerequisite_goal_ids
            ):
                self._goals[goal_id] = replace(goal, status=GoalStatus.ACTIVE)
                changed.append(goal_id)
        return tuple(changed)

    def complete_goal(
        self,
        goal_id: str,
        *,
        evidence_count: int,
    ) -> Tuple[str, ...]:
        goal = self.get(goal_id)
        if evidence_count < goal.evidence_required:
            self._goals[goal_id] = replace(
                goal,
                status=GoalStatus.NEEDS_REVISION,
            )
            return ()

        self._goals[goal_id] = replace(goal, status=GoalStatus.COMPLETED)
        return self.activate_available_goals()

    def mark_revision(self, goal_id: str) -> None:
        goal = self.get(goal_id)
        self._goals[goal_id] = replace(
            goal,
            status=GoalStatus.NEEDS_REVISION,
        )

    def active_goals(self) -> Tuple[LearningGoal, ...]:
        return tuple(
            goal for goal in self._goals.values()
            if goal.status == GoalStatus.ACTIVE
        )
