"""Catalog services: units, categories, brands, products, conversions.

Every mutating function writes its audit row before committing, so the business
change and its audit trail are one transaction. Product reads deliberately join
the inventory balance projection: the catalog list shows stock without the
frontend making a second request per row.
"""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ForbiddenError, NotFoundError, UnprocessableError
from app.modules.audit import service as audit
from app.modules.auth.dependencies import TenantContext
from app.modules.authorization.permissions import Permission
from app.modules.catalog.models import (
    Brand,
    Product,
    ProductCategory,
    ProductStatus,
    ProductUnitConversion,
    UnitOfMeasure,
)
from app.modules.catalog.schemas import (
    BrandCreate,
    BrandOut,
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    ConversionCreate,
    ConversionOut,
    ProductCreate,
    ProductDetailOut,
    ProductListOut,
    ProductOut,
    ProductUpdate,
    StockStatus,
    UnitOut,
)
from app.modules.inventory.models import InventoryBalance, ProductBatch, StockMovement

MAX_CATEGORY_DEPTH = 100


def stock_status(quantity: Decimal, minimum_stock: Decimal) -> StockStatus:
    """Single definition shared by the catalog and inventory lists."""
    if quantity <= 0:
        return "out"
    if quantity <= minimum_stock:
        return "low"
    return "ok"


