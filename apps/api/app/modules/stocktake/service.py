"""Stocktake: snapshot lines, save counts, review differences, post once.

A correction is ``counted - system quantity at the moment of counting``,
applied to the balance as it is when the count is confirmed, so stock that
moved in between (a delivery, another correction) is kept.
"""

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.errors import ConflictError, NotFoundError, UnprocessableError
from app.modules.audit import service as audit
from app.modules.catalog.models import Product, ProductCategory, ProductStatus, UnitOfMeasure
from app.modules.catalog.service import _escape_like, _q4
from app.modules.inventory.models import (
    InventoryBalance,
    ProductBatch,
    StockMovement,
    StockMovementType,
)
from app.modules.inventory.service import _conversion_factor, apply_movement
from app.modules.stocktake.models import (
    ShortageReason,
    Stocktake,
    StocktakeLine,
    StocktakeScope,
    StocktakeStatus,
)
from app.modules.stocktake.schemas import (
    ApplyOut,
    LineCount,
    LineListOut,
    LineOut,
    ReviewItem,
    ReviewOut,
    StocktakeCreate,
    StocktakeListOut,
    StocktakeOut,
    UncountedItem,
)

logger = logging.getLogger("zain.stocktake")

MAX_CORRECTIONS = 2000
ALREADY_OPEN = "A stocktake is already open"
CLOSED = "This stocktake is closed"
NOT_FOUND = "Stocktake not found"
LINE_NOT_FOUND = "Stocktake line not found"
WOULD_GO_NEGATIVE = "A stocktake correction would make stock negative"
TOO_MANY = "Too many stocktake corrections"
CATEGORY_REQUIRED = "Choose a category for this stocktake"

_SHORTAGE_TYPE = {
    ShortageReason.SHORTAGE: StockMovementType.ADJUSTMENT_OUT,
    ShortageReason.DAMAGE: StockMovementType.DAMAGE,
    ShortageReason.EXPIRY: StockMovementType.EXPIRY,
}


async def _current_quantities(
    db: AsyncSession, tenant_id: uuid.UUID, lines: list[StocktakeLine]
) -> dict[uuid.UUID, Decimal]:
    """Right-now quantity per line: batch lines read the batch, others the product."""
    product_ids = {line.product_id for line in lines if line.batch_id is None}
    batch_ids = {line.batch_id for line in lines if line.batch_id is not None}
    by_product: dict[uuid.UUID, Decimal] = {}
    by_batch: dict[uuid.UUID, Decimal] = {}
    if product_ids:
        rows = await db.execute(
            select(InventoryBalance.product_id, InventoryBalance.quantity).where(
                InventoryBalance.tenant_id == tenant_id,
                InventoryBalance.product_id.in_(product_ids),
            )
        )
        by_product = {product_id: _q4(Decimal(q)) for product_id, q in rows.all()}
    if batch_ids:
        rows = await db.execute(
            select(StockMovement.batch_id, func.sum(StockMovement.base_quantity))
            .where(StockMovement.tenant_id == tenant_id, StockMovement.batch_id.in_(batch_ids))
            .group_by(StockMovement.batch_id)
        )
        by_batch = {batch_id: _q4(Decimal(q)) for batch_id, q in rows.all()}
    return {
        line.id: (
            by_batch.get(line.batch_id, Decimal("0"))
            if line.batch_id is not None
            else by_product.get(line.product_id, Decimal("0"))
        )
        for line in lines
    }


async def _get_stocktake(
    db: AsyncSession, tenant_id: uuid.UUID, stocktake_id: uuid.UUID, *, lock: bool = False
) -> Stocktake:
    query = select(Stocktake).where(Stocktake.id == stocktake_id, Stocktake.tenant_id == tenant_id)
    if lock:
        query = query.with_for_update()
    stocktake = (await db.execute(query)).scalar_one_or_none()
    if stocktake is None:
        raise NotFoundError(NOT_FOUND)
    return stocktake


def _difference(line: StocktakeLine) -> Decimal:
    """Counted minus what the system said when this line was counted."""
    assert line.counted_base_quantity is not None
    assert line.system_quantity_at_count is not None
    return _q4(line.counted_base_quantity - line.system_quantity_at_count)


def _require_open(stocktake: Stocktake) -> None:
    if stocktake.status != StocktakeStatus.OPEN:
        raise ConflictError(CLOSED)


