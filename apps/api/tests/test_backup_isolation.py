"""Backup tables follow the same tenant isolation as every other shop table.

The nightly job must find which shops are due without reading any other
column across tenants; two narrow SECURITY DEFINER functions do that.
"""

import hashlib
import uuid
from datetime import date

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.backup.models import (
    BackupDelivery,
    BackupSettings,
    BackupStatus,
    DeliveryKind,
    DeliveryStatus,
)
from app.modules.identity.models import Tenant
from app.modules.tenancy.context import set_tenant_context
from tests.support import make_tenant

TODAY = date(2026, 11, 12)


async def _settings(
    session: AsyncSession, tenant: Tenant, status: BackupStatus, token_hash: str | None = None
) -> None:
    session.add(
        BackupSettings(
            tenant_id=tenant.id,
            email=f"owner-{uuid.uuid4().hex[:6]}@example.com",
            status=status,
            confirm_token_hash=token_hash,
        )
    )
    await session.flush()


def _delivery(tenant: Tenant, kind: DeliveryKind, status: DeliveryStatus) -> BackupDelivery:
    return BackupDelivery(
        tenant_id=tenant.id,
        delivery_date=TODAY,
        kind=kind,
        status=status,
        email="x@example.com",
    )


async def _due(db_session: AsyncSession, on: date) -> set[uuid.UUID]:
    rows = await db_session.execute(
        text("SELECT tenant_id FROM app_backup_due_tenants(CAST(:d AS date))"), {"d": on}
    )
    return set(rows.scalars().all())


async def test_backup_tables_hide_other_tenants_rows(
    db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    a = await make_tenant(owner_session)
    b = await make_tenant(owner_session)
    await _settings(owner_session, a, BackupStatus.ACTIVE)
    await _settings(owner_session, b, BackupStatus.ACTIVE)
    owner_session.add_all(
        [
            _delivery(a, DeliveryKind.MANUAL, DeliveryStatus.SENT),
            _delivery(b, DeliveryKind.MANUAL, DeliveryStatus.SENT),
        ]
    )
    await owner_session.commit()

    await set_tenant_context(db_session, a.id)

    assert (await db_session.execute(select(BackupSettings.tenant_id))).scalars().all() == [a.id]
    assert set((await db_session.execute(select(BackupDelivery.tenant_id))).scalars()) == {a.id}


async def test_due_tenants_lists_only_active_unsent(
    db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    active = await make_tenant(owner_session)
    pending = await make_tenant(owner_session)
    already_sent = await make_tenant(owner_session)
    failed_today = await make_tenant(owner_session)
    await _settings(owner_session, active, BackupStatus.ACTIVE)
    await _settings(owner_session, pending, BackupStatus.PENDING)
    await _settings(owner_session, already_sent, BackupStatus.ACTIVE)
    await _settings(owner_session, failed_today, BackupStatus.ACTIVE)
    owner_session.add_all(
        [
            _delivery(already_sent, DeliveryKind.NIGHTLY, DeliveryStatus.SENT),
            _delivery(failed_today, DeliveryKind.NIGHTLY, DeliveryStatus.FAILED),
        ]
    )
    await owner_session.commit()

    due = await _due(db_session, TODAY)

    assert active.id in due
    # One attempt per night: a failed night waits for tomorrow (spec §4).
    assert failed_today.id not in due
    assert pending.id not in due
    assert already_sent.id not in due


async def test_token_lookup_returns_tenant_for_hash_only(
    db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    tenant = await make_tenant(owner_session)
    token_hash = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    await _settings(owner_session, tenant, BackupStatus.PENDING, token_hash=token_hash)
    await owner_session.commit()

    async def lookup(value: str) -> uuid.UUID | None:
        result = await db_session.execute(text("SELECT app_backup_token_tenant(:h)"), {"h": value})
        return result.scalar_one()

    assert await lookup(token_hash) == tenant.id
    assert await lookup("0" * 64) is None


async def test_second_nightly_claim_same_day_violates_unique(
    owner_session: AsyncSession,
) -> None:
    tenant = await make_tenant(owner_session)
    owner_session.add_all(
        [
            _delivery(tenant, DeliveryKind.MANUAL, DeliveryStatus.SENT),
            _delivery(tenant, DeliveryKind.MANUAL, DeliveryStatus.SENT),
            _delivery(tenant, DeliveryKind.NIGHTLY, DeliveryStatus.CLAIMED),
        ]
    )
    await owner_session.commit()

    owner_session.add(_delivery(tenant, DeliveryKind.NIGHTLY, DeliveryStatus.CLAIMED))
    with pytest.raises(IntegrityError):
        await owner_session.commit()


@pytest.mark.parametrize(
    "signature", ["app_backup_due_tenants(date)", "app_backup_token_tenant(text)"]
)
async def test_backup_functions_are_secured(db_session: AsyncSession, signature: str) -> None:
    row = (
        await db_session.execute(
            text(
                """
                SELECT p.prosecdef AS is_security_definer,
                       p.proowner::regrole::text AS owner_name,
                       p.proacl IS NULL AS has_default_acl,
                       EXISTS (
                           SELECT 1 FROM aclexplode(p.proacl) AS a
                           WHERE a.grantee = 0 AND a.privilege_type = 'EXECUTE'
                       ) AS public_can_execute
                FROM pg_proc AS p
                WHERE p.oid = to_regprocedure(:sig)
                """
            ),
            {"sig": signature},
        )
    ).one()

    assert row.is_security_definer is True
    assert row.has_default_acl is False, "PUBLIC keeps the default EXECUTE grant"
    assert row.public_can_execute is False
    assert row.owner_name != "zain_app"
