"""Creating and reading sales invoices.

One request is one transaction: number, invoice, lines, stock movements,
batch draws and the customer's statement line are written together or not at
all. The number is taken first; its row lock makes every sale in a shop wait
for the one before it, so stock checks and numbering cannot race.
"""

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ForbiddenError, NotFoundError, UnprocessableError
from app.core.money import money
from app.modules.audit import service as audit
from app.modules.auth.dependencies import TenantContext
from app.modules.authorization.permissions import Permission
from app.modules.catalog.models import Product, ProductStatus, UnitOfMeasure
from app.modules.catalog.service import _escape_like, _q4
from app.modules.customers.ledger import post_entry
from app.modules.customers.models import Customer, LedgerKind
from app.modules.identity.models import User
from app.modules.inventory.models import ProductBatch, StockMovement, StockMovementType
from app.modules.inventory.service import _conversion_factor, apply_movement
from app.modules.sales.models import (
    SalesInvoice,
    SalesInvoiceLine,
    SalesInvoiceLineBatch,
    SalesReturn,
    SalesReturnLine,
)
from app.modules.sales.numbering import next_number
from app.modules.sales.schemas import (
    BatchDrawOut,
    CustomerRef,
    SaleIn,
    SaleLineOut,
    SaleListOut,
    SaleOut,
    SaleSummaryOut,
)

logger = logging.getLogger("zain.sales")

NOT_FOUND = "Invoice not found"
PRODUCT_NOT_FOUND = "Product not found"
CUSTOMER_NOT_FOUND = "Customer not found"
INACTIVE_CUSTOMER = "This customer is inactive"
NO_PRICE = "This product has no sale price"
NO_DISCOUNT = "Your role cannot change prices or give discounts"
DISCOUNT_TOO_HIGH = "The discount is larger than the invoice"
PAID_TOO_MUCH = "The amount paid is more than the invoice total"
CASH_IN_FULL = "A cash customer pays in full"
NOT_ENOUGH = "Not enough stock for this sale"
KEY_REUSED = "This request was already sent with different data"
ARCHIVED = "Archived products cannot receive stock movements"


@dataclass
class _Line:
    product: Product
    unit_id: uuid.UUID
    quantity: Decimal
    base_quantity: Decimal
    unit_price: Decimal
    line_total: Decimal


def _request_hash(payload: SaleIn) -> str:
    data = payload.model_dump(mode="json", exclude={"idempotency_key"})
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


async def _by_key(db: AsyncSession, tenant_id: uuid.UUID, key: str) -> SalesInvoice | None:
    return await db.scalar(
        select(SalesInvoice).where(
            SalesInvoice.tenant_id == tenant_id, SalesInvoice.idempotency_key == key
        )
    )


async def _active_customer(
    db: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID
) -> Customer:
    customer = await db.scalar(
        select(Customer).where(Customer.id == customer_id, Customer.tenant_id == tenant_id)
    )
    if customer is None:
        raise NotFoundError(CUSTOMER_NOT_FOUND)
    if not customer.active:
        raise UnprocessableError(INACTIVE_CUSTOMER)
    return customer


async def _price_lines(db: AsyncSession, context: TenantContext, payload: SaleIn) -> list[_Line]:
    tenant_id = context.tenant.id
    can_discount = context.allows(Permission.SALES_DISCOUNT)
    ids = {line.product_id for line in payload.lines}
    products = {
        product.id: product
        for product in (
            await db.execute(
                select(Product).where(Product.tenant_id == tenant_id, Product.id.in_(ids))
            )
        ).scalars()
    }
    lines: list[_Line] = []
    for entry in payload.lines:
        product = products.get(entry.product_id)
        if product is None:
            raise NotFoundError(PRODUCT_NOT_FOUND)
        if product.status is ProductStatus.ARCHIVED:
            raise ConflictError(ARCHIVED, details={"product_name": product.name_ar})
        unit_id = entry.unit_id or product.base_unit_id
        factor = await _conversion_factor(db, tenant_id=tenant_id, product=product, unit_id=unit_id)
        # The listed price is never rounded before it is multiplied: 500 g of a
        # 25.00/kg product is 12.50, not 500 x round(0.025) = 15.00.
        exact = product.sale_price * factor if product.sale_price is not None else None
        listed = money(exact) if exact is not None else None
        requested = money(entry.unit_price) if entry.unit_price is not None else None
        if requested is not None and requested != listed:
            if not can_discount:
                raise ForbiddenError(
                    NO_DISCOUNT, details={"permission": Permission.SALES_DISCOUNT.value}
                )
            price = requested
            line_total = money(entry.quantity * price)
        else:
            if exact is None or listed is None:
                raise UnprocessableError(NO_PRICE, details={"product_name": product.name_ar})
            price = listed
            line_total = money(entry.quantity * exact)
        lines.append(
            _Line(
                product=product,
                unit_id=unit_id,
                quantity=entry.quantity,
                base_quantity=_q4(entry.quantity * factor),
                unit_price=price,
                line_total=line_total,
            )
        )
    return lines


