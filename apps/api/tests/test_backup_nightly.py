"""The nightly run Vercel Cron triggers: every due shop once, never twice."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.infrastructure.db.session import get_session_factory
from app.modules.backup.delivery import deliver, run_nightly
from app.modules.backup.mailer import mailer_dependency
from app.modules.backup.models import BackupSettings, BackupStatus, DeliveryKind
from app.modules.identity.models import Tenant
from app.modules.tenancy.context import set_tenant_context
from tests.backup_fakes import RecordingMailer
from tests.support import make_tenant

RUN = "/api/v1/internal/backups/run"
SECRET = "s" * 48
NOW = datetime(2026, 12, 3, 1, 0, tzinfo=UTC)


@pytest_asyncio.fixture(autouse=True)
async def only_this_tests_shops(owner_session: AsyncSession) -> AsyncIterator[None]:
    """The test database is shared: stop shops other tests left active."""
    await owner_session.execute(
        update(BackupSettings)
        .where(BackupSettings.status == BackupStatus.ACTIVE)
        .values(status=BackupStatus.STOPPED)
    )
    await owner_session.commit()
    yield


@pytest.fixture
def mailer(test_app: FastAPI) -> Iterator[RecordingMailer]:
    recorder = RecordingMailer()
    settings = get_settings().model_copy(update={"cron_secret": SecretStr(SECRET)})
    test_app.dependency_overrides[mailer_dependency] = lambda: recorder
    test_app.dependency_overrides[get_settings] = lambda: settings
    yield recorder
    test_app.dependency_overrides.clear()


async def _shop(owner_session: AsyncSession, status: BackupStatus) -> tuple[Tenant, str]:
    tenant = await make_tenant(owner_session)
    email = f"shop-{uuid.uuid4().hex[:8]}@example.com"
    owner_session.add(BackupSettings(tenant_id=tenant.id, email=email, status=status))
    await owner_session.commit()
    return tenant, email


def _to(mailer: RecordingMailer) -> list[str]:
    return sorted(message.to for message in mailer.sent)


async def test_run_requires_cron_secret(
    client: AsyncClient, owner_session: AsyncSession, mailer: RecordingMailer
) -> None:
    missing = await client.get(RUN)
    wrong = await client.get(RUN, headers={"Authorization": "Bearer wrong"})
    right = await client.get(RUN, headers={"Authorization": f"Bearer {SECRET}"})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert right.status_code == 200, right.text
    assert right.json()["configured"] is True


async def test_run_refused_when_no_secret_is_configured(
    client: AsyncClient, test_app: FastAPI
) -> None:
    unset = get_settings().model_copy(update={"cron_secret": None})
    test_app.dependency_overrides[get_settings] = lambda: unset

    response = await client.get(RUN, headers={"Authorization": "Bearer "})

    assert response.status_code == 401
    test_app.dependency_overrides.clear()


async def test_run_sends_each_due_shop_once(owner_session: AsyncSession) -> None:
    _, a = await _shop(owner_session, BackupStatus.ACTIVE)
    _, b = await _shop(owner_session, BackupStatus.ACTIVE)
    await _shop(owner_session, BackupStatus.PENDING)
    mailer = RecordingMailer()

    first = await run_nightly(get_session_factory(), mailer=mailer, now=NOW)
    second = await run_nightly(get_session_factory(), mailer=mailer, now=NOW)

    assert _to(mailer) == sorted([a, b])
    assert (first.sent, first.failed, first.remaining) == (2, 0, 0)
    assert second.sent == 0


async def test_concurrent_runs_send_once(owner_session: AsyncSession) -> None:
    _, a = await _shop(owner_session, BackupStatus.ACTIVE)
    _, b = await _shop(owner_session, BackupStatus.ACTIVE)
    mailer = RecordingMailer()

    await asyncio.gather(
        run_nightly(get_session_factory(), mailer=mailer, now=NOW),
        run_nightly(get_session_factory(), mailer=mailer, now=NOW),
    )

    assert _to(mailer) == sorted([a, b])


async def test_deadline_leaves_remaining(owner_session: AsyncSession) -> None:
    _, a = await _shop(owner_session, BackupStatus.ACTIVE)
    _, b = await _shop(owner_session, BackupStatus.ACTIVE)
    mailer = RecordingMailer()
    ticks = iter([0.0, 0.0, 500.0])

    first = await run_nightly(
        get_session_factory(), mailer=mailer, now=NOW, clock=lambda: next(ticks, 500.0)
    )
    second = await run_nightly(get_session_factory(), mailer=mailer, now=NOW)

    assert (first.sent, first.remaining) == (1, 1)
    assert second.sent == 1
    assert _to(mailer) == sorted([a, b])


async def test_run_skips_shop_whose_address_went_back_to_pending(
    db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    tenant, _ = await _shop(owner_session, BackupStatus.ACTIVE)
    # The owner saves a new address after the run listed the shop as due.
    await owner_session.execute(
        update(BackupSettings)
        .where(BackupSettings.tenant_id == tenant.id)
        .values(email="new-unconfirmed@example.com", status=BackupStatus.PENDING)
    )
    await owner_session.commit()
    mailer = RecordingMailer()

    await set_tenant_context(db_session, tenant.id)
    row = await deliver(
        db_session, tenant_id=tenant.id, kind=DeliveryKind.NIGHTLY, mailer=mailer, now=NOW
    )

    assert row is None
    assert mailer.attempts == 0


async def test_run_without_mailer_reports_not_configured(owner_session: AsyncSession) -> None:
    await _shop(owner_session, BackupStatus.ACTIVE)

    summary = await run_nightly(get_session_factory(), mailer=None, now=NOW)

    assert summary.configured is False
    assert (summary.sent, summary.failed, summary.skipped) == (0, 0, 0)


async def test_failed_shop_does_not_stop_the_others(owner_session: AsyncSession) -> None:
    await _shop(owner_session, BackupStatus.ACTIVE)
    await _shop(owner_session, BackupStatus.ACTIVE)
    mailer = RecordingMailer(always_fail="عنوان البريد مرفوض.")

    async def no_sleep(_: float) -> None:
        return None

    summary = await run_nightly(get_session_factory(), mailer=mailer, now=NOW, sleep=no_sleep)

    assert (summary.sent, summary.failed) == (0, 2)


async def test_one_broken_shop_does_not_stop_the_night(
    owner_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.backup import delivery as delivery_module

    real_deliver = delivery_module.deliver
    _, healthy = await _shop(owner_session, BackupStatus.ACTIVE)
    broken, _ = await _shop(owner_session, BackupStatus.ACTIVE)

    async def flaky(db: AsyncSession, *, tenant_id: uuid.UUID, **kwargs: object) -> object:
        if tenant_id == broken.id:
            raise RuntimeError("connection dropped")
        return await real_deliver(db, tenant_id=tenant_id, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(delivery_module, "deliver", flaky)
    mailer = RecordingMailer()

    summary = await run_nightly(get_session_factory(), mailer=mailer, now=NOW)

    assert _to(mailer) == [healthy]
    assert (summary.sent, summary.failed) == (1, 1)
