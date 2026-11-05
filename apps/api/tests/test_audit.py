"""Audit trail: attribution, atomicity, scope and immutability."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import MembershipRole
from app.modules.tenancy.context import set_tenant_context
from tests.support import (
    adjust_api,
    auth_header,
    create_product_api,
    seed_member,
    seeded_login,
    unit_id,
)


async def test_writes_are_attributed_to_the_actor(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    body, headers, _, user = await seeded_login(client, owner_session)
    product = await create_product_api(client, headers)

    response = await client.get("/api/v1/audit", headers=headers)

    assert response.status_code == 200, response.text
    entries = response.json()["items"]
    created = next(entry for entry in entries if entry["action"] == "product.created")
    assert created["entity_type"] == "product"
    assert created["entity_id"] == product["id"]
    assert created["actor_id"] == str(user.id)
    assert created["actor_name"] == "مستخدم اختبار"
    assert created["after_state"]["sku"] == product["sku"]
    assert created["before_state"] is None


async def test_movement_audit_records_the_balance_transition(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, headers)
    await adjust_api(client, headers, product_id=product["id"], quantity="7")

    response = await client.get(
        "/api/v1/audit",
        params={"action": "inventory.movement.created"},
        headers=headers,
    )

    entry = response.json()["items"][0]
    assert entry["entity_type"] == "stock_movement"
    assert entry["after_state"]["base_quantity"] == "7.0000"
    assert entry["meta"]["balance_before"] == "0.0000"
    assert entry["meta"]["balance_after"] == "7.0000"
    assert entry["meta"]["reason"] == "رصيد افتتاحي"


async def test_update_and_archive_keep_before_and_after(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, headers, name_ar="اسم قديم")

    await client.patch(
        f"/api/v1/products/{product['id']}", json={"name_ar": "اسم جديد"}, headers=headers
    )
    await client.delete(f"/api/v1/products/{product['id']}", headers=headers)

    response = await client.get(
        "/api/v1/audit",
        params={"entity_type": "product", "entity_id": product["id"]},
        headers=headers,
    )
    actions = [entry["action"] for entry in response.json()["items"]]

    assert actions == ["product.archived", "product.updated", "product.created"]
    updated = next(
        entry for entry in response.json()["items"] if entry["action"] == "product.updated"
    )
    assert updated["before_state"]["name_ar"] == "اسم قديم"
    assert updated["after_state"]["name_ar"] == "اسم جديد"


async def test_a_rejected_operation_leaves_no_audit_row(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, headers)
    await adjust_api(client, headers, product_id=product["id"], quantity="3")

    rejected = await client.post(
        "/api/v1/inventory/adjustments",
        json={
            "product_id": product["id"],
            "movement_type": "adjustment_out",
            "quantity": "10",
            "unit_id": str(unit_id("piece")),
            "reason": "صرف أكبر من الرصيد",
        },
        headers=headers,
    )
    assert rejected.status_code == 409

    response = await client.get(
        "/api/v1/audit",
        params={"action": "inventory.movement.created"},
        headers=headers,
    )
    assert response.json()["total"] == 1

    movements = await client.get("/api/v1/inventory/movements", headers=headers)
    assert movements.json()["total"] == 1


async def test_audit_is_owner_only(client: AsyncClient, owner_session: AsyncSession) -> None:
    for role in (
        MembershipRole.MANAGER,
        MembershipRole.CASHIER,
        MembershipRole.INVENTORY_MANAGER,
    ):
        _, headers, _, _ = await seeded_login(client, owner_session, role=role)

        response = await client.get("/api/v1/audit", headers=headers)

        assert response.status_code == 403, role
        assert response.json()["error"]["details"]["permission"] == "audit.read"


async def test_audit_is_tenant_scoped(client: AsyncClient, owner_session: AsyncSession) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    await create_product_api(client, headers)

    _, other_headers, _, _ = await seeded_login(client, owner_session, tenant_name="متجر آخر")
    response = await client.get("/api/v1/audit", headers=other_headers)

    assert response.status_code == 200
    assert response.json()["total"] == 0


async def test_catalog_audit_covers_categories_brands_and_conversions(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    category = (
        await client.post("/api/v1/categories", json={"name": "أسمدة"}, headers=headers)
    ).json()
    await client.patch(
        f"/api/v1/categories/{category['id']}", json={"name": "أسمدة معدنية"}, headers=headers
    )
    await client.post("/api/v1/brands", json={"name": "شل"}, headers=headers)

    for action, entity_type in (
        ("category.created", "product_category"),
        ("category.updated", "product_category"),
        ("brand.created", "brand"),
    ):
        response = await client.get("/api/v1/audit", params={"action": action}, headers=headers)
        assert response.json()["total"] == 1, action
        assert response.json()["items"][0]["entity_type"] == entity_type


async def test_audit_rows_cannot_be_edited_or_deleted_by_the_runtime_role(
    client: AsyncClient, owner_session: AsyncSession, db_session: AsyncSession
) -> None:
    _, headers, tenant, _ = await seeded_login(client, owner_session)
    await create_product_api(client, headers)
    entry = (await client.get("/api/v1/audit", headers=headers)).json()["items"][0]

    await set_tenant_context(db_session, tenant.id)
    with pytest.raises(DBAPIError):
        await db_session.execute(
            text("UPDATE audit_logs SET action = 'tampered' WHERE id = :id"),
            {"id": entry["id"]},
        )

    with pytest.raises(DBAPIError):
        await db_session.execute(text("DELETE FROM audit_logs WHERE id = :id"), {"id": entry["id"]})


async def test_audit_states_never_contain_credentials(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    await create_product_api(client, headers)

    response = await client.get("/api/v1/audit", headers=headers)
    payload = response.text.lower()

    for fragment in ("password", "access_token", "refresh_token", "secret", "authorization"):
        assert fragment not in payload


async def test_audit_filter_by_actor(client: AsyncClient, owner_session: AsyncSession) -> None:
    _, headers, _, owner = await seeded_login(client, owner_session)
    await create_product_api(client, headers)

    response = await client.get(
        "/api/v1/audit", params={"actor_id": str(owner.id)}, headers=headers
    )
    assert response.json()["total"] == 1

    response = await client.get(
        "/api/v1/audit", params={"actor_id": str(uuid.uuid4())}, headers=headers
    )
    assert response.json()["total"] == 0


async def test_audit_requires_a_session(client: AsyncClient) -> None:
    response = await client.get("/api/v1/audit")

    assert response.status_code == 401


async def test_audit_is_visible_across_roles_of_the_same_owner_only(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    """A second owner account in the same workspace sees the shared trail."""
    from app.modules.identity.models import Membership

    _, headers, tenant, _ = await seeded_login(client, owner_session)
    await create_product_api(client, headers)

    second, _, _ = await seed_member(owner_session, tenant_name="مساحة أخرى")
    owner_session.add(Membership(tenant_id=tenant.id, user_id=second.id, role=MembershipRole.OWNER))
    await owner_session.commit()
    second_body = await client.post(
        "/api/v1/auth/login",
        json={"email": second.email, "password": "ZainAgri!2026", "tenant_id": str(tenant.id)},
    )
    second_headers = auth_header(second_body.json())

    response = await client.get("/api/v1/audit", headers=second_headers)

    assert response.status_code == 200
    assert response.json()["total"] == 1