async def draw_batches(
    db: AsyncSession, tenant_id: uuid.UUID, product_id: uuid.UUID, base_quantity: Decimal
) -> list[tuple[uuid.UUID, Decimal]]:
    """First-expiring batches first (no expiry last); across batches when needed."""
    on_hand = func.sum(StockMovement.base_quantity)
    rows = (
        await db.execute(
            select(ProductBatch.id, on_hand)
            .join(
                StockMovement,
                and_(
                    StockMovement.batch_id == ProductBatch.id,
                    StockMovement.tenant_id == ProductBatch.tenant_id,
                ),
            )
            .where(ProductBatch.tenant_id == tenant_id, ProductBatch.product_id == product_id)
            .group_by(ProductBatch.id, ProductBatch.expiry_date, ProductBatch.batch_number)
            .having(on_hand > 0)
            .order_by(ProductBatch.expiry_date.asc().nulls_last(), ProductBatch.batch_number)
        )
    ).all()
    draws: list[tuple[uuid.UUID, Decimal]] = []
    remaining = base_quantity
    for batch_id, available in rows:
        if remaining <= 0:
            break
        take = min(remaining, _q4(Decimal(available)))
        draws.append((batch_id, take))
        remaining = _q4(remaining - take)
    if remaining > 0:
        return []
    return draws


async def create_sale(
    db: AsyncSession, context: TenantContext, actor_id: uuid.UUID, payload: SaleIn
) -> tuple[SaleOut, bool]:
    """Returns ``(invoice, created)``; ``created`` is False for a repeated request."""
    tenant_id = context.tenant.id
    request_hash = _request_hash(payload)

    existing = await _by_key(db, tenant_id, payload.idempotency_key)
    if existing is not None:
        return await _replay(db, tenant_id, existing, request_hash)

    customer = (
        await _active_customer(db, tenant_id, payload.customer_id) if payload.customer_id else None
    )
    lines = await _price_lines(db, context, payload)
    subtotal = money(sum((line.line_total for line in lines), Decimal("0")))
    discount = money(payload.discount)
    if discount > 0 and not context.allows(Permission.SALES_DISCOUNT):
        raise ForbiddenError(NO_DISCOUNT, details={"permission": Permission.SALES_DISCOUNT.value})
    if discount > subtotal:
        raise UnprocessableError(DISCOUNT_TOO_HIGH)
    total = money(subtotal - discount)
    paid = money(payload.paid) if payload.paid is not None else total
    if paid > total:
        raise UnprocessableError(PAID_TOO_MUCH)
    if customer is None and paid != total:
        raise UnprocessableError(CASH_IN_FULL)

    number = await next_number(db, tenant_id, "invoice")
    invoice = SalesInvoice(
        tenant_id=tenant_id,
        number=number,
        customer_id=customer.id if customer else None,
        subtotal=subtotal,
        discount=discount,
        total=total,
        paid=paid,
        credit=money(total - paid),
        idempotency_key=payload.idempotency_key,
        request_hash=request_hash,
        created_by=actor_id,
    )
    db.add(invoice)
    try:
        await db.flush()
    except IntegrityError:
        # A concurrent request with the same key won: answer with its invoice.
        await db.rollback()
        winner = await _by_key(db, tenant_id, payload.idempotency_key)
        if winner is None:
            raise
        return await _replay(db, tenant_id, winner, request_hash)

    invoice_id = invoice.id
    reason = f"فاتورة بيع رقم {number}"
    saved_lines = []
    for position, line in enumerate(lines, start=1):
        row = SalesInvoiceLine(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            position=position,
            product_id=line.product.id,
            name_ar=line.product.name_ar,
            unit_id=line.unit_id,
            quantity=line.quantity,
            base_quantity=line.base_quantity,
            unit_price=line.unit_price,
            line_total=line.line_total,
        )
        db.add(row)
        saved_lines.append((row, line))
    await db.flush()

    # Stock in product order, so this sale and a stocktake lock balances alike.
    for row, line in sorted(saved_lines, key=lambda pair: str(pair[1].product.id)):
        name = line.product.name_ar
        try:
            if line.product.tracks_batches:
                draws = await draw_batches(db, tenant_id, line.product.id, line.base_quantity)
                if not draws:
                    raise ConflictError(NOT_ENOUGH)
                for batch_id, base_quantity in draws:
                    await apply_movement(
                        db,
                        tenant_id=tenant_id,
                        actor_id=actor_id,
                        product_id=line.product.id,
                        movement_type=StockMovementType.SALE,
                        quantity=base_quantity,
                        unit_id=line.product.base_unit_id,
                        reason=reason,
                        batch_id=batch_id,
                        reference_type="sales_invoice",
                        reference_id=invoice_id,
                    )
                    db.add(
                        SalesInvoiceLineBatch(
                            tenant_id=tenant_id,
                            line_id=row.id,
                            batch_id=batch_id,
                            base_quantity=base_quantity,
                        )
                    )
            else:
                await apply_movement(
                    db,
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    product_id=line.product.id,
                    movement_type=StockMovementType.SALE,
                    quantity=line.quantity,
                    unit_id=line.unit_id,
                    reason=reason,
                    reference_type="sales_invoice",
                    reference_id=invoice_id,
                )
        except ConflictError as exc:
            await db.rollback()
            raise ConflictError(NOT_ENOUGH, details={"product_name": name}) from exc

    if customer is not None and invoice.credit > 0:
        await post_entry(
            db,
            tenant_id=tenant_id,
            customer_id=customer.id,
            kind=LedgerKind.INVOICE,
            amount=invoice.credit,
            actor_id=actor_id,
            reference_type="sales_invoice",
            reference_id=invoice_id,
            note=reason,
        )
    await audit.record(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="sale.created",
        entity_type="sales_invoice",
        entity_id=invoice_id,
        after_state={
            "number": number,
            "total": total,
            "paid": paid,
            "credit": invoice.credit,
            "lines": len(lines),
        },
    )
    await db.commit()
    logger.info("sale.created", extra={"tenant_id": str(tenant_id), "rows": len(lines)})
    return await get_sale(db, tenant_id, invoice_id), True


