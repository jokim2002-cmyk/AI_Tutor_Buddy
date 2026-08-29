from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Dict, Tuple

from .guardian_models import GuardianProfile
from .guardian_privacy import GuardianPrivacyPolicy
from .home_support_planner import HomeSupportPlanner
from .parent_alerts import ParentAlertPolicy
from .parent_report_repository import ParentReportRepository
from .parent_reporting_models import (
    ChildDashboardCard,
    LearningReportInput,
    ParentDashboard,
    ParentProgressReport,
    ParentReportPreferences,
    ReportPeriod,
)


class ParentMonitoringService:
    """Guardian-authorized report generation, history, dashboard, and safe alerts."""

    def __init__(
        self,
        *,
        repository: ParentReportRepository | None = None,
        privacy_policy: GuardianPrivacyPolicy | None = None,
        home_support_planner: HomeSupportPlanner | None = None,
        alert_policy: ParentAlertPolicy | None = None,
    ) -> None:
        self.repository = repository or ParentReportRepository()
        self.privacy = privacy_policy or GuardianPrivacyPolicy()
        self.home_support = home_support_planner or HomeSupportPlanner()
        self.alerts = alert_policy or ParentAlertPolicy()
        self._preferences: Dict[str, ParentReportPreferences] = {}

    def set_preferences(self, preferences: ParentReportPreferences) -> None:
        preferences.validate()
        self._preferences[preferences.guardian_id] = preferences

    def get_preferences(self, guardian_id: str) -> ParentReportPreferences:
        return self._preferences.get(
            guardian_id,
            ParentReportPreferences(guardian_id=guardian_id),
        )

    def generate_report(
        self,
        guardian: GuardianProfile,
        report_input: LearningReportInput,
        period: ReportPeriod,
    ) -> ParentProgressReport:
        guardian.validate()
        report_input.validate()
        self.privacy.assert_child_access(guardian, report_input.student_id)
        preferences = self.get_preferences(guardian.guardian_id)

        if period not in preferences.enabled_periods:
            raise PermissionError(f"{period.value} reports are disabled")

        now = datetime.now(timezone.utc).isoformat()
        report_id = self._report_id(guardian.guardian_id, report_input, period, now)
        readiness_summary, uncertainty = self._readiness_text(
            report_input,
            include=preferences.include_exam_readiness,
        )
        support_actions = (
            self.home_support.build(report_input)
            if preferences.include_home_support
            else ()
        )

        report = ParentProgressReport(
            report_id=report_id,
            guardian_id=guardian.guardian_id,
            student_id=report_input.student_id,
            student_name=report_input.student_name,
            period=period,
            period_start=report_input.period_start,
            period_end=report_input.period_end,
            headline=self._headline(report_input, period),
            learning_summary=self._learning_summary(report_input),
            strengths=tuple(report_input.strengths),
            support_areas=tuple(report_input.support_areas),
            interest_signals=tuple(report_input.interests),
            home_support_actions=tuple(support_actions),
            readiness_summary=readiness_summary,
            readiness_uncertainty=uncertainty,
            wellbeing_note=(
                "Progress should be discussed without pressure, shame, or comparison."
            ),
            privacy_notice=(
                "Sensitive student notes are excluded. This report contains temporary "
                "learning evidence, not permanent labels or deterministic predictions."
            ),
            generated_at=now,
        )
        self.repository.save_report(report)

        for alert in self.alerts.build_alerts(guardian.guardian_id, report_input):
            self.repository.save_alert(alert)

        return report

    def dashboard(self, guardian: GuardianProfile) -> ParentDashboard:
        guardian.validate()
        cards = []
        for child_id in guardian.child_ids:
            reports = self.repository.list_reports(
                guardian.guardian_id, student_id=child_id
            )
            alerts = self.repository.list_alerts(
                guardian.guardian_id, student_id=child_id, open_only=True
            )
            latest = reports[0] if reports else None
            cards.append(
                ChildDashboardCard(
                    student_id=child_id,
                    student_name=latest.student_name if latest else child_id,
                    latest_headline=(
                        latest.headline if latest else "No report generated yet"
                    ),
                    strengths=latest.strengths if latest else (),
                    support_areas=latest.support_areas if latest else (),
                    readiness_summary=(
                        latest.readiness_summary
                        if latest
                        else "Readiness evidence not available"
                    ),
                    open_alert_count=len(alerts),
                    latest_report_id=latest.report_id if latest else None,
                )
            )
        return ParentDashboard(
            guardian_id=guardian.guardian_id,
            children=tuple(cards),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    def _report_id(
        guardian_id: str,
        report_input: LearningReportInput,
        period: ReportPeriod,
        generated_at: str,
    ) -> str:
        raw = (
            f"{guardian_id}|{report_input.student_id}|{period.value}|"
            f"{report_input.period_start}|{report_input.period_end}|{generated_at}"
        )
        return "report_" + sha256(raw.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _learning_summary(report_input: LearningReportInput) -> Tuple[str, ...]:
        summary = list(report_input.completed_topics)
        if report_input.sessions_completed:
            summary.append(
                f"{report_input.sessions_completed} learning session(s) completed"
            )
        if report_input.learning_minutes:
            summary.append(f"{report_input.learning_minutes} learning minutes recorded")
        return tuple(summary) or ("No completed learning activity recorded.",)

    @staticmethod
    def _headline(
        report_input: LearningReportInput,
        period: ReportPeriod,
    ) -> str:
        if report_input.completed_topics:
            return (
                f"{report_input.student_name} made {period.value} progress across "
                f"{len(report_input.completed_topics)} topic(s)."
            )
        return (
            f"{report_input.student_name}'s {period.value} report needs more learning evidence."
        )

    @staticmethod
    def _readiness_text(
        report_input: LearningReportInput,
        *,
        include: bool,
    ) -> Tuple[str, str]:
        if not include:
            return "Exam readiness sharing is disabled.", ""
        if report_input.readiness_score is None:
            return (
                "Exam readiness cannot yet be estimated.",
                "More learning and assessment evidence is required.",
            )
        confidence = report_input.evidence_confidence or 0.0
        score_pct = round(report_input.readiness_score * 100)
        band = (report_input.readiness_band or "evidence-based estimate").replace("_", " ")
        return (
            f"Current readiness estimate: {score_pct}% ({band}).",
            (
                "Evidence confidence is limited; treat this as guidance, not prediction."
                if confidence < 0.6
                else "This remains a non-deterministic estimate based on current evidence."
            ),
        )
