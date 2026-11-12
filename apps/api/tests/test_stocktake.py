"""Stocktake (جرد): count, review, apply once."""

from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import MembershipRole
from tests.support import (
    adjust_api,
    create_product_api,
    make_category,
    seeded_login,
    unit_id,
)

BASE = "/api/v1/stocktakes"


async def _start(client: AsyncClient, headers: dict[str, str], **body: Any) -> dict[str, Any]:
    response = await client.post(BASE, json={"scope": "all", **body}, headers=headers)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


async def _lines(client: AsyncClient, headers: dict[str, str], stocktake_id: str) -> list[Any]:
    response = await client.get(f"{BASE}/{stocktake_id}/lines", headers=headers)
    assert response.status_code == 200, response.text
    items: list[Any] = response.json()["items"]
    return items


async def _count(
    client: AsyncClient,
    headers: dict[str, str],
    stocktake_id: str,
    line_id: str,
    quantity: str,
    **extra: Any,
) -> Any:
    return await client.put(
        f"{BASE}/{stocktake_id}/lines/{line_id}",
        json={"quantity": quantity, **extra},
        headers=headers,
    )


async def _stocked(
    client: AsyncClient, headers: dict[str, str], quantity: str = "10", **product: Any
) -> dict[str, Any]:
    created = await create_product_api(client, headers, **product)
    await adjust_api(client, headers, product_id=created["id"], quantity=quantity)
    return created


async def _balance(client: AsyncClient, headers: dict[str, str], product_id: str) -> Decimal:
    items = (await client.get("/api/v1/inventory", headers=headers)).json()["items"]
    return Decimal(next(i for i in items if i["product_id"] == product_id)["quantity"])


