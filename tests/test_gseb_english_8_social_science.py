from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

from phase11_ai import GyanVerseAIService
from phase11_core import LearningMode, StudentLearningContext, SyllabusRepository, detect_context_from_message


class Grade8SocialScienceSyllabusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project_root = Path(__file__).resolve().parents[1]
        cls.syllabus_dir = cls.project_root / "syllabus"
        cls.package_path = cls.syllabus_dir / "gseb-english-8-social-science.json"
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
        subject: str = "Social Science",
        chapter: str = "Chapter 15 - Indian Constitution",
        topic: str = "Need for a Constitution and Framing of Indian Constitution",
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
        self.assertEqual(payload.get("subject"), "Social Science")

        source = payload.get("source", {})
        pdf_hashes = source.get("pdf_sha256", {})
        self.assertEqual(
            pdf_hashes.get("Std-8_Social_Science_EnglishMedium.pdf"),
            "5067928b1f60ee0519fe24e7c8907b768653c9ba7c6dbca80cf09a60b2211254",
        )

    def test_discoverable_through_repository(self) -> None:
        syllabus = self.repo.find(
            board="GSEB",
            medium="English",
            standard=8,
            subject="Social Science",
        )
        self.assertIsNotNone(syllabus, "Grade 8 Social Science package must be discoverable via SyllabusRepository")
        self.assertEqual(syllabus.key, "gseb-english-8-social-science")
        self.assertEqual(syllabus.subject, "Social Science")

    def test_social_studies_alias_resolves_correctly(self) -> None:
        ctx = self.context(subject="Social Studies")
        updated_ctx, detected = detect_context_from_message("I need help with Social Studies", ctx, self.repo)
        self.assertEqual(updated_ctx.current_subject, "Social Science")
        self.assertEqual(detected.get("subject"), "Social Science")

    def test_exact_chapter_and_topic_counts(self) -> None:
        syllabus = self.repo.find(
            board="GSEB",
            medium="English",
            standard=8,
            subject="Social Science",
        )
        self.assertIsNotNone(syllabus)
        self.assertEqual(len(syllabus.chapters), 19, "Must have exactly 19 chapters")

        all_topics = [t for c in syllabus.chapters for t in c.topics]
        self.assertEqual(len(all_topics), 57, "Must have exactly 57 topics (3 per chapter)")

    def test_every_chapter_has_valid_topic_coverage(self) -> None:
        syllabus = self.repo.find(
            board="GSEB",
            medium="English",
            standard=8,
            subject="Social Science",
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
            subject="Social Science",
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
            chapter="Chapter 15 - Indian Constitution",
            topic="Need for a Constitution and Framing of Indian Constitution",
        )
        ans = service.ask(
            message="Give me two examples of key features of the Indian Constitution",
            context=ctx,
        )
        self.assertIn("Teacher-authored content", ans)
        self.assertEqual(service.last_metrics.route, "local-syllabus")

    def test_stored_exercises_map_one_to_one_with_solutions(self) -> None:
        syllabus = self.repo.find(
            board="GSEB",
            medium="English",
            standard=8,
            subject="Social Science",
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
            chapter="Chapter 15 - Indian Constitution",
            topic="Need for a Constitution and Framing of Indian Constitution",
        )
        hint_response = service.ask(
            message="Give me a hint for the question: Who served as the President of the Constituent Assembly?",
            context=ctx,
        )
        self.assertIn("Hint", hint_response)
        self.assertNotIn("Dr. Rajendra Prasad.", hint_response)
        self.assertEqual(service.last_metrics.route, "local-syllabus")

    def test_deterministic_answer_reviews_marked_locally(self) -> None:
        service = self.service(api_key="mock-key")
        ctx = self.context(
            chapter="Chapter 17 - The Judiciary",
            topic="Structure of Indian Judiciary: Integrated System",
        )

        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            correct = service.ask_stream(
                message="Question: Is the decision of the Supreme Court of India binding on all lower courts in India? My answer: Yes. Is my answer correct?",
                context=ctx,
            )
            self.assertIn("Result: Correct.", correct)
            self.assertEqual(service.last_metrics.route, "local-syllabus")

            wrong = service.ask_stream(
                message="Question: Is the decision of the Supreme Court of India binding on all lower courts in India? My answer: No. Is my answer correct?",
                context=ctx,
            )
            self.assertIn("Result: Incorrect.", wrong)
            self.assertEqual(service.last_metrics.route, "local-syllabus")

    def test_open_ended_answers_not_falsely_marked_by_guessing(self) -> None:
        service = self.service(api_key="mock-key")
        ctx = self.context(
            chapter="Chapter 15 - Indian Constitution",
            topic="Key Features: Preamble, Secularism, Federalism and Parliamentary System",
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
                message="Question: What is meant by a 'Secular State' in the Indian Constitution? My answer: It means equal treatment of all religions by the state without adopting an official religion. Is my answer correct?",
                context=ctx,
            )
        self.assertEqual(review, "Grounded open-ended evaluation by AI tutor.")
        self.assertEqual(service.last_metrics.route, "gemini-single-chunk")
        service._client.models.generate_content_stream.assert_called_once()

    def test_all_chapter_test_wording_variants_work(self) -> None:
        service = self.service(api_key="")

        variants = [
            "Generate a chapter test for Indian Constitution",
            "Generate a chapter test with answers for Indian Constitution",
            "Generate a chapter test and answers for Indian Constitution",
        ]

        for prompt in variants:
            ctx = self.context(
                chapter="Chapter 15 - Indian Constitution",
                topic="Need for a Constitution and Framing of Indian Constitution",
            )
            resp = service.ask(message=prompt, context=ctx)
            self.assertIn("Chapter test", resp)
            self.assertEqual(service.last_metrics.route, "local-syllabus")

    def test_civic_and_inclusion_safety_boundaries_pass(self) -> None:
        syllabus = self.repo.find(
            board="GSEB",
            medium="English",
            standard=8,
            subject="Social Science",
        )
        self.assertIsNotNone(syllabus)

        # Check Chapter 16 (Parliament and Law - Peaceful democratic protests)
        ch16 = next(c for c in syllabus.chapters if "Parliament and Law" in c.title)
        topic3 = ch16.topics[2]
        self.assertIn("Peaceful Democratic Protests", topic3.title)
        self.assertIn("peaceful", topic3.explanation.lower())
        self.assertIn("public property", topic3.explanation.lower())

        service = self.service(api_key="")
        ctx = self.context(
            chapter="Chapter 16 - Parliament and Law",
            topic="Rule of Law, Unpopular Laws and Peaceful Democratic Protests",
        )
        ans = service.ask(
            message="Civic Safety: How should citizens express opposition to an unpopular law in a democracy?",
            context=ctx,
        )
        self.assertIn("peaceful", ans.lower())
        self.assertIn("damaging public property", ans.lower())

    def test_grade_7_social_science_remains_isolated(self) -> None:
        service = self.service(api_key="")

        # Grade 7 Social Science query (Harshavardhana)
        ctx_g7 = StudentLearningContext(
            board="GSEB",
            medium="English",
            standard=7,
            preferred_language="English",
            current_subject="Social Science",
            current_chapter="Semester 1 — Two Big States",
            current_topic="Harshavardhana and the kingdom of Kanauj",
            learning_mode=LearningMode.EXPLAIN.value,
            onboarding_complete=True,
        ).validate()

        ans_g7 = service.ask(message="Explain Harshavardhana and the kingdom of Kanauj", context=ctx_g7)
        self.assertIn("harshavardhana ruled a large north indian kingdom", ans_g7.lower())
        self.assertNotIn("Indian Constitution", ans_g7)

        # Grade 8 Social Science query (Indian Constitution)
        ctx_g8 = self.context(
            chapter="Chapter 15 - Indian Constitution",
            topic="Need for a Constitution and Framing of Indian Constitution",
        )
        ans_g8 = service.ask(message="Explain Need for a Constitution and Framing of Indian Constitution", context=ctx_g8)
        self.assertIn("constitution", ans_g8.lower())
        self.assertNotIn("Harshavardhana", ans_g8)

    def test_all_existing_grade_8_english_medium_subjects_remain_isolated(self) -> None:
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
        self.assertNotIn("Indian Constitution", ans_eng8)

        # Grade 8 Maths query
        ctx_math8 = StudentLearningContext(
            board="GSEB",
            medium="English",
            standard=8,
            preferred_language="English",
            current_subject="Mathematics",
            current_chapter="Chapter 5 - Squares and Square Roots",
            current_topic="Properties of Square Numbers and Patterns",
            learning_mode=LearningMode.EXPLAIN.value,
            onboarding_complete=True,
        ).validate()
        ans_math8 = service.ask(message="Explain properties of square numbers and patterns", context=ctx_math8)
        self.assertIn("square number", ans_math8.lower())
        self.assertNotIn("Indian Constitution", ans_math8)

        # Grade 8 Science query
        ctx_sci8 = StudentLearningContext(
            board="GSEB",
            medium="English",
            standard=8,
            preferred_language="English",
            current_subject="Science & Technology",
            current_chapter="Chapter 3 - Coal and Petroleum",
            current_topic="Inexhaustible and Exhaustible Natural Resources",
            learning_mode=LearningMode.EXPLAIN.value,
            onboarding_complete=True,
        ).validate()
        ans_sci8 = service.ask(message="Explain inexhaustible and exhaustible natural resources", context=ctx_sci8)
        self.assertIn("inexhaustible resources", ans_sci8.lower())
        self.assertNotIn("Indian Constitution", ans_sci8)

    def test_exact_local_syllabus_routes_do_not_consume_provider(self) -> None:
        service = self.service(api_key="")
        ctx = self.context(
            chapter="Chapter 15 - Indian Constitution",
            topic="Need for a Constitution and Framing of Indian Constitution",
        )

        ans = service.ask(message="Explain Need for a Constitution and Framing of Indian Constitution", context=ctx)
        self.assertIn("Teacher-authored content", ans)
        self.assertEqual(service.last_metrics.route, "local-syllabus")


if __name__ == "__main__":
    unittest.main()
