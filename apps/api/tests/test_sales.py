"""Creating a sale: invoice, stock, credit, numbering, prices and idempotency."""

import asyncio
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import MembershipRole
from tests.sales_support import (
    SALES,
    add_conversion,
    balance_of,
    line,
    sale_body,
    sell,
    stocked_product,
)
from tests.support import adjust_api, seeded_login, unit_id


async def _customer(client: AsyncClient, headers: dict[str, str], name: str = "الحاج محمود") -> str:
    response = await client.post("/api/v1/customers", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    customer_id: str = response.json()["id"]
    return customer_id


async def _customer_balance(client: AsyncClient, headers: dict[str, str], customer_id: str) -> str:
    statement = (
        await client.get(f"/api/v1/customers/{customer_id}/statement", headers=headers)
    ).json()
    balance: str = statement["balance"]
    return balance


async def test_cash_sale_creates_invoice_and_takes_stock(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, tenant, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers, quantity="10", name_ar="يوريا")

    invoice = await sell(client, headers, sale_body([line(product, "3")]))

    assert invoice["number"] == 1
    assert (invoice["subtotal"], invoice["total"], invoice["paid"], invoice["credit"]) == (
        "75.00",
        "75.00",
        "75.00",
        "0.00",
    )
    assert invoice["lines"][0]["name_ar"] == "يوريا"
    assert invoice["lines"][0]["line_total"] == "75.00"
    assert await balance_of(client, headers, product["id"]) == Decimal("7")
    movement = (
        await owner_session.execute(
            text(
                "SELECT movement_type::text AS kind, base_quantity, reference_type, reference_id"
                " FROM stock_movements WHERE tenant_id = :t AND movement_type = 'sale'"
            ),
            {"t": tenant.id},
        )
    ).one()
    assert (movement.kind, movement.base_quantity) == ("sale", Decimal("-3"))
    assert (movement.reference_type, str(movement.reference_id)) == ("sales_invoice", invoice["id"])


async def test_paid_defaults_to_the_total(client: AsyncClient, owner_session: AsyncSession) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers)

    invoice = await sell(client, headers, sale_body([line(product, "2")]))

    assert (invoice["paid"], invoice["credit"]) == ("50.00", "0.00")


