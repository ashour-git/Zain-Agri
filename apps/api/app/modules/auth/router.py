"""Authentication HTTP endpoints.

Routers stay thin: parse input, call the service, shape the contract. Every
response that mints a refresh token also sets the HttpOnly cookie; the token
itself never appears in a response body.
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import ForbiddenError, TooManyRequestsError, UnauthorizedError
from app.core.ratelimit import auth_limiter
from app.infrastructure.db.session import get_session
from app.modules.auth import service
from app.modules.auth.cookies import clear_refresh_cookie, set_refresh_cookie
from app.modules.auth.dependencies import CurrentPrincipal, get_current_tenant
from app.modules.auth.schemas import (
    LoginRequest,
    MeResponse,
    RefreshRequest,
    RegisterRequest,
    SessionOut,
    TokenResponse,
)
from app.modules.identity.models import MembershipRole, Tenant, User
from app.modules.tenancy.context import set_tenant_context

logger = logging.getLogger("zain.security")

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _throttle(request: Request, settings: Settings, *, scope: str, subject: str = "") -> None:
    key = f"{scope}:{_client_ip(request)}:{subject.strip().lower()}"
    if not auth_limiter.allow(
        key,
        limit=settings.auth_rate_limit_attempts,
        window_seconds=settings.auth_rate_limit_window_seconds,
    ):
        logger.warning(
            "auth_rate_limited",
            extra={
                "event": "auth.rate_limited",
                "path": request.url.path,
                "ip": _client_ip(request),
            },
        )
        raise TooManyRequestsError(
            "Too many attempts, please try again later",
            retry_after=auth_limiter.retry_after(
                key, window_seconds=settings.auth_rate_limit_window_seconds
            ),
        )


async def _token_response(
    db: AsyncSession,
    settings: Settings,
    response: Response,
    *,
    user: User,
    access_token: str,
    expires_in: int,
    refresh_token: str | None,
    tenant_id: uuid.UUID | None,
    role: MembershipRole | None,
    requires_selection: bool,
) -> TokenResponse:
    """Common shaping for register/login/refresh: cookie out, body in."""
    tenants = await service.user_tenants(db, user.id)
    tenant_out = None
    if tenant_id is not None:
        # `tenants` is behind RLS. The workspace was just validated against the
        # caller's memberships, so binding the transaction to it here is safe.
        await set_tenant_context(db, tenant_id)
        tenant_out = await db.get(Tenant, tenant_id)
    permissions = service.permissions_for_role(role) if role is not None else []

    if refresh_token is not None:
        set_refresh_cookie(response, refresh_token, settings)

    return TokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        user=user,
        tenant=tenant_out,
        role=role,
        permissions=permissions,
        tenants=tenants,
        requires_tenant_selection=requires_selection,
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: SessionDep,
    settings: SettingsDep,
) -> TokenResponse:
    _throttle(request, settings, scope="register")
    user, refresh_token, access_token, expires_in = await service.register(
        db,
        settings,
        email=str(payload.email),
        password=payload.password,
        full_name=payload.full_name,
        user_agent=request.headers.get("user-agent"),
    )
    return await _token_response(
        db,
        settings,
        response,
        user=user,
        access_token=access_token,
        expires_in=expires_in,
        refresh_token=refresh_token,
        tenant_id=None,
        role=None,
        requires_selection=True,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: SessionDep,
    settings: SettingsDep,
) -> TokenResponse:
    _throttle(request, settings, scope="login", subject=str(payload.email))
    (
        user,
        refresh_token,
        access_token,
        expires_in,
        membership,
        requires_selection,
    ) = await service.login(
        db,
        settings,
        email=str(payload.email),
        password=payload.password,
        tenant_id=payload.tenant_id,
        user_agent=request.headers.get("user-agent"),
    )
    return await _token_response(
        db,
        settings,
        response,
        user=user,
        access_token=access_token,
        expires_in=expires_in,
        refresh_token=refresh_token,
        tenant_id=membership.id if membership else None,
        role=membership.role if membership else None,
        requires_selection=requires_selection,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    payload: RefreshRequest,
    request: Request,
    response: Response,
    db: SessionDep,
    settings: SettingsDep,
) -> TokenResponse:
    raw_token = request.cookies.get(settings.refresh_cookie_name)
    if not raw_token:
        raise UnauthorizedError("Invalid or expired session")

    _throttle(request, settings, scope="refresh")
    (
        user,
        new_refresh,
        access_token,
        expires_in,
        membership,
    ) = await service.refresh(
        db,
        settings,
        raw_token=raw_token,
        tenant_id=payload.tenant_id,
        user_agent=request.headers.get("user-agent"),
    )
    return await _token_response(
        db,
        settings,
        response,
        user=user,
        access_token=access_token,
        expires_in=expires_in,
        refresh_token=new_refresh,
        tenant_id=membership.id if membership else None,
        role=membership.role if membership else None,
        requires_selection=membership is None,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    db: SessionDep,
    settings: SettingsDep,
) -> Response:
    # Idempotent: an unknown or already-revoked cookie still clears state.
    await service.logout(db, raw_token=request.cookies.get(settings.refresh_cookie_name))
    clear_refresh_cookie(response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(
    response: Response,
    principal: CurrentPrincipal,
    db: SessionDep,
    settings: SettingsDep,
) -> Response:
    revoked = await service.logout_all(db, user_id=principal.user_id)
    logger.info(
        "auth_logout_all",
        extra={
            "event": "auth.logout_all",
            "user_id": str(principal.user_id),
            "tenant_id": str(principal.tenant_id) if principal.tenant_id else None,
        },
    )
    clear_refresh_cookie(response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    response.headers["X-Revoked-Sessions"] = str(revoked)
    return response


@router.get("/me", response_model=MeResponse)
async def me(
    principal: CurrentPrincipal,
    db: SessionDep,
) -> MeResponse:
    """Current identity, the workspace bound to this session, and the choices.

    A workspace that was revoked, suspended or deleted since the token was
    minted is simply not reported as current — the client is sent back to
    tenant selection instead of being half-authorised.
    """
    tenants = await service.user_tenants(db, principal.user_id)
    try:
        context = await get_current_tenant(principal, db)
    except ForbiddenError:
        context = None

    return MeResponse(
        user=principal.user,
        tenant=context.tenant if context else None,
        role=context.role if context else None,
        permissions=(
            sorted(permission.value for permission in context.permissions) if context else []
        ),
        tenants=tenants,
        requires_tenant_selection=context is None,
    )


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(
    principal: CurrentPrincipal,
    db: SessionDep,
) -> list[SessionOut]:
    rows = await service.list_sessions(
        db, user_id=principal.user_id, current_session_id=principal.session_id
    )
    return [
        SessionOut(
            id=row.id,
            created_at=row.created_at,
            expires_at=row.expires_at,
            user_agent=row.user_agent,
            is_current=is_current,
        )
        for row, is_current in rows
    ]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: uuid.UUID,
    principal: CurrentPrincipal,
    db: SessionDep,
) -> Response:
    await service.revoke_session(db, user_id=principal.user_id, session_id=session_id)
    logger.info(
        "auth_session_revoked",
        extra={
            "event": "auth.session_revoked",
            "user_id": str(principal.user_id),
            "session_id": str(session_id),
        },
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
