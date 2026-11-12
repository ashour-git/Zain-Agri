"""Authentication service.

All state changes for credentials, tokens and sessions live here. Routers stay
thin: validate input, call a function, return a contract.
"""

import logging
import secrets
import unicodedata
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import Result, delete, select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, UnauthorizedError
from app.modules.auth.models import RefreshSession
from app.modules.auth.schemas import TenantMembershipOut, check_new_password
from app.modules.auth.security import (
    create_access_token,
    dummy_verify,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    password_needs_rehash,
    verify_password,
)
from app.modules.authorization.permissions import permissions_for
from app.modules.identity.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Tenant,
    TenantStatus,
    User,
)
from app.modules.tenancy.context import set_tenant_context

logger = logging.getLogger("zain.security")

INVALID_CREDENTIALS = "Invalid email or password"
INVALID_REFRESH = "Invalid or expired session"


def _rowcount(result: Result[Any]) -> int:
    """``AsyncSession.execute`` is typed as a plain Result; DML returns a CursorResult."""
    return cast("CursorResult[Any]", result).rowcount or 0


_USER_TENANTS_SQL = text(
    """
    SELECT tenant_id, tenant_name, tenant_slug, tenant_status, role, membership_status
    FROM app_user_tenants(CAST(:user_id AS uuid))
    """
)


async def user_tenants(db: AsyncSession, user_id: uuid.UUID) -> list[TenantMembershipOut]:
    """Every workspace this user can see, read through a SECURITY DEFINER fn.

    A plain join cannot work here: ``tenants`` and ``memberships`` are behind
    RLS, and before a workspace is chosen there is no tenant context to read
    with. The function is the single audited exception — see
    docs/security/TENANT_ISOLATION.md.
    """
    rows = (await db.execute(_USER_TENANTS_SQL, {"user_id": user_id})).mappings().all()
    return [
        TenantMembershipOut(
            id=row["tenant_id"],
            name=row["tenant_name"],
            slug=row["tenant_slug"],
            status=row["tenant_status"],
            role=row["role"],
            membership_status=row["membership_status"],
        )
        for row in rows
    ]


async def _get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def _active_membership(
    db: AsyncSession, *, user_id: uuid.UUID, tenant_id: uuid.UUID
) -> TenantMembershipOut | None:
    for membership in await user_tenants(db, user_id):
        if membership.id == tenant_id:
            return membership
    return None


def _usable(membership: TenantMembershipOut) -> bool:
    """Both the workspace and the membership must be active to enter it."""
    return (
        membership.status == TenantStatus.ACTIVE
        and membership.membership_status == MembershipStatus.ACTIVE
    )


async def _issue_session(
    db: AsyncSession,
    settings: Settings,
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    family_id: uuid.UUID,
    user_agent: str | None,
) -> tuple[RefreshSession, str]:
    raw_token = generate_refresh_token()
    row = RefreshSession(
        id=uuid.uuid4(),
        user_id=user_id,
        tenant_id=tenant_id,
        token_hash=hash_refresh_token(raw_token),
        token_family_id=family_id,
        user_agent=(user_agent or "")[:400] or None,
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
    )
    db.add(row)
    await db.flush()
    return row, raw_token


def _access_token(
    settings: Settings,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    role: MembershipRole | None,
) -> tuple[str, int]:
    return create_access_token(
        user_id=user_id,
        session_id=session_id,
        tenant_id=tenant_id,
        role=role,
        settings=settings,
    )


async def register(
    db: AsyncSession,
    settings: Settings,
    *,
    email: str,
    password: str,
    full_name: str,
    user_agent: str | None,
) -> tuple[User, str, str, int]:
    normalised = email.strip().lower()
    if await _get_user_by_email(db, normalised):
        raise ConflictError("An account with this email already exists")

    user = User(
        email=normalised,
        password_hash=hash_password(password, settings),
        full_name=" ".join(full_name.split()),
        email_verified_at=None if settings.require_email_verification else datetime.now(UTC),
    )
    db.add(user)
    await db.flush()

    session_row, refresh_token = await _issue_session(
        db,
        settings,
        user_id=user.id,
        tenant_id=None,
        family_id=uuid.uuid4(),
        user_agent=user_agent,
    )
    await db.commit()

    logger.info("auth_registered", extra={"event": "auth.register", "user_id": str(user.id)})
    access_token, expires_in = _access_token(
        settings,
        user_id=user.id,
        session_id=session_row.id,
        tenant_id=None,
        role=None,
    )
    return user, refresh_token, access_token, expires_in


