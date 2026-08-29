from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict
import json
from pathlib import Path
from typing import Dict, Iterable, Tuple

from .memory_models import (
    LearningMemoryEvent,
    MemoryEventType,
    MemoryVisibility,
)


class MemoryRepository(ABC):
    @abstractmethod
    def save_event(self, event: LearningMemoryEvent) -> None:
        raise NotImplementedError

    @abstractmethod
    def events_for_student(self, student_id: str) -> Tuple[LearningMemoryEvent, ...]:
        raise NotImplementedError


class InMemoryMemoryRepository(MemoryRepository):
    def __init__(self) -> None:
        self._events: Dict[str, LearningMemoryEvent] = {}

    def save_event(self, event: LearningMemoryEvent) -> None:
        event.validate()
        self._events[event.event_id] = event

    def events_for_student(self, student_id: str) -> Tuple[LearningMemoryEvent, ...]:
        return tuple(
            event
            for event in self._events.values()
            if event.student_id == student_id
        )


class JsonlMemoryRepository(MemoryRepository):
    """Simple durable boundary for local development and migration testing."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save_event(self, event: LearningMemoryEvent) -> None:
        event.validate()
        data = asdict(event)
        data["event_type"] = event.event_type.value
        data["visibility"] = event.visibility.value
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(data, ensure_ascii=False) + "\n")

    def events_for_student(self, student_id: str) -> Tuple[LearningMemoryEvent, ...]:
        if not self.path.exists():
            return ()

        events = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            if data["student_id"] != student_id:
                continue
            events.append(
                LearningMemoryEvent(
                    event_id=data["event_id"],
                    student_id=data["student_id"],
                    concept_id=data["concept_id"],
                    event_type=MemoryEventType(data["event_type"]),
                    timestamp=data["timestamp"],
                    summary=data["summary"],
                    evidence_score=float(data["evidence_score"]),
                    visibility=MemoryVisibility(data["visibility"]),
                    source_session_id=data.get("source_session_id", ""),
                    tags=tuple(data.get("tags", ())),
                )
            )
        return tuple(events)
