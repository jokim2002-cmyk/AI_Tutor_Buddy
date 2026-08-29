import json
import unittest

from academy_core import (
    AlertSeverity,
    DeliveryChannel,
    GuardianProfile,
    GuardianRole,
    LearningReportInput,
    ParentMonitoringService,
    ParentReportExporter,
    ParentReportPreferences,
    ReportPeriod,
)


class ParentMonitoringReportTests(unittest.TestCase):
    def setUp(self):
        self.guardian = GuardianProfile(
            guardian_id="g1",
            name="Parent One",
            role=GuardianRole.PARENT,
            child_ids=("s1", "s2"),
        )
        self.service = ParentMonitoringService()
        self.input = LearningReportInput(
            student_id="s1",
            student_name="Aarav",
            period_start="2026-07-13",
            period_end="2026-07-19",
            completed_topics=("Fractions", "Decimals"),
            strengths=("Explains steps clearly",),
            support_areas=("Fraction comparison",),
            interests=("Cricket statistics",),
            effort_signals=("Retried after a mistake",),
            learning_minutes=95,
            sessions_completed=4,
            syllabus_coverage=0.72,
            readiness_score=0.64,
            readiness_band="developing",
            evidence_confidence=0.71,
            revision_priorities=("Equivalent fractions",),
            sensitive_notes=("private conversation",),
        )

    def test_daily_report_generation(self):
        report = self.service.generate_report(
            self.guardian, self.input, ReportPeriod.DAILY
        )
        self.assertEqual(report.student_id, "s1")
        self.assertEqual(report.period, ReportPeriod.DAILY)
        self.assertNotIn("private conversation", str(report.to_dict()))

    def test_weekly_report_generation(self):
        report = self.service.generate_report(
            self.guardian, self.input, ReportPeriod.WEEKLY
        )
        self.assertIn("weekly progress", report.headline)

    def test_monthly_report_generation(self):
        report = self.service.generate_report(
            self.guardian, self.input, ReportPeriod.MONTHLY
        )
        self.assertEqual(report.period.value, "monthly")

    def test_unauthorized_child_is_blocked(self):
        bad = LearningReportInput(
            student_id="other",
            student_name="Other",
            period_start="2026-07-19",
            period_end="2026-07-19",
        )
        with self.assertRaises(Exception):
            self.service.generate_report(self.guardian, bad, ReportPeriod.DAILY)

    def test_disabled_period_is_blocked(self):
        self.service.set_preferences(
            ParentReportPreferences(
                guardian_id="g1",
                enabled_periods=(ReportPeriod.WEEKLY,),
            )
        )
        with self.assertRaises(PermissionError):
            self.service.generate_report(
                self.guardian, self.input, ReportPeriod.DAILY
            )

    def test_preferences_validate_quiet_hours(self):
        with self.assertRaises(ValueError):
            ParentReportPreferences(
                guardian_id="g1", quiet_hours_start=25
            ).validate()

    def test_home_support_actions_are_pressure_safe(self):
        report = self.service.generate_report(
            self.guardian, self.input, ReportPeriod.WEEKLY
        )
        self.assertTrue(report.home_support_actions)
        self.assertTrue(all(x.pressure_safe for x in report.home_support_actions))

    def test_home_support_can_be_disabled(self):
        self.service.set_preferences(
            ParentReportPreferences(
                guardian_id="g1",
                include_home_support=False,
            )
        )
        report = self.service.generate_report(
            self.guardian, self.input, ReportPeriod.WEEKLY
        )
        self.assertEqual(report.home_support_actions, ())

    def test_readiness_can_be_disabled(self):
        self.service.set_preferences(
            ParentReportPreferences(
                guardian_id="g1",
                include_exam_readiness=False,
            )
        )
        report = self.service.generate_report(
            self.guardian, self.input, ReportPeriod.WEEKLY
        )
        self.assertIn("disabled", report.readiness_summary)

    def test_low_confidence_reports_uncertainty(self):
        low_conf = LearningReportInput(
            **{**self.input.__dict__, "evidence_confidence": 0.25}
        )
        report = self.service.generate_report(
            self.guardian, low_conf, ReportPeriod.WEEKLY
        )
        self.assertIn("limited", report.readiness_uncertainty)

    def test_report_history(self):
        self.service.generate_report(
            self.guardian, self.input, ReportPeriod.DAILY
        )
        self.service.generate_report(
            self.guardian, self.input, ReportPeriod.WEEKLY
        )
        history = self.service.repository.history("g1", student_id="s1")
        self.assertEqual(len(history), 2)

    def test_multi_child_dashboard_is_isolated(self):
        self.service.generate_report(
            self.guardian, self.input, ReportPeriod.WEEKLY
        )
        dashboard = self.service.dashboard(self.guardian)
        self.assertEqual(len(dashboard.children), 2)
        s1 = next(x for x in dashboard.children if x.student_id == "s1")
        s2 = next(x for x in dashboard.children if x.student_id == "s2")
        self.assertIsNotNone(s1.latest_report_id)
        self.assertIsNone(s2.latest_report_id)

    def test_no_activity_creates_information_alert(self):
        empty = LearningReportInput(
            student_id="s1",
            student_name="Aarav",
            period_start="2026-07-19",
            period_end="2026-07-19",
        )
        self.service.generate_report(
            self.guardian, empty, ReportPeriod.DAILY
        )
        alerts = self.service.repository.list_alerts("g1", open_only=True)
        self.assertEqual(alerts[0].severity, AlertSeverity.INFORMATIONAL)

    def test_low_readiness_creates_attention_alert(self):
        low = LearningReportInput(
            **{
                **self.input.__dict__,
                "readiness_score": 0.32,
                "evidence_confidence": 0.8,
            }
        )
        self.service.generate_report(
            self.guardian, low, ReportPeriod.WEEKLY
        )
        alerts = self.service.repository.list_alerts("g1", open_only=True)
        self.assertTrue(any(x.severity == AlertSeverity.ATTENTION for x in alerts))

    def test_safety_alert_hides_private_detail(self):
        safety = LearningReportInput(
            **{
                **self.input.__dict__,
                "safety_flags": ("internal-code-123",),
            }
        )
        self.service.generate_report(
            self.guardian, safety, ReportPeriod.DAILY
        )
        alerts = self.service.repository.list_alerts("g1", open_only=True)
        urgent = next(x for x in alerts if x.severity == AlertSeverity.URGENT)
        self.assertTrue(urgent.safety_related)
        self.assertNotIn("internal-code-123", urgent.message)

    def test_alert_acknowledgement(self):
        empty = LearningReportInput(
            student_id="s1",
            student_name="Aarav",
            period_start="2026-07-19",
            period_end="2026-07-19",
        )
        self.service.generate_report(
            self.guardian, empty, ReportPeriod.DAILY
        )
        alert = self.service.repository.list_alerts("g1")[0]
        updated = self.service.repository.acknowledge_alert(alert.alert_id)
        self.assertTrue(updated.acknowledged)

    def test_json_export(self):
        report = self.service.generate_report(
            self.guardian, self.input, ReportPeriod.WEEKLY
        )
        payload = ParentReportExporter().to_json(report)
        self.assertEqual(json.loads(payload)["student_id"], "s1")

    def test_csv_export(self):
        report = self.service.generate_report(
            self.guardian, self.input, ReportPeriod.WEEKLY
        )
        payload = ParentReportExporter().to_csv((report,))
        self.assertIn("report_id,guardian_id", payload)
        self.assertIn("Aarav", payload)

    def test_delivery_channel_enum(self):
        preferences = ParentReportPreferences(
            guardian_id="g1",
            delivery_channels=(DeliveryChannel.IN_APP, DeliveryChannel.EMAIL),
        )
        preferences.validate()
        self.assertEqual(len(preferences.delivery_channels), 2)

    def test_input_range_validation(self):
        with self.assertRaises(ValueError):
            LearningReportInput(
                student_id="s1",
                student_name="Aarav",
                period_start="x",
                period_end="y",
                readiness_score=1.2,
            ).validate()


if __name__ == "__main__":
    unittest.main()
