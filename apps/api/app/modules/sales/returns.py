"""Sales returns «مرتجع»: stock back where it came from, money back credit first.

A return never edits the invoice. It adds a numbered return document, puts the
stock back into the batches the sale drew from (the latest-expiring draw is
refilled first), takes the value off what the customer still owes on that
invoice, and hands any rest back as cash.
"""

import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, UnprocessableError
from app.core.money import money
from app.modules.audit import service as audit
from app.modules.auth.dependencies import TenantContext
from app.modules.catalog.models import Product
from app.modules.catalog.service import _q4
from app.modules.customers.ledger import post_entry
from app.modules.customers.models import LedgerKind
from app.modules.inventory.models import ProductBatch, StockMovementType
from app.modules.inventory.service import apply_movement
from app.modules.sales.models import (
    SalesInvoice,
    SalesInvoiceLine,
    SalesInvoiceLineBatch,
    SalesReturn,
    SalesReturnLine,
)
from app.modules.sales.numbering import next_number
from app.modules.sales.schemas import ReturnIn, ReturnOut

NOT_FOUND = "Invoice not found"
LINE_NOT_ON_INVOICE = "This line is not on this invoice"
TOO_MANY = "You cannot return more than was sold"
REPEATED_LINE = "Each line can appear once in a return"

_ZERO = Decimal("0")


async def _returned_so_far(
    db: AsyncSession, tenant_id: uuid.UUID, line_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, tuple[Decimal, Decimal, Decimal]]:
    """``line_id -> (quantity, base_quantity, amount)`` already returned."""
    rows = await db.execute(
        select(
            SalesReturnLine.line_id,
            func.sum(SalesReturnLine.quantity),
            func.sum(SalesReturnLine.base_quantity),
            func.sum(SalesReturnLine.amount),
        )
        .where(SalesReturnLine.tenant_id == tenant_id, SalesReturnLine.line_id.in_(line_ids))
        .group_by(SalesReturnLine.line_id)
    )
    return {
        line_id: (Decimal(qty), Decimal(base), Decimal(amount))
        for line_id, qty, base, amount in rows.all()
    }


async def _refill_plan(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    line_id: uuid.UUID,
    already_back: Decimal,
    base_quantity: Decimal,
) -> list[tuple[uuid.UUID, Decimal]]:
    """Which batches get the stock back: the sale's last FEFO draw first.

    Earlier returns of this line were placed by the same rule, so they are
    skipped first and this return continues where they stopped.
    """
    draws = (
        await db.execute(
            select(SalesInvoiceLineBatch.batch_id, SalesInvoiceLineBatch.base_quantity)
            .join(
                ProductBatch,
                and_(
                    ProductBatch.id == SalesInvoiceLineBatch.batch_id,
                    ProductBatch.tenant_id == SalesInvoiceLineBatch.tenant_id,
                ),
            )
            .where(
                SalesInvoiceLineBatch.tenant_id == tenant_id,
                SalesInvoiceLineBatch.line_id == line_id,
            )
            # Reverse of the sale's order (first-expiring first, no expiry last).
            .order_by(
                ProductBatch.expiry_date.desc().nulls_first(), ProductBatch.batch_number.desc()
            )
        )
    ).all()
    skip, need = already_back, base_quantity
    plan: list[tuple[uuid.UUID, Decimal]] = []
    for batch_id, drawn in draws:
        room = Decimal(drawn)
        used = min(skip, room)
        skip -= used
        room -= used
        take = min(need, room)
        if take > 0:
            plan.append((batch_id, _q4(take)))
            need -= take
        if need <= 0:
            break
    return plan


async def _put_back(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    row: SalesInvoiceLine,
    quantity: Decimal,
    base_quantity: Decimal,
    done_base: Decimal,
    reason: str,
    return_id: uuid.UUID,
) -> None:
    product = await db.scalar(
        select(Product).where(Product.tenant_id == tenant_id, Product.id == row.product_id)
    )
    if product is None:  # the line's foreign key makes this impossible
        raise NotFoundError("Product not found")
    moves: list[tuple[Decimal, uuid.UUID, uuid.UUID | None]]
    if product.tracks_batches:
        plan = await _refill_plan(db, tenant_id, row.id, done_base, base_quantity)
        moves = [
            (batch_quantity, product.base_unit_id, batch_id) for batch_id, batch_quantity in plan
        ]
    else:
        moves = [(quantity, row.unit_id, None)]
    for move_quantity, unit_id, batch_id in moves:
        await apply_movement(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            product_id=row.product_id,
            movement_type=StockMovementType.CUSTOMER_RETURN,
            quantity=move_quantity,
            unit_id=unit_id,
            reason=reason,
            batch_id=batch_id,
            reference_type="sales_return",
            reference_id=return_id,
        )


