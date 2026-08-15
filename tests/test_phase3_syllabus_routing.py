from __future__ import annotations

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
        self.temp = tempfile.TemporaryDirectory(prefix="gyanverse_phase3_")
        self.root = Path(self.temp.name)
        self.repo = SyllabusRepository(self.root / "syllabus")

    def tearDown(self) -> None:
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

    def test_exact_installed_topic_bypasses_provider(self) -> None:
        self.repo.install_payload(syllabus_payload())
        service = self.service()
        answer = service.ask(message="Explain addition", context=self.context())
        self.assertIn("Teacher-authored integer addition explanation", answer)
        self.assertIn("Teacher-authored content", answer)
        self.assertEqual(service.last_backend, "local syllabus")
        self.assertEqual(service.last_metrics.route, "local-syllabus")
        self.assertFalse(service.last_metrics.fallback_used)
        service._client.models.generate_content.assert_not_called()

    def test_board_and_medium_are_isolated(self) -> None:
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
        answer = service.ask(
            message="Explain addition",
            context=self.context(board="CBSE", medium="English"),
        )
        self.assertIn("CBSE English explanation", answer)
        self.assertNotIn("GSEB Gujarati explanation", answer)

    def test_standard_is_isolated(self) -> None:
        self.repo.install_payload(
            syllabus_payload(standard=7, explanation="Standard seven explanation.")
        )
        self.repo.install_payload(
            syllabus_payload(standard=8, explanation="Standard eight explanation.")
        )
        service = self.service()
        answer = service.ask(
            message="Explain addition",
            context=self.context(standard=8),
        )
        self.assertIn("Standard eight explanation", answer)
        self.assertNotIn("Standard seven explanation", answer)

    def test_context_topic_supports_exact_follow_up(self) -> None:
        self.repo.install_payload(syllabus_payload())
        service = self.service()
        answer = service.ask(
            message="Explain this again",
            context=self.context(topic="Addition"),
        )
        self.assertIn("Teacher-authored integer addition explanation", answer)
        self.assertEqual(service.last_metrics.route, "local-syllabus")

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

    def test_streaming_local_route_emits_one_visible_chunk(self) -> None:
        self.repo.install_payload(syllabus_payload())
        service = self.service()
        chunks: list[tuple[str, str]] = []
        first_visible: list[float] = []
        answer = service.ask_stream(
            message="Explain addition",
            context=self.context(),
            on_chunk=lambda accumulated, chunk: chunks.append((accumulated, chunk)),
            on_first_visible=first_visible.append,
        )
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], (answer, answer))
        self.assertEqual(len(first_visible), 1)
        self.assertEqual(service.last_metrics.route, "local-syllabus")
        service._client.models.generate_content_stream.assert_not_called()

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


if __name__ == "__main__":
    unittest.main()