async def _replay(
    db: AsyncSession, tenant_id: uuid.UUID, invoice: SalesInvoice, request_hash: str
) -> tuple[SaleOut, bool]:
    if invoice.request_hash != request_hash:
        raise UnprocessableError(KEY_REUSED)
    return await get_sale(db, tenant_id, invoice.id), False


async def get_sale(db: AsyncSession, tenant_id: uuid.UUID, invoice_id: uuid.UUID) -> SaleOut:
    found = (
        await db.execute(
            select(SalesInvoice, Customer, User.full_name)
            .outerjoin(
                Customer,
                and_(
                    Customer.id == SalesInvoice.customer_id,
                    Customer.tenant_id == SalesInvoice.tenant_id,
                ),
            )
            .outerjoin(User, User.id == SalesInvoice.created_by)
            .where(SalesInvoice.tenant_id == tenant_id, SalesInvoice.id == invoice_id)
        )
    ).first()
    if found is None:
        raise NotFoundError(NOT_FOUND)
    invoice, customer, creator = found

    line_rows = (
        await db.execute(
            select(SalesInvoiceLine, UnitOfMeasure.name_ar)
            .join(UnitOfMeasure, UnitOfMeasure.id == SalesInvoiceLine.unit_id)
            .where(
                SalesInvoiceLine.tenant_id == tenant_id,
                SalesInvoiceLine.invoice_id == invoice_id,
            )
            .order_by(SalesInvoiceLine.position)
        )
    ).all()
    line_ids = [row.id for row, _ in line_rows]
    draws: dict[uuid.UUID, list[BatchDrawOut]] = {line_id: [] for line_id in line_ids}
    returned: dict[uuid.UUID, Decimal] = {}
    if line_ids:
        for line_id, batch_id, batch_number, quantity in (
            await db.execute(
                select(
                    SalesInvoiceLineBatch.line_id,
                    SalesInvoiceLineBatch.batch_id,
                    ProductBatch.batch_number,
                    SalesInvoiceLineBatch.base_quantity,
                )
                .join(ProductBatch, ProductBatch.id == SalesInvoiceLineBatch.batch_id)
                .where(
                    SalesInvoiceLineBatch.tenant_id == tenant_id,
                    SalesInvoiceLineBatch.line_id.in_(line_ids),
                )
                .order_by(ProductBatch.expiry_date.asc().nulls_last(), ProductBatch.batch_number)
            )
        ).all():
            draws[line_id].append(
                BatchDrawOut(batch_id=batch_id, batch_number=batch_number, base_quantity=quantity)
            )
        returned = {
            line_id: Decimal(quantity)
            for line_id, quantity in (
                await db.execute(
                    select(SalesReturnLine.line_id, func.sum(SalesReturnLine.quantity))
                    .where(
                        SalesReturnLine.tenant_id == tenant_id,
                        SalesReturnLine.line_id.in_(line_ids),
                    )
                    .group_by(SalesReturnLine.line_id)
                )
            ).all()
        }
    returned_total = (
        await db.execute(
            select(func.coalesce(func.sum(SalesReturn.total), 0)).where(
                SalesReturn.tenant_id == tenant_id, SalesReturn.invoice_id == invoice_id
            )
        )
    ).scalar_one()

    return SaleOut(
        id=invoice.id,
        number=invoice.number,
        customer=(
            CustomerRef(id=customer.id, name=customer.name, phone=customer.phone)
            if customer is not None
            else None
        ),
        lines=[
            SaleLineOut(
                id=row.id,
                product_id=row.product_id,
                name_ar=row.name_ar,
                unit_id=row.unit_id,
                unit_name_ar=unit_name,
                quantity=row.quantity,
                base_quantity=row.base_quantity,
                unit_price=row.unit_price,
                line_total=row.line_total,
                returned_quantity=_q4(returned.get(row.id, Decimal("0"))),
                batches=draws[row.id],
            )
            for row, unit_name in line_rows
        ],
        subtotal=invoice.subtotal,
        discount=invoice.discount,
        total=invoice.total,
        paid=invoice.paid,
        credit=invoice.credit,
        returned_total=money(Decimal(returned_total)),
        created_at=invoice.created_at,
        created_by_name=creator,
        shared=invoice.share_token_hash is not None,
    )


