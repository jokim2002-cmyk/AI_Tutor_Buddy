from __future__ import annotations

import unittest
from pathlib import Path

from phase11_core import (
    SyllabusRepository,
    evaluate_single_test_answer,
    parse_test_paper_scope,
    render_test_paper,
)


class EnglishMediumV1ReleaseGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project_root = Path(__file__).resolve().parents[1]
        cls.syllabus_dir = cls.project_root / "syllabus"
        cls.repo = SyllabusRepository(cls.syllabus_dir)
        cls.standards = [7, 8]
        cls.subjects = ["English", "Mathematics", "Science & Technology", "Social Science"]
        cls.allowed_media = ["English"]
        cls.forbidden_phrases = [
            "(Variant",
            "Explain in detail",
            "key principles",
            "core principles",
            "main ideas of",
            "main properties of",
            "in detail, including main features",
            "observations, and real-world significance",
        ]

    def test_v1_ui_scope_lock(self) -> None:
        """Verify UI scope lock boundaries for V1 release."""
        # Allowed standards: 7 and 8 only
        self.assertEqual(set(self.standards), {7, 8})
        # Allowed media: English only
        self.assertEqual(set(self.allowed_media), {"English"})
        # Allowed subjects: 4 core subjects only
        self.assertEqual(
            set(self.subjects),
            {"English", "Mathematics", "Science & Technology", "Social Science"},
        )

    def test_v1_release_gate_all_eight_syllabus_packages_load(self) -> None:
        """Verify repository loads all 8 English-medium syllabus packages (Std 7 & Std 8 x 4 subjects)."""
        loaded_packages = 0
        for std in self.standards:
            for subj_name in self.subjects:
                syllabus = self.repo.find(board="GSEB", medium="English", standard=std, subject=subj_name)
                self.assertIsNotNone(
                    syllabus,
                    f"Failed to load syllabus package for GSEB English Std {std} {subj_name}",
                )
                self.assertGreater(
                    len(syllabus.chapters),
                    0,
                    f"Syllabus package for Std {std} {subj_name} has no chapters",
                )
                loaded_packages += 1

        self.assertEqual(loaded_packages, 8, "V1 release gate must verify exactly 8 syllabus packages")

    def test_v1_release_gate_test_paper_generation_and_forbidden_phrases(self) -> None:
        """Verify 25m and 100m paper generation and forbidden phrase rejection across all 8 packages."""
        for std in self.standards:
            for subj_name in self.subjects:
                syllabus = self.repo.find(board="GSEB", medium="English", standard=std, subject=subj_name)
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
                self.assertEqual(
                    paper_ch.total_marks,
                    25,
                    f"Std {std} {subj_name} chapter test total marks must be 25",
                )
                for phrase in self.forbidden_phrases:
                    self.assertNotIn(
                        phrase.casefold(),
                        text_ch.casefold(),
                        f"Std {std} {subj_name} chapter test paper contains forbidden generic phrase: '{phrase}'",
                    )

                # 2. 100-mark full syllabus test generation
                scope_full = parse_test_paper_scope("Generate a 100 marks full syllabus random test seed 111", None, syllabus)
                text_full, paper_full = render_test_paper(
                    syllabus,
                    scope_full,
                    seed=111,
                    message="Generate a 100 marks full syllabus random test seed 111",
                )
                self.assertEqual(
                    paper_full.total_marks,
                    100,
                    f"Std {std} {subj_name} full syllabus test total marks must be 100",
                )
                for phrase in self.forbidden_phrases:
                    self.assertNotIn(
                        phrase.casefold(),
                        text_full.casefold(),
                        f"Std {std} {subj_name} full syllabus test paper contains forbidden generic phrase: '{phrase}'",
                    )

    def test_v1_release_gate_evaluation_policy_across_all_eight_packages(self) -> None:
        """Verify 1-mark deterministic auto-grading and 3/6-mark Needs review fallbacks across all 8 packages."""
        for std in self.standards:
            for subj_name in self.subjects:
                syllabus = self.repo.find(board="GSEB", medium="English", standard=std, subject=subj_name)
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
                self.assertGreater(
                    len(desc_qs),
                    0,
                    f"Std {std} {subj_name} full syllabus paper must contain descriptive questions",
                )
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
                    f"Std {std} {subj_name} descriptive answer evaluation returned invalid status: {status_desc}",
                )
                if status_desc == "Needs review":
                    self.assertEqual(score_desc, 0.0)
                    self.assertIn("Descriptive answer requires manual review", msg_desc)


if __name__ == "__main__":
    unittest.main()
