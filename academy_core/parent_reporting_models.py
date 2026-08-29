from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Dict, Tuple


class ReportPeriod(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class AlertSeverity(str, Enum):
    INFORMATIONAL = "informational"
    ATTENTION = "attention"
    URGENT = "urgent"


class DeliveryChannel(str, Enum):
    IN_APP = "in_app"
    EMAIL = "email"
    PUSH = "push"
    NONE = "none"


@dataclass(frozen=True)
class ParentReportPreferences:
    guardian_id: str
    preferred_language: str = "auto"
    enabled_periods: Tuple[ReportPeriod, ...] = (
        ReportPeriod.DAILY,
        ReportPeriod.WEEKLY,
        ReportPeriod.MONTHLY,
    )
    delivery_channels: Tuple[DeliveryChannel, ...] = (DeliveryChannel.IN_APP,)
    include_exam_readiness: bool = True
    include_home_support: bool = True
    quiet_hours_start: int = 21
    quiet_hours_end: int = 7

    def validate(self) -> None:
        if not self.guardian_id.strip():
            raise ValueError("guardian_id is required")
        if not 0 <= self.quiet_hours_start <= 23:
            raise ValueError("quiet_hours_start must be 0..23")
        if not 0 <= self.quiet_hours_end <= 23:
            raise ValueError("quiet_hours_end must be 0..23")
        if len(set(self.enabled_periods)) != len(self.enabled_periods):
            raise ValueError("duplicate report period")
        if len(set(self.delivery_channels)) != len(self.delivery_channels):
            raise ValueError("duplicate delivery channel")


@dataclass(frozen=True)
class LearningReportInput:
    student_id: str
    student_name: str
    period_start: str
    period_end: str
    completed_topics: Tuple[str, ...] = ()
    strengths: Tuple[str, ...] = ()
    support_areas: Tuple[str, ...] = ()
    interests: Tuple[str, ...] = ()
    effort_signals: Tuple[str, ...] = ()
    learning_minutes: int = 0
    sessions_completed: int = 0
    syllabus_coverage: float | None = None
    readiness_score: float | None = None
    readiness_band: str | None = None
    evidence_confidence: float | None = None
    revision_priorities: Tuple[str, ...] = ()
    safety_flags: Tuple[str, ...] = ()
    sensitive_notes: Tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.student_id.strip():
            raise ValueError("student_id is required")
        if not self.student_name.strip():
            raise ValueError("student_name is required")
        if self.learning_minutes < 0:
            raise ValueError("learning_minutes cannot be negative")
        if self.sessions_completed < 0:
            raise ValueError("sessions_completed cannot be negative")
        for value, name in (
            (self.syllabus_coverage, "syllabus_coverage"),
            (self.readiness_score, "readiness_score"),
            (self.evidence_confidence, "evidence_confidence"),
        ):
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True)
class HomeSupportAction:
    title: str
    instruction: str
    estimated_minutes: int
    reason: str
    pressure_safe: bool = True


@dataclass(frozen=True)
class ParentProgressReport:
    report_id: str
    guardian_id: str
    student_id: str
    student_name: str
    period: ReportPeriod
    period_start: str
    period_end: str
    headline: str
    learning_summary: Tuple[str, ...]
    strengths: Tuple[str, ...]
    support_areas: Tuple[str, ...]
    interest_signals: Tuple[str, ...]
    home_support_actions: Tuple[HomeSupportAction, ...]
    readiness_summary: str
    readiness_uncertainty: str
    wellbeing_note: str
    privacy_notice: str
    generated_at: str
    generated_by: str = "GyanVerse Academy"

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["period"] = self.period.value
        return data


@dataclass(frozen=True)
class ParentAlert:
    alert_id: str
    guardian_id: str
    student_id: str
    severity: AlertSeverity
    title: str
    message: str
    recommended_action: str
    created_at: str
    safety_related: bool = False
    acknowledged: bool = False

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["severity"] = self.severity.value
        return data


@dataclass(frozen=True)
class ChildDashboardCard:
    student_id: str
    student_name: str
    latest_headline: str
    strengths: Tuple[str, ...]
    support_areas: Tuple[str, ...]
    readiness_summary: str
    open_alert_count: int
    latest_report_id: str | None


@dataclass(frozen=True)
class ParentDashboard:
    guardian_id: str
    children: Tuple[ChildDashboardCard, ...]
    generated_at: str


@dataclass(frozen=True)
class ReportHistoryEntry:
    report_id: str
    guardian_id: str
    student_id: str
    period: ReportPeriod
    period_start: str
    period_end: str
    generated_at: str
    headline: str