async def login(
    db: AsyncSession,
    settings: Settings,
    *,
    email: str,
    password: str,
    tenant_id: uuid.UUID | None,
    user_agent: str | None,
) -> tuple[User, str, str, int, TenantMembershipOut | None, bool]:
    user = await _get_user_by_email(db, email.strip().lower())
    if user is None:
        dummy_verify(password, settings)
        raise UnauthorizedError(INVALID_CREDENTIALS)

    if not verify_password(password, user.password_hash, settings) or not user.is_active:
        raise UnauthorizedError(INVALID_CREDENTIALS)

    if settings.require_email_verification and user.email_verified_at is None:
        raise ForbiddenError("Email address is not verified")

    memberships = [m for m in await user_tenants(db, user.id) if _usable(m)]

    if tenant_id is not None:
        selected = next((m for m in memberships if m.id == tenant_id), None)
        if selected is None:
            # Deliberately indistinguishable from "no such tenant".
            raise ForbiddenError("You do not have access to this workspace")
        selected_membership = selected
        needs_selection = False
    elif len(memberships) == 1:
        selected_membership = memberships[0]
        needs_selection = False
    else:
        selected_membership = None
        needs_selection = True

    if password_needs_rehash(user.password_hash, settings):
        user.password_hash = hash_password(password, settings)
    user.last_login_at = datetime.now(UTC)

    session_row, refresh_token = await _issue_session(
        db,
        settings,
        user_id=user.id,
        tenant_id=selected_membership.id if selected_membership else None,
        family_id=uuid.uuid4(),
        user_agent=user_agent,
    )
    await db.commit()

    logger.info("auth_login", extra={"event": "auth.login", "user_id": str(user.id)})
    access_token, expires_in = _access_token(
        settings,
        user_id=user.id,
        session_id=session_row.id,
        tenant_id=selected_membership.id if selected_membership else None,
        role=selected_membership.role if selected_membership else None,
    )
    return user, refresh_token, access_token, expires_in, selected_membership, needs_selection


