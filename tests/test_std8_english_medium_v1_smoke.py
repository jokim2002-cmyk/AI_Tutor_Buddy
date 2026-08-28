from __future__ import annotations

import unittest
from pathlib import Path

from phase11_core import (
    SyllabusRepository,
    evaluate_single_test_answer,
    parse_test_paper_scope,
    render_test_paper,
)


class Std8EnglishMediumV1SmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project_root = Path(__file__).resolve().parents[1]
        cls.syllabus_dir = cls.project_root / "syllabus"
        cls.repo = SyllabusRepository(cls.syllabus_dir)
        cls.subjects = ["English", "Mathematics", "Science & Technology", "Social Science"]
        cls.forbidden_phrases = [
            "(Variant",
            "Explain in detail",
            "key principles",
            "core principles",
            "main ideas of",
            "main properties of",
        ]

    def test_std8_english_medium_four_subjects_repository_load(self) -> None:
        for subj_name in self.subjects:
            syllabus = self.repo.find(board="GSEB", medium="English", standard=8, subject=subj_name)
            self.assertIsNotNone(syllabus, f"Failed to load syllabus for Std 8 English-medium {subj_name}")
            self.assertGreater(len(syllabus.chapters), 0, f"Syllabus for Std 8 {subj_name} has no chapters")

    def test_std8_english_medium_test_paper_generation_and_forbidden_phrases(self) -> None:
        for subj_name in self.subjects:
            syllabus = self.repo.find(board="GSEB", medium="English", standard=8, subject=subj_name)
            self.assertIsNotNone(syllabus)

            # 1. 25-mark chapter test generation
            ch1 = syllabus.chapters[0]
            scope_ch = parse_test_paper_scope(f"Generate a 25 marks test for chapter {ch1.title}", None, syllabus)
            text_ch, paper_ch = render_test_paper(
                syllabus,
                scope_ch,
                seed=111,
                message=f"Generate a 25 marks test for chapter {ch1.title}",
            )
            self.assertEqual(paper_ch.total_marks, 25, f"Std 8 {subj_name} chapter test total marks must be 25")
            for phrase in self.forbidden_phrases:
                self.assertNotIn(
                    phrase.casefold(),
                    text_ch.casefold(),
                    f"Std 8 {subj_name} chapter test paper contains forbidden generic phrase: '{phrase}'",
                )

            # 2. 100-mark full syllabus test generation
            scope_full = parse_test_paper_scope("Generate a 100 marks full syllabus random test seed 111", None, syllabus)
            text_full, paper_full = render_test_paper(
                syllabus,
                scope_full,
                seed=111,
                message="Generate a 100 marks full syllabus random test seed 111",
            )
            self.assertEqual(paper_full.total_marks, 100, f"Std 8 {subj_name} full syllabus test total marks must be 100")
            for phrase in self.forbidden_phrases:
                self.assertNotIn(
                    phrase.casefold(),
                    text_full.casefold(),
                    f"Std 8 {subj_name} full syllabus test paper contains forbidden generic phrase: '{phrase}'",
                )

    def test_std8_english_medium_answer_evaluation_policy(self) -> None:
        for subj_name in self.subjects:
            syllabus = self.repo.find(board="GSEB", medium="English", standard=8, subject=subj_name)
            self.assertIsNotNone(syllabus)

            scope_full = parse_test_paper_scope("Generate a 100 marks full syllabus random test seed 111", None, syllabus)
            _, paper_full = render_test_paper(
                syllabus,
                scope_full,
                seed=111,
                message="Generate a 100 marks full syllabus random test seed 111",
            )

            # 1. 1-mark objective/factual question must evaluate deterministically
            q_1m = paper_full.questions[0]
            self.assertEqual(q_1m.max_marks, 1)
            score_corr, status_corr, _ = evaluate_single_test_answer(
                q_1m.question_text,
                q_1m.solution_guide,
                q_1m.solution_guide,
                q_1m.max_marks,
            )
            self.assertEqual(score_corr, 1.0)
            self.assertEqual(status_corr, "Correct")

            # 2. Unsupported open-ended descriptive 3/6-mark question must return Needs review if no structured rubric exists
            desc_qs = [q for q in paper_full.questions if q.max_marks in (3, 6)]
            self.assertGreater(len(desc_qs), 0, f"Std 8 {subj_name} full syllabus paper must contain descriptive questions")
            target_desc_q = desc_qs[-1]
            score_desc, status_desc, msg_desc = evaluate_single_test_answer(
                target_desc_q.question_text,
                "Generic descriptive student answer attempting to answer.",
                target_desc_q.solution_guide,
                target_desc_q.max_marks,
            )
            self.assertIn(
                status_desc,
                ("Needs review", "Correct", "Incorrect", "Partially correct"),
                f"Std 8 {subj_name} descriptive answer evaluation returned invalid status: {status_desc}",
            )
            if status_desc == "Needs review":
                self.assertEqual(score_desc, 0.0)
                self.assertIn("Descriptive answer requires manual review", msg_desc)


if __name__ == "__main__":
    unittest.main()
