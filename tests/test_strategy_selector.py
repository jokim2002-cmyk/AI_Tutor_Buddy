import unittest

from academy_core import (
    Academy,
    ConfidenceLevel,
    DifficultyDirection,
    RevisionNeed,
    StepSize,
    StrategyKey,
    StudentAnalysis,
    TeacherReasoningEngine,
    TeachingAction,
    TeachingStrategySelector,
    TeachingStrategyService,
    UnderstandingState,
    all_strategies,
)


def make_analysis(
    *,
    subject="maths",
    topic="fractions",
    confidence=ConfidenceLevel.MEDIUM,
    understanding=UnderstandingState.DEVELOPING,
    revision=RevisionNeed.NONE,
    prerequisite=False,
    clarify=False,
    methods=("guided_practice",),
):
    return StudentAnalysis(
        student_id="s1",
        class_level=7,
        preferred_language="auto",
        subject=subject,
        topic=topic,
        confidence=confidence,
        understanding=understanding,
        revision_need=revision,
        recommended_teacher_subject=subject or "class_guidance",
        recommended_methods=methods,
        needs_prerequisite_check=prerequisite,
        should_ask_clarifying_question=clarify,
        evidence=(),
        safe_summary="temporary evidence",
    )


class TeachingStrategySelectorTests(unittest.TestCase):
    def setUp(self):
        self.academy = Academy()
        self.engine = TeacherReasoningEngine()
        self.selector = TeachingStrategySelector()

    def decision(self, analysis, **kwargs):
        teacher = self.academy.route(subject=analysis.subject)
        return self.engine.decide(analysis, teacher, **kwargs)

    def test_catalog_contains_expected_strategies(self):
        keys = {item.key for item in all_strategies()}
        self.assertIn(StrategyKey.STEP_BY_STEP, keys)
        self.assertIn(StrategyKey.OBSERVATION_EXPERIMENT, keys)
        self.assertIn(StrategyKey.DEBUGGING, keys)

    def test_low_confidence_confusion_selects_step_by_step(self):
        analysis = make_analysis(
            confidence=ConfidenceLevel.LOW,
            understanding=UnderstandingState.CONFUSED,
            prerequisite=True,
        )
        selection = self.selector.select(analysis, self.decision(analysis))
        self.assertEqual(selection.primary, StrategyKey.STEP_BY_STEP)
        self.assertIn(StrategyKey.CONFIDENCE_REBUILD, selection.supporting)
        self.assertIn(StrategyKey.TRANSFER_CHALLENGE, selection.avoid)

    def test_science_prefers_observation_for_extension(self):
        analysis = make_analysis(
            subject="science",
            topic="force",
            confidence=ConfidenceLevel.HIGH,
            understanding=UnderstandingState.UNDERSTOOD,
        )
        decision = self.decision(analysis, lesson_has_started=True)
        selection = self.selector.select(analysis, decision)
        self.assertEqual(decision.action, TeachingAction.EXTEND)
        self.assertIn(
            selection.primary,
            {StrategyKey.OBSERVATION_EXPERIMENT, StrategyKey.TRANSFER_CHALLENGE},
        )

    def test_computer_guided_practice_prefers_debugging(self):
        analysis = make_analysis(
            subject="computer",
            topic="loops",
            understanding=UnderstandingState.DEVELOPING,
        )
        selection = self.selector.select(analysis, self.decision(analysis))
        self.assertEqual(selection.primary, StrategyKey.DEBUGGING)

    def test_language_subject_uses_communication_practice(self):
        analysis = make_analysis(
            subject="english",
            topic="spoken introduction",
            understanding=UnderstandingState.DEVELOPING,
        )
        selection = self.selector.select(analysis, self.decision(analysis))
        self.assertEqual(selection.primary, StrategyKey.COMMUNICATION_PRACTICE)

    def test_social_science_uses_timeline_cause_effect(self):
        analysis = make_analysis(
            subject="social_science",
            topic="revolt of 1857",
            understanding=UnderstandingState.CONFUSED,
        )
        selection = self.selector.select(analysis, self.decision(analysis))
        self.assertEqual(selection.primary, StrategyKey.TIMELINE_CAUSE_EFFECT)

    def test_student_visual_preference_affects_ranking(self):
        analysis = make_analysis(
            subject="science",
            topic="cell structure",
            understanding=UnderstandingState.CONFUSED,
        )
        selection = self.selector.select(
            analysis,
            self.decision(analysis),
            student_preferences=("visual",),
        )
        ranked = [item.key for item in selection.scores]
        self.assertIn(StrategyKey.VISUAL_EXPLANATION, ranked[:3])

    def test_recent_strategy_gets_variety_penalty(self):
        analysis = make_analysis(
            subject="maths",
            understanding=UnderstandingState.CONFUSED,
        )
        without_history = self.selector.select(analysis, self.decision(analysis))
        with_history = self.selector.select(
            analysis,
            self.decision(analysis),
            prior_strategy_keys=(without_history.primary, without_history.primary),
        )
        score_without = next(
            item.score for item in without_history.scores
            if item.key == without_history.primary
        )
        score_with = next(
            item.score for item in with_history.scores
            if item.key == without_history.primary
        )
        self.assertLess(score_with, score_without)

    def test_selection_serializes(self):
        analysis = make_analysis()
        selection = self.selector.select(analysis, self.decision(analysis))
        data = selection.to_dict()
        self.assertIsInstance(data["primary"], str)
        self.assertIsInstance(data["supporting"], list)
        self.assertTrue(data["scores"])

    def test_scores_are_valid_and_explainable(self):
        analysis = make_analysis()
        selection = self.selector.select(analysis, self.decision(analysis))
        for item in selection.scores:
            item.validate()
            self.assertTrue(item.reasons)

    def test_service_combines_reasoning_and_strategy(self):
        analysis = make_analysis(
            subject="maths",
            confidence=ConfidenceLevel.LOW,
            understanding=UnderstandingState.CONFUSED,
            prerequisite=True,
        )
        lesson = TeachingStrategyService().prepare(analysis)
        self.assertEqual(
            lesson.reasoned_lesson.decision.step_size,
            StepSize.VERY_SMALL,
        )
        self.assertEqual(
            lesson.reasoned_lesson.decision.difficulty_direction,
            DifficultyDirection.REDUCE,
        )
        self.assertEqual(lesson.strategy.primary, StrategyKey.STEP_BY_STEP)

    def test_final_answer_policy_is_preserved(self):
        analysis = make_analysis(
            confidence=ConfidenceLevel.LOW,
            understanding=UnderstandingState.GUESSING,
        )
        lesson = TeachingStrategyService().prepare(
            analysis,
            student_requested_final_answer=True,
        )
        self.assertFalse(
            lesson.reasoned_lesson.decision.reveal_final_answer_immediately
        )
        self.assertNotEqual(
            lesson.strategy.primary,
            StrategyKey.TRANSFER_CHALLENGE,
        )


if __name__ == "__main__":
    unittest.main()
