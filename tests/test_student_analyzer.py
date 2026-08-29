import unittest

from academy_core.student_analyzer import (
    ConfidenceLevel,
    RevisionNeed,
    StudentAnalyzer,
    StudentContext,
    UnderstandingState,
)
from academy_core.student_context_adapter import context_from_mapping


class StudentAnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.analyzer = StudentAnalyzer()

    def test_explicit_confusion(self):
        result = self.analyzer.analyze(
            StudentContext(class_level=7, subject="maths", topic="fractions"),
            current_message="Mujhe fractions samajh nahi aa rahe",
        )
        self.assertEqual(result.subject, "maths")
        self.assertEqual(result.understanding, UnderstandingState.CONFUSED)
        self.assertTrue(result.needs_prerequisite_check)
        self.assertIn("worked_example", result.recommended_methods)

    def test_guessing_signal(self):
        result = self.analyzer.analyze(
            StudentContext(subject="science"),
            current_message="Maybe the answer is force",
        )
        self.assertEqual(result.understanding, UnderstandingState.GUESSING)
        self.assertIn("explain_reasoning", result.recommended_methods)

    def test_low_confidence_support(self):
        result = self.analyzer.analyze(
            StudentContext(subject="maths"),
            current_message="Mujhse nahi hoga, bahut difficult hai",
        )
        self.assertEqual(result.confidence, ConfidenceLevel.LOW)
        self.assertEqual(result.recommended_methods[0], "gentle_encouragement")

    def test_high_accuracy_understood(self):
        result = self.analyzer.analyze(
            StudentContext(
                subject="english",
                recent_accuracy=0.9,
                hints_used=0,
            )
        )
        self.assertEqual(result.confidence, ConfidenceLevel.HIGH)
        self.assertEqual(result.understanding, UnderstandingState.UNDERSTOOD)
        self.assertIn("independent_practice", result.recommended_methods)

    def test_urgent_revision(self):
        result = self.analyzer.analyze(
            StudentContext(
                subject="maths",
                prior_mastery=0.3,
                repeated_mistakes=3,
                days_since_last_practice=22,
            )
        )
        self.assertEqual(result.revision_need, RevisionNeed.URGENT)

    def test_unknown_subject_asks_clarification(self):
        result = self.analyzer.analyze(
            StudentContext(),
            current_message="Please help me",
        )
        self.assertTrue(result.should_ask_clarifying_question)
        self.assertEqual(result.recommended_teacher_subject, "class_guidance")

    def test_harmful_permanent_label_not_used(self):
        result = self.analyzer.analyze(
            StudentContext(subject="maths", repeated_mistakes=4)
        )
        self.assertNotIn("weak student", result.safe_summary.lower())
        self.assertIn("temporary learning signals", result.safe_summary)

    def test_context_adapter(self):
        context = context_from_mapping({
            "student_id": "s1",
            "class_level": "8",
            "subject": "python coding",
            "recent_accuracy": "0.75",
            "hints_used": "2",
            "helpful_methods": "visual_example, smaller_steps",
            "recent_messages": ["I am learning loops"],
        })
        self.assertEqual(context.class_level, 8)
        self.assertEqual(context.recent_accuracy, 0.75)
        self.assertEqual(context.helpful_methods[0], "visual_example")
        result = self.analyzer.analyze(context)
        self.assertEqual(result.subject, "computer")

    def test_invalid_class_rejected(self):
        with self.assertRaises(ValueError):
            self.analyzer.analyze(StudentContext(class_level=15))

    def test_analysis_serializes(self):
        result = self.analyzer.analyze(
            StudentContext(subject="science", recent_accuracy=0.6)
        )
        data = result.to_dict()
        self.assertEqual(data["subject"], "science")
        self.assertEqual(data["understanding"], "developing")


if __name__ == "__main__":
    unittest.main()
