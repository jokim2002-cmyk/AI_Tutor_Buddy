from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from phase11_core import SyllabusRepository


ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "gyanverse_ui.py").read_text(encoding="utf-8")


class Phase3SyllabusUIRenderTests(unittest.TestCase):
    def test_source_parses(self) -> None:
        ast.parse(UI, filename="gyanverse_ui.py")

    def test_syllabus_view_uses_stable_wrapped_row(self) -> None:
        block = UI.split("    def build_syllabus()", 1)[1].split(
            "    def build_settings()", 1
        )[0]
        self.assertIn("coverage_cards: list[ft.Control]", block)
        self.assertIn("coverage_grid = ft.Row(", block)
        self.assertIn("controls=coverage_cards", block)
        self.assertIn("wrap=True", block)
        self.assertIn("installed_packages = ft.Column(", block)
        self.assertIn("tight=True", block)
        self.assertNotIn("ft.ResponsiveRow(", block)

    def test_import_refresh_contract_remains(self) -> None:
        self.assertIn('show_view("syllabus")', UI)
        self.assertIn('"syllabus": build_syllabus', UI)

    def test_teacher_authored_package_coverage_values(self) -> None:
        payload = {
            "schema_version": 1,
            "board": "GSEB",
            "medium": "Gujarati",
            "standard": 7,
            "subject": "Mathematics",
            "textbook": "Teacher-authored demo",
            "source": {
                "title": "Render fixture",
                "publisher": "GyanVerse",
                "edition": "1",
                "official": False,
            },
            "chapters": [
                {
                    "chapter_id": "c1",
                    "number": "1",
                    "title": "Integers",
                    "topics": [
                        {
                            "topic_id": "t1",
                            "title": "Addition",
                            "explanation": "Validated teacher-authored content.",
                            "content_origin": "teacher_authored",
                        }
                    ],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            repo = SyllabusRepository(directory)
            repo.install_payload(payload)
            coverage = repo.overall_coverage()
            self.assertEqual(coverage["syllabi"], 1)
            self.assertEqual(coverage["topics"], 1)
            self.assertEqual(coverage["coverage_percent"], 100.0)
            self.assertEqual(coverage["official_coverage_percent"], 0.0)


if __name__ == "__main__":
    unittest.main()
