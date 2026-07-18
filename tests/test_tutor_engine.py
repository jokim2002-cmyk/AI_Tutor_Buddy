from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tutor_engine import TutorEngine, TutorEngineError


class TutorEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.engine = TutorEngine(db_path=self.db_path, ai_client=None)
        self.engine.ensure_student(
            student_id="s1",
            name="Test Student",
            grade=7,
            board="CBSE",
            preferred_language="English (India)",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_daily_sync_persists(self) -> None:
        result = self.engine.record_daily_sync(
            student_id="s1",
            subject="Mathematics",
            chapter="Fractions",
            topic="Unlike fractions",
        )
        self.assertEqual(result["subject"], "Mathematics")
        self.assertIn("Unlike fractions", self.engine.format_today_summary("s1"))

    def test_homework_generation_offline(self) -> None:
        homework = self.engine.generate_homework(
            student_id="s1",
            subject="Science",
            chapter="Heat",
            question_count=3,
        )
        self.assertEqual(len(homework["questions"]), 3)
        self.assertTrue(homework["homework_id"].startswith("hw-"))

    def test_homework_check_updates_progress(self) -> None:
        homework = self.engine.generate_homework(
            student_id="s1",
            subject="Science",
            chapter="Heat",
            question_count=2,
        )
        result = self.engine.check_homework(
            student_id="s1",
            homework_id=homework["homework_id"],
            answers=[
                "This is a detailed explanation with clear logical steps.",
                "This answer also explains the concept using an example.",
            ],
        )
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["score"], 2)
        self.assertIn("Science | Heat", self.engine.format_progress("s1"))

    def test_unknown_homework_is_rejected(self) -> None:
        with self.assertRaises(TutorEngineError):
            self.engine.check_homework(
                student_id="s1",
                homework_id="missing",
                answers=["answer"],
            )

    def test_student_context_contains_memory(self) -> None:
        self.engine.record_daily_sync(
            student_id="s1",
            subject="English",
            chapter="Grammar",
            topic="Tenses",
        )
        context = self.engine.build_student_context("s1")
        self.assertIn("Test Student", context)
        self.assertIn("Tenses", context)


if __name__ == "__main__":
    unittest.main(verbosity=2)
