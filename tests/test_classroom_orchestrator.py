import unittest

from academy_core import (
    Academy,
    ClassroomSessionMemory,
    GoalStatus,
    InvalidLessonTransition,
    LearningGoal,
    LearningGoalManager,
    LessonStage,
    LessonStateMachine,
    LiveClassroomOrchestrator,
    RevisionNeed,
    StrategyKey,
    StudentAnalysis,
    TeacherReasoningEngine,
    TeachingStrategySelector,
    UnderstandingState,
    ConfidenceLevel,
)


def analysis(
    *,
    understanding=UnderstandingState.DEVELOPING,
    confidence=ConfidenceLevel.MEDIUM,
    revision=RevisionNeed.NONE,
):
    return StudentAnalysis(
        student_id="alin",
        class_level=7,
        preferred_language="auto",
        subject="maths",
        topic="fractions",
        confidence=confidence,
        understanding=understanding,
        revision_need=revision,
        recommended_teacher_subject="maths",
        recommended_methods=("guided_practice",),
        needs_prerequisite_check=False,
        should_ask_clarifying_question=False,
        evidence=(),
        safe_summary="temporary evidence",
    )


class ClassroomOrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.academy = Academy()
        self.engine = TeacherReasoningEngine()
        self.selector = TeachingStrategySelector()

    def plan(self, student_analysis):
        teacher = self.academy.route(subject="maths")
        decision = self.engine.decide(student_analysis, teacher)
        strategy = self.selector.select(student_analysis, decision)
        return teacher, decision, strategy

    def test_session_starts_at_session_start(self):
        teacher, decision, strategy = self.plan(analysis())
        orchestrator = LiveClassroomOrchestrator()
        session = orchestrator.start_session(
            student_id="alin",
            teacher_name=teacher.name,
            subject="maths",
            topic="fractions",
            strategy_key=strategy.primary.value,
        )
        self.assertEqual(session.stage, LessonStage.SESSION_START)

    def test_valid_state_transition(self):
        teacher, decision, strategy = self.plan(analysis())
        orchestrator = LiveClassroomOrchestrator()
        session = orchestrator.start_session(
            student_id="alin",
            teacher_name=teacher.name,
            subject="maths",
            topic="fractions",
        )
        result = orchestrator.advance(
            session.session_id,
            decision,
            strategy,
        )
        self.assertEqual(result.session.stage, LessonStage.GREETING)

    def test_invalid_state_transition_is_blocked(self):
        teacher, decision, strategy = self.plan(analysis())
        orchestrator = LiveClassroomOrchestrator()
        session = orchestrator.start_session(
            student_id="alin",
            teacher_name=teacher.name,
            subject="maths",
            topic="fractions",
        )
        with self.assertRaises(InvalidLessonTransition):
            LessonStateMachine().transition(
                session,
                LessonStage.HOMEWORK,
            )

    def test_full_lesson_reaches_complete(self):
        teacher, decision, strategy = self.plan(analysis())
        orchestrator = LiveClassroomOrchestrator()
        session = orchestrator.start_session(
            student_id="alin",
            teacher_name=teacher.name,
            subject="maths",
            topic="fractions",
        )
        sid = session.session_id

        for _ in range(9):
            current = orchestrator.memory.get(sid)
            result = orchestrator.advance(
                sid,
                decision,
                strategy,
                understanding_confirmed=True,
                homework_required=True,
                homework_id="hw1",
            )
            if result.session.stage == LessonStage.COMPLETE:
                break

        self.assertEqual(
            orchestrator.memory.get(sid).stage,
            LessonStage.COMPLETE,
        )

    def test_failed_understanding_routes_to_revision(self):
        teacher, decision, strategy = self.plan(analysis())
        orchestrator = LiveClassroomOrchestrator()
        session = orchestrator.start_session(
            student_id="alin",
            teacher_name=teacher.name,
            subject="maths",
            topic="fractions",
        )
        sid = session.session_id

        for _ in range(7):
            result = orchestrator.advance(
                sid,
                decision,
                strategy,
                understanding_confirmed=False,
            )
            if result.session.stage == LessonStage.REVISION:
                break

        self.assertEqual(
            orchestrator.memory.get(sid).stage,
            LessonStage.REVISION,
        )

    def test_progress_event_is_written(self):
        teacher, decision, strategy = self.plan(analysis())
        memory = ClassroomSessionMemory()
        orchestrator = LiveClassroomOrchestrator(memory=memory)
        session = orchestrator.start_session(
            student_id="alin",
            teacher_name=teacher.name,
            subject="maths",
            topic="fractions",
        )
        sid = session.session_id

        for _ in range(6):
            result = orchestrator.advance(
                sid,
                decision,
                strategy,
                understanding_confirmed=True,
            )
            if result.progress_events:
                break

        self.assertTrue(memory.progress_for(sid))

    def test_staff_notifications_emitted(self):
        teacher, decision, strategy = self.plan(analysis())
        orchestrator = LiveClassroomOrchestrator()
        session = orchestrator.start_session(
            student_id="alin",
            teacher_name=teacher.name,
            subject="maths",
            topic="fractions",
        )
        sid = session.session_id
        notifications = ()

        for _ in range(8):
            result = orchestrator.advance(
                sid,
                decision,
                strategy,
                understanding_confirmed=True,
            )
            if result.staff_notifications:
                notifications = result.staff_notifications
                break

        recipients = {item.recipient_role for item in notifications}
        self.assertIn("class_teacher", recipients)
        self.assertIn("principal", recipients)

    def test_session_audit_contains_stages_and_strategy(self):
        teacher, decision, strategy = self.plan(analysis())
        orchestrator = LiveClassroomOrchestrator()
        session = orchestrator.start_session(
            student_id="alin",
            teacher_name=teacher.name,
            subject="maths",
            topic="fractions",
            strategy_key=strategy.primary.value,
        )
        orchestrator.advance(
            session.session_id,
            decision,
            strategy,
        )
        audit = orchestrator.audit(session.session_id)
        self.assertTrue(audit.stages_visited)
        self.assertIn(strategy.primary.value, audit.strategies_used)

    def test_goal_completion_unlocks_next_goal(self):
        goals = LearningGoalManager(
            (
                LearningGoal(
                    goal_id="fractions",
                    subject="maths",
                    topic="fractions",
                    status=GoalStatus.ACTIVE,
                    evidence_required=1,
                ),
                LearningGoal(
                    goal_id="decimals",
                    subject="maths",
                    topic="decimals",
                    status=GoalStatus.LOCKED,
                    prerequisite_goal_ids=("fractions",),
                ),
            )
        )
        unlocked = goals.complete_goal("fractions", evidence_count=1)
        self.assertEqual(goals.get("fractions").status, GoalStatus.COMPLETED)
        self.assertIn("decimals", unlocked)
        self.assertEqual(goals.get("decimals").status, GoalStatus.ACTIVE)

    def test_goal_without_evidence_needs_revision(self):
        goals = LearningGoalManager(
            (
                LearningGoal(
                    goal_id="fractions",
                    subject="maths",
                    topic="fractions",
                    status=GoalStatus.ACTIVE,
                    evidence_required=2,
                ),
            )
        )
        goals.complete_goal("fractions", evidence_count=1)
        self.assertEqual(
            goals.get("fractions").status,
            GoalStatus.NEEDS_REVISION,
        )

    def test_complete_session_audit_serializes(self):
        teacher, decision, strategy = self.plan(analysis())
        orchestrator = LiveClassroomOrchestrator()
        session = orchestrator.start_session(
            student_id="alin",
            teacher_name=teacher.name,
            subject="maths",
            topic="fractions",
        )
        audit = orchestrator.audit(session.session_id)
        data = audit.to_dict()
        self.assertIsInstance(data["stages_visited"], list)
        self.assertIsInstance(data["outcome"], str)

    def test_completed_session_waits_for_new_lesson(self):
        teacher, decision, strategy = self.plan(analysis())
        orchestrator = LiveClassroomOrchestrator()
        session = orchestrator.start_session(
            student_id="alin",
            teacher_name=teacher.name,
            subject="maths",
            topic="fractions",
        )
        sid = session.session_id

        for _ in range(10):
            result = orchestrator.advance(
                sid,
                decision,
                strategy,
                understanding_confirmed=True,
            )
            if result.session.stage == LessonStage.COMPLETE:
                break

        final = orchestrator.advance(
            sid,
            decision,
            strategy,
            understanding_confirmed=True,
        )
        self.assertEqual(final.session.stage, LessonStage.COMPLETE)
        self.assertFalse(final.turn.should_write_memory)


if __name__ == "__main__":
    unittest.main()