async def _out(db: AsyncSession, stocktake: Stocktake) -> StocktakeOut:
    total, counted = (
        await db.execute(
            select(func.count(), func.count(StocktakeLine.counted_at)).where(
                StocktakeLine.tenant_id == stocktake.tenant_id,
                StocktakeLine.stocktake_id == stocktake.id,
            )
        )
    ).one()
    return StocktakeOut(
        id=stocktake.id,
        name=stocktake.name,
        scope=StocktakeScope(stocktake.scope),
        category_id=stocktake.category_id,
        blind=stocktake.blind,
        status=StocktakeStatus(stocktake.status),
        created_at=stocktake.created_at,
        applied_at=stocktake.applied_at,
        total_lines=total,
        counted_lines=counted,
    )


async def start(
    db: AsyncSession, *, tenant_id: uuid.UUID, actor_id: uuid.UUID, payload: StocktakeCreate
) -> StocktakeOut:
    if payload.scope == StocktakeScope.CATEGORY:
        if payload.category_id is None:
            raise UnprocessableError(CATEGORY_REQUIRED)
        category = await db.scalar(
            select(ProductCategory.id).where(
                ProductCategory.id == payload.category_id, ProductCategory.tenant_id == tenant_id
            )
        )
        if category is None:
            raise NotFoundError("Category not found")

    product_query = select(Product).where(
        Product.tenant_id == tenant_id, Product.status == ProductStatus.ACTIVE
    )
    if payload.scope == StocktakeScope.CATEGORY:
        product_query = product_query.where(Product.category_id == payload.category_id)
    products = list((await db.execute(product_query)).scalars())

    stocktake = Stocktake(
        tenant_id=tenant_id,
        name=payload.name or f"جرد {datetime.now(UTC).date().isoformat()}",
        scope=payload.scope.value,
        category_id=payload.category_id if payload.scope == StocktakeScope.CATEGORY else None,
        blind=payload.blind,
        status=StocktakeStatus.OPEN.value,
        created_by=actor_id,
    )
    db.add(stocktake)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(ALREADY_OPEN) from exc

    batch_products = [p.id for p in products if p.tracks_batches]
    batch_stock: dict[uuid.UUID, list[uuid.UUID]] = {}
    if batch_products:
        rows = await db.execute(
            select(ProductBatch.product_id, ProductBatch.id)
            .join(
                StockMovement,
                and_(
                    StockMovement.batch_id == ProductBatch.id,
                    StockMovement.tenant_id == ProductBatch.tenant_id,
                ),
            )
            .where(ProductBatch.tenant_id == tenant_id, ProductBatch.product_id.in_(batch_products))
            .group_by(ProductBatch.product_id, ProductBatch.id)
            .having(func.sum(StockMovement.base_quantity) != 0)
        )
        for product_id, batch_id in rows.all():
            batch_stock.setdefault(product_id, []).append(batch_id)

    lines: list[StocktakeLine] = []
    for product in products:
        if product.tracks_batches:
            lines.extend(
                StocktakeLine(
                    tenant_id=tenant_id,
                    stocktake_id=stocktake.id,
                    product_id=product.id,
                    batch_id=batch_id,
                )
                for batch_id in batch_stock.get(product.id, [])
            )
        else:
            lines.append(
                StocktakeLine(tenant_id=tenant_id, stocktake_id=stocktake.id, product_id=product.id)
            )
    db.add_all(lines)

    await audit.record(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="stocktake.started",
        entity_type="stocktake",
        entity_id=stocktake.id,
        meta={"scope": payload.scope.value, "lines": len(lines)},
    )
    await db.commit()
    logger.info("stocktake.started", extra={"tenant_id": str(tenant_id), "rows": len(lines)})
    return await _out(db, stocktake)


