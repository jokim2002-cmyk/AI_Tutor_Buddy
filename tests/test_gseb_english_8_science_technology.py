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
                message="Question: How do farmers test soil acidity in modern agriculture? My answer: They use electronic pH meters. Is my answer correct?",
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

    def test_grade_8_science_damaged_seeds_answer_review_route(self) -> None:
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
            # 1. Correct answer review prompt
            # 1. Partial answer review prompt (method given, missing why reason)
            prompt_partial = (
                "Question: Why should damaged seeds be separated before sowing? "
                "My answer: Because damaged hollow seeds float in water and healthy seeds sink. "
                "Is my answer correct?"
            )
            res_partial = service.ask_stream(message=prompt_partial, context=ctx)
            self.assertNotIn("online tutor could not respond", res_partial)
            self.assertIn("Sowing, Manures and Fertilisers", res_partial)
            self.assertIn("Question: Why should damaged seeds be separated before sowing?", res_partial)
            self.assertIn("Your answer: Because damaged hollow seeds float in water and healthy seeds sink", res_partial)
            self.assertIn("Result: Partially correct.", res_partial)
            self.assertNotIn("Result: Correct.", res_partial)
            self.assertIn("Source type:", res_partial)
            self.assertTrue(
                "Science Class VIII" in res_partial or "Standard 8 Science" in res_partial,
                "Source footer must cite Science Class VIII",
            )

            # 2. Full answer review prompt (complete why reason)
            prompt_full = (
                "Question: Why should damaged seeds be separated before sowing? "
                "My answer: Damaged seeds should be separated because they are hollow and weak and may not grow into healthy plants, so farmers should sow healthy seeds. "
                "Is my answer correct?"
            )
            res_full = service.ask_stream(message=prompt_full, context=ctx)
            self.assertNotIn("online tutor could not respond", res_full)
            self.assertIn("Result: Correct.", res_full)
            self.assertIn("Source type:", res_full)

            # 3. Wrong answer review prompt
            prompt_wrong = (
                "Question: Why should damaged seeds be separated before sowing? "
                "My answer: Because they are colorful. "
                "Is my answer correct?"
            )
            res_wrong = service.ask_stream(message=prompt_wrong, context=ctx)
            self.assertNotIn("online tutor could not respond", res_wrong)
            self.assertIn("Result: Incorrect.", res_wrong)
            self.assertIn("Source type:", res_wrong)

    def test_grade_8_cross_subject_answer_review_smoke(self) -> None:
        test_cases = [
            (
                "Mathematics",
                "Chapter 1 - Rational Numbers",
                "Question: Evaluate using distributive property: (2/5 * -3/7) - (1/14) - (3/7 * 3/5). My answer: -1/2. Is my answer correct?",
                "Properties of Rational Numbers",
                "Result: Correct.",
                "Mathematics Textbook for Class VIII",
            ),
            (
                "Social Science",
                "Chapter 1 - Establishment of European and British Rule in India",
                "Question: Why did European nations search for a sea route to India in the 15th century? My answer: Because land trade routes were blocked after Constantinople fell. Is my answer correct?",
                "Arrival of European Traders and Sea Routes",
                "Result: Correct.",
                "Social Science Standard 8",
            ),
            (
                "English",
                "Semester 1 Unit 1 - Landscapes",
                "Question: Is Land Art meant to last forever in a museum? Explain. My answer: No. Is my answer correct?",
                "Land Art and Environmental Appreciation",
                "Result: Correct.",
                "English First Language Standard 8",
            ),
        ]
        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            for subject, chapter, prompt, expected_topic, expected_result, expected_source in test_cases:
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
                self.assertNotIn("online tutor could not respond", response, f"Review for {subject} must not fail to online tutor")
                self.assertIn(expected_topic, response, f"Review for {subject} must contain topic '{expected_topic}'")
                self.assertIn(expected_result, response, f"Review for {subject} must contain '{expected_result}'")
                self.assertIn("Source type:", response, f"Review for {subject} must contain source footer")
                self.assertIn(expected_source, response, f"Review for {subject} source footer must contain '{expected_source}'")

    def test_grade_8_test_paper_generation_all_requirements(self) -> None:
        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            service = self.service(api_key="mock_key")

            # 1. Grade 8 Math saved context + "Chapter 1 ka test banao"
            ctx_math = StudentLearningContext(
                board="GSEB",
                medium="English",
                standard=8,
                current_subject="Mathematics",
                current_chapter="Chapter 1 - Rational Numbers",
                onboarding_complete=True,
            ).validate()
            res_math = service.ask_stream(message="Chapter 1 ka test banao", context=ctx_math)
            self.assertNotIn("online tutor could not respond", res_math)
            self.assertIn("Subject: Mathematics", res_math)
            self.assertIn("Total Marks: 25 Marks", res_math)
            self.assertIn("Time: 45 Minutes", res_math)
            self.assertIn("Mathematics Textbook for Class VIII", res_math)
            self.assertNotIn("Answer Guide:", res_math)
            # Verify single-chapter distribution across multiple topics
            self.assertIn("[Properties of Rational Numbers]", res_math)
            self.assertIn("[Representation of Rational Numbers on the Number Line]", res_math)
            service._client.models.generate_content_stream.assert_not_called()

            # 2. Grade 8 Science saved context + "Chapter 1 to 3 ka 50 marks test banao"
            ctx_sci = StudentLearningContext(
                board="GSEB",
                medium="English",
                standard=8,
                current_subject="Science & Technology",
                current_chapter="Chapter 1 - Crop Production and Management",
                onboarding_complete=True,
            ).validate()
            res_sci = service.ask_stream(message="Chapter 1 to 3 ka 50 marks test banao", context=ctx_sci)
            self.assertNotIn("online tutor could not respond", res_sci)
            self.assertIn("Subject: Science & Technology", res_sci)
            self.assertIn("Total Marks: 50 Marks", res_sci)
            self.assertIn("Time: 90 Minutes", res_sci)
            self.assertIn("Science Class VIII", res_sci)
            self.assertNotIn("Answer Guide:", res_sci)
            # Verify multi-chapter distribution across Chapters 1, 2, and 3
            self.assertIn("[Sowing, Manures and Fertilisers]", res_sci)  # Chapter 1 topic
            self.assertIn("[Types and Habitats of Microorganisms]", res_sci)  # Chapter 2 topic
            self.assertIn("[Coal, Carbonisation and Coal Products]", res_sci)  # Chapter 3 topic

            # 3. Grade 8 Social Science + "Full book ka 3 hour 100 marks test banao"
            ctx_soc = StudentLearningContext(
                board="GSEB",
                medium="English",
                standard=8,
                current_subject="Social Science",
                current_chapter="Chapter 1 - Establishment of European and British Rule in India",
                onboarding_complete=True,
            ).validate()
            res_soc = service.ask_stream(message="Full book ka 3 hour 100 marks test banao", context=ctx_soc)
            self.assertNotIn("online tutor could not respond", res_soc)
            self.assertIn("Subject: Social Science", res_soc)
            self.assertIn("Total Marks: 100 Marks", res_soc)
            self.assertIn("Time: 3 Hours", res_soc)
            self.assertIn("Social Science Standard 8", res_soc)
            self.assertNotIn("Answer Guide:", res_soc)
            # Verify full-book distribution includes early, middle, and later chapters
            self.assertIn("[Arrival of European Traders and Sea Routes]", res_soc)  # Chapter 1 topic
            self.assertIn("[Formation of INC (1885), Moderates and Extremists]", res_soc)  # Middle Chapter topic
            self.assertTrue(
                any(
                    t in res_soc
                    for t in (
                        "[Non-Conventional Energy Resources and Conservation]",
                        "[Understanding Social Justice and Marginalised Groups]",
                        "[Role of Government in Providing Public Facilities]",
                        "[Factors Influencing Population Distribution]",
                    )
                )
            )

            # 4. Grade 8 English + "Chapter 1 test with answers"
            ctx_eng = StudentLearningContext(
                board="GSEB",
                medium="English",
                standard=8,
                current_subject="English",
                current_chapter="Semester 1 Unit 1 - Landscapes",
                onboarding_complete=True,
            ).validate()
            res_eng = service.ask_stream(message="Chapter 1 test with answers", context=ctx_eng)
            self.assertNotIn("online tutor could not respond", res_eng)
            self.assertIn("Subject: English", res_eng)
            self.assertIn("Total Marks: 25 Marks", res_eng)
            self.assertIn("Answer Guide:", res_eng)
            self.assertIn("English First Language Standard 8", res_eng)

            # 8. Grade 7/Grade 8 isolation check
            ctx_g7 = StudentLearningContext(
                board="GSEB",
                medium="English",
                standard=7,
                current_subject="Mathematics",
                current_chapter="Chapter 1 - Integers",
                onboarding_complete=True,
            ).validate()
            res_g7 = service.ask_stream(message="Chapter 1 ka test banao", context=ctx_g7)
            self.assertIn("Standard: 7", res_g7)
            self.assertNotIn("Standard: 8", res_g7)

    def test_grade_8_test_answer_evaluation_all_scenarios(self) -> None:
        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            service = self.service(api_key="mock_key")

            # 5. Guard test: ask to evaluate without prior generated test paper
            ctx_math = StudentLearningContext(
                board="GSEB",
                medium="English",
                standard=8,
                current_subject="Mathematics",
                current_chapter="Chapter 1 - Rational Numbers",
                onboarding_complete=True,
            ).validate()
            res_no_paper = service.ask_stream(message="Check my test answers out of 25", context=ctx_math)
            self.assertIn("No test paper has been generated in our current session yet", res_no_paper)
            service._client.models.generate_content_stream.assert_not_called()

            # 1. Science Chapter 1 Test generation
            ctx_sci = StudentLearningContext(
                board="GSEB",
                medium="English",
                standard=8,
                current_subject="Science & Technology",
                current_chapter="Chapter 1 - Crop Production and Management",
                onboarding_complete=True,
            ).validate()
            gen_sci = service.ask_stream(message="Chapter 1 ka 25 marks test banao", context=ctx_sci)
            self.assertNotIn("Answer Guide:", gen_sci)

            # 1a. Mismatched numbered answers (triggers warning, no silent 0/25 final)
            pasted_mismatched_sci = """Here are my answers:
1. Turning and loosening of soil allows roots to penetrate deep into the soil and breathe easily.
2. Classify wheat as Rabi crop and paddy as Kharif crop.
3. Traditional tool funnels seeds into soil whereas modern seed drill sows seeds uniformly at equal distance and depth.
4. Because damaged hollow seeds float in water and healthy seeds sink.
5. Damaged seeds are red in color.
6. Leveller is used for levelling soil."""
            eval_warning = service.ask_stream(message=pasted_mismatched_sci, context=ctx_sci)
            self.assertIn("Your pasted answers do not appear to match the question numbers", eval_warning)
            self.assertIn("Detected Question Mismatches:", eval_warning)
            self.assertNotIn("Total Marks: 0/25", eval_warning)
            service._client.models.generate_content_stream.assert_not_called()

            # 1b. Correctly ordered valid answers (grades Q1-Q6 correctly, Q7-Q12 Not answered)
            paper_qs = service._last_generated_test_paper.questions
            pasted_valid_sci = "\n".join(f"{q.question_num}. {q.solution_guide}" for q in paper_qs[:6])
            eval_sci = service.ask_stream(message=pasted_valid_sci, context=ctx_sci)
            self.assertIn("Test Evaluation", eval_sci)
            self.assertIn("Per-Question Evaluation:", eval_sci)
            self.assertIn("Science Class VIII", eval_sci)
            self.assertIn("| Q3 |", eval_sci)
            self.assertIn("Correct |", eval_sci)
            self.assertIn("Weak Topics Identified:", eval_sci)
            self.assertIn("Suggested Revision Plan:", eval_sci)
            self.assertIn("Not answered", eval_sci)
            self.assertNotIn("Total Marks: 0/25", eval_sci)
            service._client.models.generate_content_stream.assert_not_called()

            # 1c. Question-text answer format
            pasted_qtext_sci = """Q1. Classify wheat and paddy as Kharif or Rabi crops.
Ans: Paddy is a Kharif crop and wheat is a Rabi crop.

Q2. Why should damaged seeds be separated before sowing?
Ans: Damaged seeds should be separated because they are hollow and weak."""
            eval_qtext = service.ask_stream(message=pasted_qtext_sci, context=ctx_sci)
            self.assertIn("Test Evaluation", eval_qtext)
            self.assertIn("Science Class VIII", eval_qtext)
            service._client.models.generate_content_stream.assert_not_called()

            # 2. Mathematics Chapter 1 Test generation + deterministic numeric answer evaluation
            gen_math = service.ask_stream(message="Chapter 1 ka test banao", context=ctx_math)
            self.assertNotIn("Answer Guide:", gen_math)

            pasted_math_answers = """Here are my answers:
1. -5/9
2. 0
3. 1
4. -3/7
5. 5/9"""
            eval_math = service.ask_stream(message=pasted_math_answers, context=ctx_math)
            self.assertIn("Test Evaluation", eval_math)
            self.assertIn("Total Marks:", eval_math)
            self.assertIn("Mathematics Textbook for Class VIII", eval_math)

            # 3. Social Science 50-mark multi-chapter test generation + conceptual evaluation
            ctx_soc = StudentLearningContext(
                board="GSEB",
                medium="English",
                standard=8,
                current_subject="Social Science",
                current_chapter="Chapter 1 - Establishment of European and British Rule in India",
                onboarding_complete=True,
            ).validate()
            gen_soc = service.ask_stream(message="Chapter 1 to 3 ka 50 marks test banao", context=ctx_soc)
            self.assertNotIn("Answer Guide:", gen_soc)

            pasted_soc_answers = """Q1. European nations searched for sea route after Ottoman Turks captured Constantinople.
Ans: European nations searched for sea route after Ottoman Turks captured Constantinople in 1453.

Q2. Permanent Settlement in Bengal.
Ans: Permanent Settlement was introduced by Lord Cornwallis in 1793 in Bengal."""
            eval_soc = service.ask_stream(message=pasted_soc_answers, context=ctx_soc)
            self.assertIn("Test Evaluation", eval_soc)
            self.assertIn("Social Science Standard 8", eval_soc)
            service._client.models.generate_content_stream.assert_not_called()

    def test_std8_science_chapter1_three_examples_count_provider(self) -> None:
        service = self.service(api_key="mock_key")
        ctx = self.context(
            chapter="Chapter 1 - Crop Production and Management",
            topic="Agricultural Practices and Preparation of Soil",
        )
        service._client.models.generate_content.return_value = MagicMock(
            text="1. Preparation of soil by tilling.\n2. Sowing using seed drills.\n3. Irrigation using drip system.\n\nSource type: Teacher-authored content. GSEB English Standard 8 Science & Technology."
        )

        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            resp = service.ask(message="give me 3 example of chapter 1", context=ctx)

        self.assertIn("1. Preparation of soil", resp)
        self.assertIn("2. Sowing using", resp)
        self.assertIn("3. Irrigation using", resp)
        self.assertIn("Source type:", resp)
        self.assertEqual(service.last_metrics.route, "gemini-text")
        service._client.models.generate_content.assert_called_once()

    def test_flexible_example_request_uses_provider_when_configured(self) -> None:
        service = self.service(api_key="mock_key")
        ctx = self.context(
            chapter="Chapter 1 - Crop Production and Management",
            topic="Agricultural Practices and Preparation of Soil",
        )
        service._client.models.generate_content.return_value = MagicMock(
            text="Here are flexible examples grounded in Chapter 1:\n1. Tilling using plough\n2. Sowing healthy seeds"
        )

        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            resp = service.ask(message="give me examples of preparation of soil in simple language", context=ctx)

        self.assertIn("flexible examples grounded in Chapter 1", resp)
        self.assertEqual(service.last_metrics.route, "gemini-text")
        service._client.models.generate_content.assert_called_once()

    def test_provider_failure_falls_back_to_local_answer(self) -> None:
        service = self.service(api_key="mock_key")
        ctx = self.context(
            chapter="Chapter 1 - Crop Production and Management",
            topic="Agricultural Practices and Preparation of Soil",
        )
        service._client.models.generate_content.side_effect = RuntimeError("API Connection Failure")

        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            resp = service.ask(message="give me 3 example of chapter 1", context=ctx)

        self.assertIn("Teacher-authored content", resp)
        self.assertTrue(service.last_metrics.fallback_used)
        self.assertIn("fallback", service.last_metrics.route)

    def test_test_evaluation_does_not_call_provider(self) -> None:
        service = self.service(api_key="mock_key")
        ctx = self.context(
            chapter="Chapter 1 - Crop Production and Management",
            topic="Agricultural Practices and Preparation of Soil",
        )

        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            # Generate test paper locally
            test_resp = service.ask(message="Chapter 1 test banao", context=ctx)
            self.assertIn("Chapter test", test_resp)
            service._client.models.generate_content.assert_not_called()

            # Evaluate test paper locally
            eval_resp = service.ask(
                message="check my test answers\n1. ans1\n2. ans2\n3. ans3",
                context=ctx,
            )
            self.assertIn("Test Evaluation", eval_resp)
            self.assertEqual(service.last_metrics.route, "local-syllabus")
            service._client.models.generate_content.assert_not_called()

    def test_exact_stored_question_hint_uses_local_deterministic_route(self) -> None:
        service = self.service(api_key="mock_key")
        ctx = self.context(
            chapter="Chapter 3 - Coal and Petroleum",
            topic="Inexhaustible and Exhaustible Natural Resources",
        )

        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            resp = service.ask(
                message="Give me a hint for the question: Is natural gas exhaustible or inexhaustible?",
                context=ctx,
            )

        self.assertIn("Hint:", resp)
        self.assertEqual(service.last_metrics.route, "local-syllabus")
        service._client.models.generate_content.assert_not_called()

    def test_std8_science_chapter2_is_chapter_ko_explain_karo_uses_active_context(self) -> None:
        service = self.service(api_key="mock_key")
        ctx = self.context(
            chapter="Chapter 2 - Microorganisms : Friend and Foe",
            topic="Friendly Microorganisms and Commercial Uses",
        )
        service._client.models.generate_content.return_value = MagicMock(
            text="Here is Chapter 2 Microorganisms : Friend and Foe explained using syllabus grounding context."
        )

        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            resp = service.ask(message="is chapter ko explain karo", context=ctx)

        self.assertIn("Microorganisms", resp)
        self.assertNotIn("Which subject or chapter", resp)
        self.assertEqual(service.last_metrics.route, "gemini-text")
        service._client.models.generate_content.assert_called_once()
        prompt_arg = service._client.models.generate_content.call_args[1]["contents"][0]
        self.assertIn("Microorganisms", prompt_arg)

    def test_std8_science_chapter2_ye_chapter_samjhao_uses_active_context(self) -> None:
        service = self.service(api_key="mock_key")
        ctx = self.context(
            chapter="Chapter 2 - Microorganisms : Friend and Foe",
            topic="Friendly Microorganisms and Commercial Uses",
        )
        service._client.models.generate_content.return_value = MagicMock(
            text="Microorganisms friend and foe chapter overview grounded in GSEB syllabus."
        )

        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            resp = service.ask(message="ye chapter samjhao", context=ctx)

        self.assertIn("Microorganisms", resp)
        self.assertNotIn("Which subject or chapter", resp)
        self.assertEqual(service.last_metrics.route, "gemini-text")
        service._client.models.generate_content.assert_called_once()

    def test_missing_chapter_context_asks_clarification(self) -> None:
        service = self.service(api_key="")
        ctx = StudentLearningContext(
            board="GSEB",
            medium="English",
            standard=8,
            preferred_language="English",
            current_subject="",
            current_chapter="",
            onboarding_complete=True,
        )
        resp = service.ask(message="is chapter ko explain karo", context=ctx)
        self.assertIn("Which subject or chapter", resp)

    def test_std8_science_chapter3_first_topic_step_by_step_samjhao(self) -> None:
        # Test Provider Route with style constraint
        service = self.service(api_key="mock_key")
        ctx = self.context(
            chapter="Chapter 3 - Coal and Petroleum",
            topic="",
        )
        service._client.models.generate_content.return_value = MagicMock(
            text="1. Inexhaustible natural resources are present in unlimited quantities.\n2. Exhaustible natural resources are limited in nature."
        )

        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            resp = service.ask(
                message="is chapter ke first topic ko step by step samjao",
                context=ctx,
            )

        self.assertIn("Inexhaustible", resp)
        self.assertIn("1.", resp)
        service._client.models.generate_content.assert_called_once()
        prompt_arg = service._client.models.generate_content.call_args[1]["contents"][0]
        self.assertIn("Inexhaustible and Exhaustible Natural Resources", prompt_arg)
        self.assertIn("PRIVATE TEACHING STYLE CONSTRAINT", prompt_arg)
        self.assertIn("step-by-step", prompt_arg)

        # Test Local Fallback Route with step-by-step numbered output
        local_service = self.service(api_key="")
        local_resp = local_service.ask(
            message="is chapter ke first topic ko step by step samjao",
            context=ctx,
        )
        self.assertIn("Inexhaustible and Exhaustible Natural Resources", local_resp)
        self.assertIn("Step-by-step Explanation", local_resp)
        self.assertIn("1.", local_resp)

    def test_strict_scope_lock_out_of_scope_subject_asks_top_selector(self) -> None:
        service = self.service(api_key="mock_key")
        ctx = self.context(
            chapter="Chapter 2 - Microorganisms : Friend and Foe",
            topic="Friendly Microorganisms and Commercial Uses",
        )
        resp = service.ask(
            message="Explain English Chapter 1 - The Best Christmas Present in the World",
            context=ctx,
        )
        self.assertIn("top selector first", resp)
        self.assertIn("English Chapter 1", resp)

    def test_strict_scope_lock_in_scope_chapter_answers_active_chapter(self) -> None:
        service = self.service(api_key="mock_key")
        ctx = self.context(
            chapter="Chapter 3 - Coal and Petroleum",
            topic="",
        )
        service._client.models.generate_content.return_value = MagicMock(
            text="Coal and Petroleum chapter overview grounded in GSEB Std 8 Science syllabus."
        )
        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            resp = service.ask(message="is chapter ko explain karo", context=ctx)

        self.assertIn("Coal and Petroleum", resp)
        self.assertNotIn("top selector first", resp)

    def test_first_and_third_topic_difference_table(self) -> None:
        service = self.service(api_key="")
        ctx = self.context(
            chapter="Chapter 3 - Coal and Petroleum",
            topic="",
        )
        resp = service.ask(
            message="chapter 3 first aur third topic difference table me do",
            context=ctx,
        )
        self.assertIn("Feature / Concept:", resp)
        self.assertIn("Inexhaustible and Exhaustible Natural Resources", resp)
        self.assertIn("Petroleum", resp)

    def test_exact_five_useful_and_five_harmful_examples(self) -> None:
        service = self.service(api_key="")
        ctx = self.context(
            chapter="Chapter 2 - Microorganisms : Friend and Foe",
            topic="",
        )
        resp = service.ask(
            message="harmful aur useful examples exactly 5-5 do",
            context=ctx,
        )
        self.assertIn("Useful Microorganisms (5 Examples)", resp)
        self.assertIn("Harmful Microorganisms (5 Examples)", resp)
        self.assertIn("5.", resp)

    def test_specific_topic_irrigation_types_no_chapter_overview(self) -> None:
        service = self.service(api_key="")
        ctx = self.context(
            chapter="Chapter 1 - Crop Production and Management",
            topic="Irrigation",
        )
        resp = service.ask(
            message="irrigation types explain karo",
            context=ctx,
        )
        self.assertIn("Irrigation", resp)
        self.assertNotIn("Chapter overview", resp)

    def test_science_multi_chapter_test_paper_no_cross_subject_contamination(self) -> None:
        service = self.service(api_key="")
        ctx = self.context(
            chapter="Chapter 1 - Crop Production and Management",
            topic="Agricultural Practices and Preparation of Soil",
        )
        resp = service.ask(
            message="Science 25m test paper banao full book",
            context=ctx,
        )
        self.assertIn("Test Paper:", resp)
        self.assertNotIn("physiographic", resp.lower())
        self.assertNotIn("constitutional role", resp.lower())
        self.assertNotIn("interpret the graph or data display", resp.lower())

    def test_test_paper_answer_guide_matches_question_content(self) -> None:
        from phase11_core import parse_test_paper_scope, render_test_paper, validate_generated_test_paper
        service = self.service(api_key="")
        ctx = self.context(
            chapter="Chapter 2 - Microorganisms : Friend and Foe",
            topic="Friendly Microorganisms and Commercial Uses",
        )
        syl = service.syllabus_repository.find(
            board=ctx.board,
            medium=ctx.medium,
            standard=ctx.standard,
            subject=ctx.current_subject,
        )
        scope = parse_test_paper_scope("Chapter 2 25m test paper with answers", ctx, syl)
        _, paper_obj = render_test_paper(syl, scope, context=ctx, message="Chapter 2 25m test paper with answers")
        self.assertTrue(validate_generated_test_paper(paper_obj, syl))
        for q_item in paper_obj.questions:
            self.assertTrue(q_item.solution_guide and len(q_item.solution_guide) > 5)

    def test_strict_scope_lock_applies_to_answer_reviews_and_concepts(self) -> None:
        service = self.service(api_key="mock_key")
        ctx = self.context(
            chapter="Chapter 2 - Microorganisms : Friend and Foe",
            topic="Friendly Microorganisms and Commercial Uses",
        )
        # Test 1: Answer review for Ch3 concept (carbonisation, coal) while Ch2 is selected
        resp1 = service.ask(
            message="check my answer: coal is formed by carbonisation",
            context=ctx,
        )
        self.assertIn("Please select Chapter 3 - Coal and Petroleum from the top selector first", resp1)

        # Test 2: Question for Ch3 concept (coal tar, coke) while Ch2 is selected
        resp2 = service.ask(
            message="what is coal tar and coke?",
            context=ctx,
        )
        self.assertIn("Please select Chapter 3 - Coal and Petroleum from the top selector first", resp2)

        # Test 3: Yes/No question for Ch3 concept (fossil fuel) while Ch2 is selected
        resp3 = service.ask(
            message="is coal tar a fossil fuel?",
            context=ctx,
        )
        self.assertIn("Please select Chapter 3 - Coal and Petroleum from the top selector first", resp3)

    def test_abbreviation_safe_step_by_step_sentence_splitting(self) -> None:
        from phase11_core import _split_into_teaching_sentences
        text = "Weeds are unwanted plants removed manually or using weedicides (e.g. 2,4-D). Harvested grains are dried before storage in silos."
        sentences = _split_into_teaching_sentences(text)
        self.assertEqual(len(sentences), 2)
        self.assertIn("e.g. 2,4-D", sentences[0])
        self.assertIn("Harvested grains", sentences[1])

    def test_comparison_table_includes_readable_bullets_and_no_pipe_tables(self) -> None:
        service = self.service(api_key="")
        ctx = self.context(
            chapter="Chapter 3 - Coal and Petroleum",
            topic="",
        )
        resp = service.ask(
            message="chapter 3 first aur third topic difference table me do",
            context=ctx,
        )
        self.assertIn("Feature / Concept:", resp)
        self.assertIn("- Inexhaustible and Exhaustible Natural Resources:", resp)
        self.assertNotIn("| Feature", resp)
        self.assertNotIn("| --- |", resp)
        self.assertNotIn("...", resp)

    def test_interrupted_provider_stream_uses_complete_local_fallback_for_5_5_examples(self) -> None:
        service = self.service(api_key="mock_key")
        ctx = self.context(
            chapter="Chapter 2 - Microorganisms : Friend and Foe",
            topic="",
        )

        def stream_generator():
            yield MagicMock(text="Useful Microorganisms:\n1. Lactobacillus — converts milk to curd.\n2. ")
            raise RuntimeError("Network stream dropped mid-response")

        service._client.models.generate_content_stream.side_effect = lambda **kwargs: stream_generator()

        answer = service.ask_stream(
            message="mujhe chapter 2 ke microorganisms wale harmful aur useful examples exactly 5-5 do",
            context=ctx,
        )

        self.assertNotIn("Response interrupted", answer)
        self.assertNotIn("Tap Replay", answer)
        self.assertIn("Useful Microorganisms (5 Examples)", answer)
        self.assertIn("Harmful Microorganisms (5 Examples)", answer)
        self.assertIn("1. Lactobacillus", answer)
        self.assertIn("5. Decomposers", answer)
        self.assertIn("1. Salmonella typhi", answer)
        self.assertIn("5. Rust of Wheat", answer)
        self.assertEqual(service.last_backend, "local syllabus")
        self.assertTrue(service.last_metrics.fallback_used)

    def test_science_selected_math_fraction_prompt_asks_to_select_mathematics(self) -> None:
        service = self.service(api_key="mock_key")
        ctx = self.context(
            chapter="Chapter 2 - Microorganisms : Friend and Foe",
            topic="",
        )
        resp = service.ask(
            message="explain fraction comparison and rational numbers",
            context=ctx,
        )
        self.assertIn("select Mathematics", resp)
        self.assertEqual(service.last_backend, "local scope guard")
        self.assertEqual(service.last_error, "")

    def test_coke_coal_tar_coal_gas_comparison_contains_no_pipe_table(self) -> None:
        raw_output = (
            "| Feature | Coke | Coal Tar | Coal Gas |\n"
            "|---|---|---|---|\n"
            "| Physical State | Solid | Liquid | Gas |\n"
            "| Uses | Steel manufacture | Synthetic dyes | Fuel |\n"
        )
        from phase11_core import format_tutor_response
        formatted = format_tutor_response(raw_output, student_message="compare coke, coal tar and coal gas")
        self.assertNotIn("|", formatted)
        self.assertNotIn("|---|", formatted)
        self.assertIn("Coke", formatted)
        self.assertIn("Coal Tar", formatted)
        self.assertIn("Coal Gas", formatted)

    def test_science_chapter_3_test_paper_contains_no_social_reform_or_generic_question(self) -> None:
        from phase11_core import parse_test_paper_scope, render_test_paper, validate_generated_test_paper
        service = self.service(api_key="")
        ctx = self.context(
            chapter="Chapter 3 - Coal and Petroleum",
            topic="",
        )
        syl = service.syllabus_repository.find(
            board=ctx.board,
            medium=ctx.medium,
            standard=ctx.standard,
            subject=ctx.current_subject,
        )
        scope = parse_test_paper_scope("Chapter 3 25m test paper", ctx, syl)
        paper_str, paper_obj = render_test_paper(syl, scope, context=ctx, message="Chapter 3 25m test paper")
        self.assertTrue(validate_generated_test_paper(paper_obj, syl))
        self.assertNotIn("social reform", paper_str.lower())
        self.assertNotIn("constitution", paper_str.lower())
        self.assertNotIn("political", paper_str.lower())
        self.assertNotIn("interpret the graph or data display", paper_str.lower())
        for q_item in paper_obj.questions:
            self.assertTrue(q_item.solution_guide and len(q_item.solution_guide) > 5)

    def test_selected_science_chapter_3_generic_chapter_test_prompt_returns_chapter_3_paper(self) -> None:
        service = self.service(api_key="")
        ctx = self.context(
            subject="Science & Technology",
            chapter="Chapter 3 - Coal and Petroleum",
            topic="",
        )
        resp = service.ask(message="chapter test banao", context=ctx)
        self.assertIn("Test Paper: Chapter 3 - Coal and Petroleum", resp)
        self.assertNotIn("Chapter 1 - Crop Production", resp)


if __name__ == "__main__":
    unittest.main()


