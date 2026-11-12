"""Sending one shop's backup: the manual "send now" path and its failure handling."""

import logging
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.backup.delivery import deliver
from app.modules.backup.mailer import mailer_dependency
from app.modules.backup.models import (
    BackupDelivery,
    BackupSettings,
    BackupStatus,
    DeliveryKind,
    DeliveryStatus,
)
from app.modules.identity.models import Tenant
from app.modules.tenancy.context import set_tenant_context
from tests.backup_fakes import RecordingMailer
from tests.support import make_tenant, seeded_login

BACKUP = "/api/v1/tenants/current/backup"
SEND = f"{BACKUP}/send"
NOW = datetime(2026, 11, 12, 1, 0, tzinfo=UTC)


@pytest.fixture
def mailer(test_app: FastAPI) -> Iterator[RecordingMailer]:
    recorder = RecordingMailer()
    test_app.dependency_overrides[mailer_dependency] = lambda: recorder
    yield recorder
    test_app.dependency_overrides.pop(mailer_dependency, None)


async def _activate(owner_session: AsyncSession, tenant: Tenant, status: BackupStatus) -> None:
    owner_session.add(BackupSettings(tenant_id=tenant.id, email="owner@example.com", status=status))
    await owner_session.commit()


async def _no_sleep(_: float) -> None:
    return None


