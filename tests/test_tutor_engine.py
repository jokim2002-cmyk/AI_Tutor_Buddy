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
        self.assertEqual(homework["difficulty"], "foundation")

    def test_homework_check_updates_progress_and_revision(self) -> None:
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
        self.assertEqual(result["difficulty"], "challenge")
        self.assertIn("Science | Heat", self.engine.format_progress("s1"))
        self.assertIn("Science / Heat", self.engine.format_revision_queue("s1"))

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

    def test_diagnostic_generation(self) -> None:
        diagnostic = self.engine.generate_diagnostic(
            student_id="s1",
            subject="Mathematics",
            question_count=5,
        )
        self.assertEqual(len(diagnostic["questions"]), 5)
        self.assertTrue(diagnostic["diagnostic_id"].startswith("diag-"))

    def test_diagnostic_check_records_baseline(self) -> None:
        diagnostic = self.engine.generate_diagnostic(
            student_id="s1",
            subject="Mathematics",
            question_count=3,
        )
        result = self.engine.check_diagnostic(
            student_id="s1",
            diagnostic_id=diagnostic["diagnostic_id"],
            answers=["5", "", "wrong answer"],
        )
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["score"], 1)
        self.assertIn("Mathematics | Baseline", self.engine.format_progress("s1"))

    def test_misconception_detection(self) -> None:
        diagnostic = self.engine.generate_diagnostic(
            student_id="s1",
            subject="Science",
            question_count=3,
        )
        self.engine.check_diagnostic(
            student_id="s1",
            diagnostic_id=diagnostic["diagnostic_id"],
            answers=["", "I do not know", "maybe hot"],
        )
        mistakes = self.engine.format_misconceptions("s1")
        self.assertIn("Misconception patterns", mistakes)
        self.assertIn("no_attempt", mistakes)

    def test_adaptive_difficulty_defaults_to_foundation(self) -> None:
        difficulty = self.engine.get_adaptive_difficulty(
            student_id="s1",
            subject="Science",
            chapter="Heat",
        )
        self.assertEqual(difficulty, "foundation")

    def test_revision_can_be_completed(self) -> None:
        homework = self.engine.generate_homework(
            student_id="s1",
            subject="English",
            chapter="Grammar",
            question_count=1,
        )
        self.engine.check_homework(
            student_id="s1",
            homework_id=homework["homework_id"],
            answers=["A sufficiently detailed answer for the exercise."],
        )
        queue = self.engine.format_revision_queue("s1")
        revision_id = queue.splitlines()[1].split("|")[0].strip()
        self.engine.complete_revision(student_id="s1", revision_id=revision_id)
        self.assertEqual(
            self.engine.format_revision_queue("s1"),
            "No pending revision is scheduled.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
