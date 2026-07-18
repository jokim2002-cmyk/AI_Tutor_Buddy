from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Tuple

from .health_checks import HealthCheckRunner
from .security_policy import SecurityPolicy
from .stabilization_models import (
    HealthCheckResult,
    HealthStatus,
    RiskLevel,
    SecurityFinding,
    StabilizationReport,
)


class StabilizationService:
    def __init__(
        self,
        *,
        health_runner: HealthCheckRunner | None = None,
        security_policy: SecurityPolicy | None = None,
    ) -> None:
        self.health = health_runner or HealthCheckRunner()
        self.security = security_policy or SecurityPolicy()

    def assess(
        self,
        *,
        checks: Iterable[tuple[str, Callable[[], bool | tuple[bool, str]]]],
        scan_paths: Iterable[Path] = (),
        recovery_ready: bool,
        deletion_ready: bool,
        rate_limit_ready: bool,
    ) -> StabilizationReport:
        health_checks = self.health.run_many(checks)
        findings = self.security.scan_paths(scan_paths)

        health_ok = all(item.status == HealthStatus.HEALTHY for item in health_checks)
        critical_security = any(
            item.level in {RiskLevel.HIGH, RiskLevel.CRITICAL} for item in findings
        )
        release_ready = (
            health_ok
            and not critical_security
            and recovery_ready
            and deletion_ready
            and rate_limit_ready
        )

        if release_ready:
            overall = HealthStatus.HEALTHY
            summary = "All stabilization gates passed for release-candidate preparation."
        elif health_ok:
            overall = HealthStatus.DEGRADED
            summary = "Core services are healthy, but one or more stabilization gates remain."
        else:
            overall = HealthStatus.UNHEALTHY
            summary = "One or more required health checks failed."

        return StabilizationReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            overall_status=overall,
            health_checks=health_checks,
            security_findings=findings,
            recovery_ready=recovery_ready,
            deletion_ready=deletion_ready,
            rate_limit_ready=rate_limit_ready,
            release_candidate_ready=release_ready,
            summary=summary,
        )
