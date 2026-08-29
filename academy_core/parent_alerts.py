from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Tuple

from .parent_reporting_models import (
    AlertSeverity,
    LearningReportInput,
    ParentAlert,
)


class ParentAlertPolicy:
    """Creates minimal, evidence-based alerts without exposing sensitive notes."""

    def build_alerts(
        self,
        guardian_id: str,
        report_input: LearningReportInput,
    ) -> Tuple[ParentAlert, ...]:
        alerts = []
        now = datetime.now(timezone.utc).isoformat()

        if report_input.safety_flags:
            alerts.append(
                self._make(
                    guardian_id,
                    report_input.student_id,
                    AlertSeverity.URGENT,
                    "Student support needs attention",
                    (
                        "A safety-related signal requires review by an authorized adult "
                        "or school safeguarding process. Private conversation details "
                        "are not included here."
                    ),
                    "Contact the designated school safeguarding person promptly.",
                    now,
                    safety_related=True,
                )
            )

        if (
            report_input.readiness_score is not None
            and report_input.readiness_score < 0.45
            and (report_input.evidence_confidence or 0.0) >= 0.5
        ):
            alerts.append(
                self._make(
                    guardian_id,
                    report_input.student_id,
                    AlertSeverity.ATTENTION,
                    "Revision support recommended",
                    "Current evidence suggests important topics need structured revision.",
                    "Follow the revision plan and ask the teacher which prerequisite to begin with.",
                    now,
                )
            )

        if report_input.sessions_completed == 0 and report_input.learning_minutes == 0:
            alerts.append(
                self._make(
                    guardian_id,
                    report_input.student_id,
                    AlertSeverity.INFORMATIONAL,
                    "No learning activity recorded",
                    "No completed learning session was recorded for this reporting period.",
                    "Check whether the student studied offline or needs help restarting the routine.",
                    now,
                )
            )

        return tuple(alerts)

    @staticmethod
    def _make(
        guardian_id: str,
        student_id: str,
        severity: AlertSeverity,
        title: str,
        message: str,
        action: str,
        created_at: str,
        safety_related: bool = False,
    ) -> ParentAlert:
        raw = f"{guardian_id}|{student_id}|{severity.value}|{title}|{created_at}"
        alert_id = "alert_" + sha256(raw.encode("utf-8")).hexdigest()[:16]
        return ParentAlert(
            alert_id=alert_id,
            guardian_id=guardian_id,
            student_id=student_id,
            severity=severity,
            title=title,
            message=message,
            recommended_action=action,
            created_at=created_at,
            safety_related=safety_related,
        )
