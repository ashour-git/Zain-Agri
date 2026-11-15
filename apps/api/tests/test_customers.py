"""Customers: create, list with balances, statement, payments, corrections."""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.service import normalize_phone
from app.modules.identity.models import MembershipRole
from tests.support import seeded_login

BASE = "/api/v1/customers"


async def _create(
    client: AsyncClient, headers: dict[str, str], expected: int = 201, **body: Any
) -> dict[str, Any]:
    response = await client.post(BASE, json={"name": "الحاج محمود", **body}, headers=headers)
    assert response.status_code == expected, response.text
    result: dict[str, Any] = response.json()
    return result


async def _pay(client: AsyncClient, headers: dict[str, str], customer_id: str, amount: str) -> Any:
    return await client.post(
        f"{BASE}/{customer_id}/payments", json={"amount": amount}, headers=headers
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("01012345678", "+201012345678"),
        ("٠١٠١٢٣٤٥٦٧٨", "+201012345678"),
        ("+20 101 234 5678", "+201012345678"),
        ("00201112345678", "+201112345678"),
        ("0122-345-6789", "+201223456789"),
        ("01512345678", "+201512345678"),
    ],
)
def test_phone_is_normalized(raw: str, expected: str) -> None:
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["12345", "01312345678", "0101234567", "phone"])
def test_bad_phones_are_refused(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_phone(raw)


async def test_create_with_opening_balance_needs_customers_adjust(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, cashier, _, _ = await seeded_login(client, owner_session, role=MembershipRole.CASHIER)

    refused = await client.post(
        BASE, json={"name": "أحمد", "opening_balance": "100"}, headers=cashier
    )
    allowed = await _create(client, cashier, name="أحمد")

    assert refused.status_code == 403
    assert allowed["balance"] == "0.00"


async def test_owner_sets_an_opening_balance(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)

    created = await _create(client, headers, opening_balance="1250.5", phone="01012345678")

    assert created["balance"] == "1250.50"
    assert created["phone"] == "+201012345678"
    statement = (await client.get(f"{BASE}/{created['id']}/statement", headers=headers)).json()
    assert [(line["kind"], line["amount"]) for line in statement["lines"]] == [
        ("opening", "1250.50")
    ]


async def test_names_are_unique_after_normalization(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    await _create(client, headers, name="الحاج محمود")

    duplicate = await client.post(BASE, json={"name": "الحاج  مَحمود"}, headers=headers)

    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["message"] == "يوجد عميل بهذا الاسم بالفعل."


async def test_bad_phone_gets_an_arabic_message(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)

    response = await client.post(BASE, json={"name": "أحمد", "phone": "12345"}, headers=headers)

    assert response.status_code == 422
    assert "رقم" in response.json()["error"]["message"]


async def test_payment_lowers_balance_and_overpay_goes_negative(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    customer = await _create(client, headers, opening_balance="100")

    first = await _pay(client, headers, customer["id"], "60")
    second = await _pay(client, headers, customer["id"], "70")

    assert first.status_code == 201, first.text
    assert first.json()["balance"] == "40.00"
    assert second.json()["balance"] == "-30.00"


@pytest.mark.parametrize("amount", ["0", "-5", "abc"])
async def test_payment_must_be_positive(
    client: AsyncClient, owner_session: AsyncSession, amount: str
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    customer = await _create(client, headers)

    assert (await _pay(client, headers, customer["id"], amount)).status_code == 422


async def test_correction_needs_a_reason_and_customers_adjust(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, owner, tenant, _ = await seeded_login(client, owner_session)
    customer = await _create(client, owner, opening_balance="100")
    path = f"{BASE}/{customer['id']}/corrections"

    no_reason = await client.post(path, json={"amount": "-10", "reason": ""}, headers=owner)
    ok = await client.post(path, json={"amount": "-10", "reason": "خطأ في الحساب"}, headers=owner)

    assert no_reason.status_code == 422
    assert ok.status_code == 201
    assert ok.json()["balance"] == "90.00"


async def test_cashier_cannot_correct(client: AsyncClient, owner_session: AsyncSession) -> None:
    _, cashier, _, _ = await seeded_login(client, owner_session, role=MembershipRole.CASHIER)
    customer = await _create(client, cashier)

    response = await client.post(
        f"{BASE}/{customer['id']}/corrections",
        json={"amount": "5", "reason": "تجربة تعديل"},
        headers=cashier,
    )

    assert response.status_code == 403


async def test_statement_shows_running_balance(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    customer = await _create(client, headers, opening_balance="100")
    await _pay(client, headers, customer["id"], "30")
    await client.post(
        f"{BASE}/{customer['id']}/corrections",
        json={"amount": "5", "reason": "رسوم نقل"},
        headers=headers,
    )

    statement = (await client.get(f"{BASE}/{customer['id']}/statement", headers=headers)).json()

    assert [(line["kind"], line["balance_after"]) for line in statement["lines"]] == [
        ("opening", "100.00"),
        ("payment", "70.00"),
        ("correction", "75.00"),
    ]
    assert statement["balance"] == "75.00"
    assert statement["lines"][2]["note"] == "رسوم نقل"
    assert statement["customer"]["name"] == "الحاج محمود"


async def test_list_shows_balances_and_filters_owing(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    await _create(client, headers, name="يدين", opening_balance="40")
    await _create(client, headers, name="خالص")

    everyone = (await client.get(BASE, headers=headers)).json()
    owing = (await client.get(f"{BASE}?owes=true", headers=headers)).json()
    search = (await client.get(f"{BASE}?q=خالص", headers=headers)).json()

    assert {c["name"]: c["balance"] for c in everyone["items"]} == {"يدين": "40.00", "خالص": "0.00"}
    assert [c["name"] for c in owing["items"]] == ["يدين"]
    assert [c["name"] for c in search["items"]] == ["خالص"]


async def test_inactive_customer_keeps_statement_but_cannot_buy(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    customer = await _create(client, headers, opening_balance="50")

    hidden = await client.patch(f"{BASE}/{customer['id']}", json={"active": False}, headers=headers)

    assert hidden.status_code == 200
    assert hidden.json()["active"] is False
    assert (
        await client.get(f"{BASE}/{customer['id']}/statement", headers=headers)
    ).status_code == 200
    assert (await _pay(client, headers, customer["id"], "10")).status_code == 201
    listed = (await client.get(BASE, headers=headers)).json()["items"]
    assert listed == []  # hidden from the default list
    all_listed = (await client.get(f"{BASE}?include_inactive=true", headers=headers)).json()
    assert len(all_listed["items"]) == 1


async def test_cashier_cannot_rename_or_hide(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, cashier, _, _ = await seeded_login(client, owner_session, role=MembershipRole.CASHIER)
    customer = await _create(client, cashier)

    response = await client.patch(
        f"{BASE}/{customer['id']}", json={"active": False}, headers=cashier
    )

    assert response.status_code == 403


async def test_storekeeper_has_no_access(client: AsyncClient, owner_session: AsyncSession) -> None:
    _, keeper, _, _ = await seeded_login(
        client, owner_session, role=MembershipRole.INVENTORY_MANAGER
    )

    assert (await client.get(BASE, headers=keeper)).status_code == 403
    assert (await client.post(BASE, json={"name": "أحمد"}, headers=keeper)).status_code == 403


async def test_another_shop_cannot_read_or_pay(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, mine, _, _ = await seeded_login(client, owner_session, tenant_name="متجري")
    customer = await _create(client, mine, opening_balance="10")
    _, theirs, _, _ = await seeded_login(client, owner_session, tenant_name="متجر آخر")

    assert (
        await client.get(f"{BASE}/{customer['id']}/statement", headers=theirs)
    ).status_code == 404
    assert (await _pay(client, theirs, customer["id"], "5")).status_code == 404
    assert (await client.get(BASE, headers=theirs)).json()["items"] == []


async def test_amounts_are_strings_with_two_decimals(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)

    created = await _create(client, headers, opening_balance="12.5")
    three_places = await client.post(
        BASE, json={"name": "ثالث", "opening_balance": "12.345"}, headers=headers
    )

    assert created["balance"] == "12.50"
    assert three_places.status_code == 422
