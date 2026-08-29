from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Sequence, Tuple

from .memory_models import (
    ConceptNode,
    MasteryLevel,
    RevisionRecommendation,
)


class RevisionScheduler:
    _INTERVAL_DAYS = {
        MasteryLevel.UNKNOWN: 0,
        MasteryLevel.INTRODUCED: 1,
        MasteryLevel.DEVELOPING: 2,
        MasteryLevel.PROFICIENT: 7,
        MasteryLevel.MASTERED: 21,
        MasteryLevel.NEEDS_REVISION: 0,
    }

    def schedule_next(
        self,
        node: ConceptNode,
        *,
        from_time: datetime | None = None,
    ) -> str:
        node.validate()
        now = from_time or datetime.now(timezone.utc)
        days = self._INTERVAL_DAYS[node.mastery]
        return (now + timedelta(days=days)).isoformat()

    def forgetting_risk(
        self,
        node: ConceptNode,
        *,
        now: datetime | None = None,
    ) -> bool:
        if not node.next_revision_at:
            return node.mastery in {
                MasteryLevel.INTRODUCED,
                MasteryLevel.DEVELOPING,
                MasteryLevel.NEEDS_REVISION,
            }

        current = now or datetime.now(timezone.utc)
        due = datetime.fromisoformat(node.next_revision_at)
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        return current >= due

    def recommendations(
        self,
        student_id: str,
        nodes: Sequence[ConceptNode],
        *,
        now: datetime | None = None,
    ) -> Tuple[RevisionRecommendation, ...]:
        current = now or datetime.now(timezone.utc)
        items: List[RevisionRecommendation] = []

        for node in nodes:
            if not self.forgetting_risk(node, now=current):
                continue

            priority = self._priority(node)
            reason = self._reason(node)
            strategy = self._strategy(node)
            due_at = node.next_revision_at or current.isoformat()

            items.append(
                RevisionRecommendation(
                    student_id=student_id,
                    concept_id=node.concept_id,
                    reason=reason,
                    priority=priority,
                    due_at=due_at,
                    suggested_strategy=strategy,
                )
            )

        return tuple(
            sorted(items, key=lambda item: (-item.priority, item.due_at, item.concept_id))
        )

    @staticmethod
    def _priority(node: ConceptNode) -> int:
        if node.mastery == MasteryLevel.NEEDS_REVISION:
            return 100
        if node.misconception_ids:
            return 90
        if node.mastery == MasteryLevel.DEVELOPING:
            return 75
        if node.mastery == MasteryLevel.INTRODUCED:
            return 60
        if node.mastery == MasteryLevel.PROFICIENT:
            return 40
        return 25

    @staticmethod
    def _reason(node: ConceptNode) -> str:
        if node.misconception_ids:
            return "Known misconception requires targeted revision."
        if node.mastery == MasteryLevel.NEEDS_REVISION:
            return "Recent evidence shows the concept needs revision."
        return "Revision is due to reduce forgetting risk."

    @staticmethod
    def _strategy(node: ConceptNode) -> str:
        if node.misconception_ids:
            return "misconception_repair"
        if node.mastery in {
            MasteryLevel.INTRODUCED,
            MasteryLevel.DEVELOPING,
        }:
            return "guided_retrieval_practice"
        return "spaced_recall"
