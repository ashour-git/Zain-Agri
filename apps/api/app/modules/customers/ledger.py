"""The customer statement: append a line, read a balance.

Callers own the transaction; nothing here commits. A balance is the sum of
amounts (positive = the customer owes the shop).
"""

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import UnprocessableError
from app.core.money import money
from app.modules.customers.models import CustomerLedgerEntry, LedgerKind

ZERO_AMOUNT = "The amount must not be zero"


async def post_entry(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
    kind: LedgerKind,
    amount: Decimal,
    actor_id: uuid.UUID | None,
    reference_type: str | None = None,
    reference_id: uuid.UUID | None = None,
    note: str | None = None,
) -> CustomerLedgerEntry:
    rounded = money(amount)
    if rounded == 0:
        raise UnprocessableError(ZERO_AMOUNT)
    entry = CustomerLedgerEntry(
        tenant_id=tenant_id,
        customer_id=customer_id,
        kind=kind.value,
        amount=rounded,
        reference_type=reference_type,
        reference_id=reference_id,
        note=note,
        created_by=actor_id,
    )
    db.add(entry)
    await db.flush()
    return entry


async def balances(
    db: AsyncSession, tenant_id: uuid.UUID, customer_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Decimal]:
    if not customer_ids:
        return {}
    rows = await db.execute(
        select(CustomerLedgerEntry.customer_id, func.sum(CustomerLedgerEntry.amount))
        .where(
            CustomerLedgerEntry.tenant_id == tenant_id,
            CustomerLedgerEntry.customer_id.in_(customer_ids),
        )
        .group_by(CustomerLedgerEntry.customer_id)
    )
    found = {customer_id: money(Decimal(total)) for customer_id, total in rows.all()}
    return {customer_id: found.get(customer_id, Decimal("0.00")) for customer_id in customer_ids}


async def balance(db: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID) -> Decimal:
    return (await balances(db, tenant_id, [customer_id]))[customer_id]
