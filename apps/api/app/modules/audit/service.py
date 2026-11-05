"""Audit trail writes and reads.

Write path: called from catalog/inventory services *inside* their open
transaction. It only flushes; the caller commits. A failed audit insert therefore
rolls back the business change with it.

Read path: ``audit.read`` is required at the router. This module still filters by
``tenant_id`` explicitly so a bug in the router cannot widen the scope.
"""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.audit.schemas import AuditListOut, AuditLogOut
from app.modules.identity.models import User

# Keys that must never reach the audit trail, even if a caller passes a raw
# request body by mistake. Values are dropped, not masked, so the secret cannot
# be recovered from the column.
_SENSITIVE_FRAGMENTS = (
    "password",
    "token",
    "secret",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
)


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in _SENSITIVE_FRAGMENTS)


def _jsonable(value: Any) -> Any:
    """Recursively convert values JSONB can store."""
    if isinstance(value, dict):
        return {
            str(key): _jsonable(item) for key, item in value.items() if not _is_sensitive(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, enum.Enum):
        return str(value.value)
    return value


def sanitize_state(state: dict[str, Any] | None) -> dict[str, Any] | None:
    if state is None:
        return None
    converted = _jsonable(state)
    return converted if isinstance(converted, dict) else None


async def record(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> AuditLog:
    """Append one audit row in the caller's transaction."""
    entry = AuditLog(
        tenant_id=tenant_id,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_state=sanitize_state(before_state),
        after_state=sanitize_state(after_state),
        meta=sanitize_state(meta),
    )
    db.add(entry)
    await db.flush()
    return entry


async def list_logs(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    page: int,
    page_size: int,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    action: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> AuditListOut:
    filters = [AuditLog.tenant_id == tenant_id]
    if entity_type:
        filters.append(AuditLog.entity_type == entity_type)
    if entity_id:
        filters.append(AuditLog.entity_id == entity_id)
    if action:
        filters.append(AuditLog.action == action)
    if actor_id:
        filters.append(AuditLog.actor_id == actor_id)

    total = (await db.execute(select(func.count(AuditLog.id)).where(*filters))).scalar_one()

    rows = (
        await db.execute(
            select(AuditLog, User.full_name)
            .outerjoin(User, User.id == AuditLog.actor_id)
            .where(*filters)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    items = [
        AuditLogOut(
            id=entry.id,
            actor_id=entry.actor_id,
            actor_name=actor_name,
            action=entry.action,
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            before_state=entry.before_state,
            after_state=entry.after_state,
            meta=entry.meta,
            created_at=entry.created_at,
        )
        for entry, actor_name in rows
    ]
    return AuditListOut(items=items, total=total, page=page, page_size=page_size)
