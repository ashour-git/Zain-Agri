"""Role-based access control, enforced on the server.

The important property under test is that authorisation is re-derived from the
database on every request: a token minted while an account was privileged must
stop working the moment the membership or the workspace changes.
"""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authorization.permissions import (
    ROLE_PERMISSIONS,
    Permission,
    permissions_for,
)
from app.modules.identity.models import (
    MembershipRole,
    MembershipStatus,
    TenantStatus,
    User,
)
from tests.support import auth_header, login, seed_member

ALL_ROLES = [
    MembershipRole.OWNER,
    MembershipRole.MANAGER,
    MembershipRole.CASHIER,
    MembershipRole.INVENTORY_MANAGER,
]


# --- the policy table itself ------------------------------------------------


def test_owner_holds_every_permission() -> None:
    assert permissions_for(MembershipRole.OWNER) == frozenset(Permission)


CATALOG_EDIT = {
    Permission.PRODUCTS_READ,
    Permission.PRODUCTS_CREATE,
    Permission.PRODUCTS_UPDATE,
    Permission.PRODUCTS_ARCHIVE,
    Permission.CATEGORIES_MANAGE,
}


def test_role_matrix_matches_the_documented_policy() -> None:
    assert permissions_for(MembershipRole.MANAGER) == frozenset(
        {
            Permission.SALES_OPERATE,
            Permission.SALES_REFUND,
            Permission.PURCHASES_MANAGE,
            Permission.REPORTS_VIEW,
            Permission.INVENTORY_READ,
            Permission.INVENTORY_ADJUST,
            Permission.BATCHES_MANAGE,
            *CATALOG_EDIT,
        }
    )
    assert permissions_for(MembershipRole.CASHIER) == frozenset(
        {
            Permission.SALES_OPERATE,
            Permission.PRODUCTS_READ,
            Permission.INVENTORY_READ,
        }
    )
    assert permissions_for(MembershipRole.INVENTORY_MANAGER) == frozenset(
        {
            Permission.REPORTS_VIEW,
            Permission.INVENTORY_READ,
            Permission.INVENTORY_ADJUST,
            Permission.BATCHES_MANAGE,
            *CATALOG_EDIT,
        }
    )


@pytest.mark.parametrize("role", [MembershipRole.CASHIER, MembershipRole.INVENTORY_MANAGER])
def test_restricted_roles_have_no_financial_visibility(role: MembershipRole) -> None:
    assert Permission.FINANCE_VIEW not in permissions_for(role)
    assert Permission.USERS_MANAGE not in permissions_for(role)
    assert Permission.TENANT_SETTINGS_MANAGE not in permissions_for(role)


@pytest.mark.parametrize(
    "role",
    [MembershipRole.MANAGER, MembershipRole.CASHIER, MembershipRole.INVENTORY_MANAGER],
)
def test_cost_and_audit_visibility_is_owner_only(role: MembershipRole) -> None:
    """Seeing cost price or the audit trail is an owner decision, not a default."""
    assert Permission.INVENTORY_VIEW_COST not in permissions_for(role)
    assert Permission.AUDIT_READ not in permissions_for(role)


@pytest.mark.parametrize(
    "role",
    [MembershipRole.MANAGER, MembershipRole.CASHIER, MembershipRole.INVENTORY_MANAGER],
)
def test_only_the_owner_holds_every_permission(role: MembershipRole) -> None:
    assert permissions_for(role) < permissions_for(MembershipRole.OWNER)


def test_only_the_owner_manages_settings_and_users() -> None:
    for role in ALL_ROLES:
        grants = ROLE_PERMISSIONS[role]
        expected = role is MembershipRole.OWNER
        assert (Permission.TENANT_SETTINGS_MANAGE in grants) is expected
        assert (Permission.USERS_MANAGE in grants) is expected


# --- enforcement through the API -------------------------------------------


