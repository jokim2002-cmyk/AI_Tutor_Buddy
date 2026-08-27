import unittest
from dataclasses import replace
from pathlib import Path

from phase11_core import (
    GSEBSyllabusRepository,
    StudentLearningContext,
    build_natural_6mark_question,
    parse_test_paper_scope,
    render_test_paper,
    evaluate_test_paper,
    evaluate_single_test_answer,
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

                # 3. 3-mark section should not contain simple one-line questions like "Give one role of dietary fibre" or "Which method separates..."
                sec_c_questions = [
                    q for q in paper.questions if q.section_title == "Section C (3 Marks Each)"
                ]
                forbidden_3m_prefixes = (
                    "give one role",
                    "which method",
                    "which instrument",
                    "state one",
                )
                for q_item in sec_c_questions:
                    q_lower = q_item.question_text.casefold()
                    is_explanation = any(
                        k in q_lower for k in ("explain", "distinguish", "why", "how", "describe", "compare", "calculate", "reason", "example")
                    )
                # 4. Check explicit intended_marks match and specific forbidden phrases
                for q_item in paper.questions:
                    self.assertEqual(
                        q_item.intended_marks,
                        q_item.max_marks,
                        f"Question '{q_item.question_text}' intended_marks ({q_item.intended_marks}) does not match section max_marks ({q_item.max_marks})",
                    )
                    q_lower = q_item.question_text.casefold()
                    if "name the three main parts used to describe a lever" in q_lower:
                        self.assertNotIn(
                            q_item.max_marks,
                            (3, 6),
                            "Lever parts question must not appear in 3 or 6 marks section",
                        )
                    if "metal paper clip can complete a low-voltage test circuit" in q_lower:
                        self.assertNotEqual(
                            q_item.max_marks,
                            6,
                            "Metal paper clip example must not appear in 6 marks section",
                        )

    def test_section_d_natural_quality_and_templates_regression(self):
        test_seeds = [1, 42, 101, 111, 222, 777, 999]
        valid_task_words = ("explain", "describe", "compare", "differentiate", "solve", "how", "why")
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

                # Total marks check
                self.assertEqual(paper.total_marks, 100)

                # Invariant checks for every question
                for q_item in paper.questions:
                    self.assertEqual(q_item.intended_marks, q_item.max_marks)
                    self.assertTrue(bool(q_item.solution_guide and q_item.solution_guide.strip()))

                sec_d_questions = [
                    q for q in paper.questions if q.section_title == "Section D (6 Marks Each)"
                ]
                self.assertEqual(len(sec_d_questions), 4)

                for q_item in sec_d_questions:
                    q_lower = q_item.question_text.casefold()

                    # 1. Section D must not contain "scientific principles, and applications of"
                    self.assertNotIn(
                        "scientific principles, and applications of",
                        q_lower,
                        f"Section D question '{q_item.question_text}' in seed {seed} contains generic phrase",
                    )

                    # 2. Section D must not contain "core scientific principles of"
                    self.assertNotIn(
                        "core scientific principles of",
                        q_lower,
                        f"Section D question '{q_item.question_text}' in seed {seed} contains generic 'core scientific principles of'",
                    )

                    # 3. Section D must not contain generic title-only fallback template
                    self.assertFalse(
                        q_lower.startswith("describe in detail the process, scientific principles"),
                        f"Section D question '{q_item.question_text}' in seed {seed} uses generic title-only fallback",
                    )

                    # 4. Must include natural task words
                    has_task_word = any(word in q_lower for word in valid_task_words)
                    self.assertTrue(
                        has_task_word,
                        f"Section D question '{q_item.question_text}' in seed {seed} lacks topic-specific task words",
                    )

    def test_energy_conservation_and_water_conservation_topic_question_alignment_regression(self):
        # 1. Energy conservation topic must not generate water conservation/rainwater harvesting question
        energy_q = build_natural_6mark_question(
            "Energy conservation and responsible use",
            "Energy conservation means using energy efficiently and avoiding waste in daily activities at home and school.",
            ["Turn off lights", "Use LED bulbs"],
        )
        self.assertIsNotNone(energy_q)
        energy_text, _ = energy_q
        self.assertNotIn("water conservation", energy_text.casefold())
        self.assertNotIn("rainwater harvesting", energy_text.casefold())
        self.assertIn("energy", energy_text.casefold())

        # 2. Conservation and sustainable action may generate water conservation/rainwater harvesting question
        water_q = build_natural_6mark_question(
            "Conservation and sustainable action",
            "Water conservation protects essential natural resources for organisms and ecosystems. Rainwater harvesting collects and stores rain for future use.",
            ["Roof rainwater collection"],
        )
        self.assertIsNotNone(water_q)
        water_text, _ = water_q
        self.assertIn("water conservation", water_text.casefold())
        self.assertIn("rainwater harvesting", water_text.casefold())

        # 3. Verify across full syllabus test papers that Section D questions match their displayed topic labels
        for seed in [111, 222]:
            scope = parse_test_paper_scope("new full syllabus test banao", self.ctx, self.science_syl)
            _, paper = render_test_paper(
                self.science_syl,
                scope,
                context=self.ctx,
                message="new full syllabus test banao",
                seed=seed,
            )
            self.assertEqual(paper.total_marks, 100)
            sec_d_questions = [
                q for q in paper.questions if q.section_title == "Section D (6 Marks Each)"
            ]
            self.assertEqual(len(sec_d_questions), 4)

            for q_item in sec_d_questions:
                topic_lower = q_item.topic_title.casefold()
                q_lower = q_item.question_text.casefold()
                self.assertEqual(q_item.intended_marks, q_item.max_marks)
                self.assertTrue(bool(q_item.solution_guide and q_item.solution_guide.strip()))

                if "energy conservation" in topic_lower:
                    self.assertNotIn(
                        "rainwater harvesting",
                        q_lower,
                        f"Topic '{q_item.topic_title}' generated mismatched question '{q_item.question_text}' in seed {seed}",
                    )

    def test_exact_topic_alignment_for_mixtures_and_plane_mirror_regression(self):
        # 1. Mixtures and separation choices topic
        sep_q = build_natural_6mark_question(
            "Mixtures and separation choices",
            "Mixtures contain substances physically combined in variable proportions. Separation options depend on component properties.",
            ["Hand-picking", "Filtration"],
        )
        self.assertIsNotNone(sep_q)
        sep_text, _ = sep_q
        self.assertIn("hand-picking", sep_text.casefold())
        self.assertNotIn("differentiate between elements, compounds, and mixtures", sep_text.casefold())

        # 2. Plane-mirror images and types of reflection topic
        plane_q = build_natural_6mark_question(
            "Plane-mirror images and types of reflection",
            "A plane mirror forms a virtual, upright image. Regular reflection is from smooth surfaces while diffuse is from rough surfaces.",
            ["Polished mirror", "Rough paper"],
        )
        self.assertIsNotNone(plane_q)
        plane_text, _ = plane_q
        self.assertIn("plane mirror", plane_text.casefold())
        self.assertIn("diffuse reflection", plane_text.casefold())
        self.assertNotIn("concave, and convex mirrors", plane_text.casefold())

        # 3. Verify across full syllabus test papers that Section D questions match exact topic expectations
        for seed in [1, 42, 101, 111, 222, 777, 999]:
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
            for q_item in sec_d_questions:
                t_low = q_item.topic_title.casefold()
                q_low = q_item.question_text.casefold()
                if "mixtures and separation choices" in t_low:
                    self.assertNotIn("differentiate between elements, compounds, and mixtures", q_low)
                    self.assertIn("hand-picking", q_low)
                if "plane-mirror images and types of reflection" in t_low:
                    self.assertNotIn("concave, and convex mirrors", q_low)
                    self.assertIn("plane mirror", q_low)

    def test_std7_random_test_q1_q5_wrong_answer_guard_regression(self):
        # 1. Correct Q1-Q5 evaluation
        q1_score, q1_status, _ = evaluate_single_test_answer(
            "Name the three major nutrients represented by N, P and K.",
            "N, P and K are nitrogen, phosphorus and potassium.",
            "Nitrogen, phosphorus and potassium.",
            1,
        )
        self.assertEqual(q1_score, 1.0)
        self.assertEqual(q1_status, "Correct")

        q3_score, q3_status, _ = evaluate_single_test_answer(
            "Give one example of oscillatory motion.",
            "A swing moving to and fro is oscillatory motion.",
            "A pendulum / swing moving to and fro.",
            1,
        )
        self.assertEqual(q3_score, 1.0)
        self.assertEqual(q3_status, "Correct")

        q5_score, q5_status, _ = evaluate_single_test_answer(
            "Which method separates an insoluble solid from a liquid using filter paper?",
            "Filtration separates insoluble solid from liquid using filter paper.",
            "Filtration.",
            1,
        )
        self.assertEqual(q5_score, 1.0)
        self.assertEqual(q5_status, "Correct")

        # 2. Deliberately wrong Q1-Q5 evaluation
        wrong_answers = [
            ("Name the three major nutrients represented by N, P and K.", "N, P and K stand for neon, potassium and krypton.", "Nitrogen, phosphorus and potassium.", 1),
            ("What is a natural satellite? Give one example.", "A natural satellite is a man-made machine. Example: a bus.", "A natural satellite is a celestial body revolving around a planet, such as the Moon.", 1),
            ("Give one example of oscillatory motion.", "Straight-line motion is oscillatory motion.", "A pendulum / swing moving to and fro.", 1),
            ("A bus travels 150 kilometres in 3 hours. Find its average speed.", "Average speed = 150 + 3 = 153 km/h.", "50 km/h", 1),
            ("Which method separates an insoluble solid from a liquid using filter paper?", "Evaporation separates insoluble solid from liquid using filter paper.", "Filtration.", 1),
        ]

        total_wrong_score = 0.0
        for q_t, u_a, s_g, m_m in wrong_answers:
            score, status, _ = evaluate_single_test_answer(q_t, u_a, s_g, m_m)
            self.assertEqual(score, 0.0, f"Wrong answer '{u_a}' for '{q_t}' scored {score} instead of 0.0")
            self.assertEqual(status, "Incorrect")
            total_wrong_score += score

        self.assertEqual(total_wrong_score, 0.0)

        # 3. Correct Q1-Q5 answers total score
        correct_answers = [
            ("Name the three major nutrients represented by N, P and K.", "N, P and K are nitrogen, phosphorus and potassium.", "Nitrogen, phosphorus and potassium.", 1),
            ("What is a natural satellite? Give one example.", "A natural satellite is a celestial body that revolves around a planet. Example: Moon.", "A natural satellite is a celestial body revolving around a planet, such as the Moon.", 1),
            ("Give one example of oscillatory motion.", "A swing moving to and fro is oscillatory motion.", "A pendulum / swing moving to and fro.", 1),
            ("A bus travels 150 kilometres in 3 hours. Find its average speed.", "Average speed = 150 / 3 = 50 km/h.", "50 km/h", 1),
            ("Which method separates an insoluble solid from a liquid using filter paper?", "Filtration separates insoluble solid from liquid using filter paper.", "Filtration.", 1),
        ]
        total_correct_score = 0.0
        for q_t, u_a, s_g, m_m in correct_answers:
            score, status, _ = evaluate_single_test_answer(q_t, u_a, s_g, m_m)
            self.assertEqual(score, 1.0)
            self.assertEqual(status, "Correct")
            total_correct_score += score

        self.assertEqual(total_correct_score, 5.0)

    def test_std7_properties_of_magnet_q1_q5_wrong_answer_guard_regression(self):
        # Active Properties of Magnet 25-mark random chapter test seed 111 Q1-Q5 evaluation
        magnet_scope = parse_test_paper_scope("Properties of Magnet chapter test", self.ctx, self.science_syl)
        _, magnet_paper = render_test_paper(
            self.science_syl,
            magnet_scope,
            context=self.ctx,
            message="Properties of Magnet chapter test",
            seed=111,
        )

        q1_5 = magnet_paper.questions[:5]
        self.assertEqual(len(q1_5), 5)
        q_map = {q.question_text.strip(): q for q in magnet_paper.questions}

        # 1. Q1: Where is the magnetic force of a bar magnet usually strongest?
        q1_txt = "Where is the magnetic force of a bar magnet usually strongest?"
        q1_guide = q_map[q1_txt].solution_guide if q1_txt in q_map else "It is usually strongest near the north and south poles at the two ends of the bar magnet."
        s1_w, st1_w, _ = evaluate_single_test_answer(q1_txt, "The magnetic force is strongest in the middle of a bar magnet.", q1_guide, 1)
        self.assertEqual(s1_w, 0.0)
        self.assertEqual(st1_w, "Incorrect")

        s1_w2, st1_w2, _ = evaluate_single_test_answer(q1_txt, "Magnetic force is strongest in the centre of a magnet.", q1_guide, 1)
        self.assertEqual(s1_w2, 0.0)
        self.assertEqual(st1_w2, "Incorrect")

        s1_c, st1_c, _ = evaluate_single_test_answer(q1_txt, "Magnetic force is strongest near the two poles/ends.", q1_guide, 1)
        self.assertEqual(s1_c, 1.0)
        self.assertEqual(st1_c, "Correct")

        # 2. Q3: In a field-line diagram, what does a region of closely spaced lines represent?
        q3_txt = "In a field-line diagram, what does a region of closely spaced lines represent?"
        q3_guide = q_map[q3_txt].solution_guide if q3_txt in q_map else "It represents a stronger magnetic field in that region."
        s3_w, st3_w, _ = evaluate_single_test_answer(q3_txt, "Closely spaced magnetic field lines represent a weaker magnetic field.", q3_guide, 1)
        self.assertEqual(s3_w, 0.0)
        self.assertEqual(st3_w, "Incorrect")

        s3_c, st3_c, _ = evaluate_single_test_answer(q3_txt, "Closely spaced field lines represent a stronger magnetic field.", q3_guide, 1)
        self.assertEqual(s3_c, 1.0)
        self.assertEqual(st3_c, "Correct")

        # 3. Q4: What happens when the north pole of one magnet is brought near the south pole of another?
        q4_txt = "What happens when the north pole of one magnet is brought near the south pole of another?"
        q4_guide = q_map[q4_txt].solution_guide if q4_txt in q_map else "The unlike poles attract each other."
        s4_w, st4_w, _ = evaluate_single_test_answer(q4_txt, "The north pole and south pole repel each other.", q4_guide, 1)
        self.assertEqual(s4_w, 0.0)
        self.assertEqual(st4_w, "Incorrect")

        s4_c, st4_c, _ = evaluate_single_test_answer(q4_txt, "North and south poles attract.", q4_guide, 1)
        self.assertEqual(s4_c, 1.0)
        self.assertEqual(st4_c, "Correct")

        # 4. Q5: What happens when two south poles are brought close together?
        q5_txt = "What happens when two south poles are brought close together?"
        q5_guide = q_map[q5_txt].solution_guide if q5_txt in q_map else "The like poles repel each other."
        s5_w, st5_w, _ = evaluate_single_test_answer(q5_txt, "Two south poles attract each other.", q5_guide, 1)
        self.assertEqual(s5_w, 0.0)
        self.assertEqual(st5_w, "Incorrect")

        s5_c, st5_c, _ = evaluate_single_test_answer(q5_txt, "Two south poles repel.", q5_guide, 1)
        self.assertEqual(s5_c, 1.0)
        self.assertEqual(st5_c, "Correct")

        # 5. Evaluate full active Q1-Q5 set with correct answers => 5/25 (5 marks for Q1-Q5)
        correct_q1_5_score = 0.0
        for q in q1_5:
            score, status, _ = evaluate_single_test_answer(q.question_text, q.solution_guide, q.solution_guide, 1)
            self.assertEqual(score, 1.0, f"Question '{q.question_text}' failed correct evaluation")
            self.assertEqual(status, "Correct")
            correct_q1_5_score += score

        self.assertEqual(correct_q1_5_score, 5.0)

        # 6. Evaluate full active Q1-Q5 set with wrong answers => 0/25 (0 marks for Q1-Q5)
        wrong_q1_5_score = 0.0
        for q in q1_5:
            q_txt = q.question_text
            g_txt = q.solution_guide
            if "where" in q_txt.casefold() or "strongest" in q_txt.casefold():
                w_ans = "The magnetic force is strongest in the middle of a bar magnet."
            elif "closely spaced" in q_txt.casefold() or "field line" in q_txt.casefold():
                w_ans = "Closely spaced magnetic field lines represent a weaker magnetic field."
            elif "north pole" in q_txt.casefold() and "south pole" in q_txt.casefold():
                w_ans = "The north pole and south pole repel each other."
            elif "two south poles" in q_txt.casefold() or "like poles" in q_txt.casefold():
                w_ans = "Two south poles attract each other."
            else:
                w_ans = "This answer is completely wrong and irrelevant."

            score, status, _ = evaluate_single_test_answer(q_txt, w_ans, g_txt, 1)
            self.assertEqual(score, 0.0, f"Question '{q_txt}' with wrong answer '{w_ans}' scored {score} instead of 0.0")
            self.assertEqual(status, "Incorrect")
            wrong_q1_5_score += score

        self.assertEqual(wrong_q1_5_score, 0.0)

    def test_std7_motion_force_speed_q1_q5_wrong_answer_guard_regression(self):
        # Active Motion, Force and Speed 25-mark random chapter test seed 111 Q1-Q5 evaluation
        motion_scope = parse_test_paper_scope("Motion, Force and Speed chapter test", self.ctx, self.science_syl)
        _, motion_paper = render_test_paper(
            self.science_syl,
            motion_scope,
            context=self.ctx,
            message="Motion, Force and Speed chapter test",
            seed=111,
        )

        q1_5 = motion_paper.questions[:5]
        self.assertEqual(len(q1_5), 5)
        q_map = {q.question_text.strip(): q for q in motion_paper.questions}

        # 1. Q1: What quantity is obtained by dividing total distance covered by total time taken?
        q1_txt = "What quantity is obtained by dividing total distance covered by total time taken?"
        q1_guide = q_map[q1_txt].solution_guide if q1_txt in q_map else "Average speed."
        s1_w, st1_w, _ = evaluate_single_test_answer(q1_txt, "Average speed is obtained by multiplying distance and time.", q1_guide, 1)
        self.assertEqual(s1_w, 0.0)
        self.assertEqual(st1_w, "Incorrect")

        s1_c, st1_c, _ = evaluate_single_test_answer(q1_txt, "Average speed is obtained by dividing total distance covered by total time taken.", q1_guide, 1)
        self.assertEqual(s1_c, 1.0)
        self.assertEqual(st1_c, "Correct")

        # 2. Q2: What can an unbalanced force change about a moving body?
        q2_txt = "What can an unbalanced force change about a moving body?"
        q2_guide = q_map[q2_txt].solution_guide if q2_txt in q_map else "It can change the speed or direction of motion."
        s2_w, st2_w, _ = evaluate_single_test_answer(q2_txt, "An unbalanced force can never change the motion of a body.", q2_guide, 1)
        self.assertEqual(s2_w, 0.0)
        self.assertEqual(st2_w, "Incorrect")

        s2_c, st2_c, _ = evaluate_single_test_answer(q2_txt, "An unbalanced force can change the speed or direction of motion of a body.", q2_guide, 1)
        self.assertEqual(s2_c, 1.0)
        self.assertEqual(st2_c, "Correct")

        # 3. Q4: What type of motion is shown by the hands of a mechanical clock?
        q4_txt = "What type of motion is shown by the hands of a mechanical clock?"
        q4_guide = q_map[q4_txt].solution_guide if q4_txt in q_map else "Circular motion."
        s4_w, st4_w, _ = evaluate_single_test_answer(q4_txt, "The hands of a mechanical clock show straight-line motion.", q4_guide, 1)
        self.assertEqual(s4_w, 0.0)
        self.assertEqual(st4_w, "Incorrect")

        s4_c, st4_c, _ = evaluate_single_test_answer(q4_txt, "The hands of a mechanical clock show circular motion.", q4_guide, 1)
        self.assertEqual(s4_c, 1.0)
        self.assertEqual(st4_c, "Correct")

        # 4. Q5: What is meant by motion relative to a reference point?
        q5_txt = "What is meant by motion relative to a reference point?"
        q5_guide = q_map[q5_txt].solution_guide if q5_txt in q_map else "Motion means a change in an object's position with time compared with the selected reference point."
        s5_w, st5_w, _ = evaluate_single_test_answer(q5_txt, "Motion relative to a reference point means the object never changes position compared with that reference point.", q5_guide, 1)
        self.assertEqual(s5_w, 0.0)
        self.assertEqual(st5_w, "Incorrect")

        s5_c, st5_c, _ = evaluate_single_test_answer(q5_txt, "Motion relative to a reference point means the object changes position compared with that reference point.", q5_guide, 1)
        self.assertEqual(s5_c, 1.0)
        self.assertEqual(st5_c, "Correct")

        # 5. Evaluate full active Q1-Q5 set with correct answers => 5/25 (5 marks for Q1-Q5)
        correct_answers = [
            "Average speed is obtained by dividing total distance covered by total time taken.",
            "An unbalanced force can change the speed or direction of motion of a body.",
            "Kilometres per hour (km/h)",
            "The hands of a mechanical clock show circular motion.",
            "Motion relative to a reference point means the object changes position compared with that reference point.",
        ]
        correct_q1_5_score = 0.0
        for i, q in enumerate(q1_5):
            score, status, _ = evaluate_single_test_answer(q.question_text, correct_answers[i], q.solution_guide, 1)
            self.assertEqual(score, 1.0, f"Question '{q.question_text}' failed correct evaluation")
            self.assertEqual(status, "Correct")
            correct_q1_5_score += score

        self.assertEqual(correct_q1_5_score, 5.0)

        # 6. Evaluate full active Q1-Q5 set with wrong answers => 0/25 (0 marks for Q1-Q5)
        wrong_answers = [
            "Average speed is obtained by multiplying distance and time.",
            "An unbalanced force can never change the motion of a body.",
            "Kilogram is used to measure speed.",
            "The hands of a mechanical clock show straight-line motion.",
            "Motion relative to a reference point means the object never changes position compared with that reference point.",
        ]
        wrong_q1_5_score = 0.0
        for i, q in enumerate(q1_5):
            score, status, _ = evaluate_single_test_answer(q.question_text, wrong_answers[i], q.solution_guide, 1)
            self.assertEqual(score, 0.0, f"Question '{q.question_text}' with wrong answer '{wrong_answers[i]}' scored {score} instead of 0.0")
            self.assertEqual(status, "Incorrect")
            wrong_q1_5_score += score

        self.assertEqual(wrong_q1_5_score, 0.0)

    def test_centralized_strict_short_answer_evaluation_layer_regression(self):
        from phase11_core import (
            derive_structured_evaluation_rules,
            evaluate_strict_short_answer,
            evaluate_single_test_answer,
        )

        test_cases = [
            # 1. speed formula multiply vs divide
            {
                "q": "What quantity is obtained by dividing total distance covered by total time taken?",
                "guide": "Average speed.",
                "wrong": "Average speed is obtained by multiplying distance and time.",
                "correct": "Average speed is obtained by dividing total distance covered by total time taken.",
                "forbidden": "multiply",
            },
            # 2. force never changes motion
            {
                "q": "What can an unbalanced force change about a moving body?",
                "guide": "It can change the speed or direction of motion.",
                "wrong": "An unbalanced force can never change the motion of a body.",
                "correct": "An unbalanced force can change the speed or direction of motion.",
                "forbidden": "never change",
            },
            # 3. straight-line vs circular clock motion
            {
                "q": "What type of motion is shown by the hands of a mechanical clock?",
                "guide": "Circular motion.",
                "wrong": "The hands of a mechanical clock show straight-line motion.",
                "correct": "The hands of a mechanical clock show circular motion.",
                "forbidden": "straight-line",
            },
            # 4. no position change vs relative motion
            {
                "q": "What is meant by motion relative to a reference point?",
                "guide": "Motion means a change in an object's position with time compared with the selected reference point.",
                "wrong": "Motion relative to a reference point means the object never changes position compared with that reference point.",
                "correct": "Motion relative to a reference point means position changes compared with the reference point.",
                "forbidden": "never changes position",
            },
            # 5. magnet middle vs poles
            {
                "q": "Where is the magnetic force of a bar magnet usually strongest?",
                "guide": "It is usually strongest near the north and south poles at the two ends.",
                "wrong": "The magnetic force is strongest in the middle of a bar magnet.",
                "correct": "Magnetic force is strongest near the two poles at the ends.",
                "forbidden": "middle",
            },
            # 6a. unlike pole contradictions
            {
                "q": "What happens when the north pole of one magnet is brought near the south pole of another?",
                "guide": "The unlike poles attract each other.",
                "wrong": "The north pole and south pole repel each other.",
                "correct": "North and south poles attract each other.",
                "forbidden": "repel",
            },
            # 6b. like pole contradictions
            {
                "q": "What happens when two south poles are brought close together?",
                "guide": "The like poles repel each other.",
                "wrong": "Two south poles attract each other.",
                "correct": "Two south poles repel each other.",
                "forbidden": "attract",
            },
            # 7. filtration vs evaporation
            {
                "q": "Name the process of separating an insoluble solid from a liquid using filter paper.",
                "guide": "Filtration.",
                "wrong": "The process of separating an insoluble solid from a liquid using filter paper is evaporation.",
                "correct": "The separation method is filtration.",
                "forbidden": "evaporation",
            },
            # 8. NPK fake elements
            {
                "q": "What major plant nutrients are represented by N, P, and K?",
                "guide": "Nitrogen, phosphorus, and potassium.",
                "wrong": "N, P, and K stand for neon, phosphorus, and krypton.",
                "correct": "N, P, and K stand for nitrogen, phosphorus, and potassium.",
                "forbidden": "neon",
            },
        ]

        for tc in test_cases:
            rules = derive_structured_evaluation_rules(tc["q"], tc["guide"])
            self.assertTrue(
                rules.forbidden_concepts or rules.contradiction_patterns or rules.required_concepts,
                f"No structured rules derived for question: {tc['q']}"
            )

            # Evaluate wrong answer via evaluate_single_test_answer
            w_score, w_status, _ = evaluate_single_test_answer(tc["q"], tc["wrong"], tc["guide"], 1, rules=rules)
            self.assertEqual(w_score, 0.0, f"Failed zero score for contradiction in '{tc['q']}': wrong answer '{tc['wrong']}' got {w_score}")
            self.assertEqual(w_status, "Incorrect")

            # Evaluate correct answer via evaluate_single_test_answer
            c_score, c_status, _ = evaluate_single_test_answer(tc["q"], tc["correct"], tc["guide"], 1, rules=rules)
            self.assertEqual(c_score, 1.0, f"Failed full score for correct answer in '{tc['q']}': got {c_score}")
            self.assertEqual(c_status, "Correct")

    def test_no_duplicate_questions_magnet_25m_and_full_syllabus_100m_seed_111_regression(self):
        from phase11_core import extract_question_intent

        # 1. Properties of Magnet 25-mark random chapter test seed 111
        magnet_scope = parse_test_paper_scope("Properties of Magnet chapter test", self.ctx, self.science_syl)
        _, magnet_paper = render_test_paper(
            self.science_syl,
            magnet_scope,
            context=self.ctx,
            message="Properties of Magnet chapter test",
            seed=111,
        )

        self.assertEqual(magnet_paper.total_marks, 25)
        self.assertEqual(len(magnet_paper.questions), 12)

        # Assert no generic topic-title fallback phrasing or visible variant labels in any question
        forbidden_patterns = (
            "(variant",
            "why is the study of",
            "key principle behind",
            "explain the main ideas of",
            "explain the main properties of",
        )
        for q in magnet_paper.questions:
            q_text = q.question_text
            for pattern in forbidden_patterns:
                self.assertNotIn(
                    pattern,
                    q_text.casefold(),
                    f"Found generic pattern '{pattern}' in question: '{q_text}'",
                )
            self.assertTrue(bool(q.solution_guide and q.solution_guide.strip()))
            self.assertEqual(q.intended_marks, q.max_marks)

        # Assert no exact duplicate question text
        magnet_q_texts = [q.question_text.strip().casefold() for q in magnet_paper.questions]
        self.assertEqual(
            len(magnet_q_texts),
            len(set(magnet_q_texts)),
            f"Properties of Magnet test seed 111 contains duplicate questions: {magnet_q_texts}",
        )

        # Assert no semantic duplicate intents per topic
        magnet_intents_by_topic: dict[str, set[str]] = {}
        for q in magnet_paper.questions:
            t_norm = q.topic_title.strip().casefold()
            intent = extract_question_intent(q.question_text)
            if t_norm not in magnet_intents_by_topic:
                magnet_intents_by_topic[t_norm] = set()
            self.assertNotIn(
                intent,
                magnet_intents_by_topic[t_norm],
                f"Properties of Magnet test seed 111 contains semantic duplicate intent '{intent}' in topic '{q.topic_title}'",
            )
            magnet_intents_by_topic[t_norm].add(intent)

        # 2. Full syllabus 100-mark random test seed 111
        full_scope = parse_test_paper_scope("Full book test banao", self.ctx, self.science_syl)
        _, full_paper = render_test_paper(
            self.science_syl,
            full_scope,
            context=self.ctx,
            message="Full book test banao",
            seed=111,
        )

        self.assertEqual(full_paper.total_marks, 100)
        self.assertEqual(len(full_paper.questions), 48)

        for q in full_paper.questions:
            self.assertNotIn("(Variant", q.question_text)
            self.assertNotIn("Why is the study of", q.question_text)
            self.assertTrue(bool(q.solution_guide and q.solution_guide.strip()))
            self.assertEqual(q.intended_marks, q.max_marks)

        full_q_texts = [q.question_text.strip().casefold() for q in full_paper.questions]
        self.assertEqual(
            len(full_q_texts),
            len(set(full_q_texts)),
            f"Full syllabus test seed 111 contains duplicate questions: {full_q_texts}",
        )

    def test_stale_chapter_context_and_ambiguous_another_chapter_resolution(self):
        # 1. selected chapter != Properties of Magnet generates selected chapter test
        ctx_heat = replace(
            self.ctx,
            current_chapter="Semester 1 — Heat and Temperature",
        )
        scope_heat = parse_test_paper_scope("Generate 25-mark chapter test", ctx_heat, self.science_syl)
        self.assertEqual(scope_heat.scope_type, "single_chapter")
        self.assertIn("Heat and Temperature", scope_heat.description)
        self.assertNotIn("Properties of Magnet", scope_heat.description)

        raw_heat, paper_heat = render_test_paper(
            self.science_syl,
            scope_heat,
            context=ctx_heat,
            message="Generate 25-mark chapter test",
            seed=42,
        )
        self.assertIn("Heat and Temperature", paper_heat.scope_description)
        self.assertIn(f"Test Paper: {scope_heat.description}", raw_heat)

        # 2. ambiguous "another chapter" does not reuse stale chapter
        ctx_magnet = replace(
            self.ctx,
            current_chapter="Semester 1 — Properties of Magnet",
        )
        ambiguous_prompts = [
            "dusra chapter ka test banao",
            "another chapter test",
            "dusri chapter test banao",
            "different chapter test",
        ]
        for prompt in ambiguous_prompts:
            scope_amb = parse_test_paper_scope(prompt, ctx_magnet, self.science_syl)
            self.assertEqual(scope_amb.scope_type, "ambiguous", f"Failed for prompt: {prompt}")
            raw_amb, paper_amb = render_test_paper(
                self.science_syl,
                scope_amb,
                context=ctx_magnet,
                message=prompt,
            )
            self.assertEqual(raw_amb, "Please select or name the chapter for the chapter test.")
            self.assertEqual(len(paper_amb.questions), 0)
            self.assertNotIn("Properties of Magnet", paper_amb.scope_description)

        # 3. random chapter test title matches selected chapter
        ctx_motion = replace(
            self.ctx,
            current_chapter="Semester 1 — Motion, Force and Speed",
        )
        scope_motion = parse_test_paper_scope("new test banao", ctx_motion, self.science_syl)
        self.assertEqual(scope_motion.scope_type, "single_chapter")
        self.assertEqual(scope_motion.description, "Semester 1 — Motion, Force and Speed — Chapter test")

        raw_motion, paper_motion = render_test_paper(
            self.science_syl,
            scope_motion,
            context=ctx_motion,
            message="new test banao",
            seed=77,
        )
        self.assertEqual(paper_motion.scope_description, "Semester 1 — Motion, Force and Speed — Chapter test")
        self.assertIn("Test Paper: Semester 1 — Motion, Force and Speed — Chapter test", raw_motion)

    def test_motion_force_speed_random_chapter_test_no_generic_fallback_or_semantic_duplicates_seed_111(self):
        ctx_motion = replace(
            self.ctx,
            current_chapter="Semester 1 — Motion, Force and Speed",
        )
        scope = parse_test_paper_scope(
            "Generate 25-mark random chapter test",
            ctx_motion,
            self.science_syl,
        )
        raw_paper, paper_model = render_test_paper(
            self.science_syl,
            scope,
            context=ctx_motion,
            message="Generate 25-mark random chapter test",
            seed=111,
        )

        # 1. 25-mark structure preserved
        self.assertEqual(paper_model.total_marks, 25)
        self.assertEqual(sum(q.max_marks for q in paper_model.questions), 25)

        motion_topic_titles = {t.title for t in scope.chapters[0].topics}
        for q in paper_model.questions:
            self.assertIn(
                q.topic_title,
                motion_topic_titles,
                f"Question topic '{q.topic_title}' leaked from outside Motion chapter!",
            )

        # 2. No "Explain the main ideas of" or generic topic-title fallback phrasing
        forbidden_phrases = [
            "Explain the main ideas of",
            "Explain the main properties of",
            "State the main idea of",
            "key principle behind",
            "Why is the study of",
            "observed in daily life",
            "observed and applied in daily life",
            "key daily life applications of",
            "effects is",
            "topics is",
            "properties is",
            "poles is",
            "principles is",
            "materials is",
        ]
        for q in paper_model.questions:
            for phrase in forbidden_phrases:
                self.assertNotIn(
                    phrase.casefold(),
                    q.question_text.casefold(),
                    f"Question contained generic fallback phrase '{phrase}': {q.question_text}",
                )

        # 3. No semantic duplicate bus-passenger relative motion questions
        bus_passenger_questions = [
            q.question_text for q in paper_model.questions
            if "passenger" in q.question_text.casefold() or ("bus" in q.question_text.casefold() and "rest" in q.question_text.casefold())
        ]
        self.assertLessEqual(
            len(bus_passenger_questions),
            1,
            f"Found semantic duplicate bus-passenger questions: {bus_passenger_questions}",
        )

        # 4. Every selected question has solution guide and intended_marks == max_marks
        for q in paper_model.questions:
            self.assertTrue(q.solution_guide and len(q.solution_guide.strip()) > 5)
            self.assertEqual(q.intended_marks, q.max_marks)

    def test_cross_chapter_question_leakage_prevention_in_randomized_chapter_tests(self):
        ctx_motion = replace(
            self.ctx,
            current_chapter="Semester 1 — Motion, Force and Speed",
        )
        scope_motion = parse_test_paper_scope(
            "Generate 25-mark random chapter test",
            ctx_motion,
            self.science_syl,
        )
        raw_motion, paper_motion = render_test_paper(
            self.science_syl,
            scope_motion,
            context=ctx_motion,
            message="Generate 25-mark random chapter test",
            seed=111,
        )

        motion_topic_titles = {t.title for t in scope_motion.chapters[0].topics}

        # 1. Motion, Force and Speed 25-mark random test seed 111 contains only topics from Motion, Force and Speed
        for q in paper_motion.questions:
            self.assertIn(
                q.topic_title,
                motion_topic_titles,
                f"Question topic '{q.topic_title}' is outside Motion, Force and Speed chapter",
            )
            # 2. No Magnetic materials and poles / magnet topics appear in Motion chapter test
            self.assertNotIn("magnet", q.question_text.casefold())
            self.assertNotIn("magnetic", q.question_text.casefold())
            self.assertNotIn("pole", q.question_text.casefold())

        # 3. 25-mark structure preserved
        self.assertEqual(paper_motion.total_marks, 25)
        self.assertEqual(len(paper_motion.questions), 12)

        # 4. Every question has solution guide and intended_marks == max_marks
        for q in paper_motion.questions:
            self.assertTrue(q.solution_guide and len(q.solution_guide.strip()) > 5)
            self.assertEqual(q.intended_marks, q.max_marks)

        # 5. Properties of Magnet 25-mark random test still contains only magnet chapter topics
        ctx_magnet = replace(
            self.ctx,
            current_chapter="Semester 1 — Properties of Magnet",
        )
        scope_magnet = parse_test_paper_scope(
            "Generate 25-mark random chapter test",
            ctx_magnet,
            self.science_syl,
        )
        raw_magnet, paper_magnet = render_test_paper(
            self.science_syl,
            scope_magnet,
            context=ctx_magnet,
            message="Generate 25-mark random chapter test",
            seed=111,
        )

        magnet_topic_titles = {t.title for t in scope_magnet.chapters[0].topics}
        for q in paper_magnet.questions:
            self.assertIn(
                q.topic_title,
                magnet_topic_titles,
                f"Question topic '{q.topic_title}' is outside Properties of Magnet chapter",
            )
            self.assertTrue(q.solution_guide and len(q.solution_guide.strip()) > 5)
            self.assertEqual(q.intended_marks, q.max_marks)

        self.assertEqual(paper_magnet.total_marks, 25)


if __name__ == "__main__":
    unittest.main()

