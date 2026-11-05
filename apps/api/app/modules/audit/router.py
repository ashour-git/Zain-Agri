"""Audit read API. There is deliberately no write endpoint."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.session import get_session
from app.modules.audit import service
from app.modules.audit.schemas import AuditListOut
from app.modules.auth.dependencies import TenantContext, require_permission
from app.modules.authorization.permissions import Permission

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
AuditReader = Annotated[TenantContext, Depends(require_permission(Permission.AUDIT_READ))]

Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.get("", response_model=AuditListOut)
async def list_audit_logs(
    context: AuditReader,
    db: SessionDep,
    page: Page = 1,
    page_size: PageSize = 25,
    entity_type: Annotated[str | None, Query(max_length=60)] = None,
    entity_id: uuid.UUID | None = None,
    action: Annotated[str | None, Query(max_length=80)] = None,
    actor_id: uuid.UUID | None = None,
) -> AuditListOut:
    return await service.list_logs(
        db,
        tenant_id=context.tenant.id,
        page=page,
        page_size=page_size,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_id=actor_id,
    )
