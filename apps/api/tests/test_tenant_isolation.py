"""Tenant isolation tests.

These are the security tests that matter most: if they pass while the runtime
role is a superuser or owns the tables, they prove nothing. The first test
guards that precondition.
"""

import uuid

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.modules.identity.models import Membership, MembershipRole, Tenant, User
from app.modules.tenancy.context import (
    clear_tenant_context,
    current_tenant_id,
    set_tenant_context,
)


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
    db_session.add(Membership(tenant_id=tenant_b.id, user_id=user.id, role=MembershipRole.CASHIER))

    with pytest.raises(DBAPIError, match="row-level security"):
        await db_session.commit()
    await db_session.rollback()


async def test_invalid_tenant_context_returns_no_rows(
    db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    owner_session.add(Tenant(name="Invalid Context Ltd", slug=f"ic-{uuid.uuid4().hex[:8]}"))
    await owner_session.commit()

    await set_tenant_context(db_session, uuid.uuid4())
    count = (await db_session.execute(text("SELECT count(*) FROM tenants"))).scalar_one()

    assert count == 0, "an unknown tenant id must behave like no tenant at all"


async def test_cross_tenant_update_is_a_no_op(
    db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    tenant_a = Tenant(name="Alpha Agri", slug=f"alpha-{uuid.uuid4().hex[:8]}")
    tenant_b = Tenant(name="Beta Agri", slug=f"beta-{uuid.uuid4().hex[:8]}")
    owner_session.add_all([tenant_a, tenant_b])
    await owner_session.commit()

    await set_tenant_context(db_session, tenant_a.id)
    result = await db_session.execute(
        update(Tenant).where(Tenant.id == tenant_b.id).values(name="tampered")
    )

    assert result.rowcount == 0
    await db_session.rollback()
    await owner_session.refresh(tenant_b)
    assert tenant_b.name == "Beta Agri"


async def test_cross_tenant_delete_is_a_no_op(
    db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    tenant_a = Tenant(name="Alpha Agri", slug=f"alpha-{uuid.uuid4().hex[:8]}")
    tenant_b = Tenant(name="Beta Agri", slug=f"beta-{uuid.uuid4().hex[:8]}")
    user = User(email=f"d-{uuid.uuid4().hex[:8]}@example.com", password_hash="x", full_name="D")
    owner_session.add_all([tenant_a, tenant_b, user])
    await owner_session.flush()
    owner_session.add(Membership(tenant_id=tenant_b.id, user_id=user.id, role=MembershipRole.OWNER))
    await owner_session.commit()

    await set_tenant_context(db_session, tenant_a.id)
    tenants_deleted = await db_session.execute(delete(Tenant).where(Tenant.id == tenant_b.id))
    memberships_deleted = await db_session.execute(
        delete(Membership).where(Membership.tenant_id == tenant_b.id)
    )

    assert tenants_deleted.rowcount == 0
    assert memberships_deleted.rowcount == 0
    await db_session.rollback()

    surviving = (
        (
            await owner_session.execute(
                select(Membership.id).where(Membership.tenant_id == tenant_b.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(surviving) == 1


async def test_set_config_is_transaction_local(owner_session: AsyncSession) -> None:
    """The raw database guarantee behind pooled-connection safety."""
    tenant_a = Tenant(name="Alpha Agri", slug=f"alpha-{uuid.uuid4().hex[:8]}")
    owner_session.add(tenant_a)
    await owner_session.commit()

    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect() as connection:
            await connection.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": str(tenant_a.id)},
            )
            inside = (
                await connection.execute(text("SELECT current_setting('app.tenant_id', true)"))
            ).scalar_one()
            assert inside == str(tenant_a.id)

            await connection.commit()

            after = (
                await connection.execute(text("SELECT current_setting('app.tenant_id', true)"))
            ).scalar_one_or_none()
            assert after in (None, ""), "the setting outlived its transaction"
    finally:
        await engine.dispose()


async def test_pooled_connection_does_not_leak_tenant_context(
    owner_session: AsyncSession,
) -> None:
    tenant_a = Tenant(name="Alpha Agri", slug=f"alpha-{uuid.uuid4().hex[:8]}")
    tenant_b = Tenant(name="Beta Agri", slug=f"beta-{uuid.uuid4().hex[:8]}")
    owner_session.add_all([tenant_a, tenant_b])
    await owner_session.commit()

    # pool_size=1 so the second session is guaranteed the first one's connection.
    engine = create_async_engine(get_settings().database_url, pool_size=1, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as first:
            await set_tenant_context(first, tenant_a.id)
            visible = (await first.execute(select(Tenant.id))).scalars().all()
            backend = (await first.execute(text("SELECT pg_backend_pid()"))).scalar_one()
            assert visible == [tenant_a.id]
            await first.rollback()

        async with factory() as second:
            assert (
                await second.execute(text("SELECT pg_backend_pid()"))
            ).scalar_one() == backend, "the pool handed out a different connection"

            leaked = (
                await second.execute(text("SELECT current_setting('app.tenant_id', true)"))
            ).scalar_one_or_none()
            assert leaked in (None, ""), "tenant context survived into the next borrower"
            assert (await second.execute(select(Tenant.id))).scalars().all() == []
    finally:
        await engine.dispose()


async def test_clearing_the_context_fails_closed(
    db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    tenant_a = Tenant(name="Alpha Agri", slug=f"alpha-{uuid.uuid4().hex[:8]}")
    owner_session.add(tenant_a)
    await owner_session.commit()

    await set_tenant_context(db_session, tenant_a.id)
    assert await current_tenant_id(db_session) == tenant_a.id

    await clear_tenant_context(db_session)
    assert await current_tenant_id(db_session) is None
    assert (await db_session.execute(select(Tenant.id))).scalars().all() == []


async def test_lookup_function_is_secured(db_session: AsyncSession) -> None:
    row = (
        await db_session.execute(
            text(
                """
                SELECT p.prosecdef AS is_security_definer,
                       p.proowner::regrole::text AS owner_name,
                       p.proacl IS NULL AS has_default_acl,
                       EXISTS (
                           SELECT 1 FROM aclexplode(p.proacl) AS a
                           WHERE a.grantee = 0 AND a.privilege_type = 'EXECUTE'
                       ) AS public_can_execute
                FROM pg_proc AS p
                JOIN pg_namespace AS n ON n.oid = p.pronamespace
                WHERE p.proname = 'app_user_tenants' AND n.nspname = 'public'
                """
            )
        )
    ).one()

    assert row.is_security_definer is True
    assert row.has_default_acl is False, "PUBLIC keeps the default EXECUTE grant"
    assert row.public_can_execute is False
    assert row.owner_name != "zain_app"


async def test_lookup_function_only_returns_the_callers_workspaces(
    db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    user_a = User(email=f"a-{uuid.uuid4().hex[:8]}@example.com", password_hash="x", full_name="A")
    user_b = User(email=f"b-{uuid.uuid4().hex[:8]}@example.com", password_hash="x", full_name="B")
    tenant_a = Tenant(name="Alpha Agri", slug=f"alpha-{uuid.uuid4().hex[:8]}")
    tenant_b = Tenant(name="Beta Agri", slug=f"beta-{uuid.uuid4().hex[:8]}")
    owner_session.add_all([user_a, user_b, tenant_a, tenant_b])
    await owner_session.flush()
    owner_session.add_all(
        [
            Membership(tenant_id=tenant_a.id, user_id=user_a.id, role=MembershipRole.OWNER),
            Membership(tenant_id=tenant_b.id, user_id=user_b.id, role=MembershipRole.OWNER),
        ]
    )
    await owner_session.commit()

    rows = (
        (
            await db_session.execute(
                text("SELECT tenant_id FROM app_user_tenants(CAST(:uid AS uuid))"),
                {"uid": user_a.id},
            )
        )
        .scalars()
        .all()
    )

    assert rows == [tenant_a.id]
    other = (
        (
            await db_session.execute(
                text("SELECT tenant_id FROM app_user_tenants(CAST(:uid AS uuid))"),
                {"uid": uuid.uuid4()},
            )
        )
        .scalars()
        .all()
    )
    assert other == []
