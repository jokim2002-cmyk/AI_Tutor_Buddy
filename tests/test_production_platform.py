import io
import json
import logging
import tempfile
import unittest
from pathlib import Path

from academy_core import (
    EnvironmentName,
    HealthEndpointService,
    MetricsRegistry,
    ReleaseManifestBuilder,
    RuntimeConfigManager,
    SemanticVersion,
    StartupStatus,
    StartupValidator,
    build_logger,
    set_correlation_id,
)


class ProductionPlatformTests(unittest.TestCase):
    def test_development_defaults(self):
        config = RuntimeConfigManager().load(EnvironmentName.DEVELOPMENT)
        self.assertTrue(config.debug)
        self.assertEqual(config.environment, EnvironmentName.DEVELOPMENT)

    def test_production_defaults_are_safe(self):
        config = RuntimeConfigManager().load(EnvironmentName.PRODUCTION)
        self.assertFalse(config.debug)
        self.assertTrue(config.allowed_origins)

    def test_environment_override(self):
        config = RuntimeConfigManager().load(
            EnvironmentName.DEVELOPMENT,
            environ={
                "GYANVERSE_PORT": "9001",
                "GYANVERSE_LOG_LEVEL": "warning",
                "GYANVERSE_FEATURE_VOICE": "true",
            },
        )
        self.assertEqual(config.port, 9001)
        self.assertEqual(config.log_level, "WARNING")
        self.assertTrue(config.feature_flags["voice"])

    def test_invalid_boolean_override(self):
        with self.assertRaises(ValueError):
            RuntimeConfigManager().load(
                EnvironmentName.DEVELOPMENT,
                environ={"GYANVERSE_DEBUG": "maybe"},
            )

    def test_production_debug_is_blocked(self):
        with self.assertRaises(ValueError):
            RuntimeConfigManager().load(
                EnvironmentName.PRODUCTION,
                environ={"GYANVERSE_DEBUG": "true"},
            )

    def test_startup_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = RuntimeConfigManager().load(
                EnvironmentName.DEVELOPMENT,
                environ={"GYANVERSE_DATA_DIR": tmp},
            )
            report = StartupValidator().validate(config, environ={})
            self.assertEqual(report.status, StartupStatus.READY)

    def test_startup_blocked_missing_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = RuntimeConfigManager().load(
                EnvironmentName.STAGING,
                environ={"GYANVERSE_DATA_DIR": tmp},
            )
            report = StartupValidator().validate(config, environ={})
            self.assertEqual(report.status, StartupStatus.BLOCKED)

    def test_startup_report_serializes(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = RuntimeConfigManager().load(
                EnvironmentName.DEVELOPMENT,
                environ={"GYANVERSE_DATA_DIR": tmp},
            )
            payload = StartupValidator().validate(config, environ={}).to_dict()
            self.assertEqual(payload["status"], "ready")

    def test_structured_logger_emits_json(self):
        logger = build_logger("test-json", "INFO")
        stream = io.StringIO()
        logger.handlers[0].stream = stream
        logger.info("hello", extra={"student_id": "s1"})
        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["message"], "hello")
        self.assertEqual(payload["context"]["student_id"], "s1")

    def test_correlation_id(self):
        logger = build_logger("test-correlation", "INFO")
        stream = io.StringIO()
        logger.handlers[0].stream = stream
        set_correlation_id("corr-1")
        logger.info("hello")
        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["correlation_id"], "corr-1")
        set_correlation_id(None)

    def test_metrics_counter(self):
        metrics = MetricsRegistry()
        metrics.increment("requests_total")
        metrics.increment("requests_total", 2)
        self.assertEqual(metrics.snapshot().counters["requests_total"], 3)

    def test_metrics_negative_counter_rejected(self):
        with self.assertRaises(ValueError):
            MetricsRegistry().increment("x", -1)

    def test_metrics_timing(self):
        metrics = MetricsRegistry()
        self.assertEqual(metrics.time_call("work_ms", lambda: 5), 5)
        self.assertEqual(len(metrics.snapshot().timings_ms["work_ms"]), 1)

    def test_prometheus_export(self):
        metrics = MetricsRegistry()
        metrics.increment("requests.total", 2)
        self.assertIn("requests_total 2.0", metrics.to_prometheus_text())

    def test_live_endpoint(self):
        config = RuntimeConfigManager().load(EnvironmentName.DEVELOPMENT)
        payload = HealthEndpointService(config).live()
        self.assertEqual(payload["status"], "alive")

    def test_ready_endpoint_pass(self):
        config = RuntimeConfigManager().load(EnvironmentName.DEVELOPMENT)
        payload = HealthEndpointService(config).ready((("core", lambda: True),))
        self.assertEqual(payload["status"], "ready")

    def test_ready_endpoint_failure(self):
        config = RuntimeConfigManager().load(EnvironmentName.DEVELOPMENT)
        payload = HealthEndpointService(config).ready((("core", lambda: False),))
        self.assertEqual(payload["status"], "not_ready")

    def test_semver_valid(self):
        version = SemanticVersion("1.2.3")
        self.assertEqual(version.bump_patch(), "1.2.4")
        self.assertEqual(version.bump_minor(), "1.3.0")
        self.assertEqual(version.bump_major(), "2.0.0")

    def test_semver_invalid(self):
        with self.assertRaises(ValueError):
            SemanticVersion("1.2")

    def test_release_manifest(self):
        config = RuntimeConfigManager().load(
            EnvironmentName.DEVELOPMENT,
            environ={"GYANVERSE_VERSION": "1.0.0"},
        )
        manifest = ReleaseManifestBuilder().build(
            config,
            commit="abc123",
            artifact_names=("app.zip", "app.zip", "manifest.json"),
            test_count=145,
            test_status="passed",
        )
        self.assertEqual(manifest.version, "1.0.0")
        self.assertEqual(len(manifest.artifact_names), 2)
        self.assertEqual(manifest.to_dict()["environment"], "development")

    def test_manifest_requires_commit(self):
        config = RuntimeConfigManager().load(EnvironmentName.DEVELOPMENT)
        with self.assertRaises(ValueError):
            ReleaseManifestBuilder().build(
                config,
                commit="",
                artifact_names=(),
                test_count=0,
                test_status="unknown",
            )


if __name__ == "__main__":
    unittest.main()