async def test_start_creates_one_line_per_active_product(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    await _stocked(client, headers, name_ar="سماد أ")
    await _stocked(client, headers, name_ar="سماد ب")

    stocktake = await _start(client, headers)

    assert stocktake["status"] == "open"
    assert (stocktake["total_lines"], stocktake["counted_lines"]) == (2, 0)
    assert len(await _lines(client, headers, stocktake["id"])) == 2


async def test_scope_category_counts_only_that_category(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, tenant, _ = await seeded_login(client, owner_session)
    seeds = await make_category(owner_session, tenant, name="بذور")
    await owner_session.commit()
    inside = await _stocked(client, headers, name_ar="بذور خيار", category_id=str(seeds.id))
    await _stocked(client, headers, name_ar="يوريا")

    stocktake = await _start(client, headers, scope="category", category_id=str(seeds.id))
    lines = await _lines(client, headers, stocktake["id"])

    assert [line["product_id"] for line in lines] == [inside["id"]]


async def test_default_name_uses_an_arabic_month(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    import re

    _, headers, _, _ = await seeded_login(client, owner_session)
    await _stocked(client, headers)

    stocktake = await _start(client, headers)

    assert re.fullmatch(r"جرد \d{1,2} \S+ \d{4}", stocktake["name"])
    assert "-" not in stocktake["name"]


async def test_only_one_open_stocktake_per_shop(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    await _stocked(client, headers)
    first = await _start(client, headers)

    second = await client.post(BASE, json={"scope": "all"}, headers=headers)

    assert second.status_code == 409
    cancelled = await client.post(f"{BASE}/{first['id']}/cancel", headers=headers)
    assert cancelled.status_code == 200
    assert (await client.post(BASE, json={"scope": "all"}, headers=headers)).status_code == 201


async def test_blind_count_hides_system_quantity_until_counted(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    await _stocked(client, headers, quantity="10")
    stocktake = await _start(client, headers)
    [line] = await _lines(client, headers, stocktake["id"])

    assert line["system_quantity"] is None

    await _count(client, headers, stocktake["id"], line["line_id"], "9")
    [counted] = await _lines(client, headers, stocktake["id"])
    assert Decimal(counted["system_quantity"]) == Decimal("10")


async def test_open_count_shows_system_quantity_when_not_blind(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    await _stocked(client, headers, quantity="10")
    stocktake = await _start(client, headers, blind=False)

    [line] = await _lines(client, headers, stocktake["id"])

    assert Decimal(line["system_quantity"]) == Decimal("10")


async def test_apply_posts_shortage_surplus_and_leaves_uncounted_alone(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    short = await _stocked(client, headers, quantity="10", name_ar="ناقص")
    over = await _stocked(client, headers, quantity="10", name_ar="زائد")
    skipped = await _stocked(client, headers, quantity="10", name_ar="لم يُعدّ")
    same = await _stocked(client, headers, quantity="10", name_ar="مطابق")
    stocktake = await _start(client, headers)
    by_product = {
        line["product_id"]: line["line_id"]
        for line in await _lines(client, headers, stocktake["id"])
    }
    for product, counted in ((short, "7"), (over, "12"), (same, "10")):
        assert (
            await _count(client, headers, stocktake["id"], by_product[product["id"]], counted)
        ).status_code == 200

    review = (await client.get(f"{BASE}/{stocktake['id']}/review", headers=headers)).json()
    assert [Decimal(i["difference"]) for i in review["shortages"]] == [Decimal("-3")]
    assert [Decimal(i["difference"]) for i in review["surpluses"]] == [Decimal("2")]
    assert [i["product_id"] for i in review["uncounted"]] == [skipped["id"]]

    applied = await client.post(f"{BASE}/{stocktake['id']}/apply", headers=headers)

    assert applied.status_code == 200, applied.text
    assert applied.json()["corrections"] == 2
    assert await _balance(client, headers, short["id"]) == Decimal("7")
    assert await _balance(client, headers, over["id"]) == Decimal("12")
    assert await _balance(client, headers, skipped["id"]) == Decimal("10")
    assert await _balance(client, headers, same["id"]) == Decimal("10")
    done = (await client.get(f"{BASE}/{stocktake['id']}", headers=headers)).json()
    assert done["status"] == "applied"


async def test_stock_that_moved_after_counting_is_kept(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    """Counted 8 when the system said 10; 5 more arrive before apply: 13, not 8."""
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await _stocked(client, headers, quantity="10")
    stocktake = await _start(client, headers)
    [line] = await _lines(client, headers, stocktake["id"])
    await _count(client, headers, stocktake["id"], line["line_id"], "8")
    await adjust_api(
        client, headers, product_id=product["id"], movement_type="adjustment_in", quantity="5"
    )

    await client.post(f"{BASE}/{stocktake['id']}/apply", headers=headers)

    assert await _balance(client, headers, product["id"]) == Decimal("13")


async def test_shortage_reason_picks_the_movement_type(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, tenant, _ = await seeded_login(client, owner_session)
    product = await _stocked(client, headers, quantity="10")
    stocktake = await _start(client, headers)
    [line] = await _lines(client, headers, stocktake["id"])
    await _count(client, headers, stocktake["id"], line["line_id"], "6", shortage_reason="damage")

    await client.post(f"{BASE}/{stocktake['id']}/apply", headers=headers)

    rows = (
        await owner_session.execute(
            text(
                "SELECT movement_type::text AS kind, base_quantity, reference_type, reference_id"
                " FROM stock_movements WHERE tenant_id = :t AND product_id = :p"
                " ORDER BY created_at DESC LIMIT 1"
            ),
            {"t": tenant.id, "p": product["id"]},
        )
    ).one()
    assert rows.kind == "damage"
    assert rows.base_quantity == Decimal("-4")
    assert rows.reference_type == "stocktake"
    assert str(rows.reference_id) == stocktake["id"]


async def test_apply_is_atomic_when_one_correction_would_go_negative(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    fine = await _stocked(client, headers, quantity="10", name_ar="سليم")
    drained = await _stocked(client, headers, quantity="10", name_ar="سيُسحب")
    stocktake = await _start(client, headers)
    by_product = {
        line["product_id"]: line["line_id"]
        for line in await _lines(client, headers, stocktake["id"])
    }
    await _count(client, headers, stocktake["id"], by_product[fine["id"]], "12")
    await _count(client, headers, stocktake["id"], by_product[drained["id"]], "2")
    # Stock leaves after counting: 10 -> 1, so a -8 correction would go negative.
    await adjust_api(
        client, headers, product_id=drained["id"], movement_type="adjustment_out", quantity="9"
    )

    response = await client.post(f"{BASE}/{stocktake['id']}/apply", headers=headers)

    assert response.status_code == 409
    assert response.json()["error"]["details"]["product_name"] == "سيُسحب"
    assert await _balance(client, headers, fine["id"]) == Decimal("10")  # nothing posted
    assert (await client.get(f"{BASE}/{stocktake['id']}", headers=headers)).json()[
        "status"
    ] == "open"


async def test_finished_stocktakes_cannot_be_changed(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    await _stocked(client, headers)
    stocktake = await _start(client, headers)
    [line] = await _lines(client, headers, stocktake["id"])
    await client.post(f"{BASE}/{stocktake['id']}/cancel", headers=headers)

    count = await _count(client, headers, stocktake["id"], line["line_id"], "3")
    apply = await client.post(f"{BASE}/{stocktake['id']}/apply", headers=headers)
    cancel = await client.post(f"{BASE}/{stocktake['id']}/cancel", headers=headers)

    assert (count.status_code, apply.status_code, cancel.status_code) == (409, 409, 409)


async def test_count_converts_units_to_the_base_unit(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, headers, base_unit="piece")
    await adjust_api(client, headers, product_id=product["id"], quantity="20")
    conversion = await client.post(
        f"/api/v1/products/{product['id']}/conversions",
        json={
            "from_unit_id": str(unit_id("box")),
            "to_unit_id": str(unit_id("piece")),
            "factor": "12",
        },
        headers=headers,
    )
    assert conversion.status_code == 201, conversion.text
    stocktake = await _start(client, headers)
    [line] = await _lines(client, headers, stocktake["id"])

    await _count(
        client, headers, stocktake["id"], line["line_id"], "2", unit_id=str(unit_id("box"))
    )

    [counted] = await _lines(client, headers, stocktake["id"])
    assert Decimal(counted["counted_base_quantity"]) == Decimal("24")


async def test_batch_products_are_counted_per_batch(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await create_product_api(client, headers, tracks_batches=True)
    for number, quantity in (("B-1", "5"), ("B-2", "7")):
        batch = await client.post(
            "/api/v1/inventory/batches",
            json={"product_id": product["id"], "batch_number": number},
            headers=headers,
        )
        await adjust_api(
            client,
            headers,
            product_id=product["id"],
            quantity=quantity,
            batch_id=batch.json()["id"],
        )

    stocktake = await _start(client, headers)
    lines = {line["batch_number"]: line for line in await _lines(client, headers, stocktake["id"])}
    await _count(client, headers, stocktake["id"], lines["B-1"]["line_id"], "4")
    await _count(client, headers, stocktake["id"], lines["B-2"]["line_id"], "7")
    await client.post(f"{BASE}/{stocktake['id']}/apply", headers=headers)

    assert await _balance(client, headers, product["id"]) == Decimal("11")


async def test_negative_quantity_is_refused(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    await _stocked(client, headers)
    stocktake = await _start(client, headers)
    [line] = await _lines(client, headers, stocktake["id"])

    response = await _count(client, headers, stocktake["id"], line["line_id"], "-1")

    assert response.status_code == 422


async def test_balances_still_equal_movements_after_a_stocktake(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, tenant, _ = await seeded_login(client, owner_session)
    product = await _stocked(client, headers, quantity="10")
    stocktake = await _start(client, headers)
    [line] = await _lines(client, headers, stocktake["id"])
    await _count(client, headers, stocktake["id"], line["line_id"], "6")
    await client.post(f"{BASE}/{stocktake['id']}/apply", headers=headers)

    row = (
        await owner_session.execute(
            text(
                "SELECT b.quantity AS balance, SUM(m.base_quantity) AS moved"
                " FROM inventory_balances b JOIN stock_movements m"
                " ON m.tenant_id = b.tenant_id AND m.product_id = b.product_id"
                " WHERE b.tenant_id = :t AND b.product_id = :p GROUP BY b.quantity"
            ),
            {"t": tenant.id, "p": product["id"]},
        )
    ).one()
    assert row.balance == row.moved == Decimal("6")


@pytest.mark.parametrize("role", [MembershipRole.CASHIER])
async def test_cashier_cannot_use_stocktake(
    client: AsyncClient, owner_session: AsyncSession, role: MembershipRole
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session, role=role)

    assert (await client.post(BASE, json={"scope": "all"}, headers=headers)).status_code == 403
    assert (await client.get(BASE, headers=headers)).status_code == 403


async def test_storekeeper_can_count_and_apply(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(
        client, owner_session, role=MembershipRole.INVENTORY_MANAGER
    )
    product = await _stocked(client, headers, quantity="10")
    stocktake = await _start(client, headers)
    [line] = await _lines(client, headers, stocktake["id"])
    await _count(client, headers, stocktake["id"], line["line_id"], "9")

    applied = await client.post(f"{BASE}/{stocktake['id']}/apply", headers=headers)

    assert applied.status_code == 200
    assert await _balance(client, headers, product["id"]) == Decimal("9")


async def test_another_shop_cannot_see_or_touch_a_stocktake(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, mine, _, _ = await seeded_login(client, owner_session, tenant_name="متجري")
    await _stocked(client, mine)
    stocktake = await _start(client, mine)
    [line] = await _lines(client, mine, stocktake["id"])
    _, theirs, _, _ = await seeded_login(client, owner_session, tenant_name="متجر آخر")

    assert (await client.get(f"{BASE}/{stocktake['id']}", headers=theirs)).status_code == 404
    assert (await client.get(BASE, headers=theirs)).json()["items"] == []
    assert (await _count(client, theirs, stocktake["id"], line["line_id"], "1")).status_code == 404
    assert (await client.post(f"{BASE}/{stocktake['id']}/apply", headers=theirs)).status_code == 404


async def test_search_filters_lines_by_name_or_code(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    await _stocked(client, headers, name_ar="يوريا 46", sku="UREA-46")
    await _stocked(client, headers, name_ar="بذور خيار", sku="SEED-1")
    stocktake = await _start(client, headers)

    by_name = await client.get(f"{BASE}/{stocktake['id']}/lines?q=يوريا", headers=headers)
    by_code = await client.get(f"{BASE}/{stocktake['id']}/lines?q=seed-1", headers=headers)

    assert [i["name_ar"] for i in by_name.json()["items"]] == ["يوريا 46"]
    assert [i["name_ar"] for i in by_code.json()["items"]] == ["بذور خيار"]
