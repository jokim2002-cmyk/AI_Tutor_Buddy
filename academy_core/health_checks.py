from __future__ import annotations

from time import perf_counter
from typing import Callable, Iterable, Tuple

from .stabilization_models import HealthCheckResult, HealthStatus


class HealthCheckRunner:
    def run(
        self,
        component: str,
        check: Callable[[], bool | tuple[bool, str]],
    ) -> HealthCheckResult:
        started = perf_counter()
        try:
            outcome = check()
            if isinstance(outcome, tuple):
                ok, details = outcome
            else:
                ok, details = bool(outcome), "Check completed"
            status = HealthStatus.HEALTHY if ok else HealthStatus.UNHEALTHY
        except Exception as exc:
            status = HealthStatus.UNHEALTHY
            details = f"{type(exc).__name__}: {exc}"
        latency_ms = round((perf_counter() - started) * 1000, 3)
        return HealthCheckResult(component, status, details, latency_ms)

    def run_many(
        self,
        checks: Iterable[tuple[str, Callable[[], bool | tuple[bool, str]]]],
    ) -> Tuple[HealthCheckResult, ...]:
        return tuple(self.run(name, check) for name, check in checks)
