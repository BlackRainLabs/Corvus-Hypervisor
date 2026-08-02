"""In-memory sliding-window rate limiter for the Management API."""

from __future__ import annotations

import time
from collections import defaultdict, deque


class SlidingWindowRateLimiter:
    """Allow at most ``limit`` events per ``window_seconds`` per key."""

    def __init__(self, *, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        if self.limit <= 0:
            return True
        now = time.monotonic()
        window = self._hits[key]
        cutoff = now - self.window_seconds
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= self.limit:
            return False
        window.append(now)
        return True

    def retry_after_seconds(self, key: str) -> int:
        if self.limit <= 0:
            return 0
        window = self._hits.get(key)
        if not window:
            return 0
        oldest = window[0]
        remaining = self.window_seconds - (time.monotonic() - oldest)
        return max(1, int(remaining + 0.999))
