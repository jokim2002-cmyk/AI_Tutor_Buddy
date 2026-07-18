import unittest

from academy_core import Academy
from academy_core.reasoning_engine import (
    DifficultyDirection,
    StepSize,
    TeacherReasoningEngine,
    TeachingAction,
)
from academy_core.reasoning_service import ReasoningService
from academy_core.student_analyzer import (
    ConfidenceLevel,
    RevisionNeed,
    StudentAnalysis,
    UnderstandingState,
)
from academy_core.teaching_plan import build_teaching_plan


def analysis(
    *,
    subject="maths",
    topic="fractions",
    confidence=ConfidenceLevel.MEDIUM,
    understanding=UnderstandingState.DEVELOPING,
    revision=RevisionNeed.NONE,
    prerequisite=False,
    clarify=False,
    methods=("guided_practice",),
):
    return StudentAnalysis(
        student_id="s1",
        class_level=7,
        preferred_language="auto",
        subject=subject,
        topic=topic,
        confidence=confidence,
        understanding=understanding,
        revision_need=revision,
        recommended_teacher_subject=subject or "class_guidance",
        recommended_methods=methods,
        needs_prerequisite_check=prerequisite,
        should_ask_clarifying_question=clarify,
        evidence=(),
        safe_summary="temporary learning signal",
    )


class TeacherReasoningEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = TeacherReasoningEngine()
        self.academy = Academy()
        self.math_teacher = self.academy.route(subject="maths")

    def test_missing_context_clarifies(self):
        decision = self.engine.decide(
            analysis(subject="", topic="", clarify=True),
            self.academy.route(subject=""),
        )
        self.assertEqual(decision.action, TeachingAction.CLARIFY)
        self.assertFalse(decision.reveal_final_answer_immediately)

    def test_prerequisite_gap_has_priority(self):
        decision = self.engine.decide(
            analysis(
                confidence=ConfidenceLevel.LOW,
                understanding=UnderstandingState.CONFUSED,
                prerequisite=True,
            ),
            self.math_teacher,
        )
        self.assertEqual(decision.action, TeachingAction.CHECK_PREREQUISITES)
        self.assertTrue(decision.prerequisite_check_required)
        self.assertEqual(decision.step_size, StepSize.VERY_SMALL)
        self.assertEqual(decision.difficulty_direction, DifficultyDirection.REDUCE)

    def test_guessing_receives_hint(self):
        decision = self.engine.decide(
            analysis(understanding=UnderstandingState.GUESSING),
            self.math_teacher,
        )
        self.assertEqual(decision.action, TeachingAction.GIVE_HINT)
        self.assertIn("progressive_hint", decision.selected_methods)
        self.assertFalse(decision.reveal_final_answer_immediately)

    def test_developing_gets_guided_practice(self):
        decision = self.engine.decide(
            analysis(understanding=UnderstandingState.DEVELOPING),
            self.math_teacher,
        )
        self.assertEqual(decision.action, TeachingAction.GUIDED_PRACTICE)
        self.assertTrue(decision.ask_understanding_check)

    def test_urgent_revision(self):
        decision = self.engine.decide(
            analysis(
                understanding=UnderstandingState.UNKNOWN,
                revision=RevisionNeed.URGENT,
            ),
            self.math_teacher,
        )
        self.assertEqual(decision.action, TeachingAction.REVISE)
        self.assertTrue(decision.revision_required)

    def test_understood_increases_challenge(self):
        decision = self.engine.decide(
            analysis(
                confidence=ConfidenceLevel.HIGH,
                understanding=UnderstandingState.UNDERSTOOD,
            ),
            self.math_teacher,
            lesson_has_started=True,
        )
        self.assertEqual(decision.action, TeachingAction.EXTEND)
        self.assertEqual(decision.step_size, StepSize.LARGE)
        self.assertEqual(decision.difficulty_direction, DifficultyDirection.INCREASE)

    def test_final_answer_can_be_revealed_only_when_ready(self):
        decision = self.engine.decide(
            analysis(
                confidence=ConfidenceLevel.HIGH,
                understanding=UnderstandingState.UNDERSTOOD,
            ),
            self.math_teacher,
            student_requested_final_answer=True,
        )
        self.assertEqual(decision.action, TeachingAction.INDEPENDENT_PRACTICE)
        self.assertTrue(decision.reveal_final_answer_immediately)

    def test_teaching_plan_contains_safety_rules(self):
        decision = self.engine.decide(
            analysis(understanding=UnderstandingState.CONFUSED),
            self.math_teacher,
        )
        plan = build_teaching_plan(decision)
        self.assertTrue(plan.prohibited_behaviors)
        self.assertIn("Do not shame", plan.prohibited_behaviors[0])

    def test_reasoning_service_routes_subject_teacher(self):
        lesson = ReasoningService().prepare(
            analysis(subject="science", topic="force")
        )
        self.assertEqual(lesson.decision.teacher_id, "meera_maam")
        self.assertEqual(lesson.decision.subject, "science")

    def test_decision_serializes(self):
        decision = self.engine.decide(
            analysis(understanding=UnderstandingState.DEVELOPING),
            self.math_teacher,
        )
        data = decision.to_dict()
        self.assertEqual(data["action"], "guided_practice")
        self.assertEqual(data["step_size"], "normal")

    def test_decision_has_explainable_evidence(self):
        decision = self.engine.decide(
            analysis(
                confidence=ConfidenceLevel.LOW,
                understanding=UnderstandingState.CONFUSED,
            ),
            self.math_teacher,
        )
        self.assertGreaterEqual(len(decision.evidence), 2)
        for item in decision.evidence:
            item.validate()


if __name__ == "__main__":
    unittest.main()