def sees_all_sales(context: TenantContext) -> bool:
    """Owner and manager see every invoice; a cashier sees the ones they made."""
    return context.allows(Permission.SALES_DISCOUNT)


async def get_visible_sale(
    db: AsyncSession, context: TenantContext, actor_id: uuid.UUID, invoice_id: uuid.UUID
) -> SaleOut:
    if not sees_all_sales(context):
        owner = await db.scalar(
            select(SalesInvoice.created_by).where(
                SalesInvoice.tenant_id == context.tenant.id, SalesInvoice.id == invoice_id
            )
        )
        if owner != actor_id:
            raise NotFoundError(NOT_FOUND)
    return await get_sale(db, context.tenant.id, invoice_id)


async def list_sales(
    db: AsyncSession,
    context: TenantContext,
    actor_id: uuid.UUID,
    *,
    q: str | None,
    customer_id: uuid.UUID | None,
    page: int,
    page_size: int,
) -> SaleListOut:
    tenant_id = context.tenant.id
    query = (
        select(SalesInvoice, Customer.name, User.full_name)
        .outerjoin(
            Customer,
            and_(
                Customer.id == SalesInvoice.customer_id,
                Customer.tenant_id == SalesInvoice.tenant_id,
            ),
        )
        .outerjoin(User, User.id == SalesInvoice.created_by)
        .where(SalesInvoice.tenant_id == tenant_id)
    )
    if not sees_all_sales(context):
        query = query.where(SalesInvoice.created_by == actor_id)
    if customer_id is not None:
        query = query.where(SalesInvoice.customer_id == customer_id)
    if q and q.strip():
        term = q.strip()
        if term.isdigit():
            query = query.where(SalesInvoice.number == int(term))
        else:
            query = query.where(Customer.name.ilike(f"%{_escape_like(term)}%", escape="\\"))
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = (
        await db.execute(
            query.order_by(SalesInvoice.number.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    ).all()
    return SaleListOut(
        items=[
            SaleSummaryOut(
                id=invoice.id,
                number=invoice.number,
                customer_name=customer_name,
                total=invoice.total,
                credit=invoice.credit,
                created_at=invoice.created_at,
                created_by_name=creator,
            )
            for invoice, customer_name, creator in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )
