import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from academy_core import (
    ConceptNode,
    InMemoryMemoryRepository,
    JsonlMemoryRepository,
    KnowledgeGraphError,
    LongTermStudentMemoryService,
    MasteryLevel,
    MemoryEventType,
    MemoryPrivacyPolicy,
    MemoryVisibility,
    MisconceptionMemory,
    RevisionScheduler,
    StudentKnowledgeGraph,
)


class LongTermMemoryTests(unittest.TestCase):
    def test_graph_blocks_unmet_prerequisite(self):
        graph = StudentKnowledgeGraph("alin")
        graph.add_concept(
            ConceptNode(
                concept_id="fractions",
                subject="maths",
                name="Fractions",
                mastery=MasteryLevel.DEVELOPING,
            )
        )
        graph.add_concept(
            ConceptNode(
                concept_id="decimals",
                subject="maths",
                name="Decimals",
                prerequisite_ids=("fractions",),
            )
        )
        self.assertIn("decimals", graph.blocked_concepts())

    def test_graph_unblocks_when_prerequisite_mastered(self):
        graph = StudentKnowledgeGraph("alin")
        graph.add_concept(
            ConceptNode(
                concept_id="fractions",
                subject="maths",
                name="Fractions",
                mastery=MasteryLevel.MASTERED,
            )
        )
        graph.add_concept(
            ConceptNode(
                concept_id="decimals",
                subject="maths",
                name="Decimals",
                prerequisite_ids=("fractions",),
            )
        )
        self.assertNotIn("decimals", graph.blocked_concepts())

    def test_learning_path_returns_prerequisites_first(self):
        graph = StudentKnowledgeGraph("alin")
        graph.add_concept(ConceptNode("whole_numbers", "maths", "Whole Numbers"))
        graph.add_concept(
            ConceptNode(
                "fractions",
                "maths",
                "Fractions",
                prerequisite_ids=("whole_numbers",),
            )
        )
        graph.add_concept(
            ConceptNode(
                "decimals",
                "maths",
                "Decimals",
                prerequisite_ids=("fractions",),
            )
        )
        self.assertEqual(
            graph.learning_path("decimals"),
            ("whole_numbers", "fractions", "decimals"),
        )

    def test_cycle_is_rejected(self):
        graph = StudentKnowledgeGraph("alin")
        graph.add_concept(
            ConceptNode("a", "maths", "A", prerequisite_ids=("b",))
        )
        with self.assertRaises(KnowledgeGraphError):
            graph.add_concept(
                ConceptNode("b", "maths", "B", prerequisite_ids=("a",))
            )

    def test_misconception_occurrence_increments(self):
        memory = MisconceptionMemory()
        first = memory.record(
            student_id="alin",
            concept_id="fractions",
            description="Adds denominator directly",
        )
        second = memory.record(
            student_id="alin",
            concept_id="fractions",
            description="Adds denominator directly",
        )
        self.assertEqual(first.misconception_id, second.misconception_id)
        self.assertEqual(second.occurrence_count, 2)

    def test_misconception_can_be_resolved(self):
        memory = MisconceptionMemory()
        record = memory.record(
            student_id="alin",
            concept_id="fractions",
            description="Adds denominator directly",
        )
        resolved = memory.resolve(
            record.misconception_id,
            evidence=("Solved two unlike-denominator examples",),
        )
        self.assertTrue(resolved.resolved)

    def test_revision_scheduler_detects_due_concept(self):
        scheduler = RevisionScheduler()
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        node = ConceptNode(
            concept_id="fractions",
            subject="maths",
            name="Fractions",
            mastery=MasteryLevel.DEVELOPING,
            next_revision_at=past,
        )
        recommendations = scheduler.recommendations("alin", (node,))
        self.assertEqual(recommendations[0].concept_id, "fractions")

    def test_misconception_gets_high_revision_priority(self):
        scheduler = RevisionScheduler()
        node = ConceptNode(
            concept_id="fractions",
            subject="maths",
            name="Fractions",
            mastery=MasteryLevel.DEVELOPING,
            next_revision_at=datetime.now(timezone.utc).isoformat(),
            misconception_ids=("mis1",),
        )
        recommendations = scheduler.recommendations("alin", (node,))
        self.assertEqual(recommendations[0].priority, 90)

    def test_service_records_evidence_and_updates_mastery(self):
        service = LongTermStudentMemoryService()
        service.register_concept(
            "alin",
            ConceptNode(
                concept_id="fractions",
                subject="maths",
                name="Fractions",
            ),
        )
        event = service.record_evidence(
            student_id="alin",
            concept_id="fractions",
            event_type=MemoryEventType.LESSON,
            summary="Solved equivalent fractions",
            evidence_score=0.8,
            mastery=MasteryLevel.PROFICIENT,
        )
        node = service.graph_for("alin").get("fractions")
        self.assertEqual(node.mastery, MasteryLevel.PROFICIENT)
        self.assertEqual(node.evidence_count, 1)
        self.assertEqual(service.profile("alin").event_ids, (event.event_id,))

    def test_guardian_cannot_see_teacher_event(self):
        service = LongTermStudentMemoryService()
        service.register_concept(
            "alin",
            ConceptNode("fractions", "maths", "Fractions"),
        )
        service.record_evidence(
            student_id="alin",
            concept_id="fractions",
            event_type=MemoryEventType.LESSON,
            summary="Teacher-only diagnostic",
            evidence_score=0.5,
            mastery=MasteryLevel.DEVELOPING,
            visibility=MemoryVisibility.TEACHER,
        )
        self.assertEqual(service.shared_memory("alin", "guardian"), ())

    def test_class_teacher_can_see_teacher_event(self):
        service = LongTermStudentMemoryService()
        service.register_concept(
            "alin",
            ConceptNode("fractions", "maths", "Fractions"),
        )
        service.record_evidence(
            student_id="alin",
            concept_id="fractions",
            event_type=MemoryEventType.LESSON,
            summary="Teacher evidence",
            evidence_score=0.7,
            mastery=MasteryLevel.DEVELOPING,
            visibility=MemoryVisibility.TEACHER,
        )
        self.assertEqual(len(service.shared_memory("alin", "class_teacher")), 1)

    def test_jsonl_repository_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.jsonl"
            repo = JsonlMemoryRepository(path)
            service = LongTermStudentMemoryService(repository=repo)
            service.register_concept(
                "alin",
                ConceptNode("fractions", "maths", "Fractions"),
            )
            service.record_evidence(
                student_id="alin",
                concept_id="fractions",
                event_type=MemoryEventType.PRACTICE,
                summary="Practice completed",
                evidence_score=0.9,
                mastery=MasteryLevel.MASTERED,
            )
            loaded = repo.events_for_student("alin")
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].summary, "Practice completed")

    def test_retention_keeps_restricted_event(self):
        policy = MemoryPrivacyPolicy()
        repo = InMemoryMemoryRepository()
        old_time = (datetime.now(timezone.utc) - timedelta(days=800)).isoformat()
        from academy_core import LearningMemoryEvent
        event = LearningMemoryEvent(
            event_id="e1",
            student_id="alin",
            concept_id="fractions",
            event_type=MemoryEventType.LESSON,
            timestamp=old_time,
            summary="Restricted safeguarding evidence",
            evidence_score=0.5,
            visibility=MemoryVisibility.RESTRICTED,
        )
        kept = policy.apply_retention((event,), retention_days=365)
        self.assertEqual(kept, (event,))

    def test_guardian_summary_uses_support_not_labels(self):
        service = LongTermStudentMemoryService()
        service.register_concept(
            "alin",
            ConceptNode(
                concept_id="fractions",
                subject="maths",
                name="Equivalent Fractions",
                mastery=MasteryLevel.NEEDS_REVISION,
            ),
        )
        summary = " ".join(service.guardian_summary("alin")).lower()
        self.assertIn("support area", summary)
        self.assertNotIn("weak child", summary)

    def test_graph_snapshot_serializes(self):
        graph = StudentKnowledgeGraph("alin")
        graph.add_concept(
            ConceptNode(
                concept_id="fractions",
                subject="maths",
                name="Fractions",
            )
        )
        data = graph.snapshot(revision_due=("fractions",)).to_dict()
        self.assertEqual(data["student_id"], "alin")
        self.assertEqual(data["revision_due"], ("fractions",))


if __name__ == "__main__":
    unittest.main()