async def test_every_role_can_read_its_workspace(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    for role in ALL_ROLES:
        user, tenant, _ = await seed_member(owner_session, role=role)
        body = await login(client, user.email)

        response = await client.get("/api/v1/tenants/current", headers=auth_header(body))

        assert response.status_code == 200, f"{role}: {response.text}"
        assert response.json()["id"] == str(tenant.id)


async def test_permissions_endpoint_reflects_the_role(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    expected_by_role = {
        MembershipRole.OWNER: {p.value for p in Permission},
        MembershipRole.MANAGER: {
            "sales.operate",
            "sales.refund",
            "purchases.manage",
            "reports.view",
            "inventory.read",
            "inventory.adjust",
            "batches.manage",
            "products.read",
            "products.create",
            "products.update",
            "products.archive",
            "categories.manage",
        },
        MembershipRole.CASHIER: {"sales.operate", "products.read", "inventory.read"},
        MembershipRole.INVENTORY_MANAGER: {
            "reports.view",
            "inventory.read",
            "inventory.adjust",
            "batches.manage",
            "products.read",
            "products.create",
            "products.update",
            "products.archive",
            "categories.manage",
        },
    }

    for role, expected in expected_by_role.items():
        user, _, _ = await seed_member(owner_session, role=role)
        body = await login(client, user.email)

        response = await client.get(
            "/api/v1/tenants/current/permissions", headers=auth_header(body)
        )

        assert response.status_code == 200
        assert set(response.json()) == expected, role


@pytest.mark.parametrize(
    "role",
    [MembershipRole.MANAGER, MembershipRole.CASHIER, MembershipRole.INVENTORY_MANAGER],
)
async def test_non_owners_cannot_change_workspace_settings(
    client: AsyncClient, owner_session: AsyncSession, role: MembershipRole
) -> None:
    user, tenant, _ = await seed_member(owner_session, role=role)
    body = await login(client, user.email)

    response = await client.patch(
        "/api/v1/tenants/current", json={"name": "اسم جديد"}, headers=auth_header(body)
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert response.json()["error"]["details"]["permission"] == "tenant.settings.manage"

    await owner_session.refresh(tenant)
    assert tenant.name != "اسم جديد"


async def test_owner_can_change_workspace_settings(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    user, tenant, _ = await seed_member(owner_session)
    body = await login(client, user.email)

    response = await client.patch(
        "/api/v1/tenants/current", json={"name": "مؤسسة زين الزراعية"}, headers=auth_header(body)
    )

    assert response.status_code == 200, response.text
    assert response.json()["name"] == "مؤسسة زين الزراعية"

    await owner_session.refresh(tenant)
    assert tenant.name == "مؤسسة زين الزراعية"


@pytest.mark.parametrize(
    "role",
    [MembershipRole.MANAGER, MembershipRole.CASHIER, MembershipRole.INVENTORY_MANAGER],
)
async def test_only_the_owner_can_list_members(
    client: AsyncClient, owner_session: AsyncSession, role: MembershipRole
) -> None:
    user, _, _ = await seed_member(owner_session, role=role)
    body = await login(client, user.email)

    response = await client.get("/api/v1/tenants/current/members", headers=auth_header(body))

    assert response.status_code == 403
    assert response.json()["error"]["details"]["permission"] == "users.manage"


async def test_owner_listing_members_never_leaks_hashes(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    owner, tenant, _ = await seed_member(owner_session)
    cashier: User = (
        await seed_member(owner_session, role=MembershipRole.CASHIER, tenant_name="متجر آخر")
    )[0]
    from app.modules.identity.models import Membership

    owner_session.add(
        Membership(
            tenant_id=tenant.id,
            user_id=cashier.id,
            role=MembershipRole.CASHIER,
            status=MembershipStatus.ACTIVE,
        )
    )
    await owner_session.commit()

    body = await login(client, owner.email)
    response = await client.get("/api/v1/tenants/current/members", headers=auth_header(body))

    assert response.status_code == 200
    assert {row["email"] for row in response.json()} == {owner.email, cashier.email}
    assert "password_hash" not in response.text


async def test_missing_token_is_unauthorized_everywhere(client: AsyncClient) -> None:
    for method, path in [
        ("get", "/api/v1/tenants/current"),
        ("get", "/api/v1/tenants/current/members"),
        ("get", "/api/v1/tenants/current/permissions"),
        ("get", "/api/v1/auth/sessions"),
        ("get", "/api/v1/auth/me"),
    ]:
        response = await getattr(client, method)(path)
        assert response.status_code == 401, path


async def test_a_session_without_a_workspace_cannot_reach_tenant_routes(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    """Registration mints a token with no workspace; tenant routes must refuse."""
    email = f"nowhere-{uuid.uuid4().hex[:10]}@example.com"
    registered = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "ZainAgri!2026", "full_name": "مستخدم"},
    )
    headers = auth_header(registered.json())

    response = await client.get("/api/v1/tenants/current", headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["message"] == "No workspace selected for this session"


async def test_deactivating_a_membership_takes_effect_immediately(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    user, tenant, membership = await seed_member(owner_session, role=MembershipRole.MANAGER)
    body = await login(client, user.email)
    assert (
        await client.get("/api/v1/tenants/current", headers=auth_header(body))
    ).status_code == 200

    membership.status = MembershipStatus.SUSPENDED
    await owner_session.commit()

    blocked = await client.get("/api/v1/tenants/current", headers=auth_header(body))
    assert blocked.status_code == 403
    assert blocked.json()["error"]["message"] == "Your access to this workspace is not active"


async def test_suspending_a_workspace_takes_effect_immediately(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    user, tenant, _ = await seed_member(owner_session, role=MembershipRole.OWNER)
    body = await login(client, user.email)
    assert (
        await client.get("/api/v1/tenants/current", headers=auth_header(body))
    ).status_code == 200

    tenant.status = TenantStatus.SUSPENDED
    await owner_session.commit()

    blocked = await client.get("/api/v1/tenants/current", headers=auth_header(body))
    assert blocked.status_code == 403
    assert blocked.json()["error"]["message"] == "This workspace is suspended"


async def test_demoting_a_role_takes_effect_immediately(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    user, tenant, membership = await seed_member(owner_session, role=MembershipRole.OWNER)
    body = await login(client, user.email)

    membership.role = MembershipRole.CASHIER
    await owner_session.commit()

    allowed = await client.get("/api/v1/tenants/current", headers=auth_header(body))
    denied = await client.patch(
        "/api/v1/tenants/current", json={"name": "محاولة"}, headers=auth_header(body)
    )

    assert allowed.status_code == 200
    assert denied.status_code == 403


async def test_deactivating_the_account_invalidates_the_token(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    user, _, _ = await seed_member(owner_session)
    body = await login(client, user.email)

    await owner_session.execute(
        text("UPDATE users SET is_active = false WHERE id = :uid"), {"uid": user.id}
    )
    await owner_session.commit()

    response = await client.get("/api/v1/auth/me", headers=auth_header(body))
    assert response.status_code == 401


async def test_me_downgrades_gracefully_when_the_workspace_is_suspended(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    """`/auth/me` is a navigation aid: it reports no current workspace instead of 403."""
    user, tenant, _ = await seed_member(owner_session)
    body = await login(client, user.email)

    tenant.status = TenantStatus.SUSPENDED
    await owner_session.commit()

    payload: dict[str, Any] = (
        await client.get("/api/v1/auth/me", headers=auth_header(body))
    ).json()
    assert payload["tenant"] is None
    assert payload["requires_tenant_selection"] is True
    assert payload["tenants"][0]["status"] == "suspended"