async def test_numbers_are_consecutive_per_shop(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, mine, _, _ = await seeded_login(client, owner_session, tenant_name="متجري")
    _, theirs, _, _ = await seeded_login(client, owner_session, tenant_name="متجر آخر")
    a = await stocked_product(client, mine)
    b = await stocked_product(client, theirs)

    numbers = [(await sell(client, mine, sale_body([line(a)])))["number"] for _ in range(2)]
    other = (await sell(client, theirs, sale_body([line(b)])))["number"]

    assert numbers == [1, 2]
    assert other == 1


async def test_concurrent_sales_get_distinct_numbers(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers, quantity="20")

    responses = await asyncio.gather(
        *(client.post(SALES, json=sale_body([line(product)]), headers=headers) for _ in range(5))
    )

    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    assert sorted(r.json()["number"] for r in responses) == [1, 2, 3, 4, 5]
    assert await balance_of(client, headers, product["id"]) == Decimal("15")


async def test_not_enough_stock_writes_nothing_and_names_the_product(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, tenant, _ = await seeded_login(client, owner_session)
    plenty = await stocked_product(client, headers, quantity="10", name_ar="كثير")
    scarce = await stocked_product(client, headers, quantity="1", name_ar="قليل")

    response = await client.post(
        SALES, json=sale_body([line(plenty, "2"), line(scarce, "2")]), headers=headers
    )

    assert response.status_code == 409
    assert response.json()["error"]["details"]["product_name"] == "قليل"
    assert await balance_of(client, headers, plenty["id"]) == Decimal("10")
    invoices = (
        await owner_session.execute(
            text("SELECT count(*) FROM sales_invoices WHERE tenant_id = :t"), {"t": tenant.id}
        )
    ).scalar_one()
    assert invoices == 0


async def test_same_product_twice_checks_combined_stock(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers, quantity="5")

    response = await client.post(
        SALES, json=sale_body([line(product, "3"), line(product, "3")]), headers=headers
    )

    assert response.status_code == 409
    assert await balance_of(client, headers, product["id"]) == Decimal("5")


async def test_converted_unit_price_uses_the_factor(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers, quantity="30", sale_price="12.50")
    await add_conversion(client, headers, product["id"], "box", "piece", "12")

    invoice = await sell(
        client, headers, sale_body([line(product, "2", unit_id=str(unit_id("box")))])
    )

    assert invoice["lines"][0]["unit_price"] == "150.00"
    assert invoice["lines"][0]["base_quantity"] == "24.0000"
    assert invoice["total"] == "300.00"
    assert await balance_of(client, headers, product["id"]) == Decimal("6")


async def test_rounding_is_half_up_per_line(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers, quantity="10", sale_price="0.33")

    invoice = await sell(client, headers, sale_body([line(product, "1.5")]))

    assert invoice["lines"][0]["line_total"] == "0.50"  # 0.495 -> 0.50


async def test_cashier_cannot_change_price_or_discount(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, owner, tenant, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, owner)
    from tests.support import login, make_membership, make_user

    cashier_user = await make_user(owner_session)
    await make_membership(
        owner_session, tenant=tenant, user=cashier_user, role=MembershipRole.CASHIER
    )
    await owner_session.commit()
    from tests.support import auth_header

    cashier = auth_header(await login(client, cashier_user.email, tenant_id=tenant.id))

    price = await client.post(
        SALES, json=sale_body([line(product, unit_price="20")]), headers=cashier
    )
    discount = await client.post(
        SALES, json=sale_body([line(product)], discount="5"), headers=cashier
    )
    same_price = await client.post(
        SALES, json=sale_body([line(product, unit_price="25.00")]), headers=cashier
    )

    assert price.status_code == 403
    assert discount.status_code == 403
    assert same_price.status_code == 201  # the normal price is not a change


async def test_owner_can_change_price_and_discount_up_to_subtotal(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers)

    invoice = await sell(
        client, headers, sale_body([line(product, "2", unit_price="20")], discount="5")
    )
    too_much = await client.post(
        SALES, json=sale_body([line(product)], discount="26"), headers=headers
    )

    assert (invoice["subtotal"], invoice["discount"], invoice["total"]) == (
        "40.00",
        "5.00",
        "35.00",
    )
    assert too_much.status_code == 422


async def test_product_without_price_blocks_the_cashier_but_not_the_owner(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, owner, tenant, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, owner, sale_price=None)
    from tests.support import auth_header, login, make_membership, make_user

    cashier_user = await make_user(owner_session)
    await make_membership(
        owner_session, tenant=tenant, user=cashier_user, role=MembershipRole.CASHIER
    )
    await owner_session.commit()
    cashier = auth_header(await login(client, cashier_user.email, tenant_id=tenant.id))

    blocked = await client.post(SALES, json=sale_body([line(product)]), headers=cashier)
    no_price_owner = await client.post(SALES, json=sale_body([line(product)]), headers=owner)
    priced_owner = await client.post(
        SALES, json=sale_body([line(product, unit_price="30")]), headers=owner
    )

    assert blocked.status_code == 422
    assert (
        blocked.json()["error"]["message"] == "لا يوجد سعر بيع لهذا الصنف. اطلب من المالك تحديده."
    )
    assert no_price_owner.status_code == 422
    assert priced_owner.status_code == 201


async def test_cash_customer_must_pay_in_full(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers)

    response = await client.post(SALES, json=sale_body([line(product)], paid="10"), headers=headers)

    assert response.status_code == 422
    assert (
        response.json()["error"]["message"]
        == "الزبون النقدي يدفع المبلغ كاملًا. اختر عميلًا للبيع بالآجل."
    )


async def test_credit_sale_posts_statement_line(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers)
    customer_id = await _customer(client, headers)

    invoice = await sell(
        client, headers, sale_body([line(product, "4")], paid="40", customer_id=customer_id)
    )

    assert (invoice["paid"], invoice["credit"]) == ("40.00", "60.00")
    assert invoice["customer"]["name"] == "الحاج محمود"
    assert await _customer_balance(client, headers, customer_id) == "60.00"
    statement = (
        await client.get(f"/api/v1/customers/{customer_id}/statement", headers=headers)
    ).json()
    assert statement["lines"][0]["reference_id"] == invoice["id"]


async def test_fully_paid_customer_sale_adds_no_statement_line(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers)
    customer_id = await _customer(client, headers)

    await sell(client, headers, sale_body([line(product)], customer_id=customer_id))

    statement = (
        await client.get(f"/api/v1/customers/{customer_id}/statement", headers=headers)
    ).json()
    assert statement["lines"] == []


async def test_paid_more_than_total_is_refused(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers)
    customer_id = await _customer(client, headers)

    response = await client.post(
        SALES, json=sale_body([line(product)], paid="30", customer_id=customer_id), headers=headers
    )

    assert response.status_code == 422


async def test_inactive_customer_cannot_buy(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers)
    customer_id = await _customer(client, headers)
    await client.patch(f"/api/v1/customers/{customer_id}", json={"active": False}, headers=headers)

    response = await client.post(
        SALES, json=sale_body([line(product)], paid="0", customer_id=customer_id), headers=headers
    )

    assert response.status_code == 422
    assert response.json()["error"]["message"] == "هذا العميل موقوف. فعّله أولًا أو اختر عميلًا آخر."


async def test_fefo_across_batches(client: AsyncClient, owner_session: AsyncSession) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers, quantity="0", tracks_batches=True)
    batch_ids = {}
    for number, expiry in (("LATE", "2027-01-31"), ("EARLY", "2026-12-31"), ("NONE", None)):
        body = {"product_id": product["id"], "batch_number": number}
        if expiry:
            body["expiry_date"] = expiry
        created = await client.post("/api/v1/inventory/batches", json=body, headers=headers)
        batch_ids[number] = created.json()["id"]
        await adjust_api(
            client, headers, product_id=product["id"], quantity="2", batch_id=batch_ids[number]
        )

    invoice = await sell(client, headers, sale_body([line(product, "5")]))

    draws = {d["batch_number"]: d["base_quantity"] for d in invoice["lines"][0]["batches"]}
    assert draws == {"EARLY": "2.0000", "LATE": "2.0000", "NONE": "1.0000"}
    assert await balance_of(client, headers, product["id"]) == Decimal("1")


async def test_same_key_same_body_returns_the_same_invoice(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers)
    body = sale_body([line(product, "2")], key="counter-key-0001")

    first = await client.post(SALES, json=body, headers=headers)
    again = await client.post(SALES, json=body, headers=headers)

    assert first.status_code == 201
    assert again.status_code == 200
    assert again.json()["id"] == first.json()["id"]
    assert await balance_of(client, headers, product["id"]) == Decimal("8")


async def test_same_key_other_body_is_refused(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers)
    await sell(client, headers, sale_body([line(product, "1")], key="counter-key-0002"))

    other = await client.post(
        SALES, json=sale_body([line(product, "2")], key="counter-key-0002"), headers=headers
    )

    assert other.status_code == 422
    assert other.json()["error"]["message"] == "هذا الطلب أُرسل من قبل ببيانات مختلفة."


async def test_concurrent_duplicates_make_one_invoice(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers)
    body = sale_body([line(product)], key="counter-key-0003")

    responses = await asyncio.gather(
        *(client.post(SALES, json=body, headers=headers) for _ in range(3))
    )

    assert {r.status_code for r in responses} <= {200, 201}
    assert len({r.json()["id"] for r in responses}) == 1
    assert await balance_of(client, headers, product["id"]) == Decimal("9")


async def test_storekeeper_cannot_sell(client: AsyncClient, owner_session: AsyncSession) -> None:
    _, headers, _, _ = await seeded_login(
        client, owner_session, role=MembershipRole.INVENTORY_MANAGER
    )
    product = await stocked_product(client, headers)

    response = await client.post(SALES, json=sale_body([line(product)]), headers=headers)

    assert response.status_code == 403


async def test_archived_product_cannot_be_sold(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers)
    await client.delete(f"/api/v1/products/{product['id']}", headers=headers)

    response = await client.post(SALES, json=sale_body([line(product)]), headers=headers)

    assert response.status_code in (409, 422)


async def test_another_shops_product_is_not_found(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, mine, _, _ = await seeded_login(client, owner_session, tenant_name="متجري")
    _, theirs, _, _ = await seeded_login(client, owner_session, tenant_name="متجر آخر")
    their_product = await stocked_product(client, theirs)

    response = await client.post(SALES, json=sale_body([line(their_product)]), headers=mine)

    assert response.status_code == 404
    assert await balance_of(client, theirs, their_product["id"]) == Decimal("10")


async def test_lines_are_required(client: AsyncClient, owner_session: AsyncSession) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)

    response = await client.post(SALES, json=sale_body([]), headers=headers)

    assert response.status_code == 422


async def test_balances_equal_movements_after_sales(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, tenant, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers, quantity="10")
    for quantity in ("1", "2.5"):
        await sell(client, headers, sale_body([line(product, quantity)]))

    row = (
        await owner_session.execute(
            text(
                "SELECT b.quantity AS balance, SUM(m.base_quantity) AS moved"
                " FROM inventory_balances b JOIN stock_movements m"
                " ON m.tenant_id = b.tenant_id AND m.product_id = b.product_id"
                " WHERE b.tenant_id = :t GROUP BY b.quantity"
            ),
            {"t": tenant.id},
        )
    ).one()
    assert row.balance == row.moved == Decimal("6.5")


async def test_manual_adjustment_cannot_record_a_sale(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers)

    for kind in ("sale", "customer_return"):
        response = await client.post(
            "/api/v1/inventory/adjustments",
            json={
                "product_id": product["id"],
                "movement_type": kind,
                "quantity": "1",
                "unit_id": str(unit_id("piece")),
                "reason": "محاولة يدوية",
            },
            headers=headers,
        )
        assert response.status_code == 422, kind


async def test_lines_keep_the_order_they_were_entered(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    names = ["ي", "أ", "م", "ب", "س"]
    products = [await stocked_product(client, headers, name_ar=name) for name in names]

    invoice = await sell(client, headers, sale_body([line(p) for p in products]))

    assert [entry["name_ar"] for entry in invoice["lines"]] == names
