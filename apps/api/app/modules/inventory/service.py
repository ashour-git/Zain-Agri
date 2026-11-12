"""Inventory services: balances, ledger, adjustments, batches.

Correctness model
-----------------
``stock_movements`` is the source of truth. ``inventory_balances`` is a projection
that is only ever written here, in the same transaction as the movement. Every
mutation first creates (or finds) the balance row and takes a row lock on it, so
two concurrent adjustments for the same product serialise. The lock is also the
mutex used for batch-level checks: no other movement for the same product can be
in flight while the batch sum is verified.

Negative stock is rejected. An opening balance is accepted only while the product
has no movements at all. Anything else is a compensating adjustment.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ForbiddenError, NotFoundError, UnprocessableError
from app.modules.audit import service as audit
from app.modules.auth.dependencies import TenantContext
from app.modules.authorization.permissions import Permission
from app.modules.catalog.models import (
    Product,
    ProductCategory,
    ProductStatus,
    ProductUnitConversion,
    UnitOfMeasure,
)
from app.modules.catalog.schemas import StockStatus
from app.modules.catalog.service import _q4, stock_status
from app.modules.identity.models import User
from app.modules.inventory.models import (
    IMPLEMENTED_MOVEMENT_TYPES,
    INBOUND_MOVEMENT_TYPES,
    InventoryBalance,
    ProductBatch,
    StockMovement,
    StockMovementType,
)
from app.modules.inventory.schemas import (
    AdjustmentOut,
    AdjustmentRequest,
    BatchCreate,
    BatchListOut,
    BatchOut,
    InventoryDetailOut,
    InventoryItemOut,
    InventoryListOut,
    MovementDirection,
    MovementListOut,
    MovementOut,
)


def _movement_direction(movement_type: StockMovementType) -> MovementDirection:
    return "in" if movement_type in INBOUND_MOVEMENT_TYPES else "out"


def _movement_query(tenant_id: uuid.UUID) -> Any:
    return (
        select(
            StockMovement,
            Product.name_ar,
            UnitOfMeasure.code,
            UnitOfMeasure.name_ar,
            ProductBatch.batch_number,
            User.full_name,
        )
        .join(
            Product,
            and_(
                Product.id == StockMovement.product_id,
                Product.tenant_id == StockMovement.tenant_id,
            ),
        )
        .join(UnitOfMeasure, UnitOfMeasure.id == StockMovement.unit_id)
        .outerjoin(
            ProductBatch,
            and_(
                ProductBatch.id == StockMovement.batch_id,
                ProductBatch.tenant_id == StockMovement.tenant_id,
            ),
        )
        .outerjoin(User, User.id == StockMovement.created_by)
        .where(StockMovement.tenant_id == tenant_id)
    )


def _to_movement_out(row: Any, *, view_cost: bool) -> MovementOut:
    (
        movement,
        product_name_ar,
        unit_code,
        unit_name_ar,
        batch_number,
        actor_name,
    ) = row
    return MovementOut(
        id=movement.id,
        product_id=movement.product_id,
        product_name_ar=product_name_ar,
        batch_id=movement.batch_id,
        batch_number=batch_number,
        movement_type=movement.movement_type,
        direction=_movement_direction(movement.movement_type),
        quantity=movement.quantity,
        unit_id=movement.unit_id,
        unit_code=unit_code,
        unit_name_ar=unit_name_ar,
        base_quantity=movement.base_quantity,
        unit_cost=movement.unit_cost if view_cost else None,
        notes=movement.notes,
        created_by=movement.created_by,
        created_by_name=actor_name,
        created_at=movement.created_at,
    )


async def _movement_out(
    db: AsyncSession, *, tenant_id: uuid.UUID, movement_id: uuid.UUID, view_cost: bool
) -> MovementOut:
    row = (
        await db.execute(_movement_query(tenant_id).where(StockMovement.id == movement_id))
    ).one()
    return _to_movement_out(row, view_cost=view_cost)


# --- inventory list ---------------------------------------------------------


def _inventory_query(tenant_id: uuid.UUID) -> Any:
    return (
        select(
            Product,
            func.coalesce(ProductCategory.name_ar, ProductCategory.name),
            UnitOfMeasure.code,
            UnitOfMeasure.name_ar,
            func.coalesce(InventoryBalance.quantity, Decimal("0")),
            InventoryBalance.updated_at,
        )
        .outerjoin(
            ProductCategory,
            and_(
                ProductCategory.id == Product.category_id,
                ProductCategory.tenant_id == Product.tenant_id,
            ),
        )
        .join(UnitOfMeasure, UnitOfMeasure.id == Product.base_unit_id)
        .outerjoin(
            InventoryBalance,
            and_(
                InventoryBalance.product_id == Product.id,
                InventoryBalance.tenant_id == Product.tenant_id,
            ),
        )
        .where(Product.tenant_id == tenant_id)
    )


def _to_inventory_item(row: Any) -> InventoryItemOut:
    product, category_name, unit_code, unit_name_ar, quantity, updated_at = row
    qty = _q4(Decimal(quantity))
    return InventoryItemOut(
        product_id=product.id,
        sku=product.sku,
        name_ar=product.name_ar,
        name=product.name,
        category_id=product.category_id,
        category_name=category_name,
        base_unit_id=product.base_unit_id,
        base_unit_code=unit_code,
        base_unit_name_ar=unit_name_ar,
        quantity=qty,
        minimum_stock=product.minimum_stock,
        stock_status=stock_status(qty, product.minimum_stock),
        tracks_batches=product.tracks_batches,
        product_status=product.status,
        sale_price=product.sale_price,
        updated_at=updated_at,
    )


async def list_inventory(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    page: int,
    page_size: int,
    q: str | None = None,
    category_id: uuid.UUID | None = None,
    stock: StockStatus | None = None,
) -> InventoryListOut:
    filters: list[Any] = [Product.tenant_id == tenant_id]
    if q:
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        filters.append(
            or_(
                Product.name_ar.ilike(pattern, escape="\\"),
                Product.name.ilike(pattern, escape="\\"),
                Product.sku.ilike(pattern, escape="\\"),
                Product.barcode.ilike(pattern, escape="\\"),
            )
        )
    if category_id is not None:
        filters.append(Product.category_id == category_id)

    quantity = func.coalesce(InventoryBalance.quantity, Decimal("0"))
    if stock == "out":
        filters.append(quantity <= 0)
    elif stock == "low":
        filters.append(and_(quantity > 0, quantity <= Product.minimum_stock))
    elif stock == "ok":
        filters.append(quantity > Product.minimum_stock)

    total = (
        await db.execute(
            select(func.count(Product.id))
            .select_from(Product)
            .outerjoin(
                InventoryBalance,
                and_(
                    InventoryBalance.product_id == Product.id,
                    InventoryBalance.tenant_id == Product.tenant_id,
                ),
            )
            .where(*filters)
        )
    ).scalar_one()

    rows = (
        await db.execute(
            _inventory_query(tenant_id)
            .where(*filters)
            .order_by(Product.name_ar, Product.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return InventoryListOut(
        items=[_to_inventory_item(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


async def get_inventory_detail(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    product_id: uuid.UUID,
    view_cost: bool,
) -> InventoryDetailOut:
    row = (await db.execute(_inventory_query(tenant_id).where(Product.id == product_id))).first()
    if row is None:
        raise NotFoundError("Product not found")

    batches = await list_batches(
        db, tenant_id=tenant_id, page=1, page_size=100, product_id=product_id
    )
    movements = await list_movements(
        db,
        tenant_id=tenant_id,
        page=1,
        page_size=20,
        product_id=product_id,
        view_cost=view_cost,
    )
    return InventoryDetailOut(
        product=_to_inventory_item(row),
        batches=batches.items,
        movements=movements.items,
    )


# --- ledger -----------------------------------------------------------------


async def list_movements(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    page: int,
    page_size: int,
    product_id: uuid.UUID | None = None,
    movement_type: StockMovementType | None = None,
    batch_id: uuid.UUID | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    view_cost: bool = False,
) -> MovementListOut:
    filters: list[Any] = [StockMovement.tenant_id == tenant_id]
    if product_id is not None:
        filters.append(StockMovement.product_id == product_id)
    if movement_type is not None:
        filters.append(StockMovement.movement_type == movement_type)
    if batch_id is not None:
        filters.append(StockMovement.batch_id == batch_id)
    if created_from is not None:
        filters.append(StockMovement.created_at >= created_from)
    if created_to is not None:
        filters.append(StockMovement.created_at <= created_to)

    total = (await db.execute(select(func.count(StockMovement.id)).where(*filters))).scalar_one()
    rows = (
        await db.execute(
            _movement_query(tenant_id)
            .where(*filters)
            .order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return MovementListOut(
        items=[_to_movement_out(row, view_cost=view_cost) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


async def _conversion_factor(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    product: Product,
    unit_id: uuid.UUID,
) -> Decimal:
    if unit_id == product.base_unit_id:
        return Decimal("1")

    units = {
        unit.id: unit
        for unit in (
            await db.execute(
                select(UnitOfMeasure).where(UnitOfMeasure.id.in_([product.base_unit_id, unit_id]))
            )
        ).scalars()
    }
    base_unit = units.get(product.base_unit_id)
    unit = units.get(unit_id)
    if base_unit is None or unit is None:
        raise UnprocessableError("Unknown unit of measure")
    if base_unit.dimension != unit.dimension:
        raise UnprocessableError("Units belong to different dimensions")

    conversion = await db.scalar(
        select(ProductUnitConversion).where(
            ProductUnitConversion.tenant_id == tenant_id,
            ProductUnitConversion.product_id == product.id,
            or_(
                and_(
                    ProductUnitConversion.from_unit_id == unit_id,
                    ProductUnitConversion.to_unit_id == product.base_unit_id,
                ),
                and_(
                    ProductUnitConversion.from_unit_id == product.base_unit_id,
                    ProductUnitConversion.to_unit_id == unit_id,
                ),
            ),
        )
    )
    if conversion is None:
        raise UnprocessableError(
            "No conversion exists between this unit and the product's base unit"
        )
    if conversion.from_unit_id == unit_id:
        return conversion.factor
    return Decimal("1") / conversion.factor


async def _locked_balance(
    db: AsyncSession, *, tenant_id: uuid.UUID, product_id: uuid.UUID
) -> InventoryBalance:
    """Create the projection row if needed, then lock it.

    ``ON CONFLICT DO NOTHING`` makes the first-ever movement race-safe: the
    second transaction blocks on the conflicting insert, then proceeds to the
    ``FOR UPDATE`` select once the first one commits.
    """
    await db.execute(
        pg_insert(InventoryBalance)
        .values(tenant_id=tenant_id, product_id=product_id, quantity=Decimal("0"))
        .on_conflict_do_nothing(index_elements=["tenant_id", "product_id"])
    )
    balance = (
        await db.execute(
            select(InventoryBalance)
            .where(
                InventoryBalance.tenant_id == tenant_id,
                InventoryBalance.product_id == product_id,
            )
            .with_for_update()
        )
    ).scalar_one()
    return balance


@dataclass(frozen=True)
class AppliedMovement:
    movement: StockMovement
    balance_before: Decimal
    balance_after: Decimal


async def apply_movement(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    product_id: uuid.UUID,
    movement_type: StockMovementType,
    quantity: Decimal,
    unit_id: uuid.UUID,
    reason: str,
    batch_id: uuid.UUID | None = None,
    unit_cost: Decimal | None = None,
    reference_type: str | None = None,
    reference_id: uuid.UUID | None = None,
) -> AppliedMovement:
    """Validate and write one movement in the caller's transaction (no commit).

    Callers that post several movements (a stocktake) commit once, so the
    whole set is applied or none of it is.
    """
    if movement_type not in IMPLEMENTED_MOVEMENT_TYPES:
        raise UnprocessableError(f"{movement_type.value} is not writable yet")
    if unit_cost is not None and movement_type not in INBOUND_MOVEMENT_TYPES:
        raise UnprocessableError("Cost can only be recorded on inbound movements")

    product = await db.scalar(
        select(Product).where(Product.id == product_id, Product.tenant_id == tenant_id)
    )
    if product is None:
        raise NotFoundError("Product not found")
    if product.status is ProductStatus.ARCHIVED:
        raise ConflictError("Archived products cannot receive stock movements")

    factor = await _conversion_factor(db, tenant_id=tenant_id, product=product, unit_id=unit_id)

    batch: ProductBatch | None = None
    if batch_id is not None:
        batch = await db.scalar(
            select(ProductBatch).where(
                ProductBatch.id == batch_id, ProductBatch.tenant_id == tenant_id
            )
        )
        if batch is None:
            raise UnprocessableError("Batch does not belong to this workspace")
        if batch.product_id != product.id:
            raise UnprocessableError("Batch does not belong to this product")
        if not product.tracks_batches:
            raise UnprocessableError("This product does not track batches")
    elif product.tracks_batches:
        raise UnprocessableError("A batch is required for this product")

    balance = await _locked_balance(db, tenant_id=tenant_id, product_id=product.id)
    balance_before = _q4(balance.quantity)

    if movement_type is StockMovementType.OPENING_BALANCE:
        # Once per product, or once per batch for a batch-tracked product.
        prior_query = select(func.count(StockMovement.id)).where(
            StockMovement.tenant_id == tenant_id,
            StockMovement.product_id == product.id,
        )
        if batch is not None:
            prior_query = prior_query.where(StockMovement.batch_id == batch.id)
        if await db.scalar(prior_query):
            raise ConflictError("An opening balance can only be recorded once per product")

    signed = quantity if movement_type in INBOUND_MOVEMENT_TYPES else -quantity
    base_delta = _q4(signed * factor)
    if base_delta == 0:
        raise UnprocessableError("Quantity is too small for the product's precision")

    balance_after = _q4(balance_before + base_delta)
    if balance_after < 0:
        raise ConflictError(
            "Insufficient stock for this adjustment",
            details={"available": str(balance_before), "requested": str(-base_delta)},
        )

    if batch is not None and base_delta < 0:
        batch_quantity = (
            await db.execute(
                select(func.coalesce(func.sum(StockMovement.base_quantity), Decimal("0"))).where(
                    StockMovement.tenant_id == tenant_id,
                    StockMovement.batch_id == batch.id,
                )
            )
        ).scalar_one()
        available_in_batch = _q4(Decimal(batch_quantity))
        if available_in_batch + base_delta < 0:
            raise ConflictError(
                "Insufficient stock in this batch",
                details={
                    "batch_id": str(batch.id),
                    "available": str(available_in_batch),
                    "requested": str(-base_delta),
                },
            )

    movement = StockMovement(
        tenant_id=tenant_id,
        product_id=product.id,
        batch_id=batch.id if batch else None,
        movement_type=movement_type,
        quantity=quantity,
        unit_id=unit_id,
        base_quantity=base_delta,
        unit_cost=unit_cost,
        reference_type=reference_type,
        reference_id=reference_id,
        notes=reason,
        created_by=actor_id,
    )
    db.add(movement)
    balance.quantity = balance_after
    await db.flush()

    await audit.record(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="inventory.movement.created",
        entity_type="stock_movement",
        entity_id=movement.id,
        after_state={
            "product_id": movement.product_id,
            "batch_id": movement.batch_id,
            "movement_type": movement.movement_type,
            "quantity": movement.quantity,
            "unit_id": movement.unit_id,
            "base_quantity": movement.base_quantity,
            "unit_cost": movement.unit_cost,
        },
        meta={
            "reason": reason,
            "balance_before": balance_before,
            "balance_after": balance_after,
        },
    )
    return AppliedMovement(movement, balance_before, balance_after)


async def record_movement(
    db: AsyncSession,
    *,
    context: TenantContext,
    actor_id: uuid.UUID,
    payload: AdjustmentRequest,
) -> AdjustmentOut:
    if payload.unit_cost is not None and not context.allows(Permission.INVENTORY_VIEW_COST):
        raise ForbiddenError(
            "Your role cannot record costs",
            details={"permission": Permission.INVENTORY_VIEW_COST.value},
        )
    applied = await apply_movement(
        db,
        tenant_id=context.tenant.id,
        actor_id=actor_id,
        product_id=payload.product_id,
        movement_type=payload.movement_type,
        quantity=payload.quantity,
        unit_id=payload.unit_id,
        reason=payload.reason,
        batch_id=payload.batch_id,
        unit_cost=payload.unit_cost,
    )
    movement_id = applied.movement.id
    await db.commit()

    movement_out = await _movement_out(
        db,
        tenant_id=context.tenant.id,
        movement_id=movement_id,
        view_cost=context.allows(Permission.INVENTORY_VIEW_COST),
    )
    return AdjustmentOut(
        movement=movement_out,
        balance_before=applied.balance_before,
        balance_after=applied.balance_after,
    )


# --- batches ----------------------------------------------------------------


async def list_batches(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    page: int,
    page_size: int,
    product_id: uuid.UUID | None = None,
    q: str | None = None,
    expiring_by: date | None = None,
    in_stock_only: bool = False,
) -> BatchListOut:
    filters: list[Any] = [ProductBatch.tenant_id == tenant_id]
    if expiring_by is not None:
        filters.append(ProductBatch.expiry_date.is_not(None))
        filters.append(ProductBatch.expiry_date <= expiring_by)
    if product_id is not None:
        filters.append(ProductBatch.product_id == product_id)
    if q:
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        filters.append(ProductBatch.batch_number.ilike(f"%{escaped}%", escape="\\"))

    quantity = (
        select(func.coalesce(func.sum(StockMovement.base_quantity), Decimal("0")))
        .where(
            StockMovement.tenant_id == tenant_id,
            StockMovement.batch_id == ProductBatch.id,
        )
        .correlate(ProductBatch)
        .scalar_subquery()
    )
    if in_stock_only:
        filters.append(quantity > 0)

    total = (await db.execute(select(func.count(ProductBatch.id)).where(*filters))).scalar_one()
    rows = (
        await db.execute(
            select(ProductBatch, Product.name_ar, quantity)
            .join(
                Product,
                and_(
                    Product.id == ProductBatch.product_id,
                    Product.tenant_id == ProductBatch.tenant_id,
                ),
            )
            .where(*filters)
            .order_by(
                ProductBatch.expiry_date.asc().nulls_last(),
                ProductBatch.created_at.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    items = [
        BatchOut(
            id=batch.id,
            product_id=batch.product_id,
            product_name_ar=product_name_ar,
            batch_number=batch.batch_number,
            expiry_date=batch.expiry_date,
            quantity=_q4(Decimal(batch_quantity)),
            created_at=batch.created_at,
        )
        for batch, product_name_ar, batch_quantity in rows
    ]
    return BatchListOut(items=items, total=total, page=page, page_size=page_size)


async def create_batch(
    db: AsyncSession,
    *,
    context: TenantContext,
    actor_id: uuid.UUID,
    payload: BatchCreate,
) -> BatchOut:
    product = await db.scalar(
        select(Product).where(
            Product.id == payload.product_id, Product.tenant_id == context.tenant.id
        )
    )
    if product is None:
        raise NotFoundError("Product not found")
    if not product.tracks_batches:
        raise UnprocessableError("This product does not track batches")
    if product.status is ProductStatus.ARCHIVED:
        raise ConflictError("Archived products cannot receive new batches")

    exists = await db.scalar(
        select(ProductBatch.id).where(
            ProductBatch.tenant_id == context.tenant.id,
            ProductBatch.product_id == product.id,
            ProductBatch.batch_number == payload.batch_number,
        )
    )
    if exists is not None:
        raise ConflictError("A batch with this number already exists for the product")

    batch = ProductBatch(tenant_id=context.tenant.id, **payload.model_dump())
    db.add(batch)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("A batch with this number already exists for the product") from exc

    await audit.record(
        db,
        tenant_id=context.tenant.id,
        actor_id=actor_id,
        action="batch.created",
        entity_type="product_batch",
        entity_id=batch.id,
        after_state={
            "product_id": batch.product_id,
            "batch_number": batch.batch_number,
            "expiry_date": batch.expiry_date,
        },
    )
    await db.commit()
    return BatchOut(
        id=batch.id,
        product_id=batch.product_id,
        product_name_ar=product.name_ar,
        batch_number=batch.batch_number,
        expiry_date=batch.expiry_date,
        quantity=Decimal("0"),
        created_at=batch.created_at,
    )


async def reconcile(
    db: AsyncSession, *, tenant_id: uuid.UUID, product_id: uuid.UUID
) -> tuple[Decimal, Decimal]:
    """Return (ledger sum, projection). Used by tests and future admin tooling."""
    ledger = (
        await db.execute(
            select(func.coalesce(func.sum(StockMovement.base_quantity), Decimal("0"))).where(
                StockMovement.tenant_id == tenant_id,
                StockMovement.product_id == product_id,
            )
        )
    ).scalar_one()
    projection = (
        await db.execute(
            select(func.coalesce(InventoryBalance.quantity, Decimal("0"))).where(
                InventoryBalance.tenant_id == tenant_id,
                InventoryBalance.product_id == product_id,
            )
        )
    ).scalar_one()
    return _q4(Decimal(ledger)), _q4(Decimal(projection))
