"""Product catalog: products, categories, brands, units and conversions.

Every assertion goes through the HTTP API so the permission checks, the
validation and the cost-visibility rules are exercised exactly as a browser
would exercise them.
"""

import uuid
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import MembershipRole
from tests.support import (
    adjust_api,
    auth_header,
    create_product_api,
    login,
    make_category,
    make_membership,
    make_tenant,
    make_user,
    product_payload,
    seed_member,
    seeded_login,
    unit_id,
)


async def test_units_are_seeded_reference_data(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)

    response = await client.get("/api/v1/units", headers=headers)

    assert response.status_code == 200, response.text
    units = response.json()
    assert len(units) == 9
    assert {unit["code"] for unit in units} >= {"piece", "kilogram", "liter"}
    assert {unit["dimension"] for unit in units} == {"count", "mass", "volume"}


async def test_create_product_starts_out_of_stock(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)

    response = await client.post(
        "/api/v1/products",
        json=product_payload(name_ar="سماد يوريا", sale_price="1250.50"),
        headers=headers,
    )

    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    assert body["name_ar"] == "سماد يوريا"
    assert body["sale_price"] == "1250.50"
    assert body["stock_quantity"] == "0.0000"
    assert body["stock_status"] == "out"
    assert body["status"] == "active"
    assert body["base_unit_code"] == "piece"
    assert body["conversions"] == []


async def test_owner_sees_cost_price_and_cashier_does_not(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, owner_headers, tenant, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, owner_headers, cost_price="40.00")

    cashier_user = await make_user(owner_session)
    await make_membership(
        owner_session, tenant=tenant, user=cashier_user, role=MembershipRole.CASHIER
    )
    await owner_session.commit()

    cashier_body = await login(client, cashier_user.email, tenant_id=tenant.id)
    cashier_headers = auth_header(cashier_body)

    owner_view = await client.get(f"/api/v1/products/{product['id']}", headers=owner_headers)
    cashier_view = await client.get(f"/api/v1/products/{product['id']}", headers=cashier_headers)

    assert owner_view.json()["cost_price"] == "40.00"
    assert cashier_view.status_code == 200
    assert cashier_view.json()["cost_price"] is None


