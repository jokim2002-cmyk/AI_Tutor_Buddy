from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

from phase11_ai import GyanVerseAIService
from phase11_core import LearningMode, StudentLearningContext, SyllabusRepository


def syllabus_payload(
    *,
    board: str = "GSEB",
    medium: str = "Gujarati",
    standard: int = 7,
    subject: str = "Mathematics",
    chapter: str = "Integers",
    topic: str = "Addition",
    explanation: str = "Teacher-authored integer addition explanation.",
    origin: str = "teacher_authored",
) -> dict:
    return {
        "schema_version": 1,
        "board": board,
        "medium": medium,
        "standard": standard,
        "subject": subject,
        "textbook": f"{board} Standard {standard} {subject}",
        "source": {
            "title": f"{board} routing test source",
            "publisher": "GyanVerse test fixture",
            "edition": "2026-test",
            "official": origin == "official",
        },
        "chapters": [
            {
                "chapter_id": "chapter-1",
                "number": "1",
                "title": chapter,
                "topics": [
                    {
                        "topic_id": "topic-1",
                        "title": topic,
                        "learning_objectives": ["Understand the topic"],
                        "explanation": explanation,
                        "examples": ["Example from the validated package."],
                        "exercises": ["Exercise question from the package?"],
                        "solutions": ["Validated solution from the package."],
                        "practice_questions": ["Practice question from the package?"],
                        "marks_pattern": "2 marks",
                        "content_origin": origin,
                    }
                ],
            }
        ],
    }


