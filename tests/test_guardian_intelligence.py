import unittest

from academy_core import (
    FuturePathAdvisor,
    GuardianAccessError,
    GuardianLearningService,
    GuardianPrivacyPolicy,
    GuardianProfile,
    GuardianReportBuilder,
    GuardianRole,
    LearningActivity,
    StudentProgressSnapshot,
)


def alin_snapshot():
    return StudentProgressSnapshot(
        student_id="alin",
        student_name="Alin",
        date_label="Today",
        activities=(
            LearningActivity(
                subject="maths",
                topic="fractions",
                duration_minutes=20,
                understanding="understood",
                confidence="high",
                strategy_used="visual_explanation",
            ),
            LearningActivity(
                subject="science",
                topic="force",
                duration_minutes=18,
                understanding="developing",
                confidence="medium",
                strategy_used="observation_experiment",
            ),
            LearningActivity(
                subject="english",
                topic="sentence formation",
                duration_minutes=10,
                understanding="confused",
                confidence="low",
                strategy_used="communication_practice",
            ),
        ),
        interests=("computer coding", "maths puzzles"),
        strengths=("Visual fraction models", "Logical problem solving"),
        support_needs=("Written English confidence",),
        voluntary_questions=(
            "How do computer games use maths?",
            "Can I build a small coding project?",
        ),
        persistence_signals=("Continued after two incorrect attempts",),
        preferred_learning_methods=("visual", "examples"),
        sensitive_notes=("Student shared a private emotional concern.",),
    )


def guardian():
    return GuardianProfile(
        guardian_id="g1",
        name="Parent",
        role=GuardianRole.PARENT,
        child_ids=("alin", "austin"),
    )


class GuardianIntelligenceTests(unittest.TestCase):
    def test_guardian_profile_supports_multiple_children(self):
        profile = guardian()
        profile.validate()
        self.assertEqual(len(profile.child_ids), 2)

    def test_unauthorized_child_access_is_blocked(self):
        with self.assertRaises(GuardianAccessError):
            GuardianPrivacyPolicy().assert_child_access(guardian(), "other_child")

    def test_sensitive_notes_are_not_exposed(self):
        sanitized = GuardianPrivacyPolicy().sanitize_for_guardian(alin_snapshot())
        self.assertEqual(sanitized.sensitive_notes, ())

    def test_daily_report_contains_learning_and_home_support(self):
        report = GuardianReportBuilder().build_daily_report(alin_snapshot())
        self.assertIn("Maths: fractions", report.learned_today)
        self.assertTrue(report.home_support_actions)
        self.assertIn("Private student conversations", report.privacy_notice)

    def test_report_does_not_create_permanent_weak_label(self):
        report = GuardianReportBuilder().build_daily_report(alin_snapshot())
        joined = " ".join(report.support_needs).lower()
        self.assertNotIn("weak student", joined)
        self.assertNotIn("low intelligence", joined)

    def test_future_path_is_exploration_not_command(self):
        suggestion = FuturePathAdvisor().suggest(alin_snapshot())
        self.assertTrue(suggestion.exploration_areas)
        self.assertIn("not a career decision", suggestion.caution.lower())
        self.assertNotIn("must become", suggestion.caution.lower())

    def test_future_path_includes_computer_exploration(self):
        suggestion = FuturePathAdvisor().suggest(alin_snapshot())
        joined = " ".join(suggestion.exploration_areas).lower()
        self.assertIn("coding", joined)

    def test_class_teacher_answers_today_question(self):
        service = GuardianLearningService(snapshots={"alin": alin_snapshot()})
        response = service.ask_class_teacher(
            guardian(),
            "alin",
            "Aaj Alin ne kya padha?",
        )
        self.assertEqual(response.speaker_role, "Class Teacher")
        self.assertIn("fractions", response.answer)
        self.assertIsNotNone(response.report)

    def test_principal_answers_future_path_question(self):
        service = GuardianLearningService(snapshots={"alin": alin_snapshot()})
        response = service.ask_principal(
            guardian(),
            "alin",
            "Alin ka future path kya ho sakta hai?",
        )
        self.assertEqual(response.speaker_role, "Principal")
        self.assertIsNotNone(response.future_path)
        self.assertIn("exploration", response.answer.lower())

    def test_sibling_comparison_is_blocked(self):
        service = GuardianLearningService(snapshots={"alin": alin_snapshot()})
        response = service.ask_principal(
            guardian(),
            "alin",
            "Compare Alin vs Austin, who is better?",
        )
        self.assertTrue(response.comparison_blocked)
        self.assertIn("Har student ka learning path alag", response.answer)

    def test_guardian_report_serializes(self):
        report = GuardianReportBuilder().build_daily_report(alin_snapshot())
        data = report.to_dict()
        self.assertEqual(data["student_name"], "Alin")
        self.assertIsInstance(data["learned_today"], tuple)

    def test_future_path_serializes(self):
        suggestion = FuturePathAdvisor().suggest(alin_snapshot())
        data = suggestion.to_dict()
        self.assertEqual(data["student_id"], "alin")
        self.assertIsInstance(data["exploration_areas"], tuple)


if __name__ == "__main__":
    unittest.main()