async def create_return(
    db: AsyncSession,
    context: TenantContext,
    actor_id: uuid.UUID,
    invoice_id: uuid.UUID,
    payload: ReturnIn,
) -> ReturnOut:
    tenant_id = context.tenant.id
    invoice = await db.scalar(
        select(SalesInvoice)
        .where(SalesInvoice.tenant_id == tenant_id, SalesInvoice.id == invoice_id)
        # One return at a time per invoice, so two people cannot over-return.
        .with_for_update()
    )
    if invoice is None:
        raise NotFoundError(NOT_FOUND)

    requested = [item.line_id for item in payload.lines]
    if len(set(requested)) != len(requested):
        raise UnprocessableError(REPEATED_LINE)
    lines = {
        row.id: row
        for row in (
            await db.scalars(
                select(SalesInvoiceLine).where(
                    SalesInvoiceLine.tenant_id == tenant_id,
                    SalesInvoiceLine.invoice_id == invoice_id,
                    SalesInvoiceLine.id.in_(requested),
                )
            )
        ).all()
    }
    if len(lines) != len(requested):
        raise UnprocessableError(LINE_NOT_ON_INVOICE)
    before = await _returned_so_far(db, tenant_id, requested)

    # The discount is spread over the lines by value, so a returned piece
    # refunds what it really cost the customer.
    share = invoice.total / invoice.subtotal if invoice.subtotal > 0 else _ZERO
    planned: list[tuple[SalesInvoiceLine, Decimal, Decimal, Decimal, Decimal]] = []
    for item in payload.lines:
        row = lines[item.line_id]
        quantity = _q4(item.quantity)
        done_qty, done_base, done_amount = before.get(row.id, (_ZERO, _ZERO, _ZERO))
        left = _q4(row.quantity - done_qty)
        if quantity > left:
            raise UnprocessableError(
                TOO_MANY, details={"product_name": row.name_ar, "available": str(left)}
            )
        net_line = money(row.line_total * share)
        if quantity == left:
            # The last pieces take whatever value is left, so rounding never drifts.
            amount = money(net_line - done_amount)
            base_quantity = _q4(row.base_quantity - done_base)
        else:
            amount = money(net_line * quantity / row.quantity)
            base_quantity = _q4(row.base_quantity * quantity / row.quantity)
        planned.append((row, quantity, base_quantity, max(amount, _ZERO), done_base))

    earlier_total, credit_taken = (
        await db.execute(
            select(
                func.coalesce(func.sum(SalesReturn.total), 0),
                func.coalesce(func.sum(SalesReturn.credit_reduction), 0),
            ).where(SalesReturn.tenant_id == tenant_id, SalesReturn.invoice_id == invoice_id)
        )
    ).one()
    total = min(
        money(sum((entry[3] for entry in planned), _ZERO)),
        money(invoice.total - Decimal(earlier_total)),
    )
    total = max(total, _ZERO)
    credit_reduction = max(min(total, money(invoice.credit - Decimal(credit_taken))), _ZERO)
    cash_refund = money(total - credit_reduction)

    number = await next_number(db, tenant_id, "return")
    document = SalesReturn(
        tenant_id=tenant_id,
        number=number,
        invoice_id=invoice_id,
        total=total,
        credit_reduction=credit_reduction,
        cash_refund=cash_refund,
        reason=payload.reason,
        created_by=actor_id,
    )
    db.add(document)
    await db.flush()
    return_id = document.id
    reason = f"مرتجع رقم {number} من فاتورة {invoice.number}"

    # Product order, like a sale, so concurrent documents lock balances alike.
    for row, quantity, base_quantity, amount, done_base in sorted(
        planned, key=lambda entry: str(entry[0].product_id)
    ):
        db.add(
            SalesReturnLine(
                tenant_id=tenant_id,
                return_id=return_id,
                line_id=row.id,
                quantity=quantity,
                base_quantity=base_quantity,
                amount=amount,
            )
        )
        await _put_back(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            row=row,
            quantity=quantity,
            base_quantity=base_quantity,
            done_base=done_base,
            reason=reason,
            return_id=return_id,
        )

    if invoice.customer_id is not None and credit_reduction > 0:
        await post_entry(
            db,
            tenant_id=tenant_id,
            customer_id=invoice.customer_id,
            kind=LedgerKind.RETURN,
            amount=-credit_reduction,
            actor_id=actor_id,
            reference_type="sales_return",
            reference_id=return_id,
            note=reason,
        )
    await audit.record(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="sale.returned",
        entity_type="sales_return",
        entity_id=return_id,
        after_state={
            "number": number,
            "invoice_number": invoice.number,
            "total": total,
            "credit_reduction": credit_reduction,
            "cash_refund": cash_refund,
            "reason": payload.reason,
        },
    )
    await db.commit()
    return ReturnOut(
        id=return_id,
        number=number,
        total=total,
        credit_reduction=credit_reduction,
        cash_refund=cash_refund,
    )
