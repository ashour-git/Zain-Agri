"""Tenant context propagation into PostgreSQL.

Row Level Security policies read ``current_setting('app.tenant_id')``.
``set_config(..., true)`` is transaction-local, so a pooled connection can
never leak one tenant's context into the next request.

The tenant id always originates from the authenticated server-side identity.
It must never come from a request body, query string or header.
"""

import uuid
from typing import Any

from sqlalchemy import Connection, event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

_CURRENT_TENANT_SQL = text("SELECT current_setting('app.tenant_id', true)")
_SET_TENANT_SQL = text("SELECT set_config('app.tenant_id', :tid, true)")

TENANT_INFO_KEY = "app.tenant_id"


@event.listens_for(Session, "after_begin")
def _reapply_tenant_context(session: Session, transaction: Any, connection: Connection) -> None:
    """Re-apply the tenant on every transaction of a bound session.

    ``commit()`` ends the transaction and PostgreSQL discards a transaction-local
    setting. Without this hook every query after a commit would silently run
    with no RLS context, and the failure mode would be an empty result set
    rather than an error.
    """
    tenant_id = session.info.get(TENANT_INFO_KEY)
    if tenant_id:
        connection.execute(_SET_TENANT_SQL, {"tid": tenant_id})


async def set_tenant_context(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Bind this session (and every later transaction on it) to a tenant."""
    session.info[TENANT_INFO_KEY] = str(tenant_id)
    await session.execute(_SET_TENANT_SQL, {"tid": str(tenant_id)})


async def clear_tenant_context(session: AsyncSession) -> None:
    session.info.pop(TENANT_INFO_KEY, None)
    await session.execute(_SET_TENANT_SQL, {"tid": ""})


async def current_tenant_id(session: AsyncSession) -> uuid.UUID | None:
    """Read back the tenant bound to this transaction (diagnostics/tests)."""
    raw = (await session.execute(_CURRENT_TENANT_SQL)).scalar_one_or_none()
    return uuid.UUID(raw) if raw else None
