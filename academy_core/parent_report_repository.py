from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Tuple

from .parent_reporting_models import (
    ParentAlert,
    ParentProgressReport,
    ReportHistoryEntry,
)


class ParentReportRepository:
    """In-memory persistence boundary for parent reports, preferences, and alerts."""

    def __init__(self) -> None:
        self._reports: Dict[str, ParentProgressReport] = {}
        self._report_ids_by_guardian: Dict[str, List[str]] = defaultdict(list)
        self._alerts: Dict[str, ParentAlert] = {}
        self._alert_ids_by_guardian: Dict[str, List[str]] = defaultdict(list)

    def save_report(self, report: ParentProgressReport) -> None:
        self._reports[report.report_id] = report
        ids = self._report_ids_by_guardian[report.guardian_id]
        if report.report_id not in ids:
            ids.append(report.report_id)

    def get_report(self, report_id: str) -> ParentProgressReport:
        try:
            return self._reports[report_id]
        except KeyError as exc:
            raise KeyError(f"Unknown report: {report_id}") from exc

    def list_reports(
        self,
        guardian_id: str,
        *,
        student_id: str | None = None,
    ) -> Tuple[ParentProgressReport, ...]:
        reports = [
            self._reports[report_id]
            for report_id in self._report_ids_by_guardian.get(guardian_id, [])
        ]
        if student_id is not None:
            reports = [report for report in reports if report.student_id == student_id]
        return tuple(sorted(reports, key=lambda item: item.generated_at, reverse=True))

    def history(
        self,
        guardian_id: str,
        *,
        student_id: str | None = None,
    ) -> Tuple[ReportHistoryEntry, ...]:
        return tuple(
            ReportHistoryEntry(
                report_id=report.report_id,
                guardian_id=report.guardian_id,
                student_id=report.student_id,
                period=report.period,
                period_start=report.period_start,
                period_end=report.period_end,
                generated_at=report.generated_at,
                headline=report.headline,
            )
            for report in self.list_reports(guardian_id, student_id=student_id)
        )

    def save_alert(self, alert: ParentAlert) -> None:
        self._alerts[alert.alert_id] = alert
        ids = self._alert_ids_by_guardian[alert.guardian_id]
        if alert.alert_id not in ids:
            ids.append(alert.alert_id)

    def list_alerts(
        self,
        guardian_id: str,
        *,
        student_id: str | None = None,
        open_only: bool = False,
    ) -> Tuple[ParentAlert, ...]:
        alerts = [
            self._alerts[alert_id]
            for alert_id in self._alert_ids_by_guardian.get(guardian_id, [])
        ]
        if student_id is not None:
            alerts = [alert for alert in alerts if alert.student_id == student_id]
        if open_only:
            alerts = [alert for alert in alerts if not alert.acknowledged]
        return tuple(sorted(alerts, key=lambda item: item.created_at, reverse=True))

    def acknowledge_alert(self, alert_id: str) -> ParentAlert:
        from dataclasses import replace
        if alert_id not in self._alerts:
            raise KeyError(f"Unknown alert: {alert_id}")
        updated = replace(self._alerts[alert_id], acknowledged=True)
        self._alerts[alert_id] = updated
        return updated
