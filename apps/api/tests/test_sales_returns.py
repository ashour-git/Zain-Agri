"""Sales returns: stock back to the same batches, credit first then cash, limits."""

from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import MembershipRole
from tests.sales_support import SALES, balance_of, line, sale_body, sell, stocked_product
from tests.support import (
    adjust_api,
    auth_header,
    login,
    make_membership,
    make_user,
    seeded_login,
)


def _return_body(*lines: tuple[str, str], reason: str = "الزبون رجّع الصنف") -> dict[str, Any]:
    return {
        "lines": [{"line_id": line_id, "quantity": quantity} for line_id, quantity in lines],
        "reason": reason,
    }


async def _give_back(
    client: AsyncClient,
    headers: dict[str, str],
    invoice: dict[str, Any],
    *lines: tuple[str, str],
    expected: int = 201,
) -> dict[str, Any]:
    response = await client.post(
        f"{SALES}/{invoice['id']}/returns", json=_return_body(*lines), headers=headers
    )
    assert response.status_code == expected, response.text
    result: dict[str, Any] = response.json()
    return result


async def _customer(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post("/api/v1/customers", json={"name": "الحاج سيد"}, headers=headers)
    assert response.status_code == 201, response.text
    customer_id: str = response.json()["id"]
    return customer_id


async def _balance(client: AsyncClient, headers: dict[str, str], customer_id: str) -> str:
    statement = (
        await client.get(f"/api/v1/customers/{customer_id}/statement", headers=headers)
    ).json()
    balance: str = statement["balance"]
    return balance


async def _batch_quantities(session: AsyncSession, product_id: str) -> dict[str, Decimal]:
    rows = await session.execute(
        text(
            "SELECT b.batch_number, coalesce(sum(m.base_quantity), 0) FROM product_batches b"
            " LEFT JOIN stock_movements m ON m.batch_id = b.id"
            " WHERE b.product_id = :p GROUP BY b.batch_number"
        ),
        {"p": product_id},
    )
    return {number: Decimal(quantity) for number, quantity in rows.all()}


async def test_return_puts_stock_back_to_the_same_batches(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers, quantity="0", tracks_batches=True)
    for number, expiry in (("EARLY", "2026-12-31"), ("LATE", "2027-06-30")):
        created = await client.post(
            "/api/v1/inventory/batches",
            json={"product_id": product["id"], "batch_number": number, "expiry_date": expiry},
            headers=headers,
        )
        await adjust_api(
            client, headers, product_id=product["id"], quantity="2", batch_id=created.json()["id"]
        )
    invoice = await sell(client, headers, sale_body([line(product, "3")]))
    line_id = invoice["lines"][0]["id"]

    await _give_back(client, headers, invoice, (line_id, "1"))
    after_first = await _batch_quantities(owner_session, product["id"])
    await _give_back(client, headers, invoice, (line_id, "2"))
    after_second = await _batch_quantities(owner_session, product["id"])

    # The most recent draw (LATE) is refilled first, then EARLY.
    assert after_first == {"EARLY": Decimal("0"), "LATE": Decimal("2")}
    assert after_second == {"EARLY": Decimal("2"), "LATE": Decimal("2")}
    kinds = (
        await owner_session.execute(
            text(
                "SELECT DISTINCT reference_type FROM stock_movements"
                " WHERE product_id = :p AND movement_type = 'customer_return'"
            ),
            {"p": product["id"]},
        )
    ).scalars()
    assert list(kinds) == ["sales_return"]


async def test_return_of_a_plain_product_restores_the_balance(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers, quantity="10")
    invoice = await sell(client, headers, sale_body([line(product, "4")]))

    await _give_back(client, headers, invoice, (invoice["lines"][0]["id"], "3"))

    assert await balance_of(client, headers, product["id"]) == Decimal("9")
    detail = (await client.get(f"{SALES}/{invoice['id']}", headers=headers)).json()
    assert detail["lines"][0]["returned_quantity"] == "3.0000"
    assert detail["returned_total"] == "75.00"


async def test_cannot_return_more_than_sold_minus_returned(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers)
    invoice = await sell(client, headers, sale_body([line(product, "3")]))
    line_id = invoice["lines"][0]["id"]

    await _give_back(client, headers, invoice, (line_id, "2"))
    refused = await _give_back(client, headers, invoice, (line_id, "2"), expected=422)

    assert refused["error"]["code"] == "unprocessable"
    assert await balance_of(client, headers, product["id"]) == Decimal("9")


async def test_return_reduces_credit_first_then_cash(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers, quantity="20", sale_price="10.00")
    customer_id = await _customer(client, headers)
    invoice = await sell(
        client, headers, sale_body([line(product, "10")], customer_id=customer_id, paid="60")
    )
    assert await _balance(client, headers, customer_id) == "40.00"

    result = await _give_back(client, headers, invoice, (invoice["lines"][0]["id"], "7"))

    assert (result["total"], result["credit_reduction"], result["cash_refund"]) == (
        "70.00",
        "40.00",
        "30.00",
    )
    assert await _balance(client, headers, customer_id) == "0.00"
    statement = (
        await client.get(f"/api/v1/customers/{customer_id}/statement", headers=headers)
    ).json()
    assert [entry["kind"] for entry in statement["lines"]] == ["invoice", "return"]


async def test_second_return_only_takes_what_is_still_owed(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers, quantity="20", sale_price="10.00")
    customer_id = await _customer(client, headers)
    invoice = await sell(
        client, headers, sale_body([line(product, "10")], customer_id=customer_id, paid="60")
    )
    line_id = invoice["lines"][0]["id"]

    first = await _give_back(client, headers, invoice, (line_id, "3"))
    second = await _give_back(client, headers, invoice, (line_id, "3"))

    assert (first["credit_reduction"], first["cash_refund"]) == ("30.00", "0.00")
    assert (second["credit_reduction"], second["cash_refund"]) == ("10.00", "20.00")
    assert await _balance(client, headers, customer_id) == "0.00"


async def test_cash_invoice_return_is_all_cash(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers)
    invoice = await sell(client, headers, sale_body([line(product, "2")]))

    result = await _give_back(client, headers, invoice, (invoice["lines"][0]["id"], "1"))

    assert (result["total"], result["credit_reduction"], result["cash_refund"]) == (
        "25.00",
        "0.00",
        "25.00",
    )


async def test_return_refunds_the_discounted_price(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers)
    # 4 x 25 = 100, discount 20: each piece really cost 20.
    invoice = await sell(client, headers, sale_body([line(product, "4")], discount="20"))
    line_id = invoice["lines"][0]["id"]

    one = await _give_back(client, headers, invoice, (line_id, "1"))
    rest = await _give_back(client, headers, invoice, (line_id, "3"))

    assert one["total"] == "20.00"
    assert rest["total"] == "60.00"
    detail = (await client.get(f"{SALES}/{invoice['id']}", headers=headers)).json()
    assert detail["returned_total"] == "80.00"


async def test_free_item_can_be_returned(client: AsyncClient, owner_session: AsyncSession) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers)
    invoice = await sell(client, headers, sale_body([line(product, "1", unit_price="0")]))

    result = await _give_back(client, headers, invoice, (invoice["lines"][0]["id"], "1"))

    assert result["total"] == "0.00"
    assert await balance_of(client, headers, product["id"]) == Decimal("10")


