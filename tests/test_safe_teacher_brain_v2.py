from __future__ import annotations

import unittest
from pathlib import Path

from phase11_ai import GyanVerseAIService
from phase11_core import StudentLearningContext, SyllabusRepository


class SafeTeacherBrainV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[1]
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

    def test_unsafe_monkey_patch_removed(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "phase11_ai.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("_GV_TB_ORIGINAL_ASK", source)
        self.assertNotIn("GyanVerseAIService.ask = _gv_tb_ask", source)
        self.assertIn("PUBLIC TEACHER RESPONSE CONTRACT", source)

    def test_exam_memory_prompt_does_not_generate_test_paper_offline(self) -> None:
        service = GyanVerseAIService(api_key="", syllabus_repository=self.repo)
        answer = service.ask(
            message="what should I remember for exam?",
            context=self.context,
        )

        self.assertIn("Remember for exam", answer)
        self.assertIn("Try this", answer)
        self.assertIn("Source type:", answer)
        self.assertNotIn("Test Paper:", answer)

    def test_explicit_test_request_still_generates_test_paper(self) -> None:
        service = GyanVerseAIService(api_key="", syllabus_repository=self.repo)
        answer = service.ask(message="test banao", context=self.context)

        self.assertIn("Test Paper:", answer)
        self.assertIn("Subject: English", answer)

    def test_provider_prompt_contains_teacher_contract_without_bypassing_provider(self) -> None:
        service = GyanVerseAIService(api_key="", syllabus_repository=self.repo)
        prompt = service._build_provider_prompt(
            message="muje ye chapter padhaao",
            context=self.context,
            attachments=(),
        )

        self.assertIn("PUBLIC TEACHER RESPONSE CONTRACT", prompt)
        self.assertIn("Source type:", prompt)
        self.assertIn("CURRENT LEARNING CONTEXT", prompt)


if __name__ == "__main__":
    unittest.main()
