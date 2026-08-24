from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

from phase11_ai import GyanVerseAIService
from phase11_core import LearningMode, StudentLearningContext, SyllabusRepository


class Grade8MathematicsSyllabusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project_root = Path(__file__).resolve().parents[1]
        cls.syllabus_dir = cls.project_root / "syllabus"
        cls.package_path = cls.syllabus_dir / "gseb-english-8-mathematics.json"
        cls.repo = SyllabusRepository(cls.syllabus_dir)

    def service(self, *, api_key: str = "", repo: SyllabusRepository | None = None) -> GyanVerseAIService:
        if repo is None:
            repo = self.repo
        service = GyanVerseAIService(
            api_key=api_key,
            syllabus_repository=repo,
            tts_cache_dir=self.project_root / "tts",
        )
        if api_key:
            service._client = MagicMock()
        else:
            service._client = None
        return service

    def context(
        self,
        *,
        board: str = "GSEB",
        medium: str = "English",
        standard: int = 8,
        subject: str = "Mathematics",
        chapter: str = "Chapter 5 - Squares and Square Roots",
        topic: str = "Properties of Square Numbers and Patterns",
        mode: str = LearningMode.EXPLAIN.value,
    ) -> StudentLearningContext:
        return StudentLearningContext(
            board=board,
            medium=medium,
            standard=standard,
            preferred_language="English",
            current_subject=subject,
            current_chapter=chapter,
            current_topic=topic,
            learning_mode=mode,
            onboarding_complete=True,
        ).validate()

    def test_package_file_exists_and_hashes(self) -> None:
        self.assertTrue(
            self.package_path.exists(),
            f"Missing package file: {self.package_path}",
        )
        payload = json.loads(self.package_path.read_text(encoding="utf-8"))

        self.assertEqual(payload.get("board"), "GSEB")
        self.assertEqual(payload.get("medium"), "English")
        self.assertEqual(payload.get("standard"), 8)
        self.assertEqual(payload.get("subject"), "Mathematics")

        source = payload.get("source", {})
        pdf_hashes = source.get("pdf_sha256", {})
        self.assertEqual(
            pdf_hashes.get("Std-8_Maths_English_Medium.pdf"),
            "f2bacd9552c7a7d136f70c68850bc280a4678421fd42e76cddb6a4f269f7a7d2",
        )

    def test_discoverable_through_repository(self) -> None:
        syllabus = self.repo.find(
            board="GSEB",
            medium="English",
            standard=8,
            subject="Mathematics",
        )
        self.assertIsNotNone(syllabus, "Grade 8 Mathematics package must be discoverable via SyllabusRepository")
        self.assertEqual(syllabus.key, "gseb-english-8-mathematics")
        self.assertEqual(syllabus.subject, "Mathematics")

    def test_exact_chapter_and_topic_counts(self) -> None:
        syllabus = self.repo.find(
            board="GSEB",
            medium="English",
            standard=8,
            subject="Mathematics",
        )
        self.assertIsNotNone(syllabus)
        self.assertEqual(len(syllabus.chapters), 13, "Must have exactly 13 chapters")
        
        all_topics = [t for c in syllabus.chapters for t in c.topics]
        self.assertEqual(len(all_topics), 39, "Must have exactly 39 topics (3 per chapter)")

    def test_every_chapter_has_valid_topic_coverage(self) -> None:
        syllabus = self.repo.find(
            board="GSEB",
            medium="English",
            standard=8,
            subject="Mathematics",
        )
        self.assertIsNotNone(syllabus)
        for chapter in syllabus.chapters:
            self.assertTrue(
                len(chapter.topics) >= 2,
                f"Chapter {chapter.title} must have at least 2 topics",
            )
            for topic in chapter.topics:
                self.assertTrue(topic.title, f"Topic in chapter {chapter.title} missing title")
                self.assertTrue(topic.explanation, f"Topic {topic.title} missing explanation")
                self.assertTrue(topic.learning_objectives, f"Topic {topic.title} missing learning objectives")

    def test_every_topic_supports_two_examples_request(self) -> None:
        syllabus = self.repo.find(
            board="GSEB",
            medium="English",
            standard=8,
            subject="Mathematics",
        )
        self.assertIsNotNone(syllabus)
        for chapter in syllabus.chapters:
            for topic in chapter.topics:
                self.assertTrue(
                    len(topic.examples) >= 2,
                    f"Topic '{topic.title}' in chapter '{chapter.title}' must contain at least 2 examples",
                )

    def test_chapter_level_two_examples_routes_pass(self) -> None:
        service = self.service(api_key="")
        ctx = self.context(
            chapter="Chapter 5 - Squares and Square Roots",
            topic="Properties of Square Numbers and Patterns",
        )
        ans = service.ask(
            message="Give me two examples of Pythagorean triplets",
            context=ctx,
        )
        self.assertIn("Teacher-authored content", ans)
        self.assertEqual(service.last_metrics.route, "local-syllabus")

    def test_stored_exercises_map_one_to_one_with_solutions(self) -> None:
        syllabus = self.repo.find(
            board="GSEB",
            medium="English",
            standard=8,
            subject="Mathematics",
        )
        self.assertIsNotNone(syllabus)
        total_exercises = 0
        total_solutions = 0
        for chapter in syllabus.chapters:
            for topic in chapter.topics:
                self.assertEqual(
                    len(topic.exercises),
                    len(topic.solutions),
                    f"Topic '{topic.title}' exercises count != solutions count",
                )
                self.assertEqual(
                    len(topic.practice_questions),
                    len(topic.practice_solutions),
                    f"Topic '{topic.title}' practice questions count != practice solutions count",
                )
                total_exercises += len(topic.exercises)
                total_solutions += len(topic.solutions)

        self.assertTrue(total_exercises > 0)
        self.assertEqual(total_exercises, total_solutions)

    def test_exact_question_supports_private_actionable_hint(self) -> None:
        service = self.service(api_key="")
        ctx = self.context(
            chapter="Chapter 5 - Squares and Square Roots",
            topic="Properties of Square Numbers and Patterns",
        )
        hint_response = service.ask(
            message="Give me a hint for the question: What will be the unit digit of the square of 272?",
            context=ctx,
        )
        self.assertIn("Hint", hint_response)
        self.assertNotIn("Unit digit of 272 is 2", hint_response)
        self.assertEqual(service.last_metrics.route, "local-syllabus")

    def test_deterministic_answer_reviews_marked_locally(self) -> None:
        service = self.service(api_key="mock-key")
        ctx = self.context(
            chapter="Chapter 5 - Squares and Square Roots",
            topic="Properties of Square Numbers and Patterns",
        )

        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            correct = service.ask_stream(
                message="Question: Is 1057 a perfect square? Give reason. My answer: No, because a perfect square number never ends with digit 7. Is my answer correct?",
                context=ctx,
            )
            self.assertIn("Result:", correct)
            self.assertEqual(service.last_metrics.route, "local-syllabus")

    def test_open_ended_answers_not_falsely_marked_by_guessing(self) -> None:
        service = self.service(api_key="mock-key")
        ctx = self.context(
            chapter="Chapter 2 - Linear Equations in One Variable",
            topic="Applications and Word Problems of Linear Equations",
        )
        service._client.models.generate_content_stream.return_value = [
            MagicMock(text="Grounded open-ended evaluation by AI tutor.")
        ]

        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            review = service.ask_stream(
                message="Question: Three consecutive integers add up to 51. Find these integers. My answer: Let integers be x, x+1, x+2. 3x+3=51, x=16, so 16, 17, 18. Is my answer correct?",
                context=ctx,
            )
        self.assertEqual(review, "Grounded open-ended evaluation by AI tutor.")
        self.assertEqual(service.last_metrics.route, "gemini-single-chunk")
        service._client.models.generate_content_stream.assert_called_once()

    def test_all_chapter_test_wording_variants_work(self) -> None:
        service = self.service(api_key="")

        variants = [
            "Generate a chapter test for Squares and Square Roots",
            "Generate a chapter test with answers for Squares and Square Roots",
            "Generate a chapter test and answers for Squares and Square Roots",
        ]

        for prompt in variants:
            ctx = self.context(
                chapter="Chapter 5 - Squares and Square Roots",
                topic="Properties of Square Numbers and Patterns",
            )
            resp = service.ask(message=prompt, context=ctx)
            self.assertIn("Chapter test", resp)
            self.assertEqual(service.last_metrics.route, "local-syllabus")

    def test_grade_7_mathematics_remains_isolated(self) -> None:
        service = self.service(api_key="")

        # Grade 7 Maths query (Pie Graph)
        ctx_g7 = StudentLearningContext(
            board="GSEB",
            medium="English",
            standard=7,
            preferred_language="English",
            current_subject="Mathematics",
            current_chapter="Semester 1 — Pie Graph",
            current_topic="Reading and interpreting pie graphs",
            learning_mode=LearningMode.EXPLAIN.value,
            onboarding_complete=True,
        ).validate()

        ans_g7 = service.ask(message="Explain reading and interpreting pie graphs", context=ctx_g7)
        self.assertIn("pie graph represents one whole", ans_g7.lower())
        self.assertNotIn("Squares and Square Roots", ans_g7)

        # Grade 8 Maths query (Squares and Square Roots)
        ctx_g8 = self.context(
            chapter="Chapter 5 - Squares and Square Roots",
            topic="Properties of Square Numbers and Patterns",
        )
        ans_g8 = service.ask(message="Explain properties of square numbers and patterns", context=ctx_g8)
        self.assertIn("square number", ans_g8.lower())
        self.assertNotIn("Pie Graph", ans_g8)

    def test_grade_8_english_remains_isolated(self) -> None:
        service = self.service(api_key="")

        # Grade 8 English query
        ctx_eng8 = StudentLearningContext(
            board="GSEB",
            medium="English",
            standard=8,
            preferred_language="English",
            current_subject="English",
            current_chapter="Semester 1 Unit 1 - Landscapes",
            current_topic="Land Art and Environmental Appreciation",
            learning_mode=LearningMode.EXPLAIN.value,
            onboarding_complete=True,
        ).validate()

        ans_eng8 = service.ask(message="Explain Land Art", context=ctx_eng8)
        self.assertIn("land art refers to artistic creations", ans_eng8.lower())
        self.assertNotIn("Squares and Square Roots", ans_eng8)

    def test_exact_local_syllabus_routes_do_not_consume_provider(self) -> None:
        service = self.service(api_key="")
        ctx = self.context(
            chapter="Chapter 5 - Squares and Square Roots",
            topic="Properties of Square Numbers and Patterns",
        )

        ans = service.ask(message="Explain Properties of Square Numbers and Patterns", context=ctx)
        self.assertIn("Teacher-authored content", ans)
        self.assertEqual(service.last_metrics.route, "local-syllabus")


if __name__ == "__main__":
    unittest.main()