async def test_line_from_another_invoice_is_refused(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers)
    first = await sell(client, headers, sale_body([line(product)]))
    second = await sell(client, headers, sale_body([line(product)]))

    await _give_back(client, headers, first, (second["lines"][0]["id"], "1"), expected=422)


async def test_return_numbers_are_separate_and_consecutive(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers)
    first = await sell(client, headers, sale_body([line(product, "2")]))
    second = await sell(client, headers, sale_body([line(product, "2")]))

    one = await _give_back(client, headers, second, (second["lines"][0]["id"], "1"))
    two = await _give_back(client, headers, first, (first["lines"][0]["id"], "1"))
    third = await sell(client, headers, sale_body([line(product)]))

    assert (one["number"], two["number"]) == (1, 2)
    assert third["number"] == 3


async def test_cashier_cannot_return(client: AsyncClient, owner_session: AsyncSession) -> None:
    _, owner, tenant, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, owner)
    cashier_user = await make_user(owner_session)
    await make_membership(
        owner_session, tenant=tenant, user=cashier_user, role=MembershipRole.CASHIER
    )
    await owner_session.commit()
    cashier = auth_header(await login(client, cashier_user.email, tenant_id=tenant.id))
    invoice = await sell(client, cashier, sale_body([line(product)]))

    await _give_back(client, cashier, invoice, (invoice["lines"][0]["id"], "1"), expected=403)


async def test_another_shop_cannot_return(client: AsyncClient, owner_session: AsyncSession) -> None:
    _, mine, _, _ = await seeded_login(client, owner_session, tenant_name="متجري")
    _, theirs, _, _ = await seeded_login(client, owner_session, tenant_name="متجر آخر")
    product = await stocked_product(client, mine)
    invoice = await sell(client, mine, sale_body([line(product, "2")]))

    await _give_back(client, theirs, invoice, (invoice["lines"][0]["id"], "1"), expected=404)
    assert await balance_of(client, mine, product["id"]) == Decimal("8")
