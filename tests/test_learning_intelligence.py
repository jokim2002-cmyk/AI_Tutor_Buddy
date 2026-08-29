import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from academy_core import (ConceptNode, LearningIntelligenceService, LongTermStudentMemoryService, MasteryLevel,
    MemoryEventType, ReadinessBand, TrendDirection)


class LearningIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.memory=LongTermStudentMemoryService()
        self.memory.register_concept("s1",ConceptNode("whole","maths","Whole Numbers",mastery=MasteryLevel.MASTERED,confidence_score=.9,evidence_count=3))
        self.memory.register_concept("s1",ConceptNode("fractions","maths","Fractions",prerequisite_ids=("whole",),mastery=MasteryLevel.DEVELOPING,confidence_score=.55,evidence_count=2))
        self.memory.register_concept("s1",ConceptNode("decimals","maths","Decimals",prerequisite_ids=("fractions",)))
        self.service=LearningIntelligenceService(self.memory)

    def record(self, concept, score, mastery):
        return self.memory.record_evidence(student_id="s1",concept_id=concept,event_type=MemoryEventType.PRACTICE,
            summary="Evidence",evidence_score=score,mastery=mastery)

    def test_profile_contains_registered_concepts(self):
        self.assertEqual(len(self.service.build_profile("s1").concepts),3)

    def test_blocked_prerequisite_increases_priority_reason(self):
        p=self.service.build_profile("s1"); d=next(c for c in p.concepts if c.concept_id=="decimals")
        self.assertTrue(any("prerequisite" in r.lower() for r in d.reasons))

    def test_subject_aggregation(self):
        p=self.service.build_profile("s1")
        self.assertEqual(p.subjects[0].subject,"maths"); self.assertEqual(len(p.subjects[0].priority_concepts),3)

    def test_sparse_evidence_reports_uncertainty(self):
        report=self.service.build_profile("s1").exam_readiness
        self.assertEqual(report.readiness_band,ReadinessBand.INSUFFICIENT_EVIDENCE)
        self.assertTrue(report.uncertainty_reasons)

    def test_evidence_confidence_is_bounded(self):
        for _ in range(10): self.record("fractions",.8,MasteryLevel.PROFICIENT)
        r=self.service.build_profile("s1").exam_readiness
        self.assertGreaterEqual(r.evidence_confidence,0); self.assertLessEqual(r.evidence_confidence,1)

    def test_readiness_is_not_deterministic_claim(self):
        s=self.service.summary(self.service.build_profile("s1"),"guardian")
        self.assertIn("not a fixed prediction",s.headline)

    def test_guardian_summary_uses_support_language(self):
        s=self.service.summary(self.service.build_profile("s1"),"guardian")
        self.assertTrue(all(x.startswith("Support area:") for x in s.support_areas))
        self.assertNotIn("weak child"," ".join(s.support_areas).lower())

    def test_unknown_audience_is_rejected(self):
        with self.assertRaises(ValueError): self.service.summary(self.service.build_profile("s1"),"public")

    def test_revision_plan_orders_high_priority_first(self):
        p=self.service.build_profile("s1")
        scores=[next(c.priority_score for c in p.concepts if c.concept_id==i.concept_id) for i in p.revision_plan]
        self.assertEqual(scores,sorted(scores,reverse=True))

    def test_revision_plan_includes_prerequisite_first(self):
        p=self.service.build_profile("s1")
        d=next(i for i in p.revision_plan if i.concept_id=="decimals")
        self.assertIn("fractions",d.prerequisite_first)

    def test_misconception_changes_action(self):
        self.memory.record_evidence(student_id="s1",concept_id="fractions",event_type=MemoryEventType.MISCONCEPTION,
            summary="Error",evidence_score=.3,mastery=MasteryLevel.NEEDS_REVISION,misconception="Adds denominators")
        p=self.service.build_profile("s1"); i=next(x for x in p.revision_plan if x.concept_id=="fractions")
        self.assertEqual(i.suggested_action,"targeted misconception repair")

    def test_learning_velocity_detects_improvement(self):
        for score in (.2,.3,.8,.9): self.record("fractions",score,MasteryLevel.DEVELOPING)
        self.assertEqual(self.service.build_profile("s1").effort_trend,TrendDirection.IMPROVING)

    def test_learning_velocity_detects_decline(self):
        for score in (.9,.8,.3,.2): self.record("fractions",score,MasteryLevel.DEVELOPING)
        self.assertEqual(self.service.build_profile("s1").effort_trend,TrendDirection.DECLINING)

    def test_exam_report_serializes_enum(self):
        data=self.service.build_profile("s1").exam_readiness.to_dict()
        self.assertIsInstance(data["readiness_band"],str)

    def test_student_isolation(self):
        self.memory.register_concept("s2",ConceptNode("letters","english","Letters"))
        self.assertEqual(len(self.service.build_profile("s2").concepts),1)
        self.assertEqual(len(self.service.build_profile("s1").concepts),3)

    def test_empty_student_profile_is_safe(self):
        p=self.service.build_profile("empty")
        self.assertEqual(p.exam_readiness.readiness_score,0.0)
        self.assertEqual(p.revision_plan,())

    def test_scores_remain_bounded(self):
        p=self.service.build_profile("s1")
        self.assertTrue(all(0<=c.priority_score<=100 for c in p.concepts))
        self.assertTrue(0<=p.exam_readiness.readiness_score<=1)

    def test_teacher_summary_contains_actions(self):
        s=self.service.summary(self.service.build_profile("s1"),"teacher")
        self.assertTrue(s.next_actions)

if __name__=='__main__': unittest.main()
