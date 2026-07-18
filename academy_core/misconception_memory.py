from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Dict, Tuple
from uuid import uuid4

from .memory_models import MisconceptionRecord


class MisconceptionMemory:
    def __init__(self) -> None:
        self._records: Dict[str, MisconceptionRecord] = {}

    def record(
        self,
        *,
        student_id: str,
        concept_id: str,
        description: str,
        timestamp: str | None = None,
    ) -> MisconceptionRecord:
        now = timestamp or datetime.now(timezone.utc).isoformat()
        normalized = description.strip().lower()

        for record_id, record in list(self._records.items()):
            if (
                record.student_id == student_id
                and record.concept_id == concept_id
                and record.description.strip().lower() == normalized
                and not record.resolved
            ):
                updated = replace(
                    record,
                    last_seen_at=now,
                    occurrence_count=record.occurrence_count + 1,
                )
                self._records[record_id] = updated
                return updated

        record = MisconceptionRecord(
            misconception_id=f"mis_{uuid4().hex[:12]}",
            student_id=student_id,
            concept_id=concept_id,
            description=description.strip(),
            first_seen_at=now,
            last_seen_at=now,
        )
        record.validate()
        self._records[record.misconception_id] = record
        return record

    def resolve(
        self,
        misconception_id: str,
        *,
        evidence: Tuple[str, ...],
    ) -> MisconceptionRecord:
        record = self._records[misconception_id]
        updated = replace(
            record,
            resolved=True,
            resolution_evidence=tuple(dict.fromkeys(evidence)),
        )
        self._records[misconception_id] = updated
        return updated

    def unresolved_for_concept(
        self,
        student_id: str,
        concept_id: str,
    ) -> Tuple[MisconceptionRecord, ...]:
        return tuple(
            record
            for record in self._records.values()
            if (
                record.student_id == student_id
                and record.concept_id == concept_id
                and not record.resolved
            )
        )

    def all(self) -> Tuple[MisconceptionRecord, ...]:
        return tuple(self._records.values())
