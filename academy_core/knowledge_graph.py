from __future__ import annotations

from dataclasses import replace
from typing import Dict, Iterable, List, Sequence, Tuple

from .memory_models import ConceptNode, KnowledgeGraphSnapshot, MasteryLevel


class KnowledgeGraphError(ValueError):
    pass


class StudentKnowledgeGraph:
    def __init__(self, student_id: str) -> None:
        if not student_id.strip():
            raise ValueError("student_id is required")
        self.student_id = student_id
        self._nodes: Dict[str, ConceptNode] = {}

    def add_concept(self, node: ConceptNode) -> None:
        node.validate()
        if node.concept_id in self._nodes:
            raise KnowledgeGraphError(f"duplicate concept_id: {node.concept_id}")
        self._nodes[node.concept_id] = node
        self._assert_no_cycle()

    def upsert_concept(self, node: ConceptNode) -> None:
        node.validate()
        previous = self._nodes.get(node.concept_id)
        self._nodes[node.concept_id] = node
        try:
            self._assert_no_cycle()
        except Exception:
            if previous is None:
                self._nodes.pop(node.concept_id, None)
            else:
                self._nodes[node.concept_id] = previous
            raise

    def get(self, concept_id: str) -> ConceptNode:
        return self._nodes[concept_id]

    def all_nodes(self) -> Tuple[ConceptNode, ...]:
        return tuple(self._nodes.values())

    def prerequisites_met(self, concept_id: str) -> bool:
        node = self.get(concept_id)
        for prereq_id in node.prerequisite_ids:
            prereq = self._nodes.get(prereq_id)
            if prereq is None:
                return False
            if prereq.mastery not in {
                MasteryLevel.PROFICIENT,
                MasteryLevel.MASTERED,
            }:
                return False
        return True

    def blocked_concepts(self) -> Tuple[str, ...]:
        blocked = [
            node.concept_id
            for node in self._nodes.values()
            if node.prerequisite_ids and not self.prerequisites_met(node.concept_id)
        ]
        return tuple(sorted(blocked))

    def update_mastery(
        self,
        concept_id: str,
        *,
        mastery: MasteryLevel,
        confidence_score: float,
        evidence_count: int,
        last_evidence_at: str,
        next_revision_at: str = "",
        misconception_ids: Sequence[str] = (),
    ) -> ConceptNode:
        node = self.get(concept_id)
        updated = replace(
            node,
            mastery=mastery,
            confidence_score=confidence_score,
            evidence_count=evidence_count,
            last_evidence_at=last_evidence_at,
            next_revision_at=next_revision_at,
            misconception_ids=tuple(dict.fromkeys(misconception_ids)),
        )
        updated.validate()
        self._nodes[concept_id] = updated
        return updated

    def learning_path(self, concept_id: str) -> Tuple[str, ...]:
        if concept_id not in self._nodes:
            raise KeyError(concept_id)

        ordered: List[str] = []
        visited: set[str] = set()

        def walk(current: str) -> None:
            if current in visited:
                return
            visited.add(current)
            node = self._nodes[current]
            for prereq in node.prerequisite_ids:
                if prereq not in self._nodes:
                    raise KnowledgeGraphError(
                        f"missing prerequisite {prereq} for {current}"
                    )
                walk(prereq)
            ordered.append(current)

        walk(concept_id)
        return tuple(ordered)

    def snapshot(self, *, revision_due: Sequence[str] = ()) -> KnowledgeGraphSnapshot:
        edges = []
        for node in self._nodes.values():
            for prereq in node.prerequisite_ids:
                edges.append((prereq, node.concept_id))
        return KnowledgeGraphSnapshot(
            student_id=self.student_id,
            nodes=self.all_nodes(),
            edges=tuple(edges),
            blocked_concepts=self.blocked_concepts(),
            revision_due=tuple(revision_due),
        )

    def _assert_no_cycle(self) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise KnowledgeGraphError("knowledge graph cycle detected")
            if node_id in visited:
                return
            visiting.add(node_id)
            node = self._nodes[node_id]
            for prereq in node.prerequisite_ids:
                if prereq in self._nodes:
                    visit(prereq)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in tuple(self._nodes):
            visit(node_id)