async def refresh(
    db: AsyncSession,
    settings: Settings,
    *,
    raw_token: str,
    tenant_id: uuid.UUID | None,
    user_agent: str | None,
) -> tuple[User, str, str, int, TenantMembershipOut | None]:
    digest = hash_refresh_token(raw_token)
    row = (
        await db.execute(
            select(RefreshSession).where(RefreshSession.token_hash == digest).with_for_update()
        )
    ).scalar_one_or_none()

    if row is None:
        raise UnauthorizedError(INVALID_REFRESH)

    now = datetime.now(UTC)

    if row.revoked_at is not None:
        # A revoked token was replayed. Rotate the whole family out of service.
        await db.execute(
            update(RefreshSession)
            .where(
                RefreshSession.token_family_id == row.token_family_id,
                RefreshSession.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        await db.commit()
        logger.warning(
            "auth_refresh_reuse_detected",
            extra={
                "event": "auth.refresh_reuse",
                "user_id": str(row.user_id),
                "tenant_id": str(row.tenant_id) if row.tenant_id else None,
            },
        )
        raise UnauthorizedError(INVALID_REFRESH)

    if row.expires_at <= now:
        raise UnauthorizedError(INVALID_REFRESH)

    user = await db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError(INVALID_REFRESH)

    selected = (
        await _active_membership(db, user_id=user.id, tenant_id=row.tenant_id)
        if row.tenant_id
        else None
    )
    if row.tenant_id is not None and (selected is None or not _usable(selected)):
        # Membership revoked or tenant suspended since the session was issued.
        await db.execute(
            update(RefreshSession).where(RefreshSession.id == row.id).values(revoked_at=now)
        )
        await db.commit()
        raise UnauthorizedError(INVALID_REFRESH)

    if tenant_id is not None and tenant_id != row.tenant_id:
        candidate = await _active_membership(db, user_id=user.id, tenant_id=tenant_id)
        if candidate is None or not _usable(candidate):
            raise ForbiddenError("You do not have access to this workspace")
        selected = candidate

    new_row, new_refresh = await _issue_session(
        db,
        settings,
        user_id=user.id,
        tenant_id=selected.id if selected else None,
        family_id=row.token_family_id,
        user_agent=user_agent,
    )
    row.revoked_at = now
    row.replaced_by_id = new_row.id
    await db.commit()

    access_token, expires_in = _access_token(
        settings,
        user_id=user.id,
        session_id=new_row.id,
        tenant_id=selected.id if selected else None,
        role=selected.role if selected else None,
    )
    return user, new_refresh, access_token, expires_in, selected


async def logout(db: AsyncSession, *, raw_token: str | None) -> None:
    if not raw_token:
        return
    await db.execute(
        update(RefreshSession)
        .where(
            RefreshSession.token_hash == hash_refresh_token(raw_token),
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    await db.commit()


async def logout_all(db: AsyncSession, *, user_id: uuid.UUID) -> int:
    result = await db.execute(
        update(RefreshSession)
        .where(
            RefreshSession.user_id == user_id,
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    await db.commit()
    return _rowcount(result)


async def list_sessions(
    db: AsyncSession, *, user_id: uuid.UUID, current_session_id: uuid.UUID
) -> list[tuple[RefreshSession, bool]]:
    now = datetime.now(UTC)
    rows = (
        (
            await db.execute(
                select(RefreshSession)
                .where(
                    RefreshSession.user_id == user_id,
                    RefreshSession.revoked_at.is_(None),
                    RefreshSession.expires_at > now,
                )
                .order_by(RefreshSession.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [(row, row.id == current_session_id) for row in rows]


async def revoke_session(db: AsyncSession, *, user_id: uuid.UUID, session_id: uuid.UUID) -> None:
    result = await db.execute(
        update(RefreshSession)
        .where(
            RefreshSession.id == session_id,
            RefreshSession.user_id == user_id,
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    await db.commit()
    if not _rowcount(result):
        # Same answer whether it never existed or belongs to someone else.
        raise NotFoundError("Session not found")


def slugify(name: str) -> str:
    """ASCII-safe, lowercase, hyphenated. Arabic names fall back to 'store'."""
    normalised = unicodedata.normalize("NFKD", name)
    ascii_only = normalised.encode("ascii", "ignore").decode("ascii").lower()
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in ascii_only)
    joined = "-".join(part for part in cleaned.split("-") if part)
    return joined[:50] or "store"


async def create_tenant(
    db: AsyncSession,
    settings: Settings,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    name: str,
    user_agent: str | None,
) -> tuple[Tenant, str, str, int]:
    """Create a workspace and its OWNER membership in one transaction.

    The caller always owns what they create; no request value can attach them
    to an existing workspace.

    ``tenants`` is protected by RLS, so the transaction is bound to the id of
    the row about to be inserted. The policy stays strict — ``id = context`` —
    instead of gaining an "anyone may insert" escape hatch for onboarding.
    """
    base_slug = slugify(name)
    tenant: Tenant | None = None

    for attempt in range(6):
        slug = base_slug if attempt == 0 else f"{base_slug}-{secrets.token_hex(3)}"
        tenant_id = uuid.uuid4()
        await set_tenant_context(db, tenant_id)

        candidate = Tenant(id=tenant_id, name=name, slug=slug, status=TenantStatus.ACTIVE)
        db.add(candidate)
        try:
            await db.flush()
        except IntegrityError:
            # Slug taken. A rolled-back transaction also drops the setting, and
            # the session re-applies it on the next attempt.
            await db.rollback()
            continue
        tenant = candidate
        break

    if tenant is None:
        raise ConflictError("Could not allocate a workspace address, try another name")

    db.add(
        Membership(
            tenant_id=tenant.id,
            user_id=user_id,
            role=MembershipRole.OWNER,
            status=MembershipStatus.ACTIVE,
        )
    )
    await db.flush()

    # Rotate the session so the token minted before onboarding cannot be
    # replayed against the new workspace.
    previous = await db.get(RefreshSession, session_id)
    new_row, raw_token = await _issue_session(
        db,
        settings,
        user_id=user_id,
        tenant_id=tenant.id,
        family_id=uuid.uuid4(),
        user_agent=user_agent,
    )
    if previous is not None and previous.user_id == user_id:
        previous.revoked_at = datetime.now(UTC)
        previous.replaced_by_id = new_row.id

    await db.commit()

    logger.info(
        "tenant_created",
        extra={"event": "tenant.create", "user_id": str(user_id), "tenant_id": str(tenant.id)},
    )
    access_token, expires_in = _access_token(
        settings,
        user_id=user_id,
        session_id=new_row.id,
        tenant_id=tenant.id,
        role=MembershipRole.OWNER,
    )
    return tenant, raw_token, access_token, expires_in


def permissions_for_role(role: MembershipRole) -> list[str]:
    return sorted(permission.value for permission in permissions_for(role))


async def purge_expired_sessions(db: AsyncSession, *, older_than_days: int = 90) -> int:
    """Housekeeping hook. Not scheduled in Sprint 02."""
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    result = await db.execute(delete(RefreshSession).where(RefreshSession.expires_at < cutoff))
    await db.commit()
    return _rowcount(result)


async def set_password(db: AsyncSession, user: User, new_password: str) -> None:
    """Store a new password hash and end every open session. Caller commits."""
    user.password_hash = hash_password(new_password, get_settings())
    await db.execute(
        update(RefreshSession)
        .where(RefreshSession.user_id == user.id, RefreshSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    return await _get_user_by_email(db, email.strip().lower())


async def reset_password(db: AsyncSession, *, email: str, new_password: str) -> bool:
    """Set a new password and end every open session. Admin use only (reset_password.py).

    Applies the same password rules as registration. Returns False when no
    account has this email.
    """
    check_new_password(new_password)

    user = await _get_user_by_email(db, email.strip().lower())
    if user is None:
        return False

    await set_password(db, user, new_password)
    await db.commit()
    logger.info("auth.password_reset", extra={"user_id": str(user.id)})
    return True