async def test_manual_send_emails_attachment(
    client: AsyncClient, owner_session: AsyncSession, mailer: RecordingMailer
) -> None:
    _, headers, tenant, _ = await seeded_login(client, owner_session)
    await _activate(owner_session, tenant, BackupStatus.ACTIVE)

    response = await client.post(SEND, headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["manual_sends_left"] == 2
    [email] = mailer.sent
    assert email.to == "owner@example.com"
    assert email.subject.startswith(f"نسخة متجر {tenant.name} ليوم ")
    assert email.attachment is not None
    filename, content = email.attachment
    assert filename.startswith(tenant.slug) and filename.endswith(".xlsx")
    row = (
        await owner_session.execute(
            select(BackupDelivery).where(BackupDelivery.tenant_id == tenant.id)
        )
    ).scalar_one()
    assert row.status == DeliveryStatus.SENT
    assert row.kind == DeliveryKind.MANUAL
    assert row.file_bytes == len(content) > 0


async def test_manual_send_requires_confirmed_address(
    client: AsyncClient, owner_session: AsyncSession, mailer: RecordingMailer
) -> None:
    _, headers, tenant, _ = await seeded_login(client, owner_session)
    await _activate(owner_session, tenant, BackupStatus.PENDING)

    response = await client.post(SEND, headers=headers)

    assert response.status_code == 409
    assert response.json()["error"]["message"] == "أكّد عنوان البريد أولًا."
    assert mailer.sent == []


async def test_fourth_manual_send_same_day_refused(
    client: AsyncClient, owner_session: AsyncSession, mailer: RecordingMailer
) -> None:
    _, headers, tenant, _ = await seeded_login(client, owner_session)
    await _activate(owner_session, tenant, BackupStatus.ACTIVE)
    for _ in range(3):
        assert (await client.post(SEND, headers=headers)).status_code == 200

    fourth = await client.post(SEND, headers=headers)

    assert fourth.status_code == 429
    assert fourth.json()["error"]["message"] == "وصلت للحد اليومي: 3 نسخ يدوية. حاول غدًا."
    assert int(fourth.headers["Retry-After"]) > 0
    assert len(mailer.sent) == 3


async def test_manual_send_is_owner_only(
    client: AsyncClient, owner_session: AsyncSession, mailer: RecordingMailer
) -> None:
    from app.modules.identity.models import MembershipRole

    _, headers, tenant, _ = await seeded_login(client, owner_session, role=MembershipRole.MANAGER)
    await _activate(owner_session, tenant, BackupStatus.ACTIVE)

    assert (await client.post(SEND, headers=headers)).status_code == 403
    assert mailer.sent == []


async def test_retry_once_then_succeed(
    db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    tenant = await make_tenant(owner_session)
    await _activate(owner_session, tenant, BackupStatus.ACTIVE)
    mailer = RecordingMailer(failures=["تعذّر الإرسال. سنحاول في الليلة القادمة.", None])
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    await set_tenant_context(db_session, tenant.id)
    row = await deliver(
        db_session,
        tenant_id=tenant.id,
        kind=DeliveryKind.NIGHTLY,
        mailer=mailer,
        now=NOW,
        sleep=sleep,
    )

    assert row is not None and row.status == DeliveryStatus.SENT
    assert waits == [30]
    assert len(mailer.sent) == 1


async def test_two_failures_record_arabic_reason(
    client: AsyncClient,
    db_session: AsyncSession,
    owner_session: AsyncSession,
    mailer: RecordingMailer,
) -> None:
    _, headers, tenant, _ = await seeded_login(client, owner_session)
    await _activate(owner_session, tenant, BackupStatus.ACTIVE)
    failing = RecordingMailer(always_fail="تعذّر الإرسال. سنحاول في الليلة القادمة.")

    await set_tenant_context(db_session, tenant.id)
    row = await deliver(
        db_session,
        tenant_id=tenant.id,
        kind=DeliveryKind.NIGHTLY,
        mailer=failing,
        now=datetime.now(UTC),
        sleep=_no_sleep,
    )

    assert row is not None and row.status == DeliveryStatus.FAILED
    assert row.error_reason_ar == "تعذّر الإرسال. سنحاول في الليلة القادمة."
    assert failing.attempts == 2
    status = (await client.get(BACKUP, headers=headers)).json()
    assert status["last_error_ar"] == "تعذّر الإرسال. سنحاول في الليلة القادمة."


async def test_three_failed_nights_counted(
    client: AsyncClient, owner_session: AsyncSession, mailer: RecordingMailer
) -> None:
    _, headers, tenant, _ = await seeded_login(client, owner_session)
    await _activate(owner_session, tenant, BackupStatus.ACTIVE)

    def night(day: date, status: DeliveryStatus) -> BackupDelivery:
        return BackupDelivery(
            tenant_id=tenant.id,
            delivery_date=day,
            kind=DeliveryKind.NIGHTLY,
            status=status,
            email="owner@example.com",
            error_reason_ar="عنوان البريد مرفوض." if status == DeliveryStatus.FAILED else None,
        )

    first = date(2026, 11, 1)
    owner_session.add_all(
        [
            night(first, DeliveryStatus.SENT),
            *(night(first + timedelta(days=i), DeliveryStatus.FAILED) for i in (1, 2, 3)),
        ]
    )
    await owner_session.commit()

    assert (await client.get(BACKUP, headers=headers)).json()["consecutive_failures"] == 3

    owner_session.add(night(first + timedelta(days=4), DeliveryStatus.SENT))
    await owner_session.commit()

    assert (await client.get(BACKUP, headers=headers)).json()["consecutive_failures"] == 0


async def test_delivery_logs_have_no_address(
    db_session: AsyncSession, owner_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    tenant = await make_tenant(owner_session)
    await _activate(owner_session, tenant, BackupStatus.ACTIVE)
    caplog.set_level(logging.DEBUG)

    await set_tenant_context(db_session, tenant.id)
    await deliver(
        db_session,
        tenant_id=tenant.id,
        kind=DeliveryKind.NIGHTLY,
        mailer=RecordingMailer(always_fail="عنوان البريد مرفوض."),
        now=NOW,
        sleep=_no_sleep,
    )

    backup_records = [r for r in caplog.records if r.name == "zain.backup"]
    assert backup_records
    for record in backup_records:
        assert "@" not in record.getMessage()
        assert all("@" not in str(value) for value in vars(record).values())


async def test_database_error_while_building_is_recorded_as_failed(
    db_session: AsyncSession, owner_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A SQL error aborts the transaction; the failure must still be saved."""
    from sqlalchemy import text

    from app.modules.backup import delivery as delivery_module
    from app.modules.backup.mailer import GENERIC_AR

    async def broken_build(db: AsyncSession, **_: object) -> None:
        await db.execute(text("SELECT 1 / 0"))

    monkeypatch.setattr(delivery_module, "build_workbook", broken_build)
    tenant = await make_tenant(owner_session)
    await _activate(owner_session, tenant, BackupStatus.ACTIVE)

    await set_tenant_context(db_session, tenant.id)
    row = await deliver(
        db_session,
        tenant_id=tenant.id,
        kind=DeliveryKind.NIGHTLY,
        mailer=RecordingMailer(),
        now=NOW,
    )

    assert row is not None and row.status == DeliveryStatus.FAILED
    tenant_id = tenant.id
    owner_session.expire_all()
    saved = (
        await owner_session.execute(
            select(BackupDelivery).where(BackupDelivery.tenant_id == tenant_id)
        )
    ).scalar_one()
    assert saved.status == DeliveryStatus.FAILED
    assert saved.error_reason_ar == GENERIC_AR


async def test_oversized_file_fails_without_sending(
    db_session: AsyncSession, owner_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.backup import delivery as delivery_module
    from app.modules.backup.mailer import TOO_LARGE_AR

    monkeypatch.setattr(delivery_module, "MAX_ATTACHMENT_BYTES", 10)
    tenant = await make_tenant(owner_session)
    await _activate(owner_session, tenant, BackupStatus.ACTIVE)
    mailer = RecordingMailer()

    await set_tenant_context(db_session, tenant.id)
    row = await deliver(
        db_session, tenant_id=tenant.id, kind=DeliveryKind.NIGHTLY, mailer=mailer, now=NOW
    )

    assert row is not None and row.error_reason_ar == TOO_LARGE_AR
    assert mailer.attempts == 0


async def test_rejected_address_is_not_retried(
    db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    tenant = await make_tenant(owner_session)
    await _activate(owner_session, tenant, BackupStatus.ACTIVE)
    mailer = RecordingMailer(always_fail="عنوان البريد مرفوض.")
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    await set_tenant_context(db_session, tenant.id)
    await deliver(
        db_session,
        tenant_id=tenant.id,
        kind=DeliveryKind.NIGHTLY,
        mailer=mailer,
        now=NOW,
        sleep=sleep,
    )

    assert mailer.attempts == 1
    assert waits == []
