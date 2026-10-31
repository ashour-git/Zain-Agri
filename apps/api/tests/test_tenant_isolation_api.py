"""Cross-tenant access through the HTTP API.

The database suite proves RLS holds. This suite proves the application layer
cannot be talked out of it either — there is no request field anywhere that
selects a workspace other than the one bound to the caller's session.
"""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import MembershipRole, Tenant
from tests.support import auth_header, login, seed_member


async def test_each_session_only_ever_sees_its_own_workspace(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    user_a, tenant_a, _ = await seed_member(owner_session, tenant_name="متجر أ")
    user_b, tenant_b, _ = await seed_member(owner_session, tenant_name="متجر ب")

    body_a = await login(client, user_a.email)
    body_b = await login(client, user_b.email)

    first = await client.get("/api/v1/tenants/current", headers=auth_header(body_a))
    second = await client.get("/api/v1/tenants/current", headers=auth_header(body_b))

    assert first.json()["id"] == str(tenant_a.id)
    assert second.json()["id"] == str(tenant_b.id)
    assert tenant_b.name not in first.text


async def test_interleaved_requests_never_cross_tenants(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    """Six alternating calls over one pooled connection."""
    user_a, tenant_a, _ = await seed_member(owner_session, tenant_name="متجر أ")
    user_b, tenant_b, _ = await seed_member(owner_session, tenant_name="متجر ب")
    body_a = await login(client, user_a.email)
    body_b = await login(client, user_b.email)
    headers_a = auth_header(body_a)
    headers_b = auth_header(body_b)

    for _ in range(3):
        assert (await client.get("/api/v1/tenants/current", headers=headers_a)).json()["id"] == str(
            tenant_a.id
        )
        assert (await client.get("/api/v1/tenants/current", headers=headers_b)).json()["id"] == str(
            tenant_b.id
        )


async def test_member_listing_never_includes_another_workspace(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    owner_a, tenant_a, _ = await seed_member(owner_session, tenant_name="متجر أ")
    owner_b, _, _ = await seed_member(owner_session, tenant_name="متجر ب")

    body = await login(client, owner_a.email)
    response = await client.get("/api/v1/tenants/current/members", headers=auth_header(body))

    assert response.status_code == 200
    assert [row["email"] for row in response.json()] == [owner_a.email]
    assert owner_b.email not in response.text


async def test_renaming_a_workspace_cannot_touch_another(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    owner_a, _, _ = await seed_member(owner_session, tenant_name="متجر أ")
    _, tenant_b, _ = await seed_member(owner_session, tenant_name="متجر ب")

    body = await login(client, owner_a.email)
    response = await client.patch(
        "/api/v1/tenants/current", json={"name": "اسم مستعار"}, headers=auth_header(body)
    )
    assert response.status_code == 200

    await owner_session.refresh(tenant_b)
    assert tenant_b.name == "متجر ب"


async def test_a_workspace_id_in_the_body_is_ignored(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    """Passing someone else's tenant_id to the rename endpoint changes nothing."""
    owner_a, tenant_a, _ = await seed_member(owner_session, tenant_name="متجر أ")
    _, tenant_b, _ = await seed_member(owner_session, tenant_name="متجر ب")

    body = await login(client, owner_a.email)
    response = await client.patch(
        "/api/v1/tenants/current",
        json={"name": "اسم جديد", "tenant_id": str(tenant_b.id)},
        headers=auth_header(body),
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(tenant_a.id)

    await owner_session.refresh(tenant_b)
    assert tenant_b.name == "متجر ب"


async def test_role_in_one_workspace_does_not_grant_it_in_another(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    """The same person can be OWNER here and CASHIER there."""
    from tests.support import make_membership, make_tenant, make_user

    user = await make_user(owner_session)
    own = await make_tenant(owner_session, name="متجره")
    borrowed = await make_tenant(owner_session, name="متجر غيره")
    await make_membership(owner_session, tenant=own, user=user, role=MembershipRole.OWNER)
    await make_membership(owner_session, tenant=borrowed, user=user, role=MembershipRole.CASHIER)
    await owner_session.commit()

    manager_here = await login(client, user.email, tenant_id=own.id)
    cashier_there = await login(client, user.email, tenant_id=borrowed.id)

    assert (
        await client.patch(
            "/api/v1/tenants/current",
            json={"name": "جديد"},
            headers=auth_header(manager_here),
        )
    ).status_code == 200
    assert (
        await client.patch(
            "/api/v1/tenants/current",
            json={"name": "جديد"},
            headers=auth_header(cashier_there),
        )
    ).status_code == 403

    await owner_session.refresh(borrowed)
    assert borrowed.name == "متجر غيره"


async def test_deleting_the_workspace_ends_its_sessions(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    """`refresh_sessions.tenant_id` cascades, so the session dies with the workspace."""
    user, tenant, _ = await seed_member(owner_session)
    body = await login(client, user.email)
    assert (
        await client.get("/api/v1/tenants/current", headers=auth_header(body))
    ).status_code == 200

    await owner_session.delete(await owner_session.get(Tenant, tenant.id))
    await owner_session.commit()

    # The access token names a session row that no longer exists.
    assert (
        await client.get("/api/v1/tenants/current", headers=auth_header(body))
    ).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers=auth_header(body))).status_code == 401
