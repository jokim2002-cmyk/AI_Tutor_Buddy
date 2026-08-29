from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from phase11_core import StudentLearningContext, SyllabusRepository


def _payload() -> dict:
    def topic(title: str) -> dict:
        return {
            "title": title,
            "explanation": f"Teacher-authored explanation for {title}.",
            "content_origin": "teacher_authored",
        }

    return {
        "schema_version": 1,
        "board": "GSEB",
        "medium": "Gujarati",
        "standard": 7,
        "subject": "Mathematics",
        "textbook": "Specificity Test Mathematics",
        "source": {
            "title": "Specificity Test Source",
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
                    topic("Integers"),
                    topic("Addition of Integers"),
                    topic("Subtraction of Integers"),
                    topic("Multiplication of Integers"),
                    topic("Properties of Integer Operations"),
                    topic("Division of Integers"),
                ],
            },
            {
                "chapter_id": "fractions",
                "number": "2",
                "title": "Fractions and Decimals",
                "topics": [
                    {
                        "title": "Fractions and Decimals",
                        "content_origin": "metadata_only",
                    }
                ],
            },
        ],
    }


def _context(*, topic: str = "", chapter: str = "") -> StudentLearningContext:
    return StudentLearningContext(
        name="SpecificityStudent",
        board="GSEB",
        medium="Gujarati",
        standard=7,
        preferred_language="English",
        current_subject="Mathematics",
        current_chapter=chapter,
        current_topic=topic,
        learning_mode="explain",
        onboarding_complete=True,
    ).validate()


class TestPhase3SyllabusTopicSpecificity(unittest.TestCase):
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

    def test_specific_addition_beats_generic_integers(self) -> None:
        self.assert_topic(
            "Explain addition of integers",
            "Addition of Integers",
        )

    def test_specific_multiplication_beats_generic_integers(self) -> None:
        self.assert_topic(
            "Explain multiplication of integers",
            "Multiplication of Integers",
        )

    def test_all_integer_operation_topics_resolve_exactly(self) -> None:
        cases = {
            "Explain integers": "Integers",
            "Explain subtraction of integers": "Subtraction of Integers",
            "Explain properties of integer operations": "Properties of Integer Operations",
            "Explain division of integers": "Division of Integers",
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assert_topic(message, expected)

    def test_explicit_message_overrides_stale_generic_topic_context(self) -> None:
        self.assert_topic(
            "Explain addition of integers",
            "Addition of Integers",
            context=_context(topic="Integers", chapter="Integers"),
        )

    def test_metadata_topic_still_resolves(self) -> None:
        self.assert_topic(
            "Explain fractions and decimals",
            "Fractions and Decimals",
        )


if __name__ == "__main__":
    unittest.main()
