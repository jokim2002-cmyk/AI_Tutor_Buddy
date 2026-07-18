from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from threading import RLock
from time import perf_counter
from typing import Callable, Dict, Mapping


@dataclass(frozen=True)
class MetricsSnapshot:
    counters: Mapping[str, float]
    gauges: Mapping[str, float]
    timings_ms: Mapping[str, tuple[float, ...]]


class MetricsRegistry:
    def __init__(self) -> None:
        self._counters: Dict[str, float] = defaultdict(float)
        self._gauges: Dict[str, float] = {}
        self._timings: Dict[str, list[float]] = defaultdict(list)
        self._lock = RLock()

    def increment(self, name: str, amount: float = 1.0) -> None:
        if amount < 0:
            raise ValueError("counter increment cannot be negative")
        with self._lock:
            self._counters[name] += amount

    def set_gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = float(value)

    def observe_ms(self, name: str, value_ms: float) -> None:
        if value_ms < 0:
            raise ValueError("timing cannot be negative")
        with self._lock:
            self._timings[name].append(float(value_ms))

    def time_call(self, name: str, fn: Callable[[], object]) -> object:
        started = perf_counter()
        try:
            return fn()
        finally:
            self.observe_ms(name, (perf_counter() - started) * 1000)

    def snapshot(self) -> MetricsSnapshot:
        with self._lock:
            return MetricsSnapshot(
                counters=dict(self._counters),
                gauges=dict(self._gauges),
                timings_ms={k: tuple(v) for k, v in self._timings.items()},
            )

    def to_prometheus_text(self) -> str:
        lines = []
        snapshot = self.snapshot()
        for name, value in sorted(snapshot.counters.items()):
            lines.append(f"{self._sanitize(name)} {value}")
        for name, value in sorted(snapshot.gauges.items()):
            lines.append(f"{self._sanitize(name)} {value}")
        for name, values in sorted(snapshot.timings_ms.items()):
            metric = self._sanitize(name)
            lines.append(f"{metric}_count {len(values)}")
            lines.append(f"{metric}_sum {sum(values)}")
        return "\n".join(lines) + ("\n" if lines else "")

    @staticmethod
    def _sanitize(name: str) -> str:
        return "".join(ch if ch.isalnum() or ch in "_:" else "_" for ch in name)
