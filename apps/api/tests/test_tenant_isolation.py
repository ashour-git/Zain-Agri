"""Tenant isolation tests.

These are the security tests that matter most: if they pass while the runtime
role is a superuser or owns the tables, they prove nothing. The first test
guards that precondition.
"""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import Membership, MembershipRole, Tenant, User
from app.modules.tenancy.context import set_tenant_context


async def test_runtime_role_cannot_bypass_rls(db_session: AsyncSession) -> None:
    row = (
        await db_session.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        )
    ).one()

    assert row.rolsuper is False, "runtime role is a superuser: RLS is bypassed"
    assert row.rolbypassrls is False, "runtime role has BYPASSRLS: RLS is bypassed"


async def test_no_tenant_context_returns_no_rows(
    db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    owner_session.add(Tenant(name="No Context Ltd", slug=f"nc-{uuid.uuid4().hex[:8]}"))
    await owner_session.commit()

    count = (await db_session.execute(text("SELECT count(*) FROM tenants"))).scalar_one()

    assert count == 0, "queries without tenant context must fail closed"


async def test_tenant_sees_only_its_own_rows(
    db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    tenant_a = Tenant(name="Alpha Agri", slug=f"alpha-{uuid.uuid4().hex[:8]}")
    tenant_b = Tenant(name="Beta Agri", slug=f"beta-{uuid.uuid4().hex[:8]}")
    owner_session.add_all([tenant_a, tenant_b])
    await owner_session.commit()

    await set_tenant_context(db_session, tenant_a.id)
    visible = (await db_session.execute(select(Tenant.id))).scalars().all()

    assert visible == [tenant_a.id]


async def test_memberships_are_isolated(
    db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    tenant_a = Tenant(name="Alpha Agri", slug=f"alpha-{uuid.uuid4().hex[:8]}")
    tenant_b = Tenant(name="Beta Agri", slug=f"beta-{uuid.uuid4().hex[:8]}")
    user_a = User(email=f"a-{uuid.uuid4().hex[:8]}@example.com", password_hash="x", full_name="A")
    user_b = User(email=f"b-{uuid.uuid4().hex[:8]}@example.com", password_hash="x", full_name="B")
    owner_session.add_all([tenant_a, tenant_b, user_a, user_b])
    await owner_session.flush()
    owner_session.add_all(
        [
            Membership(tenant_id=tenant_a.id, user_id=user_a.id, role=MembershipRole.OWNER),
            Membership(tenant_id=tenant_b.id, user_id=user_b.id, role=MembershipRole.OWNER),
        ]
    )
    await owner_session.commit()

    await set_tenant_context(db_session, tenant_a.id)
    rows = (await db_session.execute(select(Membership.tenant_id))).scalars().all()

    assert rows == [tenant_a.id]


async def test_cannot_insert_into_another_tenant(
    db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    tenant_a = Tenant(name="Alpha Agri", slug=f"alpha-{uuid.uuid4().hex[:8]}")
    tenant_b = Tenant(name="Beta Agri", slug=f"beta-{uuid.uuid4().hex[:8]}")
    user = User(email=f"x-{uuid.uuid4().hex[:8]}@example.com", password_hash="x", full_name="X")
    owner_session.add_all([tenant_a, tenant_b, user])
    await owner_session.commit()

    await set_tenant_context(db_session, tenant_a.id)
    db_session.add(Membership(tenant_id=tenant_b.id, user_id=user.id, role=MembershipRole.MEMBER))

    with pytest.raises(DBAPIError, match="row-level security"):
        await db_session.commit()
    await db_session.rollback()
