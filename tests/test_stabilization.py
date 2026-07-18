import json
import tempfile
import unittest
from pathlib import Path

from academy_core import (
    DataLifecycleManager,
    HealthCheckRunner,
    HealthStatus,
    RecoveryManager,
    RiskLevel,
    SecurityPolicy,
    SlidingWindowRateLimiter,
    StabilizationService,
)


class StabilizationTests(unittest.TestCase):
    def test_health_check_pass(self):
        result = HealthCheckRunner().run("database", lambda: True)
        self.assertEqual(result.status, HealthStatus.HEALTHY)

    def test_health_check_failure(self):
        result = HealthCheckRunner().run("database", lambda: (False, "down"))
        self.assertEqual(result.status, HealthStatus.UNHEALTHY)

    def test_health_check_exception_is_captured(self):
        def boom():
            raise RuntimeError("failed")
        result = HealthCheckRunner().run("service", boom)
        self.assertIn("RuntimeError", result.details)

    def test_rate_limiter_allows_within_limit(self):
        now = [0.0]
        limiter = SlidingWindowRateLimiter(2, 10, clock=lambda: now[0])
        self.assertTrue(limiter.check("u1").allowed)
        self.assertTrue(limiter.check("u1").allowed)

    def test_rate_limiter_blocks_over_limit(self):
        limiter = SlidingWindowRateLimiter(1, 10, clock=lambda: 0.0)
        self.assertTrue(limiter.check("u1").allowed)
        self.assertFalse(limiter.check("u1").allowed)

    def test_rate_limiter_recovers_after_window(self):
        now = [0.0]
        limiter = SlidingWindowRateLimiter(1, 10, clock=lambda: now[0])
        limiter.check("u1")
        now[0] = 11.0
        self.assertTrue(limiter.check("u1").allowed)

    def test_rate_limiter_isolated_keys(self):
        limiter = SlidingWindowRateLimiter(1, 10, clock=lambda: 0.0)
        self.assertTrue(limiter.check("u1").allowed)
        self.assertTrue(limiter.check("u2").allowed)

    def test_secret_scan_detects_api_key(self):
        findings = SecurityPolicy().scan_text('api_key="abc123456789"', source="x.py")
        self.assertTrue(findings)
        self.assertEqual(findings[0].level, RiskLevel.CRITICAL)

    def test_secret_scan_clean_text(self):
        findings = SecurityPolicy().scan_text("safe configuration")
        self.assertEqual(findings, ())

    def test_forbidden_secret_file_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("SAFE=1", encoding="utf-8")
            findings = SecurityPolicy().scan_paths((path,))
            self.assertTrue(any(x.code == "FORBIDDEN_SECRET_FILE" for x in findings))

    def test_backup_roundtrip(self):
        manager = RecoveryManager()
        manifest, envelope = manager.create_backup(
            {"s1": {"memory": [1, 2]}, "s2": {"reports": ["a"]}}
        )
        restored = manager.restore(envelope)
        self.assertEqual(restored["s1"]["memory"], [1, 2])
        self.assertEqual(manifest.record_count, 2)

    def test_backup_tamper_is_detected(self):
        manager = RecoveryManager()
        _, envelope = manager.create_backup({"s1": {"x": 1}})
        parsed = json.loads(envelope)
        parsed["payload"]["s1"]["x"] = 2
        with self.assertRaises(ValueError):
            manager.restore(json.dumps(parsed))

    def test_student_deletion_across_stores(self):
        stores = {
            "memory": {"s1": [1, 2], "s2": [3]},
            "reports": {"s1": {"r1": 1}},
        }
        receipt = DataLifecycleManager().delete_student("s1", stores)
        self.assertNotIn("s1", stores["memory"])
        self.assertNotIn("s1", stores["reports"])
        self.assertEqual(set(receipt.deleted_categories), {"memory", "reports"})

    def test_student_deletion_is_isolated(self):
        stores = {"memory": {"s1": [1], "s2": [2]}}
        DataLifecycleManager().delete_student("s1", stores)
        self.assertIn("s2", stores["memory"])

    def test_release_candidate_ready(self):
        report = StabilizationService().assess(
            checks=(("core", lambda: True),),
            recovery_ready=True,
            deletion_ready=True,
            rate_limit_ready=True,
        )
        self.assertTrue(report.release_candidate_ready)
        self.assertEqual(report.overall_status, HealthStatus.HEALTHY)

    def test_release_blocked_by_health(self):
        report = StabilizationService().assess(
            checks=(("core", lambda: False),),
            recovery_ready=True,
            deletion_ready=True,
            rate_limit_ready=True,
        )
        self.assertFalse(report.release_candidate_ready)
        self.assertEqual(report.overall_status, HealthStatus.UNHEALTHY)

    def test_release_blocked_by_stabilization_gate(self):
        report = StabilizationService().assess(
            checks=(("core", lambda: True),),
            recovery_ready=False,
            deletion_ready=True,
            rate_limit_ready=True,
        )
        self.assertFalse(report.release_candidate_ready)
        self.assertEqual(report.overall_status, HealthStatus.DEGRADED)

    def test_report_serializes(self):
        report = StabilizationService().assess(
            checks=(("core", lambda: True),),
            recovery_ready=True,
            deletion_ready=True,
            rate_limit_ready=True,
        )
        self.assertEqual(report.to_dict()["overall_status"], "healthy")


if __name__ == "__main__":
    unittest.main()
