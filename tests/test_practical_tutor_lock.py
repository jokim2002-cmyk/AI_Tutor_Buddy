from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

from phase11_ai import GyanVerseAIService
from phase11_core import StudentLearningContext, SyllabusRepository


class PracticalTutorLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_tutor_mode = os.environ.get("GYANVERSE_TUTOR_MODE")
        os.environ["GYANVERSE_TUTOR_MODE"] = "practical"
        root = Path(__file__).resolve().parents[1]
        self.root = root
        self.repo = SyllabusRepository(root / "syllabus")
        self.context = StudentLearningContext(
            board="GSEB",
            medium="English",
            standard=7,
            preferred_language="English",
            current_subject="English",
            current_chapter="Chapter 1 - The Day the River Spoke",
            current_topic="Jahnavi's conflict and decision",
            onboarding_complete=True,
        ).validate()

    def tearDown(self) -> None:
        if self._old_tutor_mode is None:
            os.environ.pop("GYANVERSE_TUTOR_MODE", None)
        else:
            os.environ["GYANVERSE_TUTOR_MODE"] = self._old_tutor_mode

    def test_practical_lock_source_contract_exists(self) -> None:
        source = (self.root / "phase11_ai.py").read_text(encoding="utf-8")
        self.assertIn("GYANVERSE PRACTICAL CODE-ONLY TUTOR LOCK V1", source)
        self.assertIn("def _gv_practical_tutor_mode", source)
        self.assertIn("def _gv_practical_no_match_answer", source)
        self.assertIn("def _gv_render_practical_test_paper", source)
        self.assertIn("and not _gv_practical_tutor_mode()", source)

    def test_matched_textbook_question_uses_code_only_local_answer(self) -> None:
        service = GyanVerseAIService(api_key="", syllabus_repository=self.repo)
        answer = service.ask(
            message="muje ye chapter padhaao",
            context=self.context,
        )

        self.assertIn("Jahnavi", answer)
        self.assertIn("Source type:", answer)
        self.assertEqual(service.last_metrics.route, "local-syllabus")
        self.assertNotIn("Online AI is not configured", answer)

    def test_practical_mode_does_not_call_provider_for_matched_question(self) -> None:
        service = GyanVerseAIService(api_key="mock-key", syllabus_repository=self.repo)
        service._client = MagicMock()

        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            answer = service.ask(
                message="muje ye chapter padhaao",
                context=self.context,
            )

        self.assertIn("Jahnavi", answer)
        self.assertEqual(service.last_metrics.route, "local-syllabus")
        service._client.models.generate_content.assert_not_called()

    def test_unmatched_question_stays_inside_selected_chapter(self) -> None:
        service = GyanVerseAIService(api_key="", syllabus_repository=self.repo)
        answer = service.ask(
            message="who won the cricket match yesterday?",
            context=self.context,
        )

        self.assertIn("I can answer only from the selected chapter", answer)
        self.assertIn("Selected subject: English", answer)
        self.assertIn("Selected chapter: Chapter 1 - The Day the River Spoke", answer)
        self.assertEqual(service.last_metrics.route, "practical-no-match")

    def test_missing_chapter_requires_selection(self) -> None:
        service = GyanVerseAIService(api_key="", syllabus_repository=self.repo)
        context = StudentLearningContext(
            board="GSEB",
            medium="English",
            standard=7,
            preferred_language="English",
            current_subject="English",
            current_chapter="",
            current_topic="",
            onboarding_complete=True,
        ).validate()

        answer = service.ask(message="answer do", context=context)

        self.assertIn("Please select Board, Medium, Standard, Subject and Chapter first", answer)

    def test_test_generation_remains_available_in_practical_mode(self) -> None:
        service = GyanVerseAIService(api_key="", syllabus_repository=self.repo)
        answer = service.ask(message="20 marks test banao", context=self.context)

        self.assertIn("Test Paper:", answer)
        self.assertIn("Subject: English", answer)
        self.assertIn("Total Marks:", answer)

    def test_ui_labels_are_practical_not_ai_teacher_promises(self) -> None:
        ui_source = (self.root / "gyanverse_ui.py").read_text(encoding="utf-8")

        self.assertIn("Ask a textbook question from the selected chapter", ui_source)
        self.assertIn('ft.dropdown.Option(LearningMode.EXPLAIN.value, "Answer")', ui_source)
        self.assertIn('ft.dropdown.Option(LearningMode.HOMEWORK.value, "Homework")', ui_source)
        self.assertIn('ft.dropdown.Option(LearningMode.EXAM.value, "Test / Exam")', ui_source)


if __name__ == "__main__":
    unittest.main()
