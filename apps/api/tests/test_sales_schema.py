"""Sales and customers: permissions, tenant isolation and append-only statement."""

import hashlib
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authorization.permissions import Permission, permissions_for
from app.modules.customers.models import Customer, CustomerLedgerEntry
from app.modules.identity.models import MembershipRole, Tenant
from app.modules.sales.models import (
    SalesInvoice,
    SalesInvoiceLine,
    SalesInvoiceLineBatch,
    SalesReturn,
    SalesReturnLine,
    ShopCounter,
)
from app.modules.tenancy.context import set_tenant_context
from tests.support import make_batch_row, make_product_row, make_tenant, unit_id

SALES = {Permission.SALES_OPERATE, Permission.SALES_REFUND, Permission.SALES_DISCOUNT}


def test_role_permissions() -> None:
    owner = permissions_for(MembershipRole.OWNER)
    manager = permissions_for(MembershipRole.MANAGER)
    cashier = permissions_for(MembershipRole.CASHIER)
    keeper = permissions_for(MembershipRole.INVENTORY_MANAGER)

    for perms in (owner, manager):
        assert {Permission.SALES_DISCOUNT, Permission.CUSTOMERS_ADJUST} <= perms
    assert Permission.SALES_OPERATE in cashier
    assert (
        not {Permission.SALES_DISCOUNT, Permission.CUSTOMERS_ADJUST, Permission.SALES_REFUND}
        & cashier
    )
    assert not (SALES | {Permission.CUSTOMERS_ADJUST}) & keeper


async def _seed_shop(session: AsyncSession, tenant: Tenant) -> None:
    product = await make_product_row(session, tenant)
    batch = await make_batch_row(session, tenant, product)
    customer = Customer(tenant_id=tenant.id, name="الحاج محمود", name_key=f"k-{uuid.uuid4()}")
    session.add(customer)
    session.add(ShopCounter(tenant_id=tenant.id, name="invoice", value=1))
    await session.flush()
    session.add(
        CustomerLedgerEntry(
            tenant_id=tenant.id, customer_id=customer.id, kind="opening", amount=Decimal("100")
        )
    )
    invoice = SalesInvoice(
        tenant_id=tenant.id,
        number=1,
        customer_id=customer.id,
        subtotal=Decimal("10"),
        discount=Decimal("0"),
        total=Decimal("10"),
        paid=Decimal("10"),
        credit=Decimal("0"),
        idempotency_key=f"key-{uuid.uuid4()}",
        request_hash="h",
    )
    session.add(invoice)
    await session.flush()
    line = SalesInvoiceLine(
        tenant_id=tenant.id,
        invoice_id=invoice.id,
        position=1,
        product_id=product.id,
        name_ar="صنف",
        unit_id=unit_id("piece"),
        quantity=Decimal("1"),
        base_quantity=Decimal("1"),
        unit_price=Decimal("10"),
        line_total=Decimal("10"),
    )
    session.add(line)
    await session.flush()
    session.add(
        SalesInvoiceLineBatch(
            tenant_id=tenant.id, line_id=line.id, batch_id=batch.id, base_quantity=Decimal("1")
        )
    )
    sales_return = SalesReturn(
        tenant_id=tenant.id,
        number=1,
        invoice_id=invoice.id,
        total=Decimal("10"),
        credit_reduction=Decimal("0"),
        cash_refund=Decimal("10"),
        reason="مرتجع",
    )
    session.add(sales_return)
    await session.flush()
    session.add(
        SalesReturnLine(
            tenant_id=tenant.id,
            return_id=sales_return.id,
            line_id=line.id,
            quantity=Decimal("1"),
            base_quantity=Decimal("1"),
            amount=Decimal("10"),
        )
    )
    await session.flush()


@pytest.mark.parametrize(
    "model",
    [
        ShopCounter,
        Customer,
        CustomerLedgerEntry,
        SalesInvoice,
        SalesInvoiceLine,
        SalesInvoiceLineBatch,
        SalesReturn,
        SalesReturnLine,
    ],
)
async def test_sales_tables_are_tenant_isolated(
    db_session: AsyncSession, owner_session: AsyncSession, model: type
) -> None:
    mine = await make_tenant(owner_session)
    theirs = await make_tenant(owner_session)
    await _seed_shop(owner_session, mine)
    await _seed_shop(owner_session, theirs)
    await owner_session.commit()

    await set_tenant_context(db_session, mine.id)
    tenants = set((await db_session.execute(select(model.tenant_id))).scalars())  # type: ignore[attr-defined]

    assert tenants == {mine.id}


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE customer_ledger SET amount = 0 WHERE tenant_id = :t",
        "DELETE FROM customer_ledger WHERE tenant_id = :t",
    ],
)
async def test_customer_ledger_is_append_only(
    db_session: AsyncSession, owner_session: AsyncSession, statement: str
) -> None:
    tenant = await make_tenant(owner_session)
    await _seed_shop(owner_session, tenant)
    await owner_session.commit()
    await set_tenant_context(db_session, tenant.id)

    with pytest.raises(DBAPIError):
        await db_session.execute(text(statement), {"t": tenant.id})


async def test_share_token_function_is_secured(db_session: AsyncSession) -> None:
    row = (
        await db_session.execute(
            text(
                """
                SELECT p.prosecdef AS is_security_definer,
                       p.proowner::regrole::text AS owner_name,
                       p.proacl IS NULL AS has_default_acl,
                       EXISTS (
                           SELECT 1 FROM aclexplode(p.proacl) AS a
                           WHERE a.grantee = 0 AND a.privilege_type = 'EXECUTE'
                       ) AS public_can_execute
                FROM pg_proc AS p
                WHERE p.oid = to_regprocedure('app_invoice_by_share_token(text)')
                """
            )
        )
    ).one()

    assert row.is_security_definer is True
    assert row.has_default_acl is False
    assert row.public_can_execute is False
    assert row.owner_name != "zain_app"


async def test_share_token_lookup_returns_only_ids(
    db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    tenant = await make_tenant(owner_session)
    await _seed_shop(owner_session, tenant)
    token_hash = hashlib.sha256(b"secret-token").hexdigest()
    invoice = (
        await owner_session.execute(select(SalesInvoice).where(SalesInvoice.tenant_id == tenant.id))
    ).scalar_one()
    invoice.share_token_hash = token_hash
    await owner_session.commit()

    found = (
        await db_session.execute(
            text("SELECT * FROM app_invoice_by_share_token(:h)"), {"h": token_hash}
        )
    ).all()
    missing = (
        await db_session.execute(
            text("SELECT * FROM app_invoice_by_share_token(:h)"), {"h": "0" * 64}
        )
    ).all()

    assert [tuple(row) for row in found] == [(tenant.id, invoice.id)]
    assert missing == []


async def test_invoice_number_unique_per_shop(owner_session: AsyncSession) -> None:
    first = await make_tenant(owner_session)
    second = await make_tenant(owner_session)

    def invoice(tenant: Tenant) -> SalesInvoice:
        return SalesInvoice(
            tenant_id=tenant.id,
            number=7,
            subtotal=Decimal("1"),
            discount=Decimal("0"),
            total=Decimal("1"),
            paid=Decimal("1"),
            credit=Decimal("0"),
            idempotency_key=f"key-{uuid.uuid4()}",
            request_hash="h",
        )

    owner_session.add_all([invoice(first), invoice(second)])
    await owner_session.commit()  # same number in two shops is fine

    owner_session.add(invoice(first))
    with pytest.raises(IntegrityError):
        await owner_session.commit()
