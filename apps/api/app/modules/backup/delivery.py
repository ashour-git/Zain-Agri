"""Build and email one shop's backup, and record the outcome.

The caller has set the shop's tenant context. A delivery row is committed
(claimed) before any work: for nightly runs the partial unique index turns a
second claim on the same Cairo day into a skip, so no shop gets two emails.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BackupMailNotConfiguredError, ConflictError, TooManyRequestsError
from app.modules.audit import service as audit
from app.modules.backup.mailer import GENERIC_AR, Mailer, MailError, OutgoingEmail
from app.modules.backup.models import BackupDelivery, BackupStatus, DeliveryKind, DeliveryStatus
from app.modules.backup.service import (
    MANUAL_SENDS_PER_DAY,
    NOT_CONFIGURED,
    load_settings,
    manual_sends_today,
)
from app.modules.backup.workbook import CAIRO, build_workbook, cairo_date
from app.modules.identity.models import Tenant

logger = logging.getLogger("zain.backup")

RETRY_DELAY_SECONDS = 30.0
NOT_CONFIRMED = "Backup email is not confirmed"
LIMIT_REACHED = "Daily manual backup limit reached"
Sleep = Callable[[float], Awaitable[None]]


async def _send_with_retry(
    mailer: Mailer, message: OutgoingEmail, *, sleep: Sleep, retry_delay: float
) -> None:
    try:
        await mailer.send(message)
    except MailError:
        await sleep(retry_delay)
        await mailer.send(message)


async def deliver(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    kind: DeliveryKind,
    mailer: Mailer,
    now: datetime,
    sleep: Sleep = asyncio.sleep,
    retry_delay: float = RETRY_DELAY_SECONDS,
) -> BackupDelivery | None:
    """Send today's backup. ``None`` when the shop is not active or already claimed."""
    started = time.monotonic()
    settings_row = await load_settings(db, tenant_id)
    if settings_row is None or settings_row.status != BackupStatus.ACTIVE:
        return None

    day = cairo_date(now)
    row = BackupDelivery(
        tenant_id=tenant_id,
        delivery_date=day,
        kind=kind,
        status=DeliveryStatus.CLAIMED,
        email=settings_row.email,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.info("backup.skipped", extra={"tenant_id": str(tenant_id), "reason": "claimed"})
        return None

    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one()
    try:
        built = await build_workbook(db, tenant_id=tenant_id, now=now)
        row.file_bytes = len(built.content)
        row.row_counts = built.row_counts
        message = OutgoingEmail(
            to=row.email,
            subject=f"نسخة متجر {tenant.name} ليوم {day.isoformat()}",
            body=(
                f"مرفق نسخة من بيانات متجر «{tenant.name}» ليوم {day.isoformat()}: "
                "المنتجات والرصيد والحركات والدفعات وسجل النشاط.\n\n"
                "احتفظ بالملف في مكان آمن. لإيقاف هذه الرسائل افتح «النسخة اليومية» في الإعدادات."
            ),
            attachment=(built.filename, built.content),
        )
        await _send_with_retry(mailer, message, sleep=sleep, retry_delay=retry_delay)
        row.status = DeliveryStatus.SENT
        row.error_reason_ar = None
    except MailError as exc:
        row.status = DeliveryStatus.FAILED
        row.error_reason_ar = exc.reason_ar
    except Exception:
        logger.exception("backup.build_failed", extra={"tenant_id": str(tenant_id)})
        row.status = DeliveryStatus.FAILED
        row.error_reason_ar = GENERIC_AR
    await db.commit()

    logger.info(
        "backup.delivered",
        extra={
            "tenant_id": str(tenant_id),
            "kind": str(kind),
            "result": str(row.status),
            "file_bytes": row.file_bytes,
            "rows": row.row_counts,
            "duration_ms": round((time.monotonic() - started) * 1000),
        },
    )
    return row


MANUAL_RETRY_DELAY_SECONDS = 5.0


def _seconds_to_cairo_midnight(now: datetime) -> int:
    local = now.astimezone(CAIRO)
    midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(int((midnight - local).total_seconds()), 1)


async def send_now(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    mailer: Mailer | None,
    now: datetime,
    sleep: Sleep = asyncio.sleep,
) -> BackupDelivery:
    """The owner's «أرسل نسخة الآن»: at most 3 a day, confirmed address only."""
    if mailer is None:
        raise BackupMailNotConfiguredError(NOT_CONFIGURED)
    settings_row = await load_settings(db, tenant_id)
    if settings_row is None or settings_row.status != BackupStatus.ACTIVE:
        raise ConflictError(NOT_CONFIRMED)
    if await manual_sends_today(db, tenant_id, cairo_date(now)) >= MANUAL_SENDS_PER_DAY:
        raise TooManyRequestsError(LIMIT_REACHED, retry_after=_seconds_to_cairo_midnight(now))

    await audit.record(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="backup.manual_send",
        entity_type="backup",
        entity_id=tenant_id,
    )
    row = await deliver(
        db,
        tenant_id=tenant_id,
        kind=DeliveryKind.MANUAL,
        mailer=mailer,
        now=now,
        sleep=sleep,
        retry_delay=MANUAL_RETRY_DELAY_SECONDS,
    )
    assert row is not None  # manual deliveries are never unique-claimed
    return row
