from __future__ import annotations

import unittest
from pathlib import Path
from phase11_ai import GyanVerseAIService
from phase11_core import LearningMode, StudentLearningContext, SyllabusRepository


class V1ScopeGuardAllSubjectsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project_root = Path(__file__).resolve().parents[1]
        cls.syllabus_dir = cls.project_root / "syllabus"
        cls.repo = SyllabusRepository(cls.syllabus_dir)

    def service(self) -> GyanVerseAIService:
        return GyanVerseAIService(
            api_key="",
            syllabus_repository=self.repo,
            tts_cache_dir=self.project_root / "tts",
        )

    def context(self, standard: int, subject: str, chapter: str) -> StudentLearningContext:
        return StudentLearningContext(
            board="GSEB",
            medium="English",
            standard=standard,
            preferred_language="English",
            current_subject=subject,
            current_chapter=chapter,
            current_topic="",
            learning_mode=LearningMode.EXPLAIN.value,
        )

    # A. Cross-subject guard matrix for Std 7 and Std 8
    def test_std8_cross_subject_guard_matrix(self) -> None:
        service = self.service()

        # Std 8 English selected -> Science prompt (photosynthesis / coal tar)
        ctx_eng = self.context(8, "English", "Chapter 1 - Writing About Writing")
        resp = service.ask(message="Explain photosynthesis", context=ctx_eng)
        self.assertIn("Please select Science & Technology", resp)
        self.assertNotIn("Writing Process", resp)
        self.assertNotIn("could not respond right now", resp)

        resp2 = service.ask(message="What is coal tar?", context=ctx_eng)
        self.assertIn("Please select Science & Technology", resp2)
        self.assertNotIn("Writing Process", resp2)

        # Std 8 Science selected -> English prompt (preposition / writing process)
        ctx_sci = self.context(8, "Science & Technology", "Chapter 3 - Coal and Petroleum")
        resp3 = service.ask(message="Explain preposition and writing process", context=ctx_sci)
        self.assertIn("Please select English", resp3)
        self.assertNotIn("Coal and Petroleum", resp3)

        # Std 8 Mathematics selected -> Science prompt (coal tar / natural gas)
        ctx_math = self.context(8, "Mathematics", "Chapter 1 - Rational Numbers")
        resp4 = service.ask(message="coal tar kya hota hai", context=ctx_math)
        self.assertIn("Please select Science & Technology", resp4)
        self.assertNotIn("Rational Numbers", resp4)

        # Std 8 Social Science selected -> Math prompt (solve equation / fraction comparison)
        ctx_ss = self.context(8, "Social Science", "Chapter 1 - Establishment of European and British Rule in India")
        resp5 = service.ask(message="explain fraction comparison and additive inverse", context=ctx_ss)
        self.assertIn("Please select Mathematics", resp5)
        self.assertNotIn("Arrival of Europeans", resp5)

    def test_std7_cross_subject_guard_matrix(self) -> None:
        service = self.service()

        # Std 7 English selected -> Science prompt (photosynthesis)
        ctx_eng = self.context(7, "English", "Semester 1 — Unit 1 - Exploring Symbols")
        resp = service.ask(message="What is photosynthesis?", context=ctx_eng)
        self.assertIn("Please select Science & Technology", resp)
        self.assertNotIn("could not respond right now", resp)

        # Std 7 Mathematics selected -> Social Science prompt (constitution / revolt)
        ctx_math = self.context(7, "Mathematics", "Semester 1 — Chapter 1 - Integers")
        resp2 = service.ask(message="Explain constitution and revolt", context=ctx_math)
        self.assertIn("Please select Social Science", resp2)

        # Std 7 Social Science selected -> Math prompt (fraction comparison)
        ctx_ss = self.context(7, "Social Science", "Semester 1 — Two Big States")
        resp3 = service.ask(message="explain fraction comparison and additive inverse", context=ctx_ss)
        self.assertIn("Please select Mathematics", resp3)

        # Std 7 Science selected -> English prompt (preposition)
        ctx_sci = self.context(7, "Science & Technology", "Semester 1 — Nutrition in Plants")
        resp4 = service.ask(message="types of prepositions in grammar", context=ctx_sci)
        self.assertIn("Please select English", resp4)

    # B. Same-subject wrong-chapter guard
    def test_same_subject_wrong_chapter_guard(self) -> None:
        service = self.service()

        # Science Ch1 selected + fermentation -> select Ch2
        ctx_ch1 = self.context(8, "Science & Technology", "Chapter 1 - Crop Production and Management")
        resp = service.ask(message="explain fermentation and microbes", context=ctx_ch1)
        self.assertIn("Please select Chapter 2 - Microorganisms : Friend and Foe", resp)

        # Science Ch2 selected + coal tar -> select Ch3
        ctx_ch2 = self.context(8, "Science & Technology", "Chapter 2 - Microorganisms : Friend and Foe")
        resp2 = service.ask(message="what is coke and coal tar?", context=ctx_ch2)
        self.assertIn("Please select Chapter 3 - Coal and Petroleum", resp2)

    # C. In-scope allowed tests
    def test_in_scope_allowed_requests(self) -> None:
        service = self.service()

        # Science Ch3 selected + "chapter test banao" returns Chapter 3 paper
        ctx_sci3 = self.context(8, "Science & Technology", "Chapter 3 - Coal and Petroleum")
        resp1 = service.ask(message="chapter test banao", context=ctx_sci3)
        self.assertIn("Test Paper: Chapter 3 - Coal and Petroleum", resp1)

        # Math selected + in-scope Math prompt
        ctx_math = self.context(8, "Mathematics", "Chapter 1 - Rational Numbers")
        resp2 = service.ask(message="what is a rational number?", context=ctx_math)
        self.assertNotIn("Please select", resp2)

        # Social Science selected + in-scope Social Science prompt
        ctx_ss = self.context(8, "Social Science", "Chapter 1 - Establishment of European and British Rule in India")
        resp3 = service.ask(message="who was Vasco da Gama?", context=ctx_ss)
        self.assertNotIn("Please select", resp3)

        # Explicit current-subject wording must not be overridden by fuzzy
        # matches from another installed subject.
        ctx_eng7 = self.context(7, "English", "Chapter 1 - The Day the River Spoke")
        resp4 = service.ask(message="muje English ka 1st chapter padhaao", context=ctx_eng7)
        self.assertNotIn("Please select Social Science", resp4)
        self.assertNotIn("Please select Science & Technology", resp4)
        self.assertNotIn("Please select Mathematics", resp4)

        resp5 = service.ask(message="Teach me English first chapter", context=ctx_eng7)
        self.assertNotIn("Please select", resp5)

    # D. Test answer evaluation
    def test_answer_evaluation_routing_after_paper_generation(self) -> None:
        service = self.service()
        ctx = self.context(8, "Science & Technology", "Chapter 3 - Coal and Petroleum")

        # Generate test paper
        service.ask(message="chapter test banao", context=ctx)
        self.assertIsNotNone(service._last_generated_test_paper)

        # Numbered student answers submission
        student_answers = (
            "1. Coal is a fossil fuel.\n"
            "2. Coke is pure carbon.\n"
            "3. Natural gas is exhaustible.\n"
            "4. Coal tar makes naphthalene balls.\n"
            "5. Assam."
        )
        resp_eval = service.ask(message=student_answers, context=ctx)
        self.assertIn("Test Evaluation", resp_eval)
        self.assertNotIn("Please select", resp_eval)


if __name__ == "__main__":
    unittest.main()
