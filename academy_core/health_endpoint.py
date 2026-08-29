from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Dict, Iterable

from .deployment_models import RuntimeConfig
from .health_checks import HealthCheckRunner
from .stabilization_models import HealthStatus


class HealthEndpointService:
    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self.runner = HealthCheckRunner()

    def live(self) -> Dict[str, object]:
        return {
            "status": "alive",
            "app": self.config.app_name,
            "version": self.config.version,
            "environment": self.config.environment.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def ready(
        self,
        checks: Iterable[tuple[str, Callable[[], bool | tuple[bool, str]]]],
    ) -> Dict[str, object]:
        results = self.runner.run_many(checks)
        ready = all(item.status == HealthStatus.HEALTHY for item in results)
        return {
            "status": "ready" if ready else "not_ready",
            "checks": [item.to_dict() for item in results],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
