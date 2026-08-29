from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Callable, Deque, Dict


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: float


class SlidingWindowRateLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: float,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.limit = limit
        self.window_seconds = float(window_seconds)
        self.clock = clock
        self._events: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = RLock()

    def check(self, key: str) -> RateLimitDecision:
        if not key.strip():
            raise ValueError("key is required")
        now = self.clock()
        with self._lock:
            events = self._events[key]
            while events and now - events[0] >= self.window_seconds:
                events.popleft()

            if len(events) >= self.limit:
                retry_after = max(0.0, self.window_seconds - (now - events[0]))
                return RateLimitDecision(False, 0, retry_after)

            events.append(now)
            return RateLimitDecision(True, self.limit - len(events), 0.0)

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)