def _q4(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"))


async def list_units(db: AsyncSession) -> list[UnitOut]:
    units = (await db.execute(select(UnitOfMeasure).order_by(UnitOfMeasure.name))).scalars()
    return [UnitOut.model_validate(unit) for unit in units]


async def _units_map(db: AsyncSession) -> dict[uuid.UUID, UnitOfMeasure]:
    units = (await db.execute(select(UnitOfMeasure))).scalars()
    return {unit.id: unit for unit in units}


def _product_query(tenant_id: uuid.UUID) -> Any:
    return (
        select(
            Product,
            func.coalesce(ProductCategory.name_ar, ProductCategory.name),
            func.coalesce(Brand.name_ar, Brand.name),
            UnitOfMeasure.code,
            UnitOfMeasure.name_ar,
            func.coalesce(InventoryBalance.quantity, Decimal("0")),
        )
        .outerjoin(
            ProductCategory,
            and_(
                ProductCategory.id == Product.category_id,
                ProductCategory.tenant_id == Product.tenant_id,
            ),
        )
        .outerjoin(
            Brand,
            and_(Brand.id == Product.brand_id, Brand.tenant_id == Product.tenant_id),
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


def _to_product_out(
    row: Any,
    *,
    units: dict[uuid.UUID, UnitOfMeasure],
    view_cost: bool,
) -> ProductOut:
    (
        product,
        category_name,
        brand_name,
        base_unit_code,
        base_unit_name_ar,
        stock_quantity,
    ) = row
    purchase_unit = units.get(product.purchase_unit_id) if product.purchase_unit_id else None
    sale_unit = units.get(product.sale_unit_id) if product.sale_unit_id else None
    quantity = _q4(Decimal(stock_quantity))

    return ProductOut(
        id=product.id,
        sku=product.sku,
        barcode=product.barcode,
        name_ar=product.name_ar,
        name=product.name,
        description=product.description,
        category_id=product.category_id,
        category_name=category_name,
        brand_id=product.brand_id,
        brand_name=brand_name,
        base_unit_id=product.base_unit_id,
        base_unit_code=base_unit_code,
        base_unit_name_ar=base_unit_name_ar,
        purchase_unit_id=product.purchase_unit_id,
        purchase_unit_code=purchase_unit.code if purchase_unit else None,
        sale_unit_id=product.sale_unit_id,
        sale_unit_code=sale_unit.code if sale_unit else None,
        cost_price=product.cost_price if view_cost else None,
        sale_price=product.sale_price,
        minimum_stock=product.minimum_stock,
        tracks_batches=product.tracks_batches,
        status=product.status,
        stock_quantity=quantity,
        stock_status=stock_status(quantity, product.minimum_stock),
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


async def _conversions_for(
    db: AsyncSession, tenant_id: uuid.UUID, product_id: uuid.UUID
) -> list[ConversionOut]:
    from_unit = UnitOfMeasure.__table__.alias("from_unit")
    to_unit = UnitOfMeasure.__table__.alias("to_unit")
    rows = (
        await db.execute(
            select(
                ProductUnitConversion,
                from_unit.c.code,
                to_unit.c.code,
            )
            .join(from_unit, from_unit.c.id == ProductUnitConversion.from_unit_id)
            .join(to_unit, to_unit.c.id == ProductUnitConversion.to_unit_id)
            .where(
                ProductUnitConversion.tenant_id == tenant_id,
                ProductUnitConversion.product_id == product_id,
            )
            .order_by(ProductUnitConversion.created_at)
        )
    ).all()
    return [
        ConversionOut(
            id=conversion.id,
            product_id=conversion.product_id,
            from_unit_id=conversion.from_unit_id,
            to_unit_id=conversion.to_unit_id,
            from_unit_code=from_code,
            to_unit_code=to_code,
            factor=conversion.factor,
            created_at=conversion.created_at,
        )
        for conversion, from_code, to_code in rows
    ]


async def list_products(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    page: int,
    page_size: int,
    q: str | None = None,
    category_id: uuid.UUID | None = None,
    status: ProductStatus | None = None,
    view_cost: bool = False,
) -> ProductListOut:
    filters: list[Any] = [Product.tenant_id == tenant_id]
    if q:
        pattern = f"%{_escape_like(q.strip())}%"
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
    if status is not None:
        filters.append(Product.status == status)

    total = (await db.execute(select(func.count(Product.id)).where(*filters))).scalar_one()
    rows = (
        await db.execute(
            _product_query(tenant_id)
            .where(*filters)
            .order_by(Product.name_ar, Product.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    units = await _units_map(db)
    items = [_to_product_out(row, units=units, view_cost=view_cost) for row in rows]
    return ProductListOut(items=items, total=total, page=page, page_size=page_size)


async def get_product(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    product_id: uuid.UUID,
    view_cost: bool,
) -> ProductDetailOut:
    row = (await db.execute(_product_query(tenant_id).where(Product.id == product_id))).first()
    if row is None:
        raise NotFoundError("Product not found")

    units = await _units_map(db)
    base = _to_product_out(row, units=units, view_cost=view_cost)
    conversions = await _conversions_for(db, tenant_id, product_id)
    return ProductDetailOut(**base.model_dump(), conversions=conversions)


async def _ensure_category(
    db: AsyncSession, tenant_id: uuid.UUID, category_id: uuid.UUID | None
) -> None:
    if category_id is None:
        return
    exists = await db.scalar(
        select(ProductCategory.id).where(
            ProductCategory.id == category_id, ProductCategory.tenant_id == tenant_id
        )
    )
    if exists is None:
        raise UnprocessableError("Category does not belong to this workspace")


async def _ensure_brand(db: AsyncSession, tenant_id: uuid.UUID, brand_id: uuid.UUID | None) -> None:
    if brand_id is None:
        return
    exists = await db.scalar(
        select(Brand.id).where(Brand.id == brand_id, Brand.tenant_id == tenant_id)
    )
    if exists is None:
        raise UnprocessableError("Brand does not belong to this workspace")


async def _ensure_units(db: AsyncSession, unit_ids: list[uuid.UUID]) -> None:
    found = set(
        (await db.execute(select(UnitOfMeasure.id).where(UnitOfMeasure.id.in_(unit_ids)))).scalars()
    )
    if found != set(unit_ids):
        raise UnprocessableError("Unknown unit of measure")


async def _ensure_product_unique(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    sku: str,
    barcode: str | None,
    exclude_id: uuid.UUID | None = None,
) -> None:
    sku_stmt = select(Product.id).where(Product.tenant_id == tenant_id, Product.sku == sku)
    if exclude_id is not None:
        sku_stmt = sku_stmt.where(Product.id != exclude_id)
    if await db.scalar(sku_stmt) is not None:
        raise ConflictError("SKU already exists in this workspace", details={"field": "sku"})

    if barcode:
        barcode_stmt = select(Product.id).where(
            Product.tenant_id == tenant_id, Product.barcode == barcode
        )
        if exclude_id is not None:
            barcode_stmt = barcode_stmt.where(Product.id != exclude_id)
        if await db.scalar(barcode_stmt) is not None:
            raise ConflictError(
                "Barcode already exists in this workspace", details={"field": "barcode"}
            )


def _product_state(product: Product) -> dict[str, Any]:
    return {
        "sku": product.sku,
        "barcode": product.barcode,
        "name_ar": product.name_ar,
        "name": product.name,
        "description": product.description,
        "category_id": product.category_id,
        "brand_id": product.brand_id,
        "base_unit_id": product.base_unit_id,
        "purchase_unit_id": product.purchase_unit_id,
        "sale_unit_id": product.sale_unit_id,
        "cost_price": product.cost_price,
        "sale_price": product.sale_price,
        "minimum_stock": product.minimum_stock,
        "tracks_batches": product.tracks_batches,
        "status": product.status,
    }


def _conflict_from_integrity(exc: IntegrityError, fallback: str) -> ConflictError:
    message = str(exc.orig)
    if "uq_products_tenant_sku" in message:
        return ConflictError("SKU already exists in this workspace", details={"field": "sku"})
    if "uq_products_tenant_barcode" in message:
        return ConflictError(
            "Barcode already exists in this workspace", details={"field": "barcode"}
        )
    if "uq_product_categories" in message:
        return ConflictError("A category with this name already exists at this level")
    if "uq_brands_tenant_name" in message:
        return ConflictError("A brand with this name already exists")
    if "uq_product_unit_conversions_pair" in message:
        return ConflictError("This conversion is already configured")
    return ConflictError(fallback)


async def create_product(
    db: AsyncSession,
    *,
    context: TenantContext,
    actor_id: uuid.UUID,
    payload: ProductCreate,
) -> ProductDetailOut:
    if payload.cost_price is not None and not context.allows(Permission.INVENTORY_VIEW_COST):
        raise ForbiddenError(
            "Your role cannot set cost prices",
            details={"permission": Permission.INVENTORY_VIEW_COST.value},
        )

    unit_ids = [
        unit_id
        for unit_id in (payload.base_unit_id, payload.purchase_unit_id, payload.sale_unit_id)
        if unit_id is not None
    ]
    await _ensure_units(db, list(dict.fromkeys(unit_ids)))
    await _ensure_category(db, context.tenant.id, payload.category_id)
    await _ensure_brand(db, context.tenant.id, payload.brand_id)
    await _ensure_product_unique(
        db, tenant_id=context.tenant.id, sku=payload.sku, barcode=payload.barcode
    )

    product = Product(tenant_id=context.tenant.id, **payload.model_dump())
    db.add(product)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise _conflict_from_integrity(exc, "Product conflicts with an existing record") from exc

    await audit.record(
        db,
        tenant_id=context.tenant.id,
        actor_id=actor_id,
        action="product.created",
        entity_type="product",
        entity_id=product.id,
        after_state=_product_state(product),
    )
    await db.commit()
    return await get_product(
        db,
        tenant_id=context.tenant.id,
        product_id=product.id,
        view_cost=context.allows(Permission.INVENTORY_VIEW_COST),
    )


async def update_product(
    db: AsyncSession,
    *,
    context: TenantContext,
    actor_id: uuid.UUID,
    product_id: uuid.UUID,
    payload: ProductUpdate,
) -> ProductDetailOut:
    product = await db.scalar(
        select(Product).where(Product.id == product_id, Product.tenant_id == context.tenant.id)
    )
    if product is None:
        raise NotFoundError("Product not found")
    if product.status is ProductStatus.ARCHIVED:
        raise ConflictError("Archived products cannot be modified")
    if "cost_price" in payload.model_fields_set and not context.allows(
        Permission.INVENTORY_VIEW_COST
    ):
        raise ForbiddenError(
            "Your role cannot set cost prices",
            details={"permission": Permission.INVENTORY_VIEW_COST.value},
        )

    fields = payload.model_fields_set
    for required in ("sku", "name_ar", "base_unit_id"):
        if required in fields and getattr(payload, required) is None:
            raise UnprocessableError(f"{required} cannot be null")

    if "base_unit_id" in fields and payload.base_unit_id != product.base_unit_id:
        has_movements = await db.scalar(
            select(func.count(StockMovement.id)).where(
                StockMovement.tenant_id == context.tenant.id,
                StockMovement.product_id == product.id,
            )
        )
        has_conversions = await db.scalar(
            select(func.count(ProductUnitConversion.id)).where(
                ProductUnitConversion.tenant_id == context.tenant.id,
                ProductUnitConversion.product_id == product.id,
            )
        )
        if has_movements or has_conversions:
            raise ConflictError("The base unit cannot change once conversions or movements exist")

    if "tracks_batches" in fields and payload.tracks_batches is False:
        has_batches = await db.scalar(
            select(func.count(ProductBatch.id)).where(
                ProductBatch.tenant_id == context.tenant.id,
                ProductBatch.product_id == product.id,
            )
        )
        if has_batches:
            raise ConflictError("Batch tracking is already in use for this product")

    if "sku" in fields or "barcode" in fields:
        await _ensure_product_unique(
            db,
            tenant_id=context.tenant.id,
            sku=payload.sku if "sku" in fields and payload.sku else product.sku,
            barcode=payload.barcode if "barcode" in fields else product.barcode,
            exclude_id=product.id,
        )
    if "category_id" in fields:
        await _ensure_category(db, context.tenant.id, payload.category_id)
    if "brand_id" in fields:
        await _ensure_brand(db, context.tenant.id, payload.brand_id)
    unit_fields = [f for f in ("base_unit_id", "purchase_unit_id", "sale_unit_id") if f in fields]
    unit_ids = [getattr(payload, field) for field in unit_fields]
    await _ensure_units(db, list(dict.fromkeys(uid for uid in unit_ids if uid is not None)))

    before = _product_state(product)
    for field in fields:
        setattr(product, field, getattr(payload, field))
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise _conflict_from_integrity(exc, "Product conflicts with an existing record") from exc

    await audit.record(
        db,
        tenant_id=context.tenant.id,
        actor_id=actor_id,
        action="product.updated",
        entity_type="product",
        entity_id=product.id,
        before_state=before,
        after_state=_product_state(product),
    )
    await db.commit()
    return await get_product(
        db,
        tenant_id=context.tenant.id,
        product_id=product.id,
        view_cost=context.allows(Permission.INVENTORY_VIEW_COST),
    )


async def set_product_status(
    db: AsyncSession,
    *,
    context: TenantContext,
    actor_id: uuid.UUID,
    product_id: uuid.UUID,
    status: ProductStatus,
) -> ProductDetailOut:
    product = await db.scalar(
        select(Product).where(Product.id == product_id, Product.tenant_id == context.tenant.id)
    )
    if product is None:
        raise NotFoundError("Product not found")

    if product.status is not status:
        before = _product_state(product)
        product.status = status
        await db.flush()
        await audit.record(
            db,
            tenant_id=context.tenant.id,
            actor_id=actor_id,
            action="product.archived" if status is ProductStatus.ARCHIVED else "product.restored",
            entity_type="product",
            entity_id=product.id,
            before_state=before,
            after_state=_product_state(product),
        )
        await db.commit()

    return await get_product(
        db,
        tenant_id=context.tenant.id,
        product_id=product.id,
        view_cost=context.allows(Permission.INVENTORY_VIEW_COST),
    )


# --- categories -------------------------------------------------------------


async def list_categories(db: AsyncSession, tenant_id: uuid.UUID) -> list[CategoryOut]:
    categories = (
        await db.execute(
            select(ProductCategory)
            .where(ProductCategory.tenant_id == tenant_id)
            .order_by(ProductCategory.name)
        )
    ).scalars()
    return [CategoryOut.model_validate(category) for category in categories]


def _category_name_taken(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    name: str,
    parent_id: uuid.UUID | None,
    exclude_id: uuid.UUID | None = None,
) -> Any:
    stmt = select(ProductCategory.id).where(
        ProductCategory.tenant_id == tenant_id,
        ProductCategory.name == name,
        ProductCategory.parent_id.is_(None)
        if parent_id is None
        else ProductCategory.parent_id == parent_id,
    )
    if exclude_id is not None:
        stmt = stmt.where(ProductCategory.id != exclude_id)
    return db.scalar(stmt)


async def _check_category_parent(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    category_id: uuid.UUID | None,
    parent_id: uuid.UUID | None,
) -> None:
    if parent_id is None:
        return
    if category_id is not None and parent_id == category_id:
        raise ConflictError("A category cannot be its own parent")

    parent = await db.scalar(
        select(ProductCategory).where(
            ProductCategory.id == parent_id, ProductCategory.tenant_id == tenant_id
        )
    )
    if parent is None:
        raise UnprocessableError("Parent category does not belong to this workspace")

    current: uuid.UUID | None = parent_id
    for _ in range(MAX_CATEGORY_DEPTH):
        if current is None:
            return
        if category_id is not None and current == category_id:
            raise ConflictError("Category hierarchy would contain a cycle")
        current = await db.scalar(
            select(ProductCategory.parent_id).where(
                ProductCategory.id == current, ProductCategory.tenant_id == tenant_id
            )
        )
    raise ConflictError("Category hierarchy is too deep")


async def create_category(
    db: AsyncSession,
    *,
    context: TenantContext,
    actor_id: uuid.UUID,
    payload: CategoryCreate,
) -> CategoryOut:
    await _check_category_parent(
        db, tenant_id=context.tenant.id, category_id=None, parent_id=payload.parent_id
    )
    if await _category_name_taken(
        db,
        tenant_id=context.tenant.id,
        name=payload.name,
        parent_id=payload.parent_id,
    ):
        raise ConflictError("A category with this name already exists at this level")

    category = ProductCategory(tenant_id=context.tenant.id, **payload.model_dump())
    db.add(category)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise _conflict_from_integrity(exc, "Category conflicts with an existing record") from exc

    await audit.record(
        db,
        tenant_id=context.tenant.id,
        actor_id=actor_id,
        action="category.created",
        entity_type="product_category",
        entity_id=category.id,
        after_state={
            "name": category.name,
            "name_ar": category.name_ar,
            "parent_id": category.parent_id,
        },
    )
    await db.commit()
    return CategoryOut.model_validate(category)


async def update_category(
    db: AsyncSession,
    *,
    context: TenantContext,
    actor_id: uuid.UUID,
    category_id: uuid.UUID,
    payload: CategoryUpdate,
) -> CategoryOut:
    category = await db.scalar(
        select(ProductCategory).where(
            ProductCategory.id == category_id,
            ProductCategory.tenant_id == context.tenant.id,
        )
    )
    if category is None:
        raise NotFoundError("Category not found")

    fields = payload.model_fields_set
    if "name" in fields and payload.name is None:
        raise UnprocessableError("name cannot be null")
    if "parent_id" in fields:
        await _check_category_parent(
            db,
            tenant_id=context.tenant.id,
            category_id=category.id,
            parent_id=payload.parent_id,
        )
    if "name" in fields:
        parent_id = payload.parent_id if "parent_id" in fields else category.parent_id
        if await _category_name_taken(
            db,
            tenant_id=context.tenant.id,
            name=payload.name or category.name,
            parent_id=parent_id,
            exclude_id=category.id,
        ):
            raise ConflictError("A category with this name already exists at this level")

    before = {"name": category.name, "name_ar": category.name_ar, "parent_id": category.parent_id}
    for field in fields:
        setattr(category, field, getattr(payload, field))
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise _conflict_from_integrity(exc, "Category conflicts with an existing record") from exc

    await audit.record(
        db,
        tenant_id=context.tenant.id,
        actor_id=actor_id,
        action="category.updated",
        entity_type="product_category",
        entity_id=category.id,
        before_state=before,
        after_state={
            "name": category.name,
            "name_ar": category.name_ar,
            "parent_id": category.parent_id,
        },
    )
    await db.commit()
    return CategoryOut.model_validate(category)


# --- brands -----------------------------------------------------------------


async def list_brands(db: AsyncSession, tenant_id: uuid.UUID) -> list[BrandOut]:
    brands = (
        await db.execute(select(Brand).where(Brand.tenant_id == tenant_id).order_by(Brand.name))
    ).scalars()
    return [BrandOut.model_validate(brand) for brand in brands]


async def create_brand(
    db: AsyncSession,
    *,
    context: TenantContext,
    actor_id: uuid.UUID,
    payload: BrandCreate,
) -> BrandOut:
    exists = await db.scalar(
        select(Brand.id).where(Brand.tenant_id == context.tenant.id, Brand.name == payload.name)
    )
    if exists is not None:
        raise ConflictError("A brand with this name already exists")

    brand = Brand(tenant_id=context.tenant.id, **payload.model_dump())
    db.add(brand)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise _conflict_from_integrity(exc, "Brand conflicts with an existing record") from exc

    await audit.record(
        db,
        tenant_id=context.tenant.id,
        actor_id=actor_id,
        action="brand.created",
        entity_type="brand",
        entity_id=brand.id,
        after_state={"name": brand.name, "name_ar": brand.name_ar},
    )
    await db.commit()
    return BrandOut.model_validate(brand)


# --- conversions ------------------------------------------------------------


async def create_conversion(
    db: AsyncSession,
    *,
    context: TenantContext,
    actor_id: uuid.UUID,
    product_id: uuid.UUID,
    payload: ConversionCreate,
) -> ConversionOut:
    product = await db.scalar(
        select(Product).where(Product.id == product_id, Product.tenant_id == context.tenant.id)
    )
    if product is None:
        raise NotFoundError("Product not found")
    if product.status is ProductStatus.ARCHIVED:
        raise ConflictError("Archived products cannot be modified")

    units = await _units_map(db)
    from_unit = units.get(payload.from_unit_id)
    to_unit = units.get(payload.to_unit_id)
    if from_unit is None or to_unit is None:
        raise UnprocessableError("Unknown unit of measure")
    if from_unit.dimension is not to_unit.dimension:
        raise UnprocessableError("Units belong to different dimensions")
    if product.base_unit_id not in (payload.from_unit_id, payload.to_unit_id):
        raise UnprocessableError(
            "A conversion must involve the product's base unit; chains are not inferred"
        )

    duplicate = await db.scalar(
        select(ProductUnitConversion.id).where(
            ProductUnitConversion.tenant_id == context.tenant.id,
            ProductUnitConversion.product_id == product.id,
            or_(
                and_(
                    ProductUnitConversion.from_unit_id == payload.from_unit_id,
                    ProductUnitConversion.to_unit_id == payload.to_unit_id,
                ),
                and_(
                    ProductUnitConversion.from_unit_id == payload.to_unit_id,
                    ProductUnitConversion.to_unit_id == payload.from_unit_id,
                ),
            ),
        )
    )
    if duplicate is not None:
        raise ConflictError("This conversion is already configured")

    conversion = ProductUnitConversion(
        tenant_id=context.tenant.id,
        product_id=product.id,
        from_unit_id=payload.from_unit_id,
        to_unit_id=payload.to_unit_id,
        factor=payload.factor,
    )
    db.add(conversion)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise _conflict_from_integrity(exc, "Conversion conflicts with an existing record") from exc

    await audit.record(
        db,
        tenant_id=context.tenant.id,
        actor_id=actor_id,
        action="conversion.created",
        entity_type="product_unit_conversion",
        entity_id=conversion.id,
        after_state={
            "product_id": conversion.product_id,
            "from_unit_id": conversion.from_unit_id,
            "to_unit_id": conversion.to_unit_id,
            "factor": conversion.factor,
        },
    )
    await db.commit()
    return ConversionOut(
        id=conversion.id,
        product_id=conversion.product_id,
        from_unit_id=conversion.from_unit_id,
        to_unit_id=conversion.to_unit_id,
        from_unit_code=from_unit.code,
        to_unit_code=to_unit.code,
        factor=conversion.factor,
        created_at=conversion.created_at,
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
