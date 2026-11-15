"""Shareable invoice links: public read without login, revoke, rate limit."""

from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import MembershipRole
from tests.sales_support import SALES, line, sale_body, sell, stocked_product
from tests.support import auth_header, login, make_membership, make_user, seeded_login

PUBLIC = "/api/v1/public/invoices"


async def _share(client: AsyncClient, headers: dict[str, str], invoice_id: str) -> str:
    response = await client.post(f"{SALES}/{invoice_id}/share", headers=headers)
    assert response.status_code == 200, response.text
    url: str = response.json()["url"]
    assert "/i/" in url
    return url.rsplit("/i/", 1)[1]


async def _credit_invoice(
    client: AsyncClient, headers: dict[str, str]
) -> tuple[dict[str, Any], str]:
    product = await stocked_product(client, headers, name_ar="سماد يوريا")
    customer = await client.post(
        "/api/v1/customers",
        json={"name": "الحاج سيد", "phone": "01012345678"},
        headers=headers,
    )
    customer_id: str = customer.json()["id"]
    invoice = await sell(
        client,
        headers,
        sale_body([line(product, "2")], customer_id=customer_id, paid="30"),
    )
    return invoice, customer_id


async def test_public_invoice_works_without_login(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session, tenant_name="مشتل زين")
    invoice, _ = await _credit_invoice(client, headers)
    token = await _share(client, headers, invoice["id"])

    response = await client.get(f"{PUBLIC}/{token}")

    assert response.status_code == 200, response.text
    assert response.headers["x-robots-tag"] == "noindex"
    body = response.json()
    assert body["shop_name"] == "مشتل زين"
    assert body["number"] == invoice["number"]
    assert (body["total"], body["paid"], body["remaining"]) == ("50.00", "30.00", "20.00")
    assert body["lines"][0]["name_ar"] == "سماد يوريا"
    detail = (await client.get(f"{SALES}/{invoice['id']}", headers=headers)).json()
    assert detail["shared"] is True


async def test_public_invoice_hides_balance_and_phone(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    invoice, _ = await _credit_invoice(client, headers)
    token = await _share(client, headers, invoice["id"])

    body = (await client.get(f"{PUBLIC}/{token}")).json()

    assert set(body) == {
        "shop_name",
        "number",
        "created_at",
        "lines",
        "subtotal",
        "discount",
        "total",
        "paid",
        "remaining",
        "returned_total",
    }
    assert set(body["lines"][0]) == {
        "name_ar",
        "unit_name_ar",
        "quantity",
        "unit_price",
        "line_total",
    }
    assert "01012345678" not in str(body)
    assert "+201012345678" not in str(body)


async def test_revoke_kills_the_link(client: AsyncClient, owner_session: AsyncSession) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    invoice, _ = await _credit_invoice(client, headers)
    token = await _share(client, headers, invoice["id"])

    revoked = await client.delete(f"{SALES}/{invoice['id']}/share", headers=headers)

    assert revoked.status_code == 204
    assert (await client.get(f"{PUBLIC}/{token}")).status_code == 404
    detail = (await client.get(f"{SALES}/{invoice['id']}", headers=headers)).json()
    assert detail["shared"] is False


async def test_reshare_gives_a_new_token_and_kills_the_old(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    invoice, _ = await _credit_invoice(client, headers)
    first = await _share(client, headers, invoice["id"])
    await client.delete(f"{SALES}/{invoice['id']}/share", headers=headers)

    second = await _share(client, headers, invoice["id"])
    third = await _share(client, headers, invoice["id"])

    assert len({first, second, third}) == 3
    assert (await client.get(f"{PUBLIC}/{second}")).status_code == 404
    assert (await client.get(f"{PUBLIC}/{third}")).status_code == 200


async def test_wrong_token_is_404(client: AsyncClient, owner_session: AsyncSession) -> None:
    await seeded_login(client, owner_session)

    response = await client.get(f"{PUBLIC}/{'x' * 43}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_cashier_shares_own_invoice_but_cannot_revoke(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, owner, tenant, _ = await seeded_login(client, owner_session)
    product = await stocked_product(client, owner)
    cashier_user = await make_user(owner_session)
    await make_membership(
        owner_session, tenant=tenant, user=cashier_user, role=MembershipRole.CASHIER
    )
    await owner_session.commit()
    cashier = auth_header(await login(client, cashier_user.email, tenant_id=tenant.id))
    mine = await sell(client, cashier, sale_body([line(product)]))
    owners = await sell(client, owner, sale_body([line(product)]))

    await _share(client, cashier, mine["id"])
    other = await client.post(f"{SALES}/{owners['id']}/share", headers=cashier)
    revoke = await client.delete(f"{SALES}/{mine['id']}/share", headers=cashier)

    assert other.status_code == 404
    assert revoke.status_code == 403


async def test_another_shop_cannot_share(client: AsyncClient, owner_session: AsyncSession) -> None:
    _, mine, _, _ = await seeded_login(client, owner_session, tenant_name="متجري")
    _, theirs, _, _ = await seeded_login(client, owner_session, tenant_name="متجر آخر")
    product = await stocked_product(client, mine)
    invoice = await sell(client, mine, sale_body([line(product)]))

    response = await client.post(f"{SALES}/{invoice['id']}/share", headers=theirs)

    assert response.status_code == 404


async def test_public_route_is_rate_limited(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    await seeded_login(client, owner_session)

    codes = [(await client.get(f"{PUBLIC}/{'y' * 43}")).status_code for _ in range(61)]

    assert set(codes[:60]) == {404}
    assert codes[60] == 429
