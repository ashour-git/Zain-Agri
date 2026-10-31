"""Reusable authentication and authorisation dependencies.

Every protected route composes these instead of reading headers or roles by
hand. The access token is advisory: the database remains the source of truth
for account state, session revocation, membership and role.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import ForbiddenError, UnauthorizedError
from app.infrastructure.db.session import get_session
from app.modules.auth.models import RefreshSession
from app.modules.auth.security import decode_access_token
from app.modules.auth.service import user_tenants
from app.modules.authorization.permissions import Permission, permissions_for
from app.modules.identity.models import (
    MembershipRole,
    MembershipStatus,
    Tenant,
    TenantStatus,
    User,
)
from app.modules.tenancy.context import set_tenant_context

INVALID_TOKEN_MESSAGE = "Invalid or expired access token"  # noqa: S105 - a message, not a secret
NO_WORKSPACE = "No workspace selected for this session"
WORKSPACE_DENIED = "You do not have access to this workspace"

bearer_scheme = HTTPBearer(auto_error=False)

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
CredentialsDep = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated person behind the current request."""

    user: User
    session_id: uuid.UUID
    tenant_id: uuid.UUID | None
    role: MembershipRole | None

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id


@dataclass(frozen=True, slots=True)
class TenantContext:
    """A validated tenant together with the caller's role inside it."""

    tenant: Tenant
    role: MembershipRole
    permissions: frozenset[Permission]

    def allows(self, permission: Permission) -> bool:
        return permission in self.permissions


async def get_current_principal(
    credentials: CredentialsDep,
    session: SessionDep,
    settings: SettingsDep,
) -> Principal:
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("Authentication required")

    try:
        claims = decode_access_token(credentials.credentials, settings)
        user_id = uuid.UUID(str(claims["sub"]))
        session_id = uuid.UUID(str(claims["sid"]))
        raw_tenant = claims.get("tid")
        tenant_id = uuid.UUID(str(raw_tenant)) if raw_tenant else None
        raw_role = claims.get("rol")
        role = MembershipRole(raw_role) if raw_role else None
    except (jwt.InvalidTokenError, KeyError, ValueError, TypeError) as exc:
        raise UnauthorizedError(INVALID_TOKEN_MESSAGE) from exc

    # Revocation must be immediate, so the session row is checked on every
    # request. This is one primary-key lookup; see AUTHENTICATION.md.
    refresh_session = await session.get(RefreshSession, session_id)
    if refresh_session is None or refresh_session.revoked_at is not None:
        raise UnauthorizedError(INVALID_TOKEN_MESSAGE)
    if refresh_session.user_id != user_id:
        raise UnauthorizedError(INVALID_TOKEN_MESSAGE)

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError(INVALID_TOKEN_MESSAGE)
    if settings.require_email_verification and user.email_verified_at is None:
        raise ForbiddenError("Email address is not verified")

    return Principal(user=user, session_id=session_id, tenant_id=tenant_id, role=role)


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]


async def get_current_tenant(
    principal: CurrentPrincipal,
    session: SessionDep,
) -> TenantContext:
    """Resolve the tenant from the token and re-validate it against the database.

    The token only says *which* tenant the session is bound to. Whether the
    caller may still enter it is decided here, from live membership and tenant
    rows — never from anything the client sent.
    """
    if principal.tenant_id is None:
        raise ForbiddenError(NO_WORKSPACE)

    memberships = await user_tenants(session, principal.user_id)
    membership = next((m for m in memberships if m.id == principal.tenant_id), None)
    if membership is None:
        raise ForbiddenError(WORKSPACE_DENIED)
    if membership.membership_status != MembershipStatus.ACTIVE:
        raise ForbiddenError("Your access to this workspace is not active")
    if membership.status != TenantStatus.ACTIVE:
        raise ForbiddenError("This workspace is suspended")

    await set_tenant_context(session, membership.id)
    tenant = await session.get(Tenant, membership.id)
    if tenant is None:  # pragma: no cover - FK guarantees the row exists
        raise ForbiddenError(WORKSPACE_DENIED)

    return TenantContext(
        tenant=tenant,
        role=membership.role,
        permissions=permissions_for(membership.role),
    )


CurrentTenant = Annotated[TenantContext, Depends(get_current_tenant)]


def require_permission(
    permission: Permission,
) -> Callable[[TenantContext], Awaitable[TenantContext]]:
    """Dependency factory: 403 unless the caller's role grants ``permission``."""

    async def _dependency(context: CurrentTenant) -> TenantContext:
        if not context.allows(permission):
            raise ForbiddenError(
                "Your role does not allow this action",
                details={"permission": permission.value},
            )
        return context

    return _dependency
