import unittest
from pathlib import Path

from phase11_ai import GyanVerseAIService
from phase11_core import StudentLearningContext, SyllabusRepository


class V1InScopeAnswerQualityAllSubjectsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = SyllabusRepository(Path(__file__).resolve().parent.parent / "syllabus")
        self.service = GyanVerseAIService(api_key="", syllabus_repository=self.repo)

    def _ctx(self, standard: int, subject: str, chapter: str) -> StudentLearningContext:
        return StudentLearningContext(
            board="GSEB",
            medium="English",
            standard=standard,
            current_subject=subject,
            current_chapter=chapter,
        )

    def test_std7_in_scope_answer_quality_matrix(self) -> None:
        packages = [
            (
                "English",
                "Chapter 1 - The Day the River Spoke",
                "summary of the day the river spoke",
                "what did Jahnavi do by the river?",
                ["Jahnavi", "River"],
            ),
            (
                "Mathematics",
                "Semester 1 — Pie Graph",
                "how to draw pie graph",
                "what is a pie graph?",
                ["Pie Graph", "circle"],
            ),
            (
                "Science & Technology",
                "Semester 1 — Properties of Magnet",
                "what are properties of magnet and magnetic poles?",
                "explain magnetic poles",
                ["Magnet", "Poles"],
            ),
            (
                "Social Science",
                "Semester 1 — Two Big States",
                "who ruled two big states?",
                "explain kingdom of Kanauj",
                ["Kanauj", "Harshavardhana"],
            ),
        ]

        for subject, chapter, summary_prompt, concept_prompt, keywords in packages:
            with self.subTest(subject=subject, chapter=chapter):
                ctx = self._ctx(7, subject, chapter)

                # A. Summary / Chapter prompt
                resp_sum = self.service.ask(message=summary_prompt, context=ctx)
                self.assertNotIn("You asked:", resp_sum)
                self.assertNotIn("could not respond right now", resp_sum)
                self.assertTrue(
                    any(kw.lower() in resp_sum.lower() for kw in keywords),
                    f"Expected one of {keywords} in response to '{summary_prompt}', got: {resp_sum[:150]}"
                )

                # B. Concept prompt
                resp_concept = self.service.ask(message=concept_prompt, context=ctx)
                self.assertNotIn("You asked:", resp_concept)
                self.assertNotIn("could not respond right now", resp_concept)
                self.assertNotIn("Please select", resp_concept)

                # C. Chapter Test prompt
                resp_test = self.service.ask(message="chapter test banao", context=ctx)
                self.assertNotIn("You asked:", resp_test)
                self.assertIn("Test Paper", resp_test)

    def test_std8_in_scope_answer_quality_matrix(self) -> None:
        packages = [
            (
                "English",
                "Semester 2 Unit 1 - Writing About Writing",
                "is chapter ko samjhao",
                "explain writing process",
                ["Writing", "Drafting"],
            ),
            (
                "Mathematics",
                "Chapter 1 - Rational Numbers",
                "explain additive inverse and reciprocal",
                "what is a rational number?",
                ["Rational Numbers", "Properties"],
            ),
            (
                "Science & Technology",
                "Chapter 3 - Coal and Petroleum",
                "what is coal tar?",
                "explain inexhaustible natural resources",
                ["Coal", "Petroleum"],
            ),
            (
                "Social Science",
                "Chapter 3 - India's First War of Independence",
                "why did the revolt fail?",
                "causes of the 1857 revolt",
                ["Revolt", "Independence"],
            ),
        ]

        for subject, chapter, summary_prompt, concept_prompt, keywords in packages:
            with self.subTest(subject=subject, chapter=chapter):
                ctx = self._ctx(8, subject, chapter)

                # A. Summary / Chapter prompt
                resp_sum = self.service.ask(message=summary_prompt, context=ctx)
                self.assertNotIn("You asked:", resp_sum)
                self.assertNotIn("could not respond right now", resp_sum)
                self.assertTrue(
                    any(kw.lower() in resp_sum.lower() for kw in keywords),
                    f"Expected one of {keywords} in response to '{summary_prompt}', got: {resp_sum[:150]}"
                )

                # B. Concept prompt
                resp_concept = self.service.ask(message=concept_prompt, context=ctx)
                self.assertNotIn("You asked:", resp_concept)
                self.assertNotIn("could not respond right now", resp_concept)
                self.assertNotIn("Please select", resp_concept)

                # C. Chapter Test prompt
                resp_test = self.service.ask(message="chapter test banao", context=ctx)
                self.assertNotIn("You asked:", resp_test)
                self.assertIn("Test Paper", resp_test)


if __name__ == "__main__":
    unittest.main()
