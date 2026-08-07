from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from phase11_core import StudentLearningContext, SyllabusRepository


def _payload() -> dict:
    return {
        "schema_version": 1,
        "board": "GSEB",
        "medium": "Gujarati",
        "standard": 7,
        "subject": "Mathematics",
        "textbook": "Alias Test Mathematics",
        "source": {
            "title": "Alias Test Source",
            "publisher": "GyanVerse",
            "edition": "test-1",
            "official": False,
        },
        "chapters": [
            {
                "chapter_id": "integers",
                "number": "1",
                "title": "Integers",
                "topics": [
                    {
                        "title": "Integers",
                        "aliases": ["પૂર્ણાંક સંખ્યાઓ", "પૂર્ણાંકો"],
                        "explanation": "Generic integer explanation.",
                        "content_origin": "teacher_authored",
                    },
                    {
                        "title": "Addition of Integers",
                        "aliases": ["પૂર્ણાંકોનો સરવાળો"],
                        "explanation": "Addition explanation.",
                        "content_origin": "teacher_authored",
                    },
                    {
                        "title": "Multiplication of Integers",
                        "aliases": ["પૂર્ણાંકોનો ગુણાકાર"],
                        "explanation": "Multiplication explanation.",
                        "content_origin": "teacher_authored",
                    },
                ],
            },
            {
                "chapter_id": "fractions",
                "number": "2",
                "title": "Fractions and Decimals",
                "topics": [
                    {
                        "title": "Fractions and Decimals",
                        "aliases": ["અપૂર્ણાંક અને દશાંશ સંખ્યાઓ"],
                        "content_origin": "metadata_only",
                    }
                ],
            },
        ],
    }


def _context(*, current_topic: str = "") -> StudentLearningContext:
    return StudentLearningContext(
        name="AliasStudent",
        board="GSEB",
        medium="Gujarati",
        standard=7,
        preferred_language="Gujarati",
        current_subject="Mathematics",
        current_chapter="",
        current_topic=current_topic,
        learning_mode="explain",
        onboarding_complete=True,
    ).validate()


class TestPhase3SyllabusTopicAliases(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = SyllabusRepository(Path(self.temp.name))
        self.repo.install_payload(_payload())

    def assert_topic(self, message: str, expected: str, *, context=None) -> None:
        match = self.repo.lookup_topic(
            message=message,
            context=context or _context(),
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.topic.title, expected)

    def test_aliases_round_trip_through_schema(self) -> None:
        syllabus = self.repo.find(
            board="GSEB",
            medium="Gujarati",
            standard=7,
            subject="Mathematics",
        )
        self.assertIsNotNone(syllabus)
        topic = syllabus.chapters[0].topics[1]
        self.assertIn("પૂર્ણાંકોનો સરવાળો", topic.aliases)

    def test_gujarati_addition_alias_routes_specific_topic(self) -> None:
        self.assert_topic("પૂર્ણાંકોનો સરવાળો સમજાવો", "Addition of Integers")

    def test_gujarati_multiplication_alias_routes_specific_topic(self) -> None:
        self.assert_topic("પૂર્ણાંકોનો ગુણાકાર સમજાવો", "Multiplication of Integers")

    def test_gujarati_metadata_alias_routes_truthfully(self) -> None:
        self.assert_topic(
            "અપૂર્ણાંક અને દશાંશ સંખ્યાઓ સમજાવો",
            "Fractions and Decimals",
        )

    def test_explicit_gujarati_alias_beats_stale_english_context(self) -> None:
        self.assert_topic(
            "પૂર્ણાંકોનો સરવાળો સમજાવો",
            "Addition of Integers",
            context=_context(current_topic="Integers"),
        )

    def test_english_titles_remain_backward_compatible(self) -> None:
        self.assert_topic(
            "Explain multiplication of integers",
            "Multiplication of Integers",
        )


if __name__ == "__main__":
    unittest.main()
