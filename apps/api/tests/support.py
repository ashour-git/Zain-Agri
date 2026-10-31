"""Fixture builders shared by the Sprint 02 suites.

Rows are created through the *owner* session so that seeding is not subject to
RLS. Anything the tests then read goes through the runtime role.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.auth.security import hash_password
from app.modules.identity.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Tenant,
    TenantStatus,
    User,
)

DEFAULT_PASSWORD = "ZainAgri!2026"
BROWSER_ORIGIN = "http://localhost:3000"


async def make_user(
    session: AsyncSession,
    *,
    email: str | None = None,
    password: str = DEFAULT_PASSWORD,
    full_name: str = "مستخدم اختبار",
    is_active: bool = True,
) -> User:
    user = User(
        email=email or f"user-{uuid.uuid4().hex[:12]}@example.com",
        password_hash=hash_password(password, get_settings()),
        full_name=full_name,
        is_active=is_active,
        email_verified_at=datetime.now(UTC),
    )
    session.add(user)
    await session.flush()
    return user


async def make_tenant(
    session: AsyncSession,
    *,
    name: str = "متجر زين",
    status: TenantStatus = TenantStatus.ACTIVE,
) -> Tenant:
    tenant = Tenant(name=name, slug=f"t-{uuid.uuid4().hex[:12]}", status=status)
    session.add(tenant)
    await session.flush()
    return tenant


async def make_membership(
    session: AsyncSession,
    *,
    tenant: Tenant,
    user: User,
    role: MembershipRole = MembershipRole.OWNER,
    status: MembershipStatus = MembershipStatus.ACTIVE,
) -> Membership:
    membership = Membership(tenant_id=tenant.id, user_id=user.id, role=role, status=status)
    session.add(membership)
    await session.flush()
    return membership


async def seed_member(
    session: AsyncSession,
    *,
    role: MembershipRole = MembershipRole.OWNER,
    tenant_status: TenantStatus = TenantStatus.ACTIVE,
    membership_status: MembershipStatus = MembershipStatus.ACTIVE,
    password: str = DEFAULT_PASSWORD,
    tenant_name: str = "متجر زين",
) -> tuple[User, Tenant, Membership]:
    """A committed user with exactly one workspace, ready to log into."""
    user = await make_user(session, password=password)
    tenant = await make_tenant(session, name=tenant_name, status=tenant_status)
    membership = await make_membership(
        session, tenant=tenant, user=user, role=role, status=membership_status
    )
    await session.commit()
    return user, tenant, membership


async def login(
    client: AsyncClient,
    email: str,
    password: str = DEFAULT_PASSWORD,
    tenant_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"email": email, "password": password}
    if tenant_id is not None:
        payload["tenant_id"] = str(tenant_id)
    response = await client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def auth_header(body: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {body['access_token']}"}
