from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Tuple

from .memory_models import LearningMemoryEvent, MemoryVisibility


class MemoryAccessError(PermissionError):
    pass


class MemoryPrivacyPolicy:
    _ROLE_ACCESS = {
        "student": {
            MemoryVisibility.STUDENT,
        },
        "subject_teacher": {
            MemoryVisibility.STUDENT,
            MemoryVisibility.TEACHER,
        },
        "class_teacher": {
            MemoryVisibility.STUDENT,
            MemoryVisibility.TEACHER,
            MemoryVisibility.CLASS_TEACHER,
        },
        "principal": {
            MemoryVisibility.STUDENT,
            MemoryVisibility.TEACHER,
            MemoryVisibility.CLASS_TEACHER,
            MemoryVisibility.PRINCIPAL,
        },
        "guardian": {
            MemoryVisibility.GUARDIAN_SUMMARY,
        },
        "safeguarding": set(MemoryVisibility),
    }

    def can_view(self, role: str, event: LearningMemoryEvent) -> bool:
        allowed = self._ROLE_ACCESS.get(role, set())
        return event.visibility in allowed

    def filter_for_role(
        self,
        role: str,
        events: Iterable[LearningMemoryEvent],
    ) -> Tuple[LearningMemoryEvent, ...]:
        return tuple(event for event in events if self.can_view(role, event))

    def retention_cutoff(
        self,
        *,
        now: datetime | None = None,
        retention_days: int = 365,
    ) -> datetime:
        if retention_days < 1:
            raise ValueError("retention_days must be positive")
        current = now or datetime.now(timezone.utc)
        return current - timedelta(days=retention_days)

    def apply_retention(
        self,
        events: Iterable[LearningMemoryEvent],
        *,
        now: datetime | None = None,
        retention_days: int = 365,
    ) -> Tuple[LearningMemoryEvent, ...]:
        cutoff = self.retention_cutoff(
            now=now,
            retention_days=retention_days,
        )
        kept = []
        for event in events:
            timestamp = datetime.fromisoformat(event.timestamp)
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            if event.visibility == MemoryVisibility.RESTRICTED:
                kept.append(event)
            elif timestamp >= cutoff:
                kept.append(event)
        return tuple(kept)
