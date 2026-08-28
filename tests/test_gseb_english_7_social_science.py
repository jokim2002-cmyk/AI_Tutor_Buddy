from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

from phase11_ai import GyanVerseAIService
from phase11_core import (
    LearningMode,
    StudentLearningContext,
    SyllabusRepository,
    detect_context_from_message,
    evaluate_single_test_answer,
    parse_test_paper_scope,
    render_test_paper,
)


class Grade7SocialScienceSyllabusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project_root = Path(__file__).resolve().parents[1]
        cls.syllabus_dir = cls.project_root / "syllabus"
        cls.package_path = cls.syllabus_dir / "gseb-english-7-social-science.json"
        cls.repo = SyllabusRepository(cls.syllabus_dir)

    def service(self, *, api_key: str = "", repo: SyllabusRepository | None = None) -> GyanVerseAIService:
        if repo is None:
            repo = self.repo
        service = GyanVerseAIService(
            api_key=api_key,
            syllabus_repository=repo,
            tts_cache_dir=self.project_root / "tts",
        )
        if api_key:
            service._client = MagicMock()
        else:
            service._client = None
        return service

    def context(
        self,
        *,
        board: str = "GSEB",
        medium: str = "English",
        standard: int = 7,
        subject: str = "Social Science",
        chapter: str = "Semester 1 — Two Big States",
        topic: str = "Harshavardhana and the kingdom of Kanauj",
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

    # -------------------------------------------------------------------------
    # Gate 1: Syllabus package loads in UI selector & Repository
    # -------------------------------------------------------------------------
    def test_package_file_exists(self) -> None:
        self.assertTrue(
            self.package_path.exists(),
            f"Missing package file: {self.package_path}",
        )
        payload = json.loads(self.package_path.read_text(encoding="utf-8"))

        self.assertEqual(payload.get("board"), "GSEB")
        self.assertEqual(payload.get("medium"), "English")
        self.assertEqual(payload.get("standard"), 7)
        self.assertEqual(payload.get("subject"), "Social Science")

    def test_discoverable_through_repository(self) -> None:
        syllabus = self.repo.find(
            board="GSEB",
            medium="English",
            standard=7,
            subject="Social Science",
        )
        self.assertIsNotNone(syllabus, "Grade 7 Social Science package must be discoverable via SyllabusRepository")
        self.assertEqual(syllabus.key, "gseb-english-7-social-science")
        self.assertEqual(syllabus.subject, "Social Science")

    def test_ui_selector_loads_std7_social_science(self) -> None:
        syllabi = self.repo.all(board="GSEB")
        g7_eng = [s for s in syllabi if s.medium.casefold() == "english" and s.standard == 7]
        subjects = sorted({s.subject for s in g7_eng})
        self.assertIn("Social Science", subjects, "UI selector must include Social Science for GSEB English Standard 7")

        soc_syllabus = next(s for s in g7_eng if s.subject == "Social Science")
        self.assertEqual(len(soc_syllabus.chapters), 21, "Must have exactly 21 chapters")
        total_topics = sum(len(c.topics) for c in soc_syllabus.chapters)
        self.assertEqual(total_topics, 63, "Must have exactly 63 topics (3 per chapter)")

    def test_social_studies_alias_resolves_correctly(self) -> None:
        ctx = self.context(subject="Social Studies")
        updated_ctx, detected = detect_context_from_message("I need help with Social Studies", ctx, self.repo)
        self.assertEqual(updated_ctx.current_subject, "Social Science")
        self.assertEqual(detected.get("subject"), "Social Science")

    # -------------------------------------------------------------------------
    # Gate 2: Chapter explanation local reply
    # -------------------------------------------------------------------------
    def test_chapter_explanation_local_reply(self) -> None:
        service = self.service(api_key="")
        ctx = self.context(
            chapter="Semester 1 — Two Big States",
            topic="Harshavardhana and the kingdom of Kanauj",
        )
        ans = service.ask(
            message="Explain Harshavardhana and the kingdom of Kanauj",
            context=ctx,
        )
        self.assertIn("Teacher-authored content", ans)
        self.assertIn("harshavardhana ruled a large north indian kingdom", ans.lower())
        self.assertEqual(service.last_metrics.route, "local-syllabus")

    # -------------------------------------------------------------------------
    # Gate 3: Two examples local reply
    # -------------------------------------------------------------------------
    def test_every_topic_supports_two_examples_request(self) -> None:
        syllabus = self.repo.find(
            board="GSEB",
            medium="English",
            standard=7,
            subject="Social Science",
        )
        self.assertIsNotNone(syllabus)
        for chapter in syllabus.chapters:
            for topic in chapter.topics:
                self.assertTrue(
                    len(topic.examples) >= 2,
                    f"Topic '{topic.title}' in chapter '{chapter.title}' must contain at least 2 examples",
                )

    def test_chapter_level_two_examples_local_reply(self) -> None:
        service = self.service(api_key="")
        ctx = self.context(
            chapter="Semester 1 — Two Big States",
            topic="Harshavardhana and the kingdom of Kanauj",
        )
        ans = service.ask(
            message="Give me two examples of Harshavardhana's reign",
            context=ctx,
        )
        self.assertIn("Teacher-authored content", ans)
        self.assertIn("Kanauj became an important political centre", ans)
        self.assertEqual(service.last_metrics.route, "local-syllabus")

    # -------------------------------------------------------------------------
    # Gate 4: Hint-only behavior
    # -------------------------------------------------------------------------
    def test_exact_question_supports_private_actionable_hint(self) -> None:
        service = self.service(api_key="")
        ctx = self.context(
            chapter="Semester 1 — Two Big States",
            topic="Harshavardhana and the kingdom of Kanauj",
        )
        hint_response = service.ask(
            message="Give me a hint for the question: Which ruler stopped Harshavardhana's expansion towards the Deccan?",
            context=ctx,
        )
        self.assertIn("Hint", hint_response)
        self.assertNotIn("Pulakeshin II", hint_response)
        self.assertEqual(service.last_metrics.route, "local-syllabus")

    # -------------------------------------------------------------------------
    # Gate 5: Answer review grounding
    # -------------------------------------------------------------------------
    def test_deterministic_answer_reviews_marked_locally(self) -> None:
        service = self.service(api_key="mock-key")
        ctx = self.context(
            chapter="Semester 1 — Two Big States",
            topic="Harshavardhana and the kingdom of Kanauj",
        )

        with patch.object(
            GyanVerseAIService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ):
            correct = service.ask_stream(
                message="Question: Which ruler stopped Harshavardhana's expansion towards the Deccan? My answer: Pulakeshin II of the Chalukya dynasty stopped Harshavardhana near the Narmada. Is my answer correct?",
                context=ctx,
            )
            self.assertIn("Result: Correct.", correct)
            self.assertEqual(service.last_metrics.route, "local-syllabus")

            wrong = service.ask_stream(
                message="Question: Which ruler stopped Harshavardhana's expansion towards the Deccan? My answer: Chandragupta Maurya. Is my answer correct?",
                context=ctx,
            )
            self.assertIn("Result: Incorrect.", wrong)
            self.assertEqual(service.last_metrics.route, "local-syllabus")

    # -------------------------------------------------------------------------
    # Gate 6: 25-mark chapter random test generation
    # -------------------------------------------------------------------------
    def test_std7_social_science_25_mark_chapter_random_test_generation(self) -> None:
        syllabus = self.repo.find(board="GSEB", medium="English", standard=7, subject="Social Science")
        self.assertIsNotNone(syllabus)
        ctx = self.context(chapter="Semester 1 — Two Big States")
        scope = parse_test_paper_scope("Semester 1 — Two Big States 25 marks test seed 111", ctx, syllabus)

        raw, paper = render_test_paper(
            syllabus,
            scope,
            seed=111,
            context=ctx,
            message="Semester 1 — Two Big States 25 marks test seed 111",
        )

        self.assertEqual(paper.total_marks, 25)
        self.assertEqual(paper.standard, 7)
        self.assertEqual(paper.subject, "Social Science")
        self.assertTrue(len(paper.questions) >= 5)

        # Check section allocation: 5x1m, 4x2m, 2x3m, 1x6m = 25m
        sec_a = [q for q in paper.questions if "Section A" in q.section_title]
        sec_b = [q for q in paper.questions if "Section B" in q.section_title]
        sec_c = [q for q in paper.questions if "Section C" in q.section_title]
        sec_d = [q for q in paper.questions if "Section D" in q.section_title]

        self.assertEqual(len(sec_a), 5, "Section A must have 5 1-mark questions")
        self.assertEqual(len(sec_b), 4, "Section B must have 4 2-mark questions")
        self.assertEqual(len(sec_c), 2, "Section C must have 2 3-mark questions")
        self.assertEqual(len(sec_d), 1, "Section D must have 1 6-mark question")
        self.assertNotIn("What was the capital", sec_d[0].question_text)
        self.assertEqual(sec_d[0].intended_marks, 6)
        self.assertEqual(sec_d[0].max_marks, 6)

    # -------------------------------------------------------------------------
    # Gate 7: Full syllabus 100-mark random test generation
    # -------------------------------------------------------------------------
    def test_std7_social_science_100_mark_full_syllabus_random_test_generation(self) -> None:
        syllabus = self.repo.find(board="GSEB", medium="English", standard=7, subject="Social Science")
        self.assertIsNotNone(syllabus)
        ctx = self.context()
        scope = parse_test_paper_scope("Full book ka 3 hour 100 marks test seed 111", ctx, syllabus)

        raw, paper = render_test_paper(
            syllabus,
            scope,
            seed=111,
            context=ctx,
            message="Full book ka 3 hour 100 marks test seed 111",
        )

        self.assertEqual(paper.total_marks, 100)
        self.assertEqual(paper.duration_minutes, 180)
        self.assertEqual(paper.standard, 7)
        self.assertEqual(paper.subject, "Social Science")
        self.assertIn("Standard 7 Social Science", paper.source_footer)

        total_q_marks = sum(q.max_marks for q in paper.questions)
        self.assertEqual(total_q_marks, 100)

    # -------------------------------------------------------------------------
    # Gate 8: Active generated paper answer evaluation
    # -------------------------------------------------------------------------
    def test_active_generated_paper_answer_evaluation(self) -> None:
        service = self.service(api_key="")
        ctx = self.context(chapter="Semester 1 — Two Big States")

        gen_resp = service.ask(
            message="Generate a 25 marks random chapter test for Two Big States seed 111",
            context=ctx,
        )
        self.assertIn("Chapter test", gen_resp)
        self.assertEqual(service.last_metrics.route, "local-syllabus")

        paper = service._last_generated_test_paper
        self.assertIsNotNone(paper)

        # Submit answers for first 2 questions
        sub_ans1 = paper.questions[0].solution_guide
        sub_ans2 = paper.questions[1].solution_guide
        submission = f"Q1: {sub_ans1}\nQ2: {sub_ans2}"

        eval_resp = service.ask_stream(
            message=f"Check my test answers:\n{submission}",
            context=ctx,
        )
        self.assertIn("Test Evaluation", eval_resp)
        self.assertIn("Q1", eval_resp)
        self.assertIn("Correct", eval_resp)

    # -------------------------------------------------------------------------
    # Gate 9: Wrong-answer guard sanity tests
    # -------------------------------------------------------------------------
    def test_wrong_answer_guard_sanity(self) -> None:
        q_text = "Which ruler stopped Harshavardhana's expansion towards the Deccan?"
        guide = "Pulakeshin II of the Chalukya dynasty stopped Harshavardhana near the Narmada."

        # Correct answer
        c_score, c_status, _ = evaluate_single_test_answer(q_text, "Pulakeshin II of the Chalukya dynasty", guide, 1)
        self.assertEqual(c_score, 1.0)
        self.assertEqual(c_status, "Correct")

        # Completely wrong answer
        w_score, w_status, _ = evaluate_single_test_answer(q_text, "Ashoka the Great", guide, 1)
        self.assertEqual(w_score, 0.0)
        self.assertEqual(w_status, "Incorrect")

    def test_chalukya_cultural_achievement_short_answer_evaluation(self) -> None:
        q_text = "Name one cultural achievement linked with the Chalukya period."
        guide = "Rock-cut caves, temples, sculpture and painting developed during the period; any one suitable example is acceptable."

        # Correct student answer mentioning temples / architecture / cave art
        c_score, c_status, _ = evaluate_single_test_answer(
            q_text,
            "Architecture such as temples or cave art was a cultural achievement of the Chalukya period.",
            guide,
            1,
        )
        self.assertEqual(c_score, 1.0)
        self.assertEqual(c_status, "Correct")

        # Wrong answer
        w_score, w_status, _ = evaluate_single_test_answer(
            q_text,
            "Pulakeshin II fought Harsha",
            guide,
            1,
        )
        self.assertEqual(w_score, 0.0)
        self.assertEqual(w_status, "Incorrect")

    # -------------------------------------------------------------------------
    # Gate 10: No generic fallback questions
    # -------------------------------------------------------------------------
    def test_no_generic_fallback_questions(self) -> None:
        syllabus = self.repo.find(board="GSEB", medium="English", standard=7, subject="Social Science")
        self.assertIsNotNone(syllabus)
        ctx = self.context(chapter="Semester 1 — Two Big States")
        scope = parse_test_paper_scope("Semester 1 — Two Big States 25 marks test seed 111", ctx, syllabus)

        _, paper = render_test_paper(
            syllabus,
            scope,
            seed=111,
            context=ctx,
            message="Semester 1 — Two Big States 25 marks test seed 111",
        )

        generic_phrases = [
            "State one key concept from your textbook",
            "What is the primary significance of this topic",
            "Explain the core principle behind this topic",
        ]

        for q in paper.questions:
            for phrase in generic_phrases:
                self.assertNotIn(
                    phrase,
                    q.question_text,
                    f"Question #{q.question_num} contains generic fallback phrase: '{phrase}'",
                )

    # -------------------------------------------------------------------------
    # Gate 11: No cross-chapter leakage
    # -------------------------------------------------------------------------
    def test_no_cross_chapter_leakage_in_single_chapter_tests(self) -> None:
        syllabus = self.repo.find(board="GSEB", medium="English", standard=7, subject="Social Science")
        self.assertIsNotNone(syllabus)
        ctx = self.context(chapter="Semester 1 — Two Big States")
        scope = parse_test_paper_scope("Semester 1 — Two Big States 25 marks test seed 111", ctx, syllabus)

        _, paper = render_test_paper(
            syllabus,
            scope,
            seed=111,
            context=ctx,
            message="Semester 1 — Two Big States 25 marks test seed 111",
        )

        selected_chapter = next(c for c in syllabus.chapters if c.title == "Semester 1 — Two Big States")
        allowed_topics = {t.title for t in selected_chapter.topics}

        # Out-of-chapter topic indicators to strictly check against leakage
        forbidden_topic_terms = [
            "Motions of the Earth",
            "Rotation and Revolution",
            "Rajput Age",
            "Mughal Empire",
            "Courts and their Importance",
            "Delhi during the Medieval Period",
            "Continents: North and South America",
        ]

        for q in paper.questions:
            self.assertIn(
                q.topic_title,
                allowed_topics,
                f"Question #{q.question_num} topic '{q.topic_title}' leaks from another chapter!",
            )
            for forbidden_term in forbidden_topic_terms:
                self.assertNotIn(
                    forbidden_term,
                    q.question_text,
                    f"Question #{q.question_num} contains leaked out-of-chapter content: '{forbidden_term}'",
                )

    # -------------------------------------------------------------------------
    # Gate 12: Two Big States Section D 6-mark Question Depth & Intended Marks
    # -------------------------------------------------------------------------
    def test_two_big_states_section_d_6mark_depth(self) -> None:
        syllabus = self.repo.find(board="GSEB", medium="English", standard=7, subject="Social Science")
        self.assertIsNotNone(syllabus)
        ctx = self.context(chapter="Semester 1 — Two Big States")
        scope = parse_test_paper_scope("Semester 1 — Two Big States 25 marks test seed 111", ctx, syllabus)

        raw, paper = render_test_paper(
            syllabus,
            scope,
            seed=111,
            context=ctx,
            message="Semester 1 — Two Big States 25 marks test seed 111",
        )

        self.assertEqual(paper.total_marks, 25)
        sec_d = [q for q in paper.questions if "Section D" in q.section_title]
        self.assertEqual(len(sec_d), 1, "Section D must contain exactly 1 6-mark question")
        q_6m = sec_d[0]

        # 1. Section D must not contain "What was the capital..." or short factual recall prompts
        self.assertNotIn("What was the capital", q_6m.question_text)
        factual_prefixes = ("What was", "Who was", "Name", "Give one", "Which")
        for prefix in factual_prefixes:
            self.assertFalse(
                q_6m.question_text.startswith(prefix),
                f"Section D question '{q_6m.question_text}' starts with factual recall prompt '{prefix}'",
            )

        # 2. Section D must contain a long-answer Social Science question
        self.assertTrue(
            any(q_6m.question_text.startswith(p) for p in ("Describe", "Explain")),
            f"Section D question '{q_6m.question_text}' is not a long-answer prompt",
        )

        # 3. Intended marks and max_marks must be 6
        self.assertEqual(q_6m.max_marks, 6)
        self.assertEqual(q_6m.intended_marks, 6)

        # 4. No generic fallback phrases
        for generic in ("scientific principles", "generic concept"):
            self.assertNotIn(generic, q_6m.question_text.lower())

        # 5. 25-mark total preserved across paper
        total_m = sum(q.max_marks for q in paper.questions)
        self.assertEqual(total_m, 25)


if __name__ == "__main__":
    unittest.main()
