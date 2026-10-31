"""Tenant management: onboarding and workspace settings.

These are the only tenant-facing endpoints Sprint 02 ships. They exist to make
tenant context resolution and RBAC testable end to end without pulling any
product module forward.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.infrastructure.db.session import get_session
from app.modules.auth import service
from app.modules.auth.cookies import set_refresh_cookie
from app.modules.auth.dependencies import (
    CurrentPrincipal,
    TenantContext,
    get_current_tenant,
    require_permission,
)
from app.modules.auth.schemas import (
    CreateTenantRequest,
    CreateTenantResponse,
    TenantMemberOut,
    TenantOut,
    UpdateTenantRequest,
)
from app.modules.authorization.permissions import Permission
from app.modules.identity.models import Membership, MembershipRole, User

logger = logging.getLogger("zain.security")

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
CurrentTenantDep = Annotated[TenantContext, Depends(get_current_tenant)]

SettingsManager = Annotated[
    TenantContext, Depends(require_permission(Permission.TENANT_SETTINGS_MANAGE))
]
UsersManager = Annotated[TenantContext, Depends(require_permission(Permission.USERS_MANAGE))]


@router.post("", response_model=CreateTenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    payload: CreateTenantRequest,
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
    db: SessionDep,
    settings: SettingsDep,
) -> CreateTenantResponse:
    """Onboard a new workspace: tenant + OWNER membership in one transaction.

    The caller always becomes the owner of what *they* create. No parameter
    lets a client attach itself to a workspace that already exists.
    """
    tenant, refresh_token, access_token, expires_in = await service.create_tenant(
        db,
        settings,
        user_id=principal.user_id,
        session_id=principal.session_id,
        name=payload.name,
        user_agent=request.headers.get("user-agent"),
    )
    set_refresh_cookie(response, refresh_token, settings)
    return CreateTenantResponse(
        tenant=TenantOut.model_validate(tenant),
        role=MembershipRole.OWNER,
        access_token=access_token,
        expires_in=expires_in,
        permissions=service.permissions_for_role(MembershipRole.OWNER),
    )


@router.get("/current", response_model=TenantOut)
async def current_tenant(context: CurrentTenantDep) -> TenantOut:
    return TenantOut.model_validate(context.tenant)


@router.patch("/current", response_model=TenantOut)
async def update_current_tenant(
    payload: UpdateTenantRequest,
    context: SettingsManager,
    db: SessionDep,
) -> TenantOut:
    tenant = context.tenant
    tenant.name = payload.name
    await db.commit()
    logger.info("tenant_updated", extra={"event": "tenant.update", "tenant_id": str(tenant.id)})
    return TenantOut.model_validate(tenant)


@router.get("/current/members", response_model=list[TenantMemberOut])
async def list_current_members(
    context: UsersManager,
    db: SessionDep,
) -> list[TenantMemberOut]:
    """Members of the current workspace, scoped by RLS as well as by predicate."""
    rows = (
        await db.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.tenant_id == context.tenant.id)
            .order_by(Membership.created_at)
        )
    ).all()
    return [
        TenantMemberOut(
            membership_id=membership.id,
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=membership.role,
            status=membership.status,
            is_active=user.is_active,
            created_at=membership.created_at,
        )
        for membership, user in rows
    ]


@router.get("/current/permissions", response_model=list[str])
async def current_permissions(context: CurrentTenantDep) -> list[str]:
    """What the caller's role may do here, straight from the policy module."""
    return sorted(permission.value for permission in context.permissions)
