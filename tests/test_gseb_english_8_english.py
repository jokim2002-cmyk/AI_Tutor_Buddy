from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

from phase11_ai import GyanVerseAIService
from phase11_core import LearningMode, StudentLearningContext, SyllabusRepository


class Grade8EnglishSyllabusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project_root = Path(__file__).resolve().parents[1]
        cls.syllabus_dir = cls.project_root / "syllabus"
        cls.package_path = cls.syllabus_dir / "gseb-english-8-english.json"
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
        subject: str = "English",
        chapter: str = "Semester 1 Unit 1 - Landscapes",
        topic: str = "Land Art and Environmental Appreciation",
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
        self.assertEqual(payload.get("subject"), "English")

        source = payload.get("source", {})
        pdf_hashes = source.get("pdf_sha256", {})
        self.assertEqual(
            pdf_hashes.get("STD 8 ENGLISH F.L-SEM 1.pdf"),
            "005371fa0f7e843aa4430bfec96b18d769c911220338aff4df60eecde37e12c8",
        )
        self.assertEqual(
            pdf_hashes.get("STD 8 ENGLISH F.L-SEM 2.pdf"),
            "b844f26ed757d5bc9de6ea97ee42e89ca628496a28a7e229dc1b654d25978421",
        )

    def test_discoverable_through_repository(self) -> None:
        syllabus = self.repo.find(
            board="GSEB",
            medium="English",
            standard=8,
            subject="English",
        )
        self.assertIsNotNone(syllabus, "Grade 8 English package must be discoverable via SyllabusRepository")
        self.assertEqual(syllabus.key, "gseb-english-8-english")

    def test_exact_chapter_count_from_both_semesters(self) -> None:
        syllabus = self.repo.find(
            board="GSEB",
            medium="English",
            standard=8,
            subject="English",
        )
        self.assertIsNotNone(syllabus)
        self.assertEqual(len(syllabus.chapters), 12, "Must have exactly 12 chapters (6 Sem 1 + 6 Sem 2)")

        sem1_chapters = [c for c in syllabus.chapters if "Semester 1" in c.title]
        sem2_chapters = [c for c in syllabus.chapters if "Semester 2" in c.title]

        self.assertEqual(len(sem1_chapters), 6, "Semester 1 must have 6 chapters")
        self.assertEqual(len(sem2_chapters), 6, "Semester 2 must have 6 chapters")

    def test_every_chapter_has_valid_topic_coverage(self) -> None:
        syllabus = self.repo.find(
            board="GSEB",
            medium="English",
            standard=8,
            subject="English",
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
            subject="English",
        )
        self.assertIsNotNone(syllabus)
        for chapter in syllabus.chapters:
            for topic in chapter.topics:
                self.assertTrue(
                    len(topic.examples) >= 2,
                    f"Topic '{topic.title}' in chapter '{chapter.title}' must contain at least 2 examples",
                )

    def test_stored_exercises_map_one_to_one_with_solutions(self) -> None:
        syllabus = self.repo.find(
            board="GSEB",
            medium="English",
            standard=8,
            subject="English",
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
            chapter="Semester 1 Unit 1 - Landscapes",
            topic="Land Art and Environmental Appreciation",
        )
        hint_response = service.ask(
            message="Give me a hint for the question: What is Land Art?",
            context=ctx,
        )
        self.assertIn("Hint", hint_response)
        self.assertNotIn("Land Art is artwork created directly in nature using natural materials like rocks, sand, and plants.", hint_response)
        self.assertEqual(service.last_metrics.route, "local-syllabus")

    def test_deterministic_answer_reviews_marked_locally(self) -> None:
        service = self.service(api_key="mock-key")
        ctx = self.context(
            chapter="Semester 1 Unit 1 - Landscapes",
            topic="Land Art and Environmental Appreciation",
        )

        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            correct = service.ask_stream(
                message="Question: Is Land Art meant to last forever in a museum? Explain. My answer: No. Is my answer correct?",
                context=ctx,
            )
            self.assertIn("Result: Correct.", correct)
            self.assertIn("Installed solution logic: No.", correct)
            self.assertEqual(service.last_metrics.route, "local-syllabus")

            wrong = service.ask_stream(
                message="Question: Is Land Art meant to last forever in a museum? Explain. My answer: Yes. Is my answer correct?",
                context=ctx,
            )
            self.assertIn("Result: Incorrect.", wrong)
            self.assertEqual(service.last_metrics.route, "local-syllabus")

    def test_open_ended_answers_not_falsely_marked_by_guessing(self) -> None:
        service = self.service(api_key="mock-key")
        ctx = self.context(
            chapter="Semester 1 Unit 1 - Landscapes",
            topic="Land Art and Environmental Appreciation",
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
                message="Question: What is Land Art? My answer: It is art made in nature using stones and soil. Is my answer correct?",
                context=ctx,
            )
        self.assertEqual(review, "Grounded open-ended evaluation by AI tutor.")
        self.assertEqual(service.last_metrics.route, "gemini-single-chunk")
        service._client.models.generate_content_stream.assert_called_once()

    def test_all_chapter_test_wording_variants_work(self) -> None:
        service = self.service(api_key="")

        variants = [
            "Generate a chapter test for Landscapes",
            "Generate a chapter test with answers for Landscapes",
            "Generate a chapter test and answers for Landscapes",
        ]

        for prompt in variants:
            ctx = self.context(
                chapter="Semester 1 Unit 1 - Landscapes",
                topic="Land Art and Environmental Appreciation",
            )
            resp = service.ask(message=prompt, context=ctx)
            self.assertIn("Chapter test", resp)
            self.assertEqual(service.last_metrics.route, "local-syllabus")

    def test_semester_1_and_semester_2_chapter_isolation(self) -> None:
        service = self.service(api_key="")

        # Sem 1 Unit 1: Landscapes
        ctx_sem1 = self.context(
            chapter="Semester 1 Unit 1 - Landscapes",
            topic="Land Art and Environmental Appreciation",
        )
        ans_sem1 = service.ask(message="Explain Land Art", context=ctx_sem1)
        self.assertIn("Land Art refers to artistic creations formed directly in the natural landscape", ans_sem1)

        # Sem 2 Unit 1: Writing About Writing
        ctx_sem2 = self.context(
            chapter="Semester 2 Unit 1 - Writing About Writing",
            topic="The Writing Process: Brainstorming, Drafting and Revision",
        )
        ans_sem2 = service.ask(message="Explain the writing process", context=ctx_sem2)
        self.assertIn("Effective writing is a multi-step process", ans_sem2)
        self.assertNotIn("Land Art refers to artistic creations", ans_sem2)

    def test_standard_7_and_standard_8_contexts_cannot_collide(self) -> None:
        service = self.service(api_key="")

        # Grade 7 English query
        ctx_std7 = StudentLearningContext(
            board="GSEB",
            medium="English",
            standard=7,
            preferred_language="English",
            current_subject="English",
            current_chapter="Chapter 1 - The Day the River Spoke",
            current_topic="Jahnavi's conflict and decision",
            learning_mode=LearningMode.EXPLAIN.value,
            onboarding_complete=True,
        ).validate()

        ans_std7 = service.ask(message="Explain Jahnavi's conflict", context=ctx_std7)
        self.assertIn("Jahnavi lives in a coastal village", ans_std7)
        self.assertNotIn("Land Art", ans_std7)

        # Grade 8 English query
        ctx_std8 = self.context(
            chapter="Semester 1 Unit 1 - Landscapes",
            topic="Land Art and Environmental Appreciation",
        )

        ans_std8 = service.ask(message="Explain Land Art", context=ctx_std8)
        self.assertIn("Land Art refers to artistic creations", ans_std8)
        self.assertNotIn("Jahnavi", ans_std8)

    def test_allowed_subject_names_constraint(self) -> None:
        syllabus_std8 = self.repo.find(
            board="GSEB",
            medium="English",
            standard=8,
            subject="English",
        )
        self.assertIsNotNone(syllabus_std8)

        allowed_subjects = {
            "English",
            "Mathematics",
            "Science & Technology",
            "Science",
            "Social Science",
        }
        all_english_syllabi = [
            s for s in self.repo.all(board="GSEB")
            if s.medium.casefold() == "english"
        ]
        for s in all_english_syllabi:
            self.assertIn(
                s.subject,
                allowed_subjects,
                f"Subject '{s.subject}' is not in allowed English-medium core subject names",
            )

    def test_all_four_grade7_english_medium_packages_still_pass(self) -> None:
        expected_g7_subjects = [
            "English",
            "Mathematics",
            "Science & Technology",
            "Social Science",
        ]
        for sub in expected_g7_subjects:
            s = self.repo.find(board="GSEB", medium="English", standard=7, subject=sub)
            self.assertIsNotNone(s, f"Grade 7 package for {sub} missing or failed to load")
            self.assertTrue(len(s.chapters) > 0, f"Grade 7 package for {sub} has 0 chapters")

    def test_exact_local_syllabus_routes_do_not_consume_provider(self) -> None:
        service = self.service(api_key="")
        ctx = self.context(
            chapter="Semester 1 Unit 1 - Landscapes",
            topic="Land Art and Environmental Appreciation",
        )

        ans = service.ask(message="Explain Land Art and Environmental Appreciation", context=ctx)
        self.assertIn("Teacher-authored content", ans)
        self.assertEqual(service.last_metrics.route, "local-syllabus")


if __name__ == "__main__":
    unittest.main()
