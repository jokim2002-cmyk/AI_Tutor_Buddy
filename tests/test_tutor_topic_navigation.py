from __future__ import annotations

import unittest
from pathlib import Path

from phase11_ai import GyanVerseAIService
from phase11_core import StudentLearningContext, SyllabusRepository


class TutorTopicNavigationRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.repo = SyllabusRepository(root / "syllabus")

    def english_ch1_context(self) -> StudentLearningContext:
        return StudentLearningContext(
            board="GSEB",
            medium="English",
            standard=7,
            preferred_language="English",
            current_subject="English",
            current_chapter="Chapter 1 - The Day the River Spoke",
            current_topic="Jahnavi's conflict and decision",
            onboarding_complete=True,
        ).validate()

    def test_context_label_includes_selected_topic(self) -> None:
        ctx = self.english_ch1_context()
        self.assertIn("Chapter 1 - The Day the River Spoke", ctx.context_label)
        self.assertIn("Jahnavi's conflict and decision", ctx.context_label)

    def test_next_topic_uses_saved_topic_context(self) -> None:
        service = GyanVerseAIService(api_key="", syllabus_repository=self.repo)
        answer = service.ask(message="next topic", context=self.english_ch1_context())

        self.assertIn("Personification, nature and encouragement", answer)
        self.assertIn("river", answer.lower())
        self.assertNotIn("Mathematics", answer)
        self.assertEqual(service.last_metrics.route, "local-syllabus")

    def test_previous_topic_uses_saved_topic_context(self) -> None:
        ctx = StudentLearningContext(
            board="GSEB",
            medium="English",
            standard=7,
            preferred_language="English",
            current_subject="English",
            current_chapter="Chapter 1 - The Day the River Spoke",
            current_topic="Personification, nature and encouragement",
            onboarding_complete=True,
        ).validate()

        service = GyanVerseAIService(api_key="", syllabus_repository=self.repo)
        answer = service.ask(message="previous topic", context=ctx)

        self.assertIn("Jahnavi's conflict and decision", answer)
        self.assertNotIn("Mathematics", answer)

    def test_ui_updates_context_before_tutor_answer(self) -> None:
        ui_source = (Path(__file__).resolve().parents[1] / "gyanverse_ui.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("def resolve_relative_topic_navigation(", ui_source)
        self.assertIn("navigated_context = resolve_relative_topic_navigation(text)", ui_source)
        self.assertIn("update_context(navigated_context)", ui_source)


if __name__ == "__main__":
    unittest.main()