async def test_a_role_without_cost_visibility_cannot_write_a_cost(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(
        client, owner_session, role=MembershipRole.INVENTORY_MANAGER
    )

    response = await client.post(
        "/api/v1/products",
        json=product_payload(cost_price="40.00"),
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["details"]["permission"] == "inventory.view_cost"


async def test_cashier_cannot_create_a_product(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session, role=MembershipRole.CASHIER)

    response = await client.post("/api/v1/products", json=product_payload(), headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["details"]["permission"] == "products.create"


async def test_sku_must_be_unique_per_workspace(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    await create_product_api(client, headers, sku="SKU-DUP")

    response = await client.post(
        "/api/v1/products", json=product_payload(sku="SKU-DUP"), headers=headers
    )

    assert response.status_code == 409
    assert response.json()["error"]["details"]["field"] == "sku"


async def test_barcode_must_be_unique_but_may_be_absent(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    await create_product_api(client, headers, barcode="6221031000001")

    duplicate = await client.post(
        "/api/v1/products", json=product_payload(barcode="6221031000001"), headers=headers
    )
    assert duplicate.status_code == 409

    first = await client.post("/api/v1/products", json=product_payload(), headers=headers)
    second = await client.post("/api/v1/products", json=product_payload(), headers=headers)
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["barcode"] is None


async def test_cross_tenant_category_is_rejected(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    other_tenant = await make_tenant(owner_session, name="متجر آخر")
    foreign_category = await make_category(owner_session, other_tenant, name="بذور الغير")
    await owner_session.commit()

    response = await client.post(
        "/api/v1/products",
        json=product_payload(category_id=str(foreign_category.id)),
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unprocessable"


async def test_unknown_unit_is_rejected(client: AsyncClient, owner_session: AsyncSession) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)

    response = await client.post(
        "/api/v1/products",
        json=product_payload(base_unit_id=str(uuid.uuid4())),
        headers=headers,
    )

    assert response.status_code == 422


async def test_archive_then_restore(client: AsyncClient, owner_session: AsyncSession) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, headers)

    archived = await client.delete(f"/api/v1/products/{product['id']}", headers=headers)
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "archived"

    update = await client.patch(
        f"/api/v1/products/{product['id']}", json={"name_ar": "اسم جديد"}, headers=headers
    )
    assert update.status_code == 409

    movement = await client.post(
        "/api/v1/inventory/adjustments",
        json={
            "product_id": product["id"],
            "movement_type": "opening_balance",
            "quantity": "5",
            "unit_id": str(unit_id("piece")),
            "reason": "رصيد افتتاحي",
        },
        headers=headers,
    )
    assert movement.status_code == 409

    restored = await client.post(f"/api/v1/products/{product['id']}/restore", headers=headers)
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == "active"


async def test_list_search_status_filter_and_pagination(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    interesting = await create_product_api(client, headers, name_ar="بذور كوسة")
    await create_product_api(client, headers, name_ar="مبيد حشري")
    await create_product_api(client, headers, name_ar="سماد عضوي")

    found = await client.get("/api/v1/products", params={"q": "كوسة"}, headers=headers)
    assert found.status_code == 200
    assert found.json()["total"] == 1
    assert found.json()["items"][0]["id"] == interesting["id"]

    paged = await client.get(
        "/api/v1/products", params={"page": 2, "page_size": 2}, headers=headers
    )
    assert paged.json()["total"] == 3
    assert len(paged.json()["items"]) == 1
    assert paged.json()["page"] == 2

    await client.delete(f"/api/v1/products/{interesting['id']}", headers=headers)
    active = await client.get("/api/v1/products", params={"status": "active"}, headers=headers)
    archived = await client.get("/api/v1/products", params={"status": "archived"}, headers=headers)
    assert active.json()["total"] == 2
    assert archived.json()["total"] == 1


async def test_stock_status_comes_from_the_balance(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, headers, minimum_stock="5")

    await adjust_api(client, headers, product_id=product["id"], quantity="3")

    listed = await client.get("/api/v1/products", params={"q": product["sku"]}, headers=headers)
    item = listed.json()["items"][0]
    assert item["stock_quantity"] == "3.0000"
    assert item["stock_status"] == "low"

    await adjust_api(
        client,
        headers,
        product_id=product["id"],
        movement_type="adjustment_in",
        quantity="10",
        reason="توريد إضافي",
    )
    listed = await client.get("/api/v1/products", params={"q": product["sku"]}, headers=headers)
    assert listed.json()["items"][0]["stock_status"] == "ok"


async def test_category_hierarchy_guardrails(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)

    root = await client.post("/api/v1/categories", json={"name": "أسمدة"}, headers=headers)
    assert root.status_code == 201, root.text
    child = await client.post(
        "/api/v1/categories",
        json={"name": "أسمدة آزوتية", "parent_id": root.json()["id"]},
        headers=headers,
    )
    assert child.status_code == 201

    duplicate = await client.post("/api/v1/categories", json={"name": "أسمدة"}, headers=headers)
    assert duplicate.status_code == 409

    cycle = await client.patch(
        f"/api/v1/categories/{root.json()['id']}",
        json={"parent_id": child.json()["id"]},
        headers=headers,
    )
    assert cycle.status_code == 409

    self_parent = await client.patch(
        f"/api/v1/categories/{root.json()['id']}",
        json={"parent_id": root.json()["id"]},
        headers=headers,
    )
    assert self_parent.status_code == 409


async def test_cashier_cannot_manage_categories(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session, role=MembershipRole.CASHIER)

    response = await client.post("/api/v1/categories", json={"name": "أسمدة"}, headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["details"]["permission"] == "categories.manage"


async def test_brand_names_are_unique_per_workspace(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)

    first = await client.post("/api/v1/brands", json={"name": "شل"}, headers=headers)
    duplicate = await client.post("/api/v1/brands", json={"name": "شل"}, headers=headers)
    listed = await client.get("/api/v1/brands", headers=headers)

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert [brand["name"] for brand in listed.json()] == ["شل"]


async def test_conversion_must_involve_the_base_unit_and_match_dimensions(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, headers, base_unit="kilogram")

    different_dimension = await client.post(
        f"/api/v1/products/{product['id']}/conversions",
        json={
            "from_unit_id": str(unit_id("liter")),
            "to_unit_id": str(unit_id("kilogram")),
            "factor": "1",
        },
        headers=headers,
    )
    assert different_dimension.status_code == 422

    valid = await client.post(
        f"/api/v1/products/{product['id']}/conversions",
        json={
            "from_unit_id": str(unit_id("gram")),
            "to_unit_id": str(unit_id("kilogram")),
            "factor": "0.001",
        },
        headers=headers,
    )
    assert valid.status_code == 201, valid.text
    assert Decimal(valid.json()["factor"]) == Decimal("0.001")

    reversed_duplicate = await client.post(
        f"/api/v1/products/{product['id']}/conversions",
        json={
            "from_unit_id": str(unit_id("kilogram")),
            "to_unit_id": str(unit_id("gram")),
            "factor": "1000",
        },
        headers=headers,
    )
    assert reversed_duplicate.status_code == 409

    counted = await create_product_api(client, headers, base_unit="piece")
    no_base_unit = await client.post(
        f"/api/v1/products/{counted['id']}/conversions",
        json={
            "from_unit_id": str(unit_id("gram")),
            "to_unit_id": str(unit_id("kilogram")),
            "factor": "1000",
        },
        headers=headers,
    )
    assert no_base_unit.status_code == 422
    assert "base unit" in no_base_unit.json()["error"]["message"].lower()

    detail = await client.get(f"/api/v1/products/{product['id']}", headers=headers)
    assert len(detail.json()["conversions"]) == 1


async def test_base_unit_is_frozen_once_stock_exists(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, headers, base_unit="piece")
    await adjust_api(client, headers, product_id=product["id"], quantity="4")

    response = await client.patch(
        f"/api/v1/products/{product['id']}",
        json={"base_unit_id": str(unit_id("kilogram"))},
        headers=headers,
    )

    assert response.status_code == 409


async def test_inventory_manager_may_edit_the_catalog_but_not_costs(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(
        client, owner_session, role=MembershipRole.INVENTORY_MANAGER
    )
    created = await create_product_api(client, headers)
    assert created["cost_price"] is None

    forbidden = await client.patch(
        f"/api/v1/products/{created['id']}", json={"cost_price": "10.00"}, headers=headers
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["details"]["permission"] == "inventory.view_cost"


@pytest.mark.parametrize(
    "role",
    [MembershipRole.MANAGER, MembershipRole.INVENTORY_MANAGER],
)
async def test_products_are_scoped_to_the_session_workspace(
    client: AsyncClient, owner_session: AsyncSession, role: MembershipRole
) -> None:
    _, owner_headers, _, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, owner_headers)

    other = await seed_member(owner_session, role=role, tenant_name="متجر آخر")
    other_headers = auth_header(await login(client, other[0].email))
    response = await client.get(f"/api/v1/products/{product['id']}", headers=other_headers)

    assert response.status_code == 404