async def list_stocktakes(db: AsyncSession, *, tenant_id: uuid.UUID) -> StocktakeListOut:
    rows = (
        (
            await db.execute(
                select(Stocktake)
                .where(Stocktake.tenant_id == tenant_id)
                .order_by(Stocktake.created_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return StocktakeListOut(items=[await _out(db, row) for row in rows])


async def get_stocktake(
    db: AsyncSession, *, tenant_id: uuid.UUID, stocktake_id: uuid.UUID
) -> StocktakeOut:
    return await _out(db, await _get_stocktake(db, tenant_id, stocktake_id))


def _line_rows(tenant_id: uuid.UUID, stocktake_id: uuid.UUID) -> Any:
    return (
        select(StocktakeLine, Product, ProductBatch.batch_number, UnitOfMeasure.name_ar)
        .join(
            Product,
            and_(
                Product.id == StocktakeLine.product_id, Product.tenant_id == StocktakeLine.tenant_id
            ),
        )
        .outerjoin(
            ProductBatch,
            and_(
                ProductBatch.id == StocktakeLine.batch_id,
                ProductBatch.tenant_id == StocktakeLine.tenant_id,
            ),
        )
        .join(UnitOfMeasure, UnitOfMeasure.id == Product.base_unit_id)
        .where(StocktakeLine.tenant_id == tenant_id, StocktakeLine.stocktake_id == stocktake_id)
    )


async def _to_line_out(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stocktake: Stocktake,
    rows: list[Any],
) -> list[LineOut]:
    open_lines = [line for line, *_ in rows if line.counted_at is None and not stocktake.blind]
    live = await _current_quantities(db, tenant_id, open_lines) if open_lines else {}
    items: list[LineOut] = []
    for line, product, batch_number, unit_name in rows:
        counted = line.counted_at is not None
        system = (
            line.system_quantity_at_count
            if counted
            else (live.get(line.id) if not stocktake.blind else None)
        )
        items.append(
            LineOut(
                line_id=line.id,
                product_id=product.id,
                sku=product.sku,
                barcode=product.barcode,
                name_ar=product.name_ar,
                batch_id=line.batch_id,
                batch_number=batch_number,
                base_unit_id=product.base_unit_id,
                base_unit_name_ar=unit_name,
                counted_quantity=line.counted_quantity,
                counted_unit_id=line.unit_id,
                counted_base_quantity=line.counted_base_quantity,
                system_quantity=system,
                shortage_reason=ShortageReason(line.shortage_reason),
            )
        )
    return items


async def list_lines(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    stocktake_id: uuid.UUID,
    q: str | None,
    only_uncounted: bool,
    page: int,
    page_size: int,
) -> LineListOut:
    stocktake = await _get_stocktake(db, tenant_id, stocktake_id)
    query = _line_rows(tenant_id, stocktake_id)
    if q and q.strip():
        pattern = f"%{_escape_like(q.strip())}%"
        query = query.where(
            Product.name_ar.ilike(pattern, escape="\\")
            | Product.name.ilike(pattern, escape="\\")
            | Product.sku.ilike(pattern, escape="\\")
            | Product.barcode.ilike(pattern, escape="\\")
        )
    if only_uncounted:
        query = query.where(StocktakeLine.counted_at.is_(None))

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = (
        await db.execute(
            query.order_by(Product.name_ar, ProductBatch.batch_number)
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    ).all()
    items = await _to_line_out(db, tenant_id, stocktake, list(rows))
    return LineListOut(items=items, total=total, page=page, page_size=page_size)


async def count_line(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    stocktake_id: uuid.UUID,
    line_id: uuid.UUID,
    payload: LineCount,
) -> LineOut:
    stocktake = await _get_stocktake(db, tenant_id, stocktake_id)
    _require_open(stocktake)
    row = (
        await db.execute(_line_rows(tenant_id, stocktake_id).where(StocktakeLine.id == line_id))
    ).first()
    if row is None:
        raise NotFoundError(LINE_NOT_FOUND)
    line, product, _, _ = row

    unit_id = payload.unit_id or product.base_unit_id
    factor = await _conversion_factor(db, tenant_id=tenant_id, product=product, unit_id=unit_id)
    system = (await _current_quantities(db, tenant_id, [line]))[line.id]

    line.counted_quantity = payload.quantity
    line.unit_id = unit_id
    line.counted_base_quantity = _q4(payload.quantity * factor)
    line.system_quantity_at_count = system
    line.counted_by = actor_id
    line.counted_at = datetime.now(UTC)
    if payload.shortage_reason is not None:
        line.shortage_reason = payload.shortage_reason.value
    await db.commit()

    fresh = (
        await db.execute(_line_rows(tenant_id, stocktake_id).where(StocktakeLine.id == line_id))
    ).all()
    return (await _to_line_out(db, tenant_id, stocktake, list(fresh)))[0]


async def review(db: AsyncSession, *, tenant_id: uuid.UUID, stocktake_id: uuid.UUID) -> ReviewOut:
    await _get_stocktake(db, tenant_id, stocktake_id)
    rows = (
        await db.execute(
            _line_rows(tenant_id, stocktake_id).order_by(Product.name_ar, ProductBatch.batch_number)
        )
    ).all()
    counted_lines = [line for line, *_ in rows if line.counted_at is not None]
    live = await _current_quantities(db, tenant_id, counted_lines) if counted_lines else {}

    shortages: list[ReviewItem] = []
    surpluses: list[ReviewItem] = []
    uncounted: list[UncountedItem] = []
    unchanged = 0
    for line, product, batch_number, unit_name in rows:
        if line.counted_at is None:
            uncounted.append(
                UncountedItem(
                    line_id=line.id,
                    product_id=product.id,
                    name_ar=product.name_ar,
                    batch_number=batch_number,
                )
            )
            continue
        difference = _difference(line)
        if difference == 0:
            unchanged += 1
            continue
        item = ReviewItem(
            line_id=line.id,
            product_id=product.id,
            name_ar=product.name_ar,
            batch_number=batch_number,
            base_unit_name_ar=unit_name,
            system_quantity_at_count=line.system_quantity_at_count,
            counted_base_quantity=line.counted_base_quantity,
            difference=difference,
            current_quantity=live[line.id],
            shortage_reason=ShortageReason(line.shortage_reason),
        )
        (shortages if difference < 0 else surpluses).append(item)
    return ReviewOut(
        shortages=shortages, surpluses=surpluses, unchanged=unchanged, uncounted=uncounted
    )


async def apply(
    db: AsyncSession, *, tenant_id: uuid.UUID, actor_id: uuid.UUID, stocktake_id: uuid.UUID
) -> ApplyOut:
    stocktake = await _get_stocktake(db, tenant_id, stocktake_id, lock=True)
    _require_open(stocktake)

    base_unit = aliased(UnitOfMeasure)
    rows = (
        await db.execute(
            select(StocktakeLine, Product.name_ar, Product.base_unit_id)
            .join(
                Product,
                and_(
                    Product.id == StocktakeLine.product_id,
                    Product.tenant_id == StocktakeLine.tenant_id,
                ),
            )
            .join(base_unit, base_unit.id == Product.base_unit_id)
            .where(
                StocktakeLine.tenant_id == tenant_id,
                StocktakeLine.stocktake_id == stocktake_id,
                StocktakeLine.counted_at.is_not(None),
            )
            # A stable order keeps two concurrent applies from deadlocking on balances.
            .order_by(StocktakeLine.product_id, StocktakeLine.batch_id)
        )
    ).all()
    corrections = [
        (line, name, base_unit_id, _difference(line)) for line, name, base_unit_id in rows
    ]
    corrections = [c for c in corrections if c[3] != 0]
    if len(corrections) > MAX_CORRECTIONS:
        raise UnprocessableError(TOO_MANY)

    for line, name, base_unit_id, difference in corrections:
        movement_type = (
            StockMovementType.ADJUSTMENT_IN
            if difference > 0
            else _SHORTAGE_TYPE[ShortageReason(line.shortage_reason)]
        )
        try:
            await apply_movement(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                product_id=line.product_id,
                movement_type=movement_type,
                quantity=abs(difference),
                unit_id=base_unit_id,
                reason=f"جرد: {stocktake.name}",
                batch_id=line.batch_id,
                reference_type="stocktake",
                reference_id=stocktake.id,
            )
        except ConflictError as exc:
            await db.rollback()
            raise ConflictError(WOULD_GO_NEGATIVE, details={"product_name": name}) from exc

    stocktake.status = StocktakeStatus.APPLIED.value
    stocktake.applied_by = actor_id
    stocktake.applied_at = datetime.now(UTC)
    await audit.record(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="stocktake.applied",
        entity_type="stocktake",
        entity_id=stocktake.id,
        meta={"corrections": len(corrections), "counted": len(rows)},
    )
    await db.commit()
    logger.info("stocktake.applied", extra={"tenant_id": str(tenant_id), "rows": len(corrections)})
    return ApplyOut(corrections=len(corrections))


async def cancel(
    db: AsyncSession, *, tenant_id: uuid.UUID, actor_id: uuid.UUID, stocktake_id: uuid.UUID
) -> StocktakeOut:
    stocktake = await _get_stocktake(db, tenant_id, stocktake_id, lock=True)
    _require_open(stocktake)
    stocktake.status = StocktakeStatus.CANCELLED.value
    await audit.record(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="stocktake.cancelled",
        entity_type="stocktake",
        entity_id=stocktake.id,
    )
    await db.commit()
    return await _out(db, stocktake)
