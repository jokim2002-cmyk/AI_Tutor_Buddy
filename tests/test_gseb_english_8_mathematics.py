from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

from phase11_ai import GyanVerseAIService
from phase11_core import (
    LearningMode,
    StudentLearningContext,
    SyllabusRepository,
    evaluate_single_test_answer,
)


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

    def test_multiplicative_inverse_hint_uses_reciprocal_rule_without_answer(self) -> None:
        service = self.service(api_key="")
        ctx = self.context(
            chapter="Chapter 1 - Rational Numbers",
            topic="Properties of Rational Numbers",
        )

        hint_response = service.ask(
            message="Give me only one hint for this homework question: Find the multiplicative inverse of -13/19.",
            context=ctx,
        )

        self.assertIn("Hint", hint_response)
        self.assertIn("multiplicative inverse", hint_response.lower())
        self.assertIn("product 1", hint_response.lower())
        self.assertIn("numerator", hint_response.lower())
        self.assertIn("denominator", hint_response.lower())
        self.assertNotIn("-19/13", hint_response)
        self.assertEqual(service.last_metrics.route, "local-syllabus")

    def test_multiplicative_inverse_embedded_review_marked_correct_locally(self) -> None:
        service = self.service(api_key="mock-key")
        ctx = self.context(
            chapter="Chapter 1 - Rational Numbers",
            topic="Properties of Rational Numbers",
        )

        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            review = service.ask_stream(
                message="Check my answer: Find the multiplicative inverse of -13/19. My answer: -19/13",
                context=ctx,
            )

        self.assertIn("Question: Find the multiplicative inverse of -13/19.", review)
        self.assertIn("Your answer: -19/13", review)
        self.assertIn("Result: Correct.", review)
        self.assertNotIn("Needs grounded review", review)
        self.assertEqual(service.last_metrics.route, "local-syllabus")
        service._client.models.generate_content_stream.assert_not_called()

    def test_multiplicative_inverse_embedded_review_marks_wrong_answer_incorrect(self) -> None:
        service = self.service(api_key="mock-key")
        ctx = self.context(
            chapter="Chapter 1 - Rational Numbers",
            topic="Properties of Rational Numbers",
        )

        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            review = service.ask_stream(
                message="Check my answer: Find the multiplicative inverse of -13/19. My answer: 13/19",
                context=ctx,
            )

        self.assertIn("Your answer: 13/19", review)
        self.assertIn("Result: Incorrect.", review)
        self.assertNotIn("Needs grounded review", review)
        self.assertEqual(service.last_metrics.route, "local-syllabus")
        service._client.models.generate_content_stream.assert_not_called()

    def test_math_test_evaluation_accepts_unordered_integer_interval_answer(self) -> None:
        awarded, result, feedback = evaluate_single_test_answer(
            q_text="Between which two integers does -7/4 lie on the number line?",
            user_ans="Between -2 and -1.",
            sol_guide="Between -1 and -2, because -7/4 = -1 (3/4).",
            max_marks=1,
        )

        self.assertEqual(awarded, 1.0)
        self.assertEqual(result, "Correct")
        self.assertEqual(feedback, "Correct answer.")

    def test_math_test_evaluation_accepts_short_final_fraction_from_worked_solution(self) -> None:
        awarded, result, feedback = evaluate_single_test_answer(
            q_text="Find a rational number exactly halfway between 1/5 and 1/4.",
            user_ans="9/40",
            sol_guide="Mean = (1/5 + 1/4)/2 = (9/20)/2 = 9/40.",
            max_marks=1,
        )

        self.assertEqual(awarded, 1.0)
        self.assertEqual(result, "Correct")
        self.assertEqual(feedback, "Correct answer.")

        wrong_awarded, wrong_result, _ = evaluate_single_test_answer(
            q_text="Find a rational number exactly halfway between 1/5 and 1/4.",
            user_ans="1/4",
            sol_guide="Mean = (1/5 + 1/4)/2 = (9/20)/2 = 9/40.",
            max_marks=1,
        )
        self.assertEqual(wrong_awarded, 0.0)
        self.assertEqual(wrong_result, "Incorrect")

    def test_math_test_evaluation_accepts_valid_rational_numbers_between_bounds(self) -> None:
        awarded, result, feedback = evaluate_single_test_answer(
            q_text="Find three rational numbers between -2/5 and 1/2.",
            user_ans="-1/5, 0, 1/5",
            sol_guide=(
                "Convert to common denominator 10: -4/10 and 5/10. Three rational "
                "numbers are -3/10, 0, and 1/10 (or 2/10 = 1/5)."
            ),
            max_marks=1,
        )

        self.assertEqual(awarded, 1.0)
        self.assertEqual(result, "Correct")
        self.assertEqual(feedback, "Correct answer.")

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

    def test_grade_8_english_wrong_conceptual_review_stays_local(self) -> None:
        service = self.service(api_key="mock-key")
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

        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            review = service.ask_stream(
                message="Check my answer: What is Land Art? My answer: Land Art is a computer game.",
                context=ctx_eng8,
            )

        self.assertIn("Land Art and Environmental Appreciation", review)
        self.assertIn("Question: What is Land Art?", review)
        self.assertIn("Your answer: Land Art is a computer game", review)
        self.assertIn("Result: Incorrect.", review)
        self.assertIn("Correct method:", review)
        self.assertIn("Source type: Teacher-authored content", review)
        self.assertNotIn("Needs grounded review", review)
        self.assertEqual(service.last_metrics.route, "local-syllabus")
        service._client.models.generate_content_stream.assert_not_called()

    def test_grade_8_english_answer_file_accepts_short_keyword_answers(self) -> None:
        beneath_marks, beneath_result, beneath_feedback = evaluate_single_test_answer(
            q_text="Identify the preposition of place in: The cabin stood beneath the tall pine trees.",
            user_ans="beneath",
            sol_guide="The preposition of place is beneath.",
            max_marks=1,
        )
        hearing_marks, hearing_result, hearing_feedback = evaluate_single_test_answer(
            q_text="What sense does auditory imagery appeal to?",
            user_ans="Hearing",
            sol_guide="Auditory imagery appeals to the sense of hearing.",
            max_marks=1,
        )

        self.assertEqual(beneath_marks, 1.0)
        self.assertEqual(beneath_result, "Correct")
        self.assertEqual(beneath_feedback, "Correct answer.")
        self.assertEqual(hearing_marks, 1.0)
        self.assertEqual(hearing_result, "Correct")
        self.assertEqual(hearing_feedback, "Correct answer.")

    def test_grade_7_english_preposition_reviews_stay_local(self) -> None:
        service = self.service(api_key="mock-key")
        ctx_eng7 = StudentLearningContext(
            board="GSEB",
            medium="English",
            standard=7,
            preferred_language="English",
            current_subject="English",
            current_chapter="Chapter 1 - The Day the River Spoke",
            current_topic="Prepositions, adverbs and descriptive paragraphs",
            learning_mode=LearningMode.EXPLAIN.value,
            onboarding_complete=True,
        ).validate()

        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            correct = service.ask_stream(
                message="Check my answer: Identify the preposition in: Jahnavi stood beside the river. My answer: beside",
                context=ctx_eng7,
            )
            wrong = service.ask_stream(
                message="Check my answer: Identify the preposition in: Jahnavi stood beside the river. My answer: river",
                context=ctx_eng7,
            )

        self.assertIn("Question: Identify the preposition in: Jahnavi stood beside the river.", correct)
        self.assertIn("Your answer: beside", correct)
        self.assertIn("Result: Correct.", correct)
        self.assertNotIn("Needs grounded review", correct)
        self.assertIn("Question: Identify the preposition in: Jahnavi stood beside the river.", wrong)
        self.assertIn("Your answer: river", wrong)
        self.assertIn("Result: Incorrect.", wrong)
        self.assertNotIn("Needs grounded review", wrong)
        self.assertEqual(service.last_metrics.route, "local-syllabus")
        service._client.models.generate_content_stream.assert_not_called()

    def test_exact_local_syllabus_routes_do_not_consume_provider(self) -> None:
        service = self.service(api_key="")
        ctx = self.context(
            chapter="Chapter 5 - Squares and Square Roots",
            topic="Properties of Square Numbers and Patterns",
        )

        ans = service.ask(message="Explain Properties of Square Numbers and Patterns", context=ctx)
        self.assertIn("Teacher-authored content", ans)
        self.assertEqual(service.last_metrics.route, "local-syllabus")



    def test_std7_math_pie_graph_test_eval_accepts_short_final_answers_from_long_guides(self):
        cases = [
            (
                "A pie graph shows 120 students; the sports sector is 90 degrees. How many students chose sports?",
                "30 students",
                "Sports represents 90/360 = 1/4 of the total, so 120 × 1/4 = 30 students.",
            ),
            (
                "Find the sector angle for 18 books out of a total of 72 books.",
                "90 degrees",
                "(18/72) × 360 = 90 degrees.",
            ),
            (
                "In a pie graph, Art is 25 percent and Music is 35 percent. Which is larger and by how many percentage points?",
                "Music is larger by 10 percentage points",
                "Music is larger. The difference is 35 − 25 = 10 percentage points.",
            ),
            (
                "A sector measures 144 degrees. Find its percentage of the circle.",
                "40 percent",
                "(144/360) × 100 = 40 percent.",
            ),
        ]
        for q_text, user_ans, guide in cases:
            with self.subTest(user_ans=user_ans):
                awarded, result, _feedback = evaluate_single_test_answer(q_text, user_ans, guide, 1)
                self.assertEqual(awarded, 1.0)
                self.assertEqual(result, "Correct")

    def test_std7_math_pie_graph_test_eval_rejects_wrong_number_unit_pair(self):
        awarded, result, feedback = evaluate_single_test_answer(
            "A pie graph shows 120 students; the sports sector is 90 degrees. How many students chose sports?",
            "90 students",
            "Sports represents 90/360 = 1/4 of the total, so 120 × 1/4 = 30 students.",
            1,
        )
        self.assertEqual(awarded, 0.0)
        self.assertEqual(result, "Incorrect")
        self.assertIn("30 students", feedback)


if __name__ == "__main__":
    unittest.main()
