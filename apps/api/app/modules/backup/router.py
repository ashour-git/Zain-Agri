"""Daily backup email routes (spec 2026-11-12 §6)."""

import hmac
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import UnauthorizedError
from app.infrastructure.db.session import get_session, get_session_factory
from app.modules.auth.dependencies import CurrentPrincipal, TenantContext, require_permission
from app.modules.authorization.permissions import Permission
from app.modules.backup import delivery, service
from app.modules.backup.mailer import MailerDep
from app.modules.backup.schemas import BackupSettingsIn, BackupStatusOut, ConfirmIn

router = APIRouter(tags=["backup"])
logger = logging.getLogger("zain.backup")

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
Owner = Annotated[TenantContext, Depends(require_permission(Permission.TENANT_SETTINGS_MANAGE))]

SETTINGS_PATH = "/api/v1/tenants/current/backup"


def _now() -> datetime:
    return datetime.now(UTC)


@router.get(SETTINGS_PATH, response_model=BackupStatusOut)
async def get_backup(context: Owner, db: SessionDep, mailer: MailerDep) -> BackupStatusOut:
    return await service.get_status(
        db, tenant_id=context.tenant.id, mail_configured=mailer is not None, now=_now()
    )


@router.put(SETTINGS_PATH, response_model=BackupStatusOut)
async def set_backup_address(
    payload: BackupSettingsIn,
    context: Owner,
    principal: CurrentPrincipal,
    db: SessionDep,
    settings: SettingsDep,
    mailer: MailerDep,
) -> BackupStatusOut:
    return await service.set_address(
        db,
        tenant=context.tenant,
        actor_id=principal.user_id,
        email=payload.email,
        mailer=mailer,
        settings=settings,
        now=_now(),
    )


@router.delete(SETTINGS_PATH, status_code=status.HTTP_204_NO_CONTENT)
async def stop_backup(context: Owner, principal: CurrentPrincipal, db: SessionDep) -> Response:
    await service.stop(db, tenant_id=context.tenant.id, actor_id=principal.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/api/v1/backup/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_backup_address(payload: ConfirmIn, db: SessionDep) -> Response:
    """Opened from the emailed link; works without signing in."""
    await service.confirm(db, token=payload.token, now=_now())
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(f"{SETTINGS_PATH}/send", response_model=BackupStatusOut)
async def send_backup_now(
    context: Owner, principal: CurrentPrincipal, db: SessionDep, mailer: MailerDep
) -> BackupStatusOut:
    now = _now()
    await delivery.send_now(
        db, tenant_id=context.tenant.id, actor_id=principal.user_id, mailer=mailer, now=now
    )
    return await service.get_status(db, tenant_id=context.tenant.id, mail_configured=True, now=now)


def _require_cron_secret(settings: Settings, authorization: str | None) -> None:
    expected = settings.cron_secret.get_secret_value() if settings.cron_secret else ""
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    # No secret configured means nobody may trigger the run.
    if not expected or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise UnauthorizedError()


@router.api_route("/api/v1/internal/backups/run", methods=["GET", "POST"], include_in_schema=False)
async def run_nightly_backups(
    settings: SettingsDep,
    mailer: MailerDep,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, int | bool]:
    """Called by Vercel Cron (GET, with ``Authorization: Bearer <CRON_SECRET>``)."""
    _require_cron_secret(settings, authorization)
    summary = await delivery.run_nightly(get_session_factory(), mailer=mailer, now=_now())
    logger.info("backup.run", extra=asdict(summary))
    return asdict(summary)
