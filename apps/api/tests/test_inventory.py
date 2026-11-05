"""Inventory: the ledger, the balance projection, adjustments and batches.

The tests care about two properties above all: stock can never go negative, and
``inventory_balances`` always equals the sum of the ledger.
"""

import asyncio
import uuid
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import MembershipRole
from app.modules.inventory.service import reconcile
from app.modules.tenancy.context import set_tenant_context
from tests.support import (
    adjust_api,
    auth_header,
    create_product_api,
    login,
    make_membership,
    make_user,
    seed_member,
    seeded_login,
    unit_id,
)


async def test_opening_balance_sets_the_balance(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, headers)

    result = await adjust_api(client, headers, product_id=product["id"], quantity="12.5")

    assert result["balance_before"] == "0.0000"
    assert result["balance_after"] == "12.5000"
    assert result["movement"]["movement_type"] == "opening_balance"
    assert result["movement"]["direction"] == "in"
    assert result["movement"]["base_quantity"] == "12.5000"
    assert result["movement"]["created_by_name"] == "مستخدم اختبار"


async def test_opening_balance_is_allowed_only_once(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, headers)
    await adjust_api(client, headers, product_id=product["id"], quantity="2")

    response = await client.post(
        "/api/v1/inventory/adjustments",
        json={
            "product_id": product["id"],
            "movement_type": "opening_balance",
            "quantity": "2",
            "unit_id": str(unit_id("piece")),
            "reason": "رصيد افتتاحي ثانٍ",
        },
        headers=headers,
    )

    assert response.status_code == 409
    assert "opening balance" in response.json()["error"]["message"].lower()


