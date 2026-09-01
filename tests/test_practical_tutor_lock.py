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

    def test_hinglish_or_between_chapter_numbers_generates_multi_chapter_test(self) -> None:
        service = GyanVerseAIService(api_key="", syllabus_repository=self.repo)
        context = StudentLearningContext(
            board="GSEB",
            medium="English",
            standard=8,
            preferred_language="English",
            current_subject="Science & Technology",
            current_chapter="Chapter 1 - Crop Production and Management",
            current_topic="Agricultural Practices and Preparation of Soil",
            onboarding_complete=True,
        ).validate()

        answer = service.ask(
            message="chapter 1 or 2 ka 20 marks ka test banao",
            context=context,
        )

        self.assertIn("Test Paper: Chapters 1, 2 (2 Chapters)", answer)
        self.assertIn("Total Marks: 20 Marks", answer)
        self.assertIn("Subject: Science & Technology", answer)
        self.assertNotIn("Chapter 1 - Crop Production and Management ? Chapter test", answer)

    def test_hinglish_aur_between_chapter_numbers_generates_multi_chapter_test(self) -> None:
        service = GyanVerseAIService(api_key="", syllabus_repository=self.repo)
        context = StudentLearningContext(
            board="GSEB",
            medium="English",
            standard=8,
            preferred_language="English",
            current_subject="Science & Technology",
            current_chapter="Chapter 1 - Crop Production and Management",
            current_topic="Agricultural Practices and Preparation of Soil",
            onboarding_complete=True,
        ).validate()

        answer = service.ask(
            message="chapter 1 aur 2 ka 20 marks ka test banao",
            context=context,
        )

        self.assertIn("Test Paper: Chapters 1, 2 (2 Chapters)", answer)
        self.assertIn("Total Marks: 20 Marks", answer)
        self.assertIn("Subject: Science & Technology", answer)

    def test_comma_only_chapter_list_generates_multi_chapter_test(self) -> None:
        service = GyanVerseAIService(api_key="", syllabus_repository=self.repo)
        context = StudentLearningContext(
            board="GSEB",
            medium="English",
            standard=8,
            preferred_language="English",
            current_subject="English",
            current_chapter="Semester 1 Unit 1 - Landscapes",
            current_topic="Land Art and Environmental Appreciation",
            onboarding_complete=True,
        ).validate()

        answer = service.ask(
            message="chapter 1,2,3 ka 50 marks test banao",
            context=context,
        )

        self.assertIn("Test Paper: Chapters 1, 2, 3 (3 Chapters)", answer)
        self.assertIn("Total Marks: 50 Marks", answer)
        self.assertIn("Subject: English", answer)

    def test_visible_test_paper_questions_do_not_show_topic_brackets(self) -> None:
        service = GyanVerseAIService(api_key="", syllabus_repository=self.repo)
        context = StudentLearningContext(
            board="GSEB",
            medium="English",
            standard=8,
            preferred_language="English",
            current_subject="English",
            current_chapter="Semester 1 Unit 1 - Landscapes",
            current_topic="Land Art and Environmental Appreciation",
            onboarding_complete=True,
        ).validate()

        answer = service.ask(
            message="chapter 1 or 2 ka 20 marks ka test banao",
            context=context,
        )

        self.assertIn("Test Paper: Chapters 1, 2 (2 Chapters)", answer)
        self.assertNotRegex(answer, r"\n\d+\.\s+\[[^\]]+\]")
        self.assertIsNotNone(service._last_generated_test_paper)
        self.assertTrue(service._last_generated_test_paper.questions[0].topic_title)

    def test_science_chapter_12_section_d_does_not_show_generic_lesson_question(self) -> None:
        service = GyanVerseAIService(api_key="", syllabus_repository=self.repo)
        context = StudentLearningContext(
            board="GSEB",
            medium="English",
            standard=8,
            preferred_language="English",
            current_subject="Science & Technology",
            current_chapter="Chapter 12 - Some Natural Phenomena",
            current_topic="",
            onboarding_complete=True,
        ).validate()

        answer = service.ask(
            message="chapter 12 ka 20 marks test banao",
            context=context,
        )

        self.assertIn("Test Paper: Chapter 12 - Some Natural Phenomena", answer)
        self.assertIn("Total Marks: 20 Marks", answer)
        self.assertNotIn(
            "Explain the lesson using clear definitions, key points, suitable examples, importance, and a short conclusion.",
            answer,
        )
        self.assertNotRegex(answer, r"\n\d+\.\s+\[[^\]]+\]")
        self.assertRegex(answer, r"10\. Explain .+\(6 Marks\)")

    def test_exact_textbook_poem_request_does_not_fake_full_text(self) -> None:
        service = GyanVerseAIService(api_key="", syllabus_repository=self.repo)
        context = StudentLearningContext(
            board="GSEB",
            medium="English",
            standard=8,
            preferred_language="English",
            current_subject="English",
            current_chapter="Semester 1 Unit 1 - Landscapes",
            current_topic="Land Art and Environmental Appreciation",
            onboarding_complete=True,
        ).validate()

        answer = service.ask(
            message="write full poem summary from textbook",
            context=context,
        )

        self.assertIn("I do not have the exact full textbook poem/text stored", answer)
        self.assertIn("paste the exact lines", answer.lower())
        self.assertEqual(service.last_metrics.route, "practical-exact-textbook-boundary")
        self.assertNotIn("Land Art refers to artistic creations", answer)

    def test_v1_ui_exposes_only_english_medium_and_language(self) -> None:
        ui_source = (self.root / "gyanverse_ui.py").read_text(encoding="utf-8")

        self.assertIn('GYANVERSE_V1_ALLOWED_MEDIUMS = ("English",)', ui_source)
        self.assertIn('GYANVERSE_V1_ALLOWED_TUTOR_LANGUAGES = ("English",)', ui_source)
        self.assertIn(
            "options=[ft.dropdown.Option(item) for item in GYANVERSE_V1_ALLOWED_MEDIUMS]",
            ui_source,
        )
        self.assertIn(
            "options=[ft.dropdown.Option(item) for item in GYANVERSE_V1_ALLOWED_TUTOR_LANGUAGES]",
            ui_source,
        )
        self.assertIn("medium=medium_field.value or GYANVERSE_V1_ALLOWED_MEDIUMS[0]", ui_source)
        self.assertIn(
            "preferred_language=language_field.value or GYANVERSE_V1_ALLOWED_TUTOR_LANGUAGES[0]",
            ui_source,
        )

        medium_block = ui_source.split("medium_field = ft.Dropdown(", 1)[1].split("standard_field = ft.Dropdown(", 1)[0]
        language_block = ui_source.split("language_field = ft.Dropdown(", 1)[1].split("subject_field = ft.Dropdown(", 1)[0]

        self.assertNotIn('"Gujarati", "English", "Hindi"', medium_block)
        self.assertNotIn('"Gujarati", "Hindi", "English"', language_block)

    def test_v1_mobile_ui_and_cloud_polish_contracts_exist(self) -> None:
        ui_source = (self.root / "gyanverse_ui.py").read_text(encoding="utf-8")

        self.assertIn("GYANVERSE_V1_CLOUD_SYNC_ENABLED = False", ui_source)
        self.assertIn("Cloud: disabled in English V1 pilot", ui_source)
        self.assertIn("Google sign-in is disabled in the English V1 pilot", ui_source)
        self.assertIn("visible=GYANVERSE_V1_CLOUD_SYNC_ENABLED", ui_source)

        self.assertIn("dialog_is_mobile = dialog_viewport_width < 700.0", ui_source)
        self.assertIn("dialog_width = max(300.0, min(560.0, dialog_viewport_width - 44.0))", ui_source)
        self.assertIn("dialog_height = max(420.0, min(500.0, dialog_viewport_height - 230.0))", ui_source)
        self.assertIn("profile_field_width = max(260.0, dialog_width - 32.0)", ui_source)
        self.assertIn("locked_scope_text = ft.Text(", ui_source)
        self.assertIn("selected_lesson_hint = ft.Text(", ui_source)
        self.assertIn("Selected chapter:", ui_source)
        self.assertIn("Selected topic:", ui_source)
        self.assertIn("visible=not dialog_is_mobile", ui_source)

        self.assertIn("width=136 if is_mobile else 140", ui_source)
        self.assertIn("mode_dropdown.width = 136 if is_mobile_res else 140", ui_source)

    def test_ui_labels_are_practical_not_ai_teacher_promises(self) -> None:
        ui_source = (self.root / "gyanverse_ui.py").read_text(encoding="utf-8")

        self.assertIn("Ask a textbook question from the selected chapter", ui_source)
        self.assertIn('ft.dropdown.Option(LearningMode.EXPLAIN.value, "Answer")', ui_source)
        self.assertIn('ft.dropdown.Option(LearningMode.HOMEWORK.value, "Homework")', ui_source)
        self.assertIn('ft.dropdown.Option(LearningMode.EXAM.value, "Test / Exam")', ui_source)


if __name__ == "__main__":
    unittest.main()
