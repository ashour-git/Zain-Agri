"""In-process rate limiting for authentication endpoints.

Deliberately simple: a sliding window per key, held in memory. It is per worker,
so a multi-worker deployment multiplies the effective limit. That is documented
in docs/security/AUTHENTICATION.md; replace with Redis if the limit must hold
across workers.
"""

import threading
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, *, limit: int, window_seconds: int, now: float | None = None) -> bool:
        """Record an attempt and return False once the window is full."""
        timestamp = time.monotonic() if now is None else now
        cutoff = timestamp - window_seconds

        with self._lock:
            bucket = self._events[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(timestamp)
            return True

    def retry_after(self, key: str, *, window_seconds: int) -> int:
        with self._lock:
            bucket = self._events.get(key)
            if not bucket:
                return 0
            return max(1, int(window_seconds - (time.monotonic() - bucket[0])))

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._events.clear()
            else:
                self._events.pop(key, None)


auth_limiter = SlidingWindowLimiter()