async def test_adjustment_out_reduces_and_cannot_go_negative(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, headers)
    await adjust_api(client, headers, product_id=product["id"], quantity="10")

    result = await adjust_api(
        client,
        headers,
        product_id=product["id"],
        movement_type="adjustment_out",
        quantity="4",
        reason="تالف",
    )
    assert result["balance_after"] == "6.0000"
    assert result["movement"]["direction"] == "out"
    assert result["movement"]["base_quantity"] == "-4.0000"

    rejected = await client.post(
        "/api/v1/inventory/adjustments",
        json={
            "product_id": product["id"],
            "movement_type": "adjustment_out",
            "quantity": "7",
            "unit_id": str(unit_id("piece")),
            "reason": "جرد",
        },
        headers=headers,
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["details"] == {
        "available": "6.0000",
        "requested": "7.0000",
    }


async def test_conversion_converts_to_the_base_unit(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, headers, base_unit="piece")
    conversion = await client.post(
        f"/api/v1/products/{product['id']}/conversions",
        json={
            "from_unit_id": str(unit_id("pack")),
            "to_unit_id": str(unit_id("piece")),
            "factor": "12",
        },
        headers=headers,
    )
    assert conversion.status_code == 201, conversion.text

    result = await adjust_api(
        client,
        headers,
        product_id=product["id"],
        quantity="2",
        unit_code="pack",
        reason="رصيد افتتاحي بالعبوة",
    )

    assert result["movement"]["unit_code"] == "pack"
    assert Decimal(result["movement"]["quantity"]) == Decimal("2")
    assert Decimal(result["movement"]["base_quantity"]) == Decimal("24")
    assert Decimal(result["balance_after"]) == Decimal("24")


async def test_unknown_conversion_is_rejected(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, headers, base_unit="piece")

    response = await client.post(
        "/api/v1/inventory/adjustments",
        json={
            "product_id": product["id"],
            "movement_type": "opening_balance",
            "quantity": "1",
            "unit_id": str(unit_id("box")),
            "reason": "رصيد افتتاحي",
        },
        headers=headers,
    )

    assert response.status_code == 422
    assert "conversion" in response.json()["error"]["message"].lower()


async def test_future_movement_types_are_not_writable(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, headers)

    response = await client.post(
        "/api/v1/inventory/adjustments",
        json={
            "product_id": product["id"],
            "movement_type": "sale",
            "quantity": "1",
            "unit_id": str(unit_id("piece")),
            "reason": "بيع",
        },
        headers=headers,
    )

    assert response.status_code == 422


async def test_cashier_cannot_adjust_stock(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, owner_headers, tenant, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, owner_headers)

    cashier_user = await make_user(owner_session)
    await make_membership(
        owner_session, tenant=tenant, user=cashier_user, role=MembershipRole.CASHIER
    )
    await owner_session.commit()
    headers = auth_header(await login(client, cashier_user.email, tenant_id=tenant.id))

    response = await client.post(
        "/api/v1/inventory/adjustments",
        json={
            "product_id": product["id"],
            "movement_type": "opening_balance",
            "quantity": "1",
            "unit_id": str(unit_id("piece")),
            "reason": "رصيد افتتاحي",
        },
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["details"]["permission"] == "inventory.adjust"


async def test_cost_is_recorded_only_by_roles_that_may_see_it(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, owner_headers, tenant, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, owner_headers, cost_price="10.00")

    owner_adjust = await adjust_api(
        client, owner_headers, product_id=product["id"], quantity="5", unit_cost="10"
    )
    assert Decimal(owner_adjust["movement"]["unit_cost"]) == Decimal("10")

    manager_user = await make_user(owner_session)
    await make_membership(
        owner_session,
        tenant=tenant,
        user=manager_user,
        role=MembershipRole.INVENTORY_MANAGER,
    )
    await owner_session.commit()
    manager_headers = auth_header(await login(client, manager_user.email, tenant_id=tenant.id))

    manager_product = await create_product_api(client, manager_headers)
    forbidden = await client.post(
        "/api/v1/inventory/adjustments",
        json={
            "product_id": manager_product["id"],
            "movement_type": "opening_balance",
            "quantity": "1",
            "unit_id": str(unit_id("piece")),
            "reason": "رصيد افتتاحي",
            "unit_cost": "10",
        },
        headers=manager_headers,
    )
    assert forbidden.status_code == 403

    movements = await client.get(
        "/api/v1/inventory/movements",
        params={"product_id": product["id"]},
        headers=manager_headers,
    )
    assert movements.json()["total"] == 1
    assert movements.json()["items"][0]["unit_cost"] is None


async def test_batches_are_required_when_the_product_tracks_them(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, headers, tracks_batches=True)

    missing = await client.post(
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
    assert missing.status_code == 422
    assert "batch" in missing.json()["error"]["message"].lower()

    created = await client.post(
        "/api/v1/inventory/batches",
        json={
            "product_id": product["id"],
            "batch_number": "B-2026-01",
            "expiry_date": "2027-06-30",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert Decimal(created.json()["quantity"]) == Decimal("0")

    opening = await adjust_api(
        client,
        headers,
        product_id=product["id"],
        quantity="5",
        batch_id=created.json()["id"],
    )
    assert opening["movement"]["batch_number"] == "B-2026-01"


async def test_batch_is_forbidden_when_the_product_does_not_track_them(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, headers)
    batch = await client.post(
        "/api/v1/inventory/batches",
        json={"product_id": product["id"], "batch_number": "B-1"},
        headers=headers,
    )
    assert batch.status_code == 422

    another = await create_product_api(client, headers, tracks_batches=True)
    batch = await client.post(
        "/api/v1/inventory/batches",
        json={"product_id": another["id"], "batch_number": "B-1"},
        headers=headers,
    )
    response = await client.post(
        "/api/v1/inventory/adjustments",
        json={
            "product_id": product["id"],
            "movement_type": "opening_balance",
            "quantity": "1",
            "unit_id": str(unit_id("piece")),
            "reason": "رصيد افتتاحي",
            "batch_id": batch.json()["id"],
        },
        headers=headers,
    )
    assert response.status_code == 422


async def test_batch_stock_cannot_go_negative(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, headers, tracks_batches=True)
    first = (
        await client.post(
            "/api/v1/inventory/batches",
            json={"product_id": product["id"], "batch_number": "B-A"},
            headers=headers,
        )
    ).json()
    second = (
        await client.post(
            "/api/v1/inventory/batches",
            json={"product_id": product["id"], "batch_number": "B-B"},
            headers=headers,
        )
    ).json()

    await adjust_api(client, headers, product_id=product["id"], quantity="5", batch_id=first["id"])
    await adjust_api(
        client,
        headers,
        product_id=product["id"],
        movement_type="adjustment_in",
        quantity="5",
        reason="توريد دفعة ثانية",
        batch_id=second["id"],
    )

    response = await client.post(
        "/api/v1/inventory/adjustments",
        json={
            "product_id": product["id"],
            "movement_type": "adjustment_out",
            "quantity": "6",
            "unit_id": str(unit_id("piece")),
            "reason": "صرف",
            "batch_id": second["id"],
        },
        headers=headers,
    )

    assert response.status_code == 409
    assert "batch" in response.json()["error"]["message"].lower()


async def test_duplicate_batch_number_is_rejected(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, headers, tracks_batches=True)
    payload = {"product_id": product["id"], "batch_number": "B-DUP"}

    first = await client.post("/api/v1/inventory/batches", json=payload, headers=headers)
    duplicate = await client.post("/api/v1/inventory/batches", json=payload, headers=headers)

    assert first.status_code == 201
    assert duplicate.status_code == 409


async def test_concurrent_adjustments_cannot_oversell(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, headers)
    await adjust_api(client, headers, product_id=product["id"], quantity="10")

    payload = {
        "product_id": product["id"],
        "movement_type": "adjustment_out",
        "quantity": "8",
        "unit_id": str(unit_id("piece")),
        "reason": "صرف متزامن",
    }
    responses = await asyncio.gather(
        client.post("/api/v1/inventory/adjustments", json=payload, headers=headers),
        client.post("/api/v1/inventory/adjustments", json=payload, headers=headers),
    )

    assert sorted(response.status_code for response in responses) == [201, 409]

    detail = await client.get(f"/api/v1/inventory/{product['id']}", headers=headers)
    assert detail.json()["product"]["quantity"] == "2.0000"


async def test_ledger_and_projection_reconcile(
    client: AsyncClient, owner_session: AsyncSession, db_session: AsyncSession
) -> None:
    _, headers, tenant, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, headers)
    await adjust_api(client, headers, product_id=product["id"], quantity="10")
    await adjust_api(
        client,
        headers,
        product_id=product["id"],
        movement_type="adjustment_out",
        quantity="3",
        reason="تالف",
    )
    await adjust_api(
        client,
        headers,
        product_id=product["id"],
        movement_type="adjustment_in",
        quantity="1.5",
        reason="جرد",
    )

    await set_tenant_context(db_session, tenant.id)
    ledger, projection = await reconcile(
        db_session, tenant_id=tenant.id, product_id=uuid.UUID(product["id"])
    )

    assert ledger == Decimal("8.5000")
    assert projection == Decimal("8.5000")


async def test_movements_are_immutable_for_the_runtime_role(
    client: AsyncClient, owner_session: AsyncSession, db_session: AsyncSession
) -> None:
    _, headers, tenant, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, headers)
    movement = (await adjust_api(client, headers, product_id=product["id"], quantity="5"))[
        "movement"
    ]

    await set_tenant_context(db_session, tenant.id)
    with pytest.raises(DBAPIError):
        await db_session.execute(
            text("UPDATE stock_movements SET quantity = 99 WHERE id = :mid"),
            {"mid": movement["id"]},
        )


async def test_movement_list_filters_and_ledger_order(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, headers)
    await adjust_api(client, headers, product_id=product["id"], quantity="5")
    await adjust_api(
        client,
        headers,
        product_id=product["id"],
        movement_type="adjustment_in",
        quantity="2",
        reason="توريد",
    )

    listed = await client.get(
        "/api/v1/inventory/movements",
        params={"product_id": product["id"]},
        headers=headers,
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 2
    assert listed.json()["items"][0]["movement_type"] == "adjustment_in"

    filtered = await client.get(
        "/api/v1/inventory/movements",
        params={"movement_type": "opening_balance"},
        headers=headers,
    )
    assert filtered.json()["total"] == 1


async def test_inventory_list_filters_by_stock_state(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    empty = await create_product_api(client, headers, name_ar="منتج بلا رصيد")
    low = await create_product_api(client, headers, name_ar="منتج قارب النفاد", minimum_stock="5")
    ok = await create_product_api(client, headers, name_ar="منتج متوفر", minimum_stock="5")

    await adjust_api(client, headers, product_id=low["id"], quantity="3")
    await adjust_api(client, headers, product_id=ok["id"], quantity="30")

    out_rows = await client.get("/api/v1/inventory", params={"stock": "out"}, headers=headers)
    low_rows = await client.get("/api/v1/inventory", params={"stock": "low"}, headers=headers)
    ok_rows = await client.get("/api/v1/inventory", params={"stock": "ok"}, headers=headers)

    assert [row["product_id"] for row in out_rows.json()["items"]] == [empty["id"]]
    assert [row["product_id"] for row in low_rows.json()["items"]] == [low["id"]]
    assert [row["product_id"] for row in ok_rows.json()["items"]] == [ok["id"]]


async def test_inventory_detail_returns_batches_and_recent_movements(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, headers, tracks_batches=True)
    batch = (
        await client.post(
            "/api/v1/inventory/batches",
            json={"product_id": product["id"], "batch_number": "B-DETAIL"},
            headers=headers,
        )
    ).json()
    await adjust_api(client, headers, product_id=product["id"], quantity="4", batch_id=batch["id"])

    detail = await client.get(f"/api/v1/inventory/{product['id']}", headers=headers)

    assert detail.status_code == 200, detail.text
    body: dict[str, Any] = detail.json()
    assert body["product"]["quantity"] == "4.0000"
    assert body["batches"][0]["quantity"] == "4.0000"
    assert body["movements"][0]["batch_number"] == "B-DETAIL"


async def test_inventory_is_tenant_scoped(client: AsyncClient, owner_session: AsyncSession) -> None:
    _, owner_headers, _, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, owner_headers)

    _, other_headers, _, _ = await seeded_login(client, owner_session, tenant_name="متجر آخر")
    assert (
        await client.get(f"/api/v1/inventory/{product['id']}", headers=other_headers)
    ).status_code == 404
    listed = await client.get("/api/v1/inventory", headers=other_headers)
    assert listed.json()["total"] == 0


async def test_balance_row_requires_a_real_product(
    db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    """The composite FK is the backstop if a service call ever forgets a check."""
    _, tenant, _ = await seed_member(owner_session)

    await set_tenant_context(db_session, tenant.id)
    with pytest.raises(DBAPIError):
        await db_session.execute(
            text(
                "INSERT INTO inventory_balances (tenant_id, product_id, quantity) "
                "VALUES (:tenant, :product, 0)"
            ),
            {"tenant": str(tenant.id), "product": str(uuid.uuid4())},
        )
