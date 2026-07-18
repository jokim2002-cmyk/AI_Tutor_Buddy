from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Dict, Mapping, Sequence, Tuple
from uuid import uuid4

from .knowledge_graph import StudentKnowledgeGraph
from .memory_models import (
    ConceptNode,
    LearningMemoryEvent,
    MasteryLevel,
    MemoryEventType,
    MemoryVisibility,
    StudentMemoryProfile,
)
from .memory_privacy import MemoryPrivacyPolicy
from .memory_repository import InMemoryMemoryRepository, MemoryRepository
from .misconception_memory import MisconceptionMemory
from .revision_scheduler import RevisionScheduler


class LongTermStudentMemoryService:
    def __init__(
        self,
        *,
        repository: MemoryRepository | None = None,
        privacy: MemoryPrivacyPolicy | None = None,
        scheduler: RevisionScheduler | None = None,
        misconceptions: MisconceptionMemory | None = None,
    ) -> None:
        self.repository = repository or InMemoryMemoryRepository()
        self.privacy = privacy or MemoryPrivacyPolicy()
        self.scheduler = scheduler or RevisionScheduler()
        self.misconceptions = misconceptions or MisconceptionMemory()
        self._graphs: Dict[str, StudentKnowledgeGraph] = {}
        self._profiles: Dict[str, StudentMemoryProfile] = {}

    def graph_for(self, student_id: str) -> StudentKnowledgeGraph:
        if student_id not in self._graphs:
            self._graphs[student_id] = StudentKnowledgeGraph(student_id)
        return self._graphs[student_id]

    def register_concept(self, student_id: str, node: ConceptNode) -> None:
        graph = self.graph_for(student_id)
        graph.add_concept(node)
        profile = self._profiles.get(
            student_id,
            StudentMemoryProfile(student_id=student_id),
        )
        self._profiles[student_id] = replace(
            profile,
            concept_ids=tuple(dict.fromkeys(profile.concept_ids + (node.concept_id,))),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

    def record_evidence(
        self,
        *,
        student_id: str,
        concept_id: str,
        event_type: MemoryEventType,
        summary: str,
        evidence_score: float,
        mastery: MasteryLevel,
        visibility: MemoryVisibility = MemoryVisibility.TEACHER,
        source_session_id: str = "",
        misconception: str = "",
    ) -> LearningMemoryEvent:
        now = datetime.now(timezone.utc)
        graph = self.graph_for(student_id)
        node = graph.get(concept_id)

        misconception_ids = list(node.misconception_ids)
        if misconception.strip():
            record = self.misconceptions.record(
                student_id=student_id,
                concept_id=concept_id,
                description=misconception,
                timestamp=now.isoformat(),
            )
            misconception_ids.append(record.misconception_id)

        next_revision_at = self.scheduler.schedule_next(
            replace(node, mastery=mastery),
            from_time=now,
        )
        updated = graph.update_mastery(
            concept_id,
            mastery=mastery,
            confidence_score=evidence_score,
            evidence_count=node.evidence_count + 1,
            last_evidence_at=now.isoformat(),
            next_revision_at=next_revision_at,
            misconception_ids=tuple(dict.fromkeys(misconception_ids)),
        )

        event = LearningMemoryEvent(
            event_id=f"mem_{uuid4().hex[:12]}",
            student_id=student_id,
            concept_id=concept_id,
            event_type=event_type,
            timestamp=now.isoformat(),
            summary=summary,
            evidence_score=evidence_score,
            visibility=visibility,
            source_session_id=source_session_id,
            tags=(mastery.value,),
        )
        event.validate()
        self.repository.save_event(event)

        profile = self._profiles.get(
            student_id,
            StudentMemoryProfile(student_id=student_id),
        )
        self._profiles[student_id] = replace(
            profile,
            event_ids=tuple(dict.fromkeys(profile.event_ids + (event.event_id,))),
            misconception_ids=tuple(
                dict.fromkeys(profile.misconception_ids + tuple(misconception_ids))
            ),
            revision_queue=tuple(
                item.concept_id
                for item in self.scheduler.recommendations(
                    student_id,
                    graph.all_nodes(),
                    now=now,
                )
            ),
            updated_at=now.isoformat(),
        )
        return event

    def revision_recommendations(self, student_id: str):
        graph = self.graph_for(student_id)
        return self.scheduler.recommendations(
            student_id,
            graph.all_nodes(),
        )

    def shared_memory(self, student_id: str, role: str):
        events = self.repository.events_for_student(student_id)
        return self.privacy.filter_for_role(role, events)

    def profile(self, student_id: str) -> StudentMemoryProfile:
        return self._profiles.get(
            student_id,
            StudentMemoryProfile(student_id=student_id),
        )

    def guardian_summary(self, student_id: str) -> Tuple[str, ...]:
        graph = self.graph_for(student_id)
        lines = []
        for node in graph.all_nodes():
            if node.mastery in {MasteryLevel.PROFICIENT, MasteryLevel.MASTERED}:
                lines.append(f"Strength: {node.name}")
            elif node.mastery in {
                MasteryLevel.DEVELOPING,
                MasteryLevel.NEEDS_REVISION,
            }:
                lines.append(f"Support area: {node.name}")
        return tuple(lines)
