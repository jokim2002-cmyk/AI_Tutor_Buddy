from __future__ import annotations

from typing import Mapping

from .future_path import FuturePathAdvisor
from .guardian_models import (
    GuardianConversationResponse,
    GuardianProfile,
    StudentProgressSnapshot,
)
from .guardian_privacy import GuardianPrivacyPolicy
from .progress_reporting import GuardianReportBuilder


class GuardianLearningService:
    """Provides privacy-safe class-teacher and principal guardian conversations."""

    def __init__(
        self,
        *,
        snapshots: Mapping[str, StudentProgressSnapshot] | None = None,
        privacy_policy: GuardianPrivacyPolicy | None = None,
        report_builder: GuardianReportBuilder | None = None,
        future_path_advisor: FuturePathAdvisor | None = None,
    ) -> None:
        self.snapshots = dict(snapshots or {})
        self.privacy = privacy_policy or GuardianPrivacyPolicy()
        self.reports = report_builder or GuardianReportBuilder()
        self.future_paths = future_path_advisor or FuturePathAdvisor()

    def register_snapshot(self, snapshot: StudentProgressSnapshot) -> None:
        snapshot.validate()
        self.snapshots[snapshot.student_id] = snapshot

    def ask_class_teacher(
        self,
        guardian: GuardianProfile,
        student_id: str,
        question: str,
    ) -> GuardianConversationResponse:
        snapshot = self._authorized_snapshot(guardian, student_id)

        if self.privacy.sibling_comparison_requested(question):
            return GuardianConversationResponse(
                speaker_name="Asha Ma'am",
                speaker_role="Class Teacher",
                answer=self.privacy.comparison_safe_message(),
                comparison_blocked=True,
                audit_tags=("guardian_access", "comparison_blocked"),
            )

        report = self.reports.build_daily_report(
            snapshot,
            generated_by="Asha Ma'am",
        )
        answer = self._class_teacher_answer(question, report)

        return GuardianConversationResponse(
            speaker_name="Asha Ma'am",
            speaker_role="Class Teacher",
            answer=answer,
            report=report,
            audit_tags=("guardian_access", "daily_progress"),
        )

    def ask_principal(
        self,
        guardian: GuardianProfile,
        student_id: str,
        question: str,
    ) -> GuardianConversationResponse:
        snapshot = self._authorized_snapshot(guardian, student_id)

        if self.privacy.sibling_comparison_requested(question):
            return GuardianConversationResponse(
                speaker_name="Principal Arvind",
                speaker_role="Principal",
                answer=self.privacy.comparison_safe_message(),
                comparison_blocked=True,
                audit_tags=("guardian_access", "comparison_blocked"),
            )

        report = self.reports.build_daily_report(
            snapshot,
            generated_by="Principal Arvind",
        )
        future_path = self.future_paths.suggest(snapshot)
        answer = self._principal_answer(question, report, future_path)

        return GuardianConversationResponse(
            speaker_name="Principal Arvind",
            speaker_role="Principal",
            answer=answer,
            report=report,
            future_path=future_path,
            audit_tags=("guardian_access", "principal_overview"),
        )

    def _authorized_snapshot(
        self,
        guardian: GuardianProfile,
        student_id: str,
    ) -> StudentProgressSnapshot:
        self.privacy.assert_child_access(guardian, student_id)
        if student_id not in self.snapshots:
            raise KeyError(f"No progress snapshot found for student: {student_id}")
        return self.privacy.sanitize_for_guardian(self.snapshots[student_id])

    @staticmethod
    def _class_teacher_answer(question: str, report) -> str:
        text = question.lower()

        if "aaj" in text or "today" in text or "kya padha" in text:
            learned = "; ".join(report.learned_today) or "No completed activity recorded."
            return (
                f"Aaj {report.student_name} ne ye padha: {learned}. "
                f"Current strengths: {', '.join(report.current_strengths) or 'still gathering evidence'}. "
                f"Support needs: {', '.join(report.support_needs) or 'no urgent academic support identified'}."
            )

        if "weak" in text or "difficulty" in text or "support" in text:
            return (
                f"{report.student_name} ke current support areas: "
                f"{', '.join(report.support_needs) or 'no clear weakness should be labelled yet'}. "
                "Ye temporary learning evidence hai, permanent label nahi."
            )

        if "interest" in text or "pasand" in text:
            return (
                f"Current interest signals: "
                f"{', '.join(report.interest_signals) or 'more observation needed'}. "
                "Interest ko marks se alag samajhna zaroori hai."
            )

        return (
            f"{report.student_name} ka daily learning report ready hai. "
            "Main aaj ka learning, strengths, support needs, interests aur "
            "home-support actions explain kar sakti hoon."
        )

    @staticmethod
    def _principal_answer(question: str, report, future_path) -> str:
        text = question.lower()

        if (
            "future" in text
            or "career" in text
            or "engineering" in text
            or "doctor" in text
            or "path" in text
        ):
            return (
                f"{report.student_name} ke liye current exploration areas: "
                f"{', '.join(future_path.exploration_areas)}. "
                f"{future_path.caution}"
            )

        return (
            f"{report.student_name} ka broader overview: strengths—"
            f"{', '.join(report.current_strengths) or 'still gathering evidence'}; "
            f"interests—{', '.join(report.interest_signals) or 'still emerging'}; "
            f"support—{', '.join(report.support_needs) or 'no urgent gap identified'}. "
            "Future planning exploration-based rahegi, forced career decision nahi."
        )
