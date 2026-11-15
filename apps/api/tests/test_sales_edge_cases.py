"""Edge cases found in review: small units, rounding on full returns, batch switch, stable links."""

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import MembershipRole
from tests.sales_support import SALES, add_conversion, line, sale_body, sell, stocked_product
from tests.support import auth_header, login, make_membership, make_user, seeded_login, unit_id


async def _gram_product(client: AsyncClient, headers: dict[str, str], price: str) -> dict:
    product = await stocked_product(
        client, headers, quantity="10", base_unit="kilogram", sale_price=price
    )
    # 1 kilogram = 1000 gram
    await add_conversion(client, headers, product["id"], "kilogram", "gram", "1000")
    return product


async def test_small_unit_is_priced_without_rounding_the_unit_price_first(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    dear = await _gram_product(client, headers, "25.00")
    cheap = await _gram_product(client, headers, "24.00")
    gram = str(unit_id("gram"))

    half_kilo = await sell(client, headers, sale_body([line(dear, "500", unit_id=gram)]))
    one_kilo = await sell(client, headers, sale_body([line(cheap, "1000", unit_id=gram)]))

    assert half_kilo["total"] == "12.50"
    assert one_kilo["total"] == "24.00"


async def test_cashier_cannot_undercharge_by_sending_the_rounded_unit_price(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, owner, tenant, _ = await seeded_login(client, owner_session)
    product = await _gram_product(client, owner, "24.00")
    cashier_user = await make_user(owner_session)
    await make_membership(
        owner_session, tenant=tenant, user=cashier_user, role=MembershipRole.CASHIER
    )
    await owner_session.commit()
    cashier = auth_header(await login(client, cashier_user.email, tenant_id=tenant.id))
    gram = str(unit_id("gram"))

    invoice = await sell(
        client, cashier, sale_body([line(product, "1000", unit_id=gram, unit_price="0.02")])
    )

    assert invoice["total"] == "24.00"


async def _discounted_credit_invoice(
    client: AsyncClient, headers: dict[str, str]
) -> tuple[dict, str]:
    products = [await stocked_product(client, headers, sale_price="10.00") for _ in range(3)]
    customer = await client.post("/api/v1/customers", json={"name": "الحاج سيد"}, headers=headers)
    customer_id: str = customer.json()["id"]
    invoice = await sell(
        client,
        headers,
        sale_body(
            [line(product) for product in products],
            discount="20",
            customer_id=customer_id,
            paid="0",
        ),
    )
    assert invoice["total"] == "10.00"
    return invoice, customer_id


async def _balance(client: AsyncClient, headers: dict[str, str], customer_id: str) -> str:
    statement = await client.get(f"/api/v1/customers/{customer_id}/statement", headers=headers)
    balance: str = statement.json()["balance"]
    return balance


async def test_full_return_of_a_discounted_invoice_clears_the_debt(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    invoice, customer_id = await _discounted_credit_invoice(client, headers)

    response = await client.post(
        f"{SALES}/{invoice['id']}/returns",
        json={
            "lines": [{"line_id": row["id"], "quantity": "1"} for row in invoice["lines"]],
            "reason": "رجّع الكل",
        },
        headers=headers,
    )

    assert response.status_code == 201, response.text
    assert response.json()["total"] == "10.00"
    assert await _balance(client, headers, customer_id) == "0.00"


async def test_line_by_line_returns_of_a_discounted_invoice_clear_the_debt(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    invoice, customer_id = await _discounted_credit_invoice(client, headers)

    totals = []
    for row in invoice["lines"]:
        response = await client.post(
            f"{SALES}/{invoice['id']}/returns",
            json={"lines": [{"line_id": row["id"], "quantity": "1"}], "reason": "رجّع صنف"},
            headers=headers,
        )
        assert response.status_code == 201, response.text
        totals.append(response.json()["total"])

    assert totals[-1] == "3.34"
    assert await _balance(client, headers, customer_id) == "0.00"


async def test_return_after_batch_tracking_was_switched_on_never_loses_stock_silently(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, tenant, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers, quantity="10")
    invoice = await sell(client, headers, sale_body([line(product, "4")]))
    switched = await client.patch(
        f"/api/v1/products/{product['id']}", json={"tracks_batches": True}, headers=headers
    )
    assert switched.status_code == 200, switched.text

    response = await client.post(
        f"{SALES}/{invoice['id']}/returns",
        json={
            "lines": [{"line_id": invoice["lines"][0]["id"], "quantity": "4"}],
            "reason": "مرتجع",
        },
        headers=headers,
    )

    returns = (
        await owner_session.execute(
            text("SELECT count(*) FROM sales_returns WHERE tenant_id = :t"), {"t": tenant.id}
        )
    ).scalar_one()
    back = (
        await owner_session.execute(
            text(
                "SELECT count(*) FROM stock_movements"
                " WHERE product_id = :p AND movement_type = 'customer_return'"
            ),
            {"p": product["id"]},
        )
    ).scalar_one()
    if response.status_code == 201:
        assert back == 1  # stock really went back
    else:
        assert response.status_code in (409, 422)
        assert (returns, back) == (0, 0)  # refused, and nothing half-written


async def test_sharing_again_returns_the_same_link_until_revoked(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, headers)
    invoice = await sell(client, headers, sale_body([line(product)]))
    share = f"{SALES}/{invoice['id']}/share"

    first = (await client.post(share, headers=headers)).json()["url"]
    again = (await client.post(share, headers=headers)).json()["url"]
    await client.delete(share, headers=headers)
    after_revoke = (await client.post(share, headers=headers)).json()["url"]

    assert first == again
    assert after_revoke != first
    old_token = first.rsplit("/i/", 1)[1]
    assert (await client.get(f"/api/v1/public/invoices/{old_token}")).status_code == 404
