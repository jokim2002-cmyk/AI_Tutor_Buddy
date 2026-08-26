import unittest
from pathlib import Path

from phase11_core import (
    GSEBSyllabusRepository,
    StudentLearningContext,
    parse_test_paper_scope,
    render_test_paper,
    evaluate_test_paper,
)
from phase11_ai import GyanVerseAIService


class RandomizedTestPaperGenerationTests(unittest.TestCase):
    def setUp(self):
        self.syllabus_dir = Path(__file__).resolve().parents[1] / "syllabus"
        self.repo = GSEBSyllabusRepository(self.syllabus_dir)
        self.science_syl = self.repo.find(
            board="GSEB",
            medium="English",
            standard=7,
            subject="Science & Technology",
        )
        self.ctx = StudentLearningContext(
            board="GSEB",
            medium="English",
            standard=7,
            preferred_language="English",
            current_subject="Science & Technology",
            current_chapter="Semester 1 — Properties of Magnet",
            onboarding_complete=True,
        ).validate()

    def test_default_deterministic_generation_still_works(self):
        scope = parse_test_paper_scope("Chapter 1 ka test banao", self.ctx, self.science_syl)
        raw1, paper1 = render_test_paper(self.science_syl, scope, context=self.ctx, message="Chapter 1 ka test banao")
        raw2, paper2 = render_test_paper(self.science_syl, scope, context=self.ctx, message="Chapter 1 ka test banao")

        self.assertEqual(raw1, raw2)
        self.assertEqual([q.question_text for q in paper1.questions], [q.question_text for q in paper2.questions])

    def test_two_random_test_requests_can_produce_different_question_selection_or_order(self):
        scope = parse_test_paper_scope("new test banao", self.ctx, self.science_syl)
        _, paper1 = render_test_paper(
            self.science_syl,
            scope,
            context=self.ctx,
            message="new test banao",
            seed=101,
        )
        _, paper2 = render_test_paper(
            self.science_syl,
            scope,
            context=self.ctx,
            message="new test banao",
            seed=999,
        )

        q_list1 = [q.question_text for q in paper1.questions]
        q_list2 = [q.question_text for q in paper2.questions]
        self.assertNotEqual(q_list1, q_list2)

    def test_answer_evaluation_still_works_against_active_randomized_paper(self):
        service = GyanVerseAIService(api_key="", syllabus_repository=self.repo)

        # 1. Generate randomized test paper
        gen_res = service.ask_stream("new test banao", context=self.ctx)
        self.assertIn("Test Paper:", gen_res)
        self.assertIsNotNone(service._last_generated_test_paper)

        active_paper = service._last_generated_test_paper

        # 2. Build answer submission targeting active paper's first question
        q1_item = active_paper.questions[0]
        sol_guide = q1_item.solution_guide

        submission = f"Q1. {sol_guide}"
        eval_res = service.ask_stream(
            f"Check my test answers:\n{submission}",
            context=self.ctx,
        )

        self.assertIn("Test Evaluation", eval_res)
        self.assertIn("Per-Question Evaluation:", eval_res)
        self.assertIn("| Q1 |", eval_res)
        self.assertIn("Correct", eval_res)

    def test_generated_paper_never_contains_questions_missing_solution_guides(self):
        test_messages = [
            "Chapter 1 test banao",
            "new test banao",
            "random test banao",
            "Full book test banao",
            "different full syllabus test banao",
        ]
        for msg in test_messages:
            with self.subTest(msg=msg):
                scope = parse_test_paper_scope(msg, self.ctx, self.science_syl)
                _, paper = render_test_paper(self.science_syl, scope, context=self.ctx, message=msg)
                self.assertTrue(len(paper.questions) > 0)
                for q_item in paper.questions:
                    self.assertIsNotNone(q_item.solution_guide)
                    self.assertTrue(
                        len(q_item.solution_guide.strip()) > 0,
                        f"Question {q_item.question_num} in '{msg}' missing solution guide",
                    )

    def test_full_syllabus_test_keeps_100_marks_structure(self):
        scope = parse_test_paper_scope("Full book test banao", self.ctx, self.science_syl)
        _, paper = render_test_paper(self.science_syl, scope, context=self.ctx, message="Full book test banao")

        self.assertEqual(paper.total_marks, 100)
        self.assertEqual(paper.duration_minutes, 180)

        sections = {}
        for q in paper.questions:
            sections[q.section_title] = sections.get(q.section_title, 0) + 1

        self.assertEqual(sections.get("Section A (1 Mark Each)"), 20)
        self.assertEqual(sections.get("Section B (2 Marks Each)"), 16)
        self.assertEqual(sections.get("Section C (3 Marks Each)"), 8)
        self.assertEqual(sections.get("Section D (6 Marks Each)"), 4)

        calculated_total = (
            sections["Section A (1 Mark Each)"] * 1
            + sections["Section B (2 Marks Each)"] * 2
            + sections["Section C (3 Marks Each)"] * 3
            + sections["Section D (6 Marks Each)"] * 6
        )
        self.assertEqual(calculated_total, 100)

    def test_chapter_test_keeps_25_marks_structure(self):
        scope = parse_test_paper_scope("Chapter 1 test banao", self.ctx, self.science_syl)
        _, paper = render_test_paper(self.science_syl, scope, context=self.ctx, message="Chapter 1 test banao")

        self.assertEqual(paper.total_marks, 25)
        self.assertEqual(paper.duration_minutes, 45)

        sections = {}
        for q in paper.questions:
            sections[q.section_title] = sections.get(q.section_title, 0) + 1

        self.assertEqual(sections.get("Section A (1 Mark Each)"), 5)
        self.assertEqual(sections.get("Section B (2 Marks Each)"), 4)
        self.assertEqual(sections.get("Section C (3 Marks Each)"), 2)
        self.assertEqual(sections.get("Section D (6 Marks Each)"), 1)

        calculated_total = (
            sections["Section A (1 Mark Each)"] * 1
            + sections["Section B (2 Marks Each)"] * 2
            + sections["Section C (3 Marks Each)"] * 3
            + sections["Section D (6 Marks Each)"] * 6
        )
        self.assertEqual(calculated_total, 25)

    def test_question_depth_matching_to_marks_regression(self):
        test_seeds = [1, 42, 101, 777, 999]
        for seed in test_seeds:
            with self.subTest(seed=seed):
                scope = parse_test_paper_scope("new full syllabus test banao", self.ctx, self.science_syl)
                _, paper = render_test_paper(
                    self.science_syl,
                    scope,
                    context=self.ctx,
                    message="new full syllabus test banao",
                    seed=seed,
                )

                sec_d_questions = [
                    q for q in paper.questions if q.section_title == "Section D (6 Marks Each)"
                ]
                sec_a_questions = [
                    q for q in paper.questions if q.section_title == "Section A (1 Mark Each)"
                ]

                # 1. 6-mark section should not contain "Which instrument", "Name the three", "Give one role", "Name the three main parts" style one-line questions.
                forbidden_6m_prefixes = (
                    "which instrument",
                    "name the three",
                    "give one role",
                    "name the three main parts",
                    "which ",
                    "name ",
                    "give one ",
                )
                for q_item in sec_d_questions:
                    q_lower = q_item.question_text.casefold()
                    for prefix in forbidden_6m_prefixes:
                        self.assertFalse(
                            q_lower.startswith(prefix),
                            f"6-mark question '{q_item.question_text}' in seed {seed} should not start with forbidden simple prefix '{prefix}'",
                        )

                # 2. 1-mark section should not contain heavy explanation prompts where answer guide expects multiple points.
                for q_item in sec_a_questions:
                    q_lower = q_item.question_text.casefold()
                    sol_words = len(q_item.solution_guide.strip().split())
                    if q_lower.startswith("explain with an example"):
                        self.assertLess(
                            sol_words,
                            25,
                            f"1-mark question '{q_item.question_text}' in seed {seed} contains heavy multi-point solution guide",
                        )


if __name__ == "__main__":
    unittest.main()
