"""Per-tenant daily question quota for the shop assistant.

A shop's day is its local calendar day (Africa/Cairo), so "questions left
today" resets at midnight where the shop is, not at UTC midnight.

In-process, like the auth limiter: per worker and cleared on restart. See
docs/security/AUTHENTICATION.md, known limitations.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from threading import Lock
from zoneinfo import ZoneInfo

SHOP_TZ = ZoneInfo("Africa/Cairo")


class QuotaExceeded(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("Daily assistant quota exceeded")
        self.retry_after = retry_after


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DailyQuota:
    def __init__(self, clock: Callable[[], datetime] = _utc_now) -> None:
        self._clock = clock
        self._used: dict[tuple[uuid.UUID, date], int] = {}
        self._lock = Lock()

    def _today(self) -> tuple[date, datetime]:
        local = self._clock().astimezone(SHOP_TZ)
        return local.date(), local

    def remaining(self, tenant_id: uuid.UUID, limit: int) -> int:
        today, _ = self._today()
        with self._lock:
            return max(0, limit - self._used.get((tenant_id, today), 0))

    def consume(self, tenant_id: uuid.UUID, limit: int) -> int:
        """Count one question and return how many are left today."""
        today, local = self._today()
        with self._lock:
            # Yesterday's counters are dead weight; drop them as we go.
            for key in [key for key in self._used if key[1] != today]:
                del self._used[key]

            used = self._used.get((tenant_id, today), 0)
            if used >= limit:
                midnight = datetime.combine(today + timedelta(days=1), time.min, SHOP_TZ)
                raise QuotaExceeded(max(1, int((midnight - local).total_seconds())))
            self._used[(tenant_id, today)] = used + 1
            return limit - used - 1

    def reset(self) -> None:
        with self._lock:
            self._used.clear()


assistant_quota = DailyQuota()
