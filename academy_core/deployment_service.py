from __future__ import annotations

from pathlib import Path
from typing import Iterable, Mapping

from .deployment_models import EnvironmentName, StartupValidationReport
from .health_endpoint import HealthEndpointService
from .metrics import MetricsRegistry
from .release_manifest import ReleaseManifestBuilder
from .runtime_config import RuntimeConfigManager
from .startup_validator import StartupValidator
from .structured_logging import build_logger


class ProductionPlatformService:
    def __init__(self) -> None:
        self.config_manager = RuntimeConfigManager()
        self.startup_validator = StartupValidator()
        self.metrics = MetricsRegistry()
        self.manifests = ReleaseManifestBuilder()

    def initialize(
        self,
        environment: EnvironmentName | str,
        *,
        environ: Mapping[str, str] | None = None,
        create_data_dir: bool = False,
    ) -> tuple[object, StartupValidationReport]:
        config = self.config_manager.load(environment, environ=environ)
        logger = build_logger("gyanverse", config.log_level)
        report = self.startup_validator.validate(
            config,
            environ=environ,
            create_data_dir=create_data_dir,
        )
        self.metrics.increment("gyanverse_startup_attempts_total")
        self.metrics.set_gauge(
            "gyanverse_startup_ready",
            1.0 if report.status.value == "ready" else 0.0,
        )
        logger.info(
            "startup validation completed",
            extra={
                "environment": config.environment.value,
                "status": report.status.value,
            },
        )
        return config, report

    @staticmethod
    def health_service(config):
        return HealthEndpointService(config)
