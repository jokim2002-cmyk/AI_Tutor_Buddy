from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

from phase11_ai import GyanVerseAIService
from phase11_core import LearningMode, StudentLearningContext, SyllabusRepository, detect_context_from_message


class Grade8ScienceTechnologySyllabusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project_root = Path(__file__).resolve().parents[1]
        cls.syllabus_dir = cls.project_root / "syllabus"
        cls.package_path = cls.syllabus_dir / "gseb-english-8-science-technology.json"
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
        subject: str = "Science & Technology",
        chapter: str = "Chapter 1 - Crop Production and Management",
        topic: str = "Agricultural Practices and Preparation of Soil",
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
        self.assertEqual(payload.get("subject"), "Science & Technology")

        source = payload.get("source", {})
        pdf_hashes = source.get("pdf_sha256", {})
        self.assertEqual(
            pdf_hashes.get("STD_8_Science_EnglishMedium.pdf"),
            "56a48fef35515f3ed54196986624857adeec5e44868b8daccf1c4a841a8be1c6",
        )

    def test_discoverable_through_repository(self) -> None:
        syllabus = self.repo.find(
            board="GSEB",
            medium="English",
            standard=8,
            subject="Science & Technology",
        )
        self.assertIsNotNone(syllabus, "Grade 8 Science & Technology package must be discoverable via SyllabusRepository")
        self.assertEqual(syllabus.key, "gseb-english-8-science-technology")
        self.assertEqual(syllabus.subject, "Science & Technology")

    def test_plain_science_alias_resolves_correctly(self) -> None:
        ctx = self.context(subject="Science")
        updated_ctx, detected = detect_context_from_message("I need help with Science", ctx, self.repo)
        self.assertEqual(updated_ctx.current_subject, "Science & Technology")
        self.assertEqual(detected.get("subject"), "Science & Technology")

    def test_exact_chapter_and_topic_counts(self) -> None:
        syllabus = self.repo.find(
            board="GSEB",
            medium="English",
            standard=8,
            subject="Science & Technology",
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
            subject="Science & Technology",
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
            subject="Science & Technology",
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
            chapter="Chapter 3 - Coal and Petroleum",
            topic="Inexhaustible and Exhaustible Natural Resources",
        )
        ans = service.ask(
            message="Give me two examples of inexhaustible natural resources",
            context=ctx,
        )
        self.assertIn("Teacher-authored content", ans)
        self.assertEqual(service.last_metrics.route, "local-syllabus")

    def test_stored_exercises_map_one_to_one_with_solutions(self) -> None:
        syllabus = self.repo.find(
            board="GSEB",
            medium="English",
            standard=8,
            subject="Science & Technology",
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
            chapter="Chapter 3 - Coal and Petroleum",
            topic="Inexhaustible and Exhaustible Natural Resources",
        )
        hint_response = service.ask(
            message="Give me a hint for the question: Is natural gas exhaustible or inexhaustible?",
            context=ctx,
        )
        self.assertIn("Hint", hint_response)
        self.assertNotIn("Exhaustible natural resource", hint_response)
        self.assertEqual(service.last_metrics.route, "local-syllabus")

    def test_deterministic_answer_reviews_marked_locally(self) -> None:
        service = self.service(api_key="mock-key")
        ctx = self.context(
            chapter="Chapter 10 - Sound",
            topic="Medium for Sound Propagation, Amplitude, Frequency and Pitch",
        )

        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            correct = service.ask_stream(
                message="Question: Can sound travel through a vacuum? Explain with a simple bell jar thought experiment. My answer: No. Is my answer correct?",
                context=ctx,
            )
            self.assertIn("Result: Correct.", correct)
            self.assertEqual(service.last_metrics.route, "local-syllabus")

            wrong = service.ask_stream(
                message="Question: Can sound travel through a vacuum? Explain with a simple bell jar thought experiment. My answer: Yes. Is my answer correct?",
                context=ctx,
            )
            self.assertIn("Result: Incorrect.", wrong)
            self.assertEqual(service.last_metrics.route, "local-syllabus")

    def test_open_ended_answers_not_falsely_marked_by_guessing(self) -> None:
        service = self.service(api_key="mock-key")
        ctx = self.context(
            chapter="Chapter 1 - Crop Production and Management",
            topic="Agricultural Practices and Preparation of Soil",
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
                message="Question: Why is turning and loosening of soil essential before sowing seeds? My answer: It allows roots to breathe deep, helps microbes growth, and brings nutrient rich soil to top layer. Is my answer correct?",
                context=ctx,
            )
        self.assertEqual(review, "Grounded open-ended evaluation by AI tutor.")
        self.assertEqual(service.last_metrics.route, "gemini-single-chunk")
        service._client.models.generate_content_stream.assert_called_once()

    def test_all_chapter_test_wording_variants_work(self) -> None:
        service = self.service(api_key="")

        variants = [
            "Generate a chapter test for Coal and Petroleum",
            "Generate a chapter test with answers for Coal and Petroleum",
            "Generate a chapter test and answers for Coal and Petroleum",
        ]

        for prompt in variants:
            ctx = self.context(
                chapter="Chapter 3 - Coal and Petroleum",
                topic="Inexhaustible and Exhaustible Natural Resources",
            )
            resp = service.ask(message=prompt, context=ctx)
            self.assertIn("Chapter test", resp)
            self.assertEqual(service.last_metrics.route, "local-syllabus")

    def test_science_safety_boundaries_pass(self) -> None:
        syllabus = self.repo.find(
            board="GSEB",
            medium="English",
            standard=8,
            subject="Science & Technology",
        )
        self.assertIsNotNone(syllabus)

        # Check Chapter 11 (Chemical Effects of Electric Current) for low-voltage battery safety boundary
        ch11 = next(c for c in syllabus.chapters if "Chemical Effects" in c.title)
        topic1 = ch11.topics[0]
        self.assertIn("low-voltage", topic1.title.lower())
        self.assertIn("household mains", topic1.explanation.lower())

        service = self.service(api_key="")
        ctx = self.context(
            chapter="Chapter 11 - Chemical Effects of Electric Current",
            topic="Do Liquids Conduct Electricity? (Low-Voltage Tester)",
        )
        ans = service.ask(
            message="Safety check: What power source must be used for testing electrical conductivity of liquids in school labs?",
            context=ctx,
        )
        self.assertIn("low-voltage", ans.lower())
        self.assertIn("mains", ans.lower())

    def test_grade_7_science_remains_isolated(self) -> None:
        service = self.service(api_key="")

        # Grade 7 Science query (Magnet)
        ctx_g7 = StudentLearningContext(
            board="GSEB",
            medium="English",
            standard=7,
            preferred_language="English",
            current_subject="Science & Technology",
            current_chapter="Semester 1 — Properties of Magnet",
            current_topic="Magnetic materials and poles",
            learning_mode=LearningMode.EXPLAIN.value,
            onboarding_complete=True,
        ).validate()

        ans_g7 = service.ask(message="Explain magnetic materials and poles", context=ctx_g7)
        self.assertIn("magnet attracts magnetic materials", ans_g7.lower())
        self.assertNotIn("Coal and Petroleum", ans_g7)

        # Grade 8 Science query (Coal and Petroleum)
        ctx_g8 = self.context(
            chapter="Chapter 3 - Coal and Petroleum",
            topic="Inexhaustible and Exhaustible Natural Resources",
        )
        ans_g8 = service.ask(message="Explain inexhaustible and exhaustible natural resources", context=ctx_g8)
        self.assertIn("inexhaustible resources", ans_g8.lower())
        self.assertNotIn("Magnet", ans_g8)

    def test_grade_8_english_and_mathematics_remain_isolated(self) -> None:
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
        self.assertNotIn("Coal and Petroleum", ans_eng8)

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
        self.assertNotIn("Coal and Petroleum", ans_math8)

    def test_exact_local_syllabus_routes_do_not_consume_provider(self) -> None:
        service = self.service(api_key="")
        ctx = self.context(
            chapter="Chapter 3 - Coal and Petroleum",
            topic="Inexhaustible and Exhaustible Natural Resources",
        )

        ans = service.ask(message="Explain Inexhaustible and Exhaustible Natural Resources", context=ctx)
        self.assertIn("Teacher-authored content", ans)
        self.assertEqual(service.last_metrics.route, "local-syllabus")

    def test_grade_8_science_damaged_seeds_hint_route(self) -> None:
        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            service = self.service(api_key="mock_key")
            ctx = self.context(
                chapter="Chapter 1 - Crop Production and Management",
                topic="Sowing, Manures and Fertilisers",
            )
            prompt = "Give me only one hint for this homework question: Why should damaged seeds be separated before sowing?"
            response = service.ask_stream(message=prompt, context=ctx)

            self.assertNotIn("online tutor could not respond", response)
            self.assertIn("Sowing, Manures and Fertilisers", response)
            self.assertIn("Hint:", response)
            self.assertNotIn("Hints:\n", response)
            self.assertNotIn("separating them ensures only healthy, high-yielding seeds are sown", response)
            self.assertIn("Source type:", response)
            self.assertTrue(
                "Science Class VIII" in response or "Standard 8 Science" in response,
                "Source footer must cite Science Class VIII or Standard 8 Science",
            )

    def test_grade_8_cross_subject_hint_route_smoke(self) -> None:
        test_cases = [
            (
                "Science & Technology",
                "Chapter 1 - Crop Production and Management",
                "Give me only one hint for this homework question: Why should damaged seeds be separated before sowing?",
                "Sowing, Manures and Fertilisers",
                "Science Class VIII",
            ),
            (
                "Mathematics",
                "Chapter 1 - Rational Numbers",
                "Give me only one hint for this homework question: Evaluate using distributive property: (2/5 * -3/7) - (1/14) - (3/7 * 3/5)",
                "Properties of Rational Numbers",
                "Mathematics Textbook for Class VIII",
            ),
            (
                "English",
                "Semester 1 Unit 1 - Landscapes",
                "Give me only one hint for this homework question: What is Land Art?",
                "Land Art and Environmental Appreciation",
                "English First Language Standard 8",
            ),
            (
                "Social Science",
                "Chapter 1 - Establishment of European and British Rule in India",
                "Give me only one hint for this homework question: Why did European nations search for a sea route to India in the 15th century?",
                "Arrival of European Traders and Sea Routes",
                "Social Science Standard 8",
            ),
        ]
        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            for subject, chapter, prompt, expected_topic, expected_source in test_cases:
                ctx = StudentLearningContext(
                    board="GSEB",
                    medium="English",
                    standard=8,
                    preferred_language="English",
                    current_subject=subject,
                    current_chapter=chapter,
                    onboarding_complete=True,
                ).validate()

                service = self.service(api_key="mock_key")
                response = service.ask_stream(message=prompt, context=ctx)
                self.assertNotIn("online tutor could not respond", response, f"Hint for {subject} must not fail to online tutor")
                self.assertIn(expected_topic, response, f"Hint for {subject} must contain topic '{expected_topic}'")
                self.assertIn("Hint:", response, f"Hint for {subject} must contain 'Hint:' label")
                self.assertIn("Source type:", response, f"Hint for {subject} must contain source footer")
                self.assertIn(expected_source, response, f"Hint for {subject} source footer must contain '{expected_source}'")


if __name__ == "__main__":
    unittest.main()

