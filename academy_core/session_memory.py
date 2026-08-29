from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import DefaultDict, Dict, Iterable, Tuple

from .classroom_models import (
    LessonSession,
    LessonStage,
    ProgressEvent,
    SessionAuditRecord,
    SessionOutcome,
)


class ClassroomSessionMemory:
    """In-memory session store with deterministic audit reconstruction."""

    def __init__(self) -> None:
        self._sessions: Dict[str, LessonSession] = {}
        self._stages: DefaultDict[str, list[LessonStage]] = defaultdict(list)
        self._strategies: DefaultDict[str, list[str]] = defaultdict(list)
        self._progress: DefaultDict[str, list[ProgressEvent]] = defaultdict(list)

    def create(self, session: LessonSession) -> None:
        session.validate()
        if session.session_id in self._sessions:
            raise ValueError(f"duplicate session_id: {session.session_id}")
        self._sessions[session.session_id] = session
        self._stages[session.session_id].append(session.stage)
        if session.last_strategy:
            self._strategies[session.session_id].append(session.last_strategy)

    def get(self, session_id: str) -> LessonSession:
        return self._sessions[session_id]

    def save(self, session: LessonSession) -> None:
        session.validate()
        self._sessions[session.session_id] = session
        if (
            not self._stages[session.session_id]
            or self._stages[session.session_id][-1] != session.stage
        ):
            self._stages[session.session_id].append(session.stage)
        if session.last_strategy:
            if (
                not self._strategies[session.session_id]
                or self._strategies[session.session_id][-1] != session.last_strategy
            ):
                self._strategies[session.session_id].append(session.last_strategy)

    def add_progress(self, event: ProgressEvent) -> None:
        self._progress[event.session_id].append(event)

    def progress_for(self, session_id: str) -> Tuple[ProgressEvent, ...]:
        return tuple(self._progress[session_id])

    def build_audit(self, session_id: str) -> SessionAuditRecord:
        session = self.get(session_id)
        progress = self.progress_for(session_id)
        summary = (
            f"Session {session.session_id} for {session.topic} ended with "
            f"{session.outcome.value}. Progress events={len(progress)}."
        )
        return SessionAuditRecord(
            session_id=session.session_id,
            student_id=session.student_id,
            teacher_name=session.teacher_name,
            subject=session.subject,
            topic=session.topic,
            stages_visited=tuple(self._stages[session_id]),
            strategies_used=tuple(self._strategies[session_id]),
            mistakes_observed=session.mistakes,
            homework_ids=session.homework_ids,
            revision_topics=session.revision_topics,
            outcome=session.outcome,
            summary=summary,
        )
