"""Per-IP sliding window: block after too many failed API key attempts."""

from __future__ import annotations

import time
from collections import defaultdict, deque


class ApiKeyFailureTracker:
    def __init__(self, *, max_failures_per_minute: int) -> None:
        self._max = max_failures_per_minute
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def is_blocked(self, ip: str) -> bool:
        now = time.monotonic()
        window = 60.0
        dq = self._failures[ip]
        while dq and now - dq[0] > window:
            dq.popleft()
        return len(dq) >= self._max

    def record_failure(self, ip: str) -> None:
        now = time.monotonic()
        window = 60.0
        dq = self._failures[ip]
        while dq and now - dq[0] > window:
            dq.popleft()
        dq.append(now)
