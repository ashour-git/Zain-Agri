"""Money rounding and the customer statement core."""

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import UnprocessableError
from app.core.money import money
from app.modules.customers.ledger import balance, balances, post_entry
from app.modules.customers.models import Customer, LedgerKind
from app.modules.identity.models import Tenant
from app.modules.tenancy.context import set_tenant_context
from tests.support import make_tenant


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("2.345", "2.35"), ("2.344", "2.34"), ("10", "10.00"), ("0.005", "0.01"), ("-2.345", "-2.35")],
)
def test_money_rounds_half_up(raw: str, expected: str) -> None:
    assert money(Decimal(raw)) == Decimal(expected)


async def _customer(owner_session: AsyncSession, tenant: Tenant, name: str = "أحمد") -> Customer:
    customer = Customer(tenant_id=tenant.id, name=name, name_key=name)
    owner_session.add(customer)
    await owner_session.commit()
    return customer


async def test_balance_is_the_sum_of_entries(
    db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    tenant = await make_tenant(owner_session)
    customer = await _customer(owner_session, tenant)
    await set_tenant_context(db_session, tenant.id)

    for kind, amount in (
        (LedgerKind.OPENING, "100"),
        (LedgerKind.INVOICE, "50"),
        (LedgerKind.PAYMENT, "-120"),
    ):
        await post_entry(
            db_session,
            tenant_id=tenant.id,
            customer_id=customer.id,
            kind=kind,
            amount=Decimal(amount),
            actor_id=None,
        )
    await db_session.commit()

    assert await balance(db_session, tenant.id, customer.id) == Decimal("30.00")


async def test_balances_for_many_customers_default_to_zero(
    db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    tenant = await make_tenant(owner_session)
    owes = await _customer(owner_session, tenant, "يدين")
    clean = await _customer(owner_session, tenant, "لا شيء")
    await set_tenant_context(db_session, tenant.id)
    await post_entry(
        db_session,
        tenant_id=tenant.id,
        customer_id=owes.id,
        kind=LedgerKind.INVOICE,
        amount=Decimal("12.50"),
        actor_id=None,
    )
    await db_session.commit()

    result = await balances(db_session, tenant.id, [owes.id, clean.id])

    assert result == {owes.id: Decimal("12.50"), clean.id: Decimal("0.00")}


async def test_zero_amount_is_refused(
    db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    tenant = await make_tenant(owner_session)
    customer = await _customer(owner_session, tenant)
    await set_tenant_context(db_session, tenant.id)

    with pytest.raises(UnprocessableError):
        await post_entry(
            db_session,
            tenant_id=tenant.id,
            customer_id=customer.id,
            kind=LedgerKind.PAYMENT,
            amount=Decimal("0.001"),
            actor_id=None,
        )
