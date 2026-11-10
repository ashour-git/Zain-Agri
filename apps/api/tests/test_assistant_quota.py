"""Per-tenant daily question quota for the shop assistant."""

import uuid
from datetime import UTC, datetime

import pytest

from app.modules.assistant.quota import DailyQuota, QuotaExceeded


def test_consume_counts_down_and_stops_at_limit() -> None:
    quota = DailyQuota(clock=lambda: datetime(2026, 11, 10, 12, tzinfo=UTC))
    tenant = uuid.uuid4()

    assert quota.consume(tenant, 2) == 1
    assert quota.consume(tenant, 2) == 0
    with pytest.raises(QuotaExceeded) as exc:
        quota.consume(tenant, 2)

    # 12:00 UTC is 14:00 in Cairo (UTC+2 in November): 10 hours to midnight.
    assert exc.value.retry_after == 10 * 3600


def test_quota_resets_at_cairo_midnight_not_utc() -> None:
    now = [datetime(2026, 11, 10, 21, 30, tzinfo=UTC)]  # 23:30 in Cairo
    quota = DailyQuota(clock=lambda: now[0])
    tenant = uuid.uuid4()
    quota.consume(tenant, 1)
    assert quota.remaining(tenant, 1) == 0

    now[0] = datetime(2026, 11, 10, 22, 30, tzinfo=UTC)  # 00:30 next day in Cairo
    assert quota.remaining(tenant, 1) == 1


def test_quota_is_per_tenant() -> None:
    quota = DailyQuota()
    shop_a, shop_b = uuid.uuid4(), uuid.uuid4()

    quota.consume(shop_a, 1)

    assert quota.remaining(shop_a, 1) == 0
    assert quota.remaining(shop_b, 1) == 1


def test_lowering_the_limit_applies_immediately() -> None:
    quota = DailyQuota()
    tenant = uuid.uuid4()
    quota.consume(tenant, 10)
    quota.consume(tenant, 10)

    assert quota.remaining(tenant, 1) == 0
    with pytest.raises(QuotaExceeded):
        quota.consume(tenant, 1)


def test_retry_after_is_right_on_the_night_clocks_go_back() -> None:
    # 2026-10-29 20:30 UTC is 23:30 Cairo summer time; clocks fall back at
    # midnight, so local midnight is 90 real minutes away, not 30.
    quota = DailyQuota(clock=lambda: datetime(2026, 10, 29, 20, 30, tzinfo=UTC))
    tenant = uuid.uuid4()
    quota.consume(tenant, 1)

    with pytest.raises(QuotaExceeded) as exc:
        quota.consume(tenant, 1)

    assert exc.value.retry_after == 90 * 60


def test_refund_gives_one_question_back() -> None:
    quota = DailyQuota()
    tenant = uuid.uuid4()
    quota.consume(tenant, 1)

    quota.refund(tenant)

    assert quota.remaining(tenant, 1) == 1
    quota.refund(tenant)  # never goes below zero used
    assert quota.remaining(tenant, 1) == 1
