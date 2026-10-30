"""Tenant context propagation into PostgreSQL.

Row Level Security policies read ``current_setting('app.tenant_id')``.
``set_config(..., true)`` is transaction-local, so a pooled connection can
never leak one tenant's context into the next request.

The tenant id always originates from the authenticated server-side identity.
It must never come from a request body, query string or header.
"""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_CURRENT_TENANT_SQL = text("SELECT current_setting('app.tenant_id', true)")


async def set_tenant_context(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Bind the current transaction to a tenant.

    Must be called inside an open transaction; the setting is discarded when
    the transaction ends.
    """
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
    )


async def clear_tenant_context(session: AsyncSession) -> None:
    await session.execute(text("SELECT set_config('app.tenant_id', '', true)"))


async def current_tenant_id(session: AsyncSession) -> uuid.UUID | None:
    """Read back the tenant bound to this transaction (diagnostics/tests)."""
    raw = (await session.execute(_CURRENT_TENANT_SQL)).scalar_one_or_none()
    return uuid.UUID(raw) if raw else None