class Phase3LocalSyllabusRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_tutor_mode = os.environ.get("GYANVERSE_TUTOR_MODE")
        os.environ["GYANVERSE_TUTOR_MODE"] = "ai"
        self.temp = tempfile.TemporaryDirectory(prefix="gyanverse_phase3_")
        self.root = Path(self.temp.name)
        self.repo = SyllabusRepository(self.root / "syllabus")

    def tearDown(self) -> None:
        if self._old_tutor_mode is None:
            os.environ.pop("GYANVERSE_TUTOR_MODE", None)
        else:
            os.environ["GYANVERSE_TUTOR_MODE"] = self._old_tutor_mode
        self.temp.cleanup()

    def service(self) -> GyanVerseAIService:
        service = GyanVerseAIService(
            api_key="mock-key",
            syllabus_repository=self.repo,
            tts_cache_dir=self.root / "tts",
        )
        service._client = MagicMock()
        return service

    def context(
        self,
        *,
        board: str = "GSEB",
        medium: str = "Gujarati",
        standard: int = 7,
        subject: str = "Mathematics",
        chapter: str = "Integers",
        topic: str = "",
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

    def test_exact_installed_topic_grounds_provider_when_configured(self) -> None:
        self.repo.install_payload(syllabus_payload())
        service = self.service()
        service._client.models.generate_content.return_value = MagicMock(
            text="Grounded provider answer."
        )

        answer = service.ask(
            message="Explain addition",
            context=self.context(),
        )

        self.assertEqual(answer, "Grounded provider answer.")
        self.assertEqual(service.last_metrics.route, "gemini-text")
        service._client.models.generate_content.assert_called_once()

        prompt_arg = (
            service._client.models.generate_content
            .call_args[1]["contents"][0]
        )
        self.assertIn("Board: GSEB", prompt_arg)
        self.assertIn("Medium: Gujarati", prompt_arg)
        self.assertIn("Standard: 7", prompt_arg)
        self.assertIn("Subject: Mathematics", prompt_arg)
        self.assertIn("Chapter: 1. Integers", prompt_arg)
        self.assertIn("Topic: Addition", prompt_arg)
        self.assertIn(
            "Teacher-authored integer addition explanation",
            prompt_arg,
        )

    def test_board_and_medium_grounding_is_isolated(self) -> None:
        self.repo.install_payload(
            syllabus_payload(
                board="GSEB",
                medium="Gujarati",
                explanation="GSEB Gujarati explanation.",
            )
        )
        self.repo.install_payload(
            syllabus_payload(
                board="CBSE",
                medium="English",
                explanation="CBSE English explanation.",
            )
        )

        service = self.service()
        service._client.models.generate_content.return_value = MagicMock(
            text="Grounded CBSE provider answer."
        )

        answer = service.ask(
            message="Explain addition",
            context=self.context(board="CBSE", medium="English"),
        )

        self.assertEqual(answer, "Grounded CBSE provider answer.")
        self.assertEqual(service.last_metrics.route, "gemini-text")
        service._client.models.generate_content.assert_called_once()

        prompt_arg = (
            service._client.models.generate_content
            .call_args[1]["contents"][0]
        )
        self.assertIn("Board: CBSE", prompt_arg)
        self.assertIn("Medium: English", prompt_arg)
        self.assertIn("CBSE English explanation.", prompt_arg)
        self.assertNotIn("GSEB Gujarati explanation.", prompt_arg)

    def test_standard_grounding_is_isolated(self) -> None:
        self.repo.install_payload(
            syllabus_payload(
                standard=7,
                explanation="Standard seven explanation.",
            )
        )
        self.repo.install_payload(
            syllabus_payload(
                standard=8,
                explanation="Standard eight explanation.",
            )
        )

        service = self.service()
        service._client.models.generate_content.return_value = MagicMock(
            text="Grounded Standard 8 provider answer."
        )

        answer = service.ask(
            message="Explain addition",
            context=self.context(standard=8),
        )

        self.assertEqual(answer, "Grounded Standard 8 provider answer.")
        self.assertEqual(service.last_metrics.route, "gemini-text")
        service._client.models.generate_content.assert_called_once()

        prompt_arg = (
            service._client.models.generate_content
            .call_args[1]["contents"][0]
        )
        self.assertIn("Standard: 8", prompt_arg)
        self.assertIn("Standard eight explanation.", prompt_arg)
        self.assertNotIn("Standard seven explanation.", prompt_arg)

    def test_context_topic_exact_follow_up_grounds_provider(self) -> None:
        self.repo.install_payload(syllabus_payload())

        service = self.service()
        service._client.models.generate_content.return_value = MagicMock(
            text="Grounded follow-up provider answer."
        )

        answer = service.ask(
            message="Explain this again",
            context=self.context(topic="Addition"),
        )

        self.assertEqual(answer, "Grounded follow-up provider answer.")
        self.assertEqual(service.last_metrics.route, "gemini-text")
        service._client.models.generate_content.assert_called_once()

        prompt_arg = (
            service._client.models.generate_content
            .call_args[1]["contents"][0]
        )
        self.assertIn("Topic: Addition", prompt_arg)
        self.assertIn(
            "Teacher-authored integer addition explanation",
            prompt_arg,
        )

    def test_context_topic_supports_generic_hint_follow_up(self) -> None:
        payload = syllabus_payload(
            topic="Reading and interpreting pie graphs",
            explanation=(
                "A pie graph represents one whole as a circle divided into sectors. "
                "The complete circle is 360 degrees and represents 100 percent."
            ),
        )
        topic = payload["chapters"][0]["topics"][0]
        topic["exercises"] = [
            "A pie graph shows 120 students; the sports sector is 90 degrees. How many students chose sports?"
        ]
        topic["solutions"] = [
            "Sports represents 90/360 = 1/4 of the total, so 120 x 1/4 = 30 students."
        ]
        self.repo.install_payload(payload)
        service = self.service()

        answer = service.ask_stream(
            message="Give me only one hint",
            context=self.context(topic="Reading and interpreting pie graphs"),
        )

        self.assertIn("Reading and interpreting pie graphs", answer)
        self.assertIn("Question: A pie graph shows 120 students", answer)
        self.assertIn("Hint:", answer)
        self.assertIn("pie graph represents one whole", answer.lower())
        self.assertNotIn("The online tutor could not respond right now", answer)
        self.assertEqual(service.last_metrics.route, "local-syllabus")
        service._client.models.generate_content_stream.assert_not_called()

    def test_context_topic_hint_follow_up_allows_chapter_number_token(self) -> None:
        payload = syllabus_payload(
            topic="Reading and interpreting pie graphs",
            explanation="A pie graph represents one whole as a circle divided into sectors.",
        )
        topic = payload["chapters"][0]["topics"][0]
        topic["exercises"] = [
            "A pie graph shows 120 students; the sports sector is 90 degrees. How many students chose sports?"
        ]
        topic["solutions"] = [
            "Sports represents 90/360 = 1/4 of the total, so 120 x 1/4 = 30 students."
        ]
        self.repo.install_payload(payload)
        service = self.service()

        answer = service.ask_stream(
            message="Give me only one hint for one Chapter 1 question",
            context=self.context(topic="Reading and interpreting pie graphs"),
        )

        self.assertIn("Reading and interpreting pie graphs", answer)
        self.assertIn("Question: A pie graph shows 120 students", answer)
        self.assertIn("Hint:", answer)
        self.assertNotIn("The online tutor could not respond right now", answer)
        self.assertEqual(service.last_metrics.route, "local-syllabus")
        service._client.models.generate_content_stream.assert_not_called()

    def test_online_configured_hint_follow_up_stays_deterministic_local(self) -> None:
        payload = syllabus_payload(
            topic="Reading and interpreting pie graphs",
            explanation="A pie graph represents one whole as a circle divided into sectors.",
        )
        topic = payload["chapters"][0]["topics"][0]
        topic["practice_questions"] = [
            "A 72-degree sector in a pie graph represents what fraction and percentage of the whole?"
        ]
        topic["practice_solutions"] = [
            "72/360 = 1/5, so it represents 20 percent."
        ]
        self.repo.install_payload(payload)
        service = self.service()

        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            answer = service.ask_stream(
                message="Give me only one hint",
                context=self.context(topic="Reading and interpreting pie graphs"),
            )

        self.assertIn("Hint:", answer)
        self.assertIn("Question:", answer)
        self.assertIn("pie graph represents one whole", answer.lower())
        self.assertNotIn("20 percent", answer)
        self.assertEqual(service.last_metrics.route, "local-syllabus")
        service._client.models.generate_content_stream.assert_not_called()

    def test_metadata_only_match_returns_truthful_missing_content(self) -> None:
        payload = syllabus_payload(explanation="", origin="metadata_only")
        topic = payload["chapters"][0]["topics"][0]
        topic["examples"] = []
        topic["exercises"] = []
        topic["solutions"] = []
        topic["practice_questions"] = []
        self.repo.install_payload(payload)
        service = self.service()
        answer = service.ask(message="Explain addition", context=self.context())
        self.assertIn("validated local explanation", answer)
        self.assertIn("will not invent textbook content", answer)
        self.assertEqual(service.last_backend, "local syllabus metadata")
        self.assertEqual(
            service.last_metrics.route,
            "local-syllabus-missing-content",
        )
        service._client.models.generate_content.assert_not_called()

    def test_unmatched_question_falls_through_existing_route(self) -> None:
        self.repo.install_payload(syllabus_payload())
        service = GyanVerseAIService(
            api_key="",
            syllabus_repository=self.repo,
            tts_cache_dir=self.root / "tts",
        )
        answer = service.ask(
            message="Explain geometry",
            context=self.context(),
        )
        self.assertNotIn(
            service.last_metrics.route,
            {"local-syllabus", "local-syllabus-missing-content"},
        )
        self.assertIn("using the local tutor", answer.lower())

    def test_streaming_grounded_provider_route_emits_visible_chunk(self) -> None:
        self.repo.install_payload(syllabus_payload())
        service = self.service()

        service._client.models.generate_content_stream.return_value = [
            MagicMock(text="Grounded streamed provider answer.")
        ]

        chunks: list[tuple[str, str]] = []
        first_visible: list[float] = []

        answer = service.ask_stream(
            message="Explain addition",
            context=self.context(),
            on_chunk=lambda accumulated, chunk: chunks.append(
                (accumulated, chunk)
            ),
            on_first_visible=first_visible.append,
        )

        self.assertEqual(answer, "Grounded streamed provider answer.")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], (answer, answer))
        self.assertEqual(len(first_visible), 1)
        self.assertEqual(service.last_metrics.route, "gemini-single-chunk")
        service._client.models.generate_content_stream.assert_called_once()

        prompt_arg = (
            service._client.models.generate_content_stream
            .call_args[1]["contents"][0]
        )
        self.assertIn("Board: GSEB", prompt_arg)
        self.assertIn("Medium: Gujarati", prompt_arg)
        self.assertIn("Standard: 7", prompt_arg)
        self.assertIn("Subject: Mathematics", prompt_arg)
        self.assertIn("Topic: Addition", prompt_arg)
        self.assertIn(
            "Teacher-authored integer addition explanation",
            prompt_arg,
        )

    def test_online_exact_yes_no_review_stays_deterministic_local(self) -> None:
        payload = syllabus_payload(
            topic="Perseverance and response to failure",
            explanation="Difficulty can be met with courage and continued effort.",
        )
        topic = payload["chapters"][0]["topics"][0]
        topic["exercises"] = [
            "Does the poem promise that every task will be easy? Explain."
        ]
        topic["solutions"] = [
            "No. It recognises difficulty and encourages continued effort."
        ]
        topic["practice_questions"] = []
        self.repo.install_payload(payload)
        service = self.service()

        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            wrong = service.ask_stream(
                message=(
                    "Question: Does the poem promise that every task will be easy? Explain. "
                    "My answer: Yes. Is my answer correct?"
                ),
                context=self.context(topic="Perseverance and response to failure"),
            )
            self.assertIn("Result: Incorrect.", wrong)
            self.assertIn("Correct method: No.", wrong)
            self.assertIn("Source type:", wrong)
            self.assertEqual(service.last_metrics.route, "local-syllabus")

            correct = service.ask_stream(
                message=(
                    "Question: Does the poem promise that every task will be easy? Explain. "
                    "My answer: No. Is my answer correct?"
                ),
                context=self.context(topic="Perseverance and response to failure"),
            )
            self.assertIn("Result: Correct.", correct)
            self.assertIn("Installed solution logic: No.", correct)
            self.assertIn("Source type:", correct)
            self.assertEqual(service.last_metrics.route, "local-syllabus")
        service._client.models.generate_content_stream.assert_not_called()

    def test_online_open_ended_review_still_uses_provider(self) -> None:
        self.repo.install_payload(syllabus_payload())
        service = self.service()
        service._client.models.generate_content_stream.return_value = [
            MagicMock(text="Grounded provider review.")
        ]

        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            answer = service.ask_stream(
                message=(
                    "Question: Exercise question from the package? "
                    "My answer: I am not sure. Is my answer correct?"
                ),
                context=self.context(topic="Addition"),
            )
        self.assertEqual(answer, "Grounded provider review.")
        self.assertEqual(service.last_metrics.route, "gemini-single-chunk")
        service._client.models.generate_content_stream.assert_called_once()

    def test_pasted_homework_template_routes_solution_and_preserves_blank(self) -> None:
        payload = syllabus_payload(
            topic="Adjectives and degrees of comparison",
            explanation="Adjectives describe nouns.",
        )
        topic = payload["chapters"][0]["topics"][0]
        topic["exercises"] = [
            "Complete: This design is ___ than that one. (clear)",
            "Complete a teacher-generated mixed test based on the stored unit skills.",
        ]
        topic["solutions"] = [
            "clearer",
            "Evaluate the response against the stored skill rubrics.",
        ]
        topic["practice_questions"] = []
        self.repo.install_payload(payload)
        service = GyanVerseAIService(
            api_key="",
            syllabus_repository=self.repo,
            tts_cache_dir=self.root / "tts",
        )

        blank_answer = service.ask(
            message=(
                "Solve this homework question: "
                "Complete: This design is ___ than that one. (clear)"
            ),
            context=self.context(topic="Addition"),
        )
        self.assertIn(
            "Question: Complete: This design is ___ than that one. (clear)",
            blank_answer,
        )
        self.assertIn("Validated solution: clearer", blank_answer)

        mixed_test_answer = service.ask(
            message=(
                "Solve this homework question: "
                "Complete a teacher-generated mixed test based on the stored unit skills."
            ),
            context=self.context(topic="Addition"),
        )
        self.assertIn(
            "Validated solution: Evaluate the response against the stored skill rubrics.",
            mixed_test_answer,
        )
        self.assertNotIn("Chapter test", mixed_test_answer)

    def test_ui_passes_repository_into_ai_service(self) -> None:
        ui = (Path(__file__).resolve().parents[1] / "gyanverse_ui.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "GyanVerseAIService(syllabus_repository=syllabus_repo)",
            ui,
        )

    def test_fresh_clone_loads_all_four_grade7_english_medium_subjects(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        syllabus_dir = project_root / "syllabus"
        self.assertTrue(syllabus_dir.exists(), f"Syllabus directory missing: {syllabus_dir}")
        repo = SyllabusRepository(syllabus_dir)

        expected_subjects = {
            "English",
            "Mathematics",
            "Science & Technology",
            "Social Science",
        }
        loaded_syllabi = repo.all(board="GSEB")
        loaded_subjects = {
            s.subject
            for s in loaded_syllabi
            if s.medium.casefold() == "english" and s.standard == 7
        }

        for subject in expected_subjects:
            self.assertIn(
                subject,
                loaded_subjects,
                f"Missing committed syllabus package for GSEB English Std 7: {subject}",
            )
            found = repo.find(
                board="GSEB",
                medium="English",
                standard=7,
                subject=subject,
            )
            self.assertIsNotNone(
                found,
                f"SyllabusRepository.find failed to return syllabus for subject: {subject}",
            )
            self.assertTrue(
                len(found.chapters) > 0,
                f"Syllabus for {subject} has no chapters loaded",
            )

        ui_code = (project_root / "gyanverse_ui.py").read_text(encoding="utf-8")
        self.assertIn(
            'GSEBSyllabusRepository(APP_DIR / "syllabus")',
            ui_code,
            "gyanverse_ui.py must load syllabus packages from APP_DIR / 'syllabus'",
        )

    def test_grade_8_ambiguous_chapter_prompts_use_saved_context(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        syllabus_dir = project_root / "syllabus"
        repo = SyllabusRepository(syllabus_dir)

        service = GyanVerseAIService(
            api_key="mock-key",
            syllabus_repository=repo,
            tts_cache_dir=self.root / "tts",
        )
        service._client = MagicMock()

        test_cases = [
            (
                "Mathematics",
                "Chapter 1 - Rational Numbers",
                "Rational Numbers",
            ),
            (
                "English",
                "Semester 1 Unit 1 - Landscapes",
                "Landscapes",
            ),
            (
                "Science & Technology",
                "Chapter 1 - Crop Production and Management",
                "Crop Production and Management",
            ),
            (
                "Social Science",
                "Chapter 1 - Establishment of European and British Rule in India",
                "Establishment of European and British Rule",
            ),
        ]

        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            for subject, chapter, expected_title_keyword in test_cases:
                service._client.models.generate_content_stream.reset_mock()
                service._client.models.generate_content_stream.return_value = [
                    MagicMock(
                        text=f"Grounded provider response for {subject}."
                    )
                ]

                ctx = StudentLearningContext(
                    board="GSEB",
                    medium="English",
                    standard=8,
                    preferred_language="English",
                    current_subject=subject,
                    current_chapter=chapter,
                    onboarding_complete=True,
                ).validate()

                response = service.ask_stream(
                    message="Explain Chapter 1 with two examples.",
                    context=ctx,
                )

                self.assertEqual(
                    response,
                    f"Grounded provider response for {subject}.",
                )
                self.assertEqual(
                    service.last_metrics.route,
                    "gemini-single-chunk",
                )
                service._client.models.generate_content_stream.assert_called_once()

                prompt_arg = (
                    service._client.models.generate_content_stream
                    .call_args[1]["contents"][0]
                )

                self.assertIn("Board: GSEB", prompt_arg)
                self.assertIn("Medium: English", prompt_arg)
                self.assertIn("Standard: 8", prompt_arg)
                self.assertIn(f"Subject: {subject}", prompt_arg)
                self.assertIn(expected_title_keyword, prompt_arg)
                self.assertIn(
                    "PRIVATE SYLLABUS GROUNDING",
                    prompt_arg,
                )
                self.assertIn(
                    "Full Chapter Grounding Context:",
                    prompt_arg,
                )
                self.assertIn(
                    "CURRENT REQUEST:",
                    prompt_arg,
                )
                self.assertIn(
                    "Explain Chapter 1 with two examples.",
                    prompt_arg,
                )



class Std7ScienceGenericExamplesRouteTests(unittest.TestCase):
    def test_std7_science_generic_examples_from_this_chapter_stays_local(self):
        from phase11_ai import GyanVerseAIService
        from phase11_core import LearningMode, StudentLearningContext, SyllabusRepository

        repo = SyllabusRepository(Path(__file__).resolve().parents[1] / "syllabus")
        service = GyanVerseAIService(api_key="", syllabus_repository=repo)
        ctx = StudentLearningContext(
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

        answer = service.ask_stream(
            message="Give me two examples from this chapter",
            context=ctx,
        )

        self.assertIn("Source type: Teacher-authored content", answer)
        self.assertIn("Examples:", answer)
        self.assertIn("1.", answer)
        self.assertIn("2.", answer)
        self.assertIn("iron pin", answer.casefold())
        self.assertIn("iron filings", answer.casefold())
        self.assertNotIn("The online tutor could not respond right now", answer)
        self.assertEqual(service.last_metrics.route, "local-syllabus")




class Std7ScienceMagnetReviewTests(unittest.TestCase):
    def test_std7_science_magnet_material_review_accepts_equivalent_polarity(self):
        from phase11_ai import GyanVerseAIService
        from phase11_core import LearningMode, StudentLearningContext, SyllabusRepository

        repo = SyllabusRepository(Path(__file__).resolve().parents[1] / "syllabus")
        service = GyanVerseAIService(api_key="", syllabus_repository=repo)
        ctx = StudentLearningContext(
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

        correct = service.ask_stream(
            message=(
                "Check my answer: Classify an iron nail, an aluminium spoon and a wooden ruler "
                "by whether a common magnet attracts them strongly. My answer: Iron nail is attracted "
                "strongly, aluminium spoon and wooden ruler are not attracted strongly."
            ),
            context=ctx,
        )
        wrong = service.ask_stream(
            message=(
                "Check my answer: Classify an iron nail, an aluminium spoon and a wooden ruler "
                "by whether a common magnet attracts them strongly. My answer: Wooden ruler is attracted strongly."
            ),
            context=ctx,
        )

        self.assertIn("Result: Correct.", correct)
        self.assertNotIn("Needs grounded review", correct)
        self.assertIn("Result: Incorrect.", wrong)
        self.assertNotIn("Needs grounded review", wrong)
        self.assertEqual(service.last_metrics.route, "local-syllabus")

    def test_std7_science_magnet_evaluation_regression_cases(self):
        from phase11_core import evaluate_single_test_answer

        q_text = (
            "Classify an iron nail, an aluminium spoon and a wooden ruler "
            "by whether a common magnet attracts them strongly."
        )
        sol_guide = (
            "The iron nail is magnetic and is attracted strongly. "
            "The aluminium spoon and wooden ruler are not strongly attracted by a common classroom magnet."
        )
        max_marks = 1

        # 1. correct classification => full marks
        awarded, result, _feedback = evaluate_single_test_answer(
            q_text,
            "Iron nail is attracted strongly; aluminium spoon and wooden ruler are not attracted strongly.",
            sol_guide,
            max_marks,
        )
        self.assertEqual(awarded, 1.0)
        self.assertEqual(result, "Correct")

        # 2. wooden ruler attracted strongly => 0 marks
        awarded, result, _feedback = evaluate_single_test_answer(
            q_text,
            "Wooden ruler is attracted strongly.",
            sol_guide,
            max_marks,
        )
        self.assertEqual(awarded, 0.0)
        self.assertEqual(result, "Incorrect")

        # 3. aluminium spoon attracted strongly => 0 marks
        awarded, result, _feedback = evaluate_single_test_answer(
            q_text,
            "Aluminium spoon is attracted strongly.",
            sol_guide,
            max_marks,
        )
        self.assertEqual(awarded, 0.0)
        self.assertEqual(result, "Incorrect")

        # 4. iron nail not attracted => 0 marks
        awarded, result, _feedback = evaluate_single_test_answer(
            q_text,
            "Iron nail is not attracted strongly.",
            sol_guide,
            max_marks,
        )
        self.assertEqual(awarded, 0.0)
        self.assertEqual(result, "Incorrect")


class Std7ScienceWaterStatesReviewTests(unittest.TestCase):
    def test_std7_science_water_states_evaluation_regression_cases(self):
        from phase11_core import evaluate_single_test_answer

        q_text = "Name the three common physical states of water."
        sol_guide = "They are solid ice, liquid water and gaseous water vapour."
        max_marks = 1

        # 1. "Solid, liquid and gas." => full marks Correct
        awarded, result, _feedback = evaluate_single_test_answer(
            q_text,
            "Solid, liquid and gas.",
            sol_guide,
            max_marks,
        )
        self.assertEqual(awarded, 1.0)
        self.assertEqual(result, "Correct")

        # 2. "Ice, water and water vapour." => full marks Correct
        awarded, result, _feedback = evaluate_single_test_answer(
            q_text,
            "Ice, water and water vapour.",
            sol_guide,
            max_marks,
        )
        self.assertEqual(awarded, 1.0)
        self.assertEqual(result, "Correct")

        # 3. "Solid and liquid only." => not full marks
        awarded, result, _feedback = evaluate_single_test_answer(
            q_text,
            "Solid and liquid only.",
            sol_guide,
            max_marks,
        )
        self.assertLess(awarded, 1.0)
        self.assertNotEqual(result, "Correct")

    def test_std7_science_water_states_review_accepts_short_answer(self):
        from phase11_ai import GyanVerseAIService
        from phase11_core import LearningMode, StudentLearningContext, SyllabusRepository

        repo = SyllabusRepository(Path(__file__).resolve().parents[1] / "syllabus")
        service = GyanVerseAIService(api_key="", syllabus_repository=repo)
        ctx = StudentLearningContext(
            board="GSEB",
            medium="English",
            standard=7,
            preferred_language="English",
            current_subject="Science & Technology",
            current_chapter="Semester 1 — Physical properties and states of water",
            current_topic="Physical properties and states of water",
            learning_mode=LearningMode.EXPLAIN.value,
            onboarding_complete=True,
        ).validate()

        correct = service.ask_stream(
            message=(
                "Check my answer: Name the three common physical states of water. "
                "My answer: Solid, liquid and gas."
            ),
            context=ctx,
        )

        self.assertIn("Result: Correct.", correct)
        self.assertNotIn("Needs grounded review", correct)


if __name__ == "__main__":
    unittest.main()


