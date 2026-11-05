"""Row-level security for every table introduced by Sprint 03.

A tenant that shares a connection pool with another tenant must still see only
its own rows. These tests use the runtime role, so they fail if RLS is missing,
if a policy is missing ``WITH CHECK``, or if the runtime role starts owning the
tables.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.catalog.models import (
    Brand,
    Product,
    ProductCategory,
    ProductUnitConversion,
)
from app.modules.identity.models import Tenant
from app.modules.inventory.models import (
    InventoryBalance,
    ProductBatch,
    StockMovement,
    StockMovementType,
)
from app.modules.tenancy.context import set_tenant_context
from tests.support import unit_id

TENANT_TABLES = [
    Product,
    ProductCategory,
    Brand,
    ProductUnitConversion,
    ProductBatch,
    StockMovement,
    InventoryBalance,
    AuditLog,
]


class Seeded:
    """One fully populated tenant: every Sprint 03 table has at least one row."""

    def __init__(
        self,
        tenant: Tenant,
        category: ProductCategory,
        brand: Brand,
        product: Product,
        spare_product: Product,
        conversion: ProductUnitConversion,
        batch: ProductBatch,
        movement: StockMovement,
        balance: InventoryBalance,
        audit: AuditLog,
    ) -> None:
        self.tenant = tenant
        self.category = category
        self.brand = brand
        self.product = product
        self.spare_product = spare_product
        self.conversion = conversion
        self.batch = batch
        self.movement = movement
        self.balance = balance
        self.audit = audit

    def rows(self) -> dict[type, object]:
        return {
            Product: self.product,
            ProductCategory: self.category,
            Brand: self.brand,
            ProductUnitConversion: self.conversion,
            ProductBatch: self.batch,
            StockMovement: self.movement,
            InventoryBalance: self.balance,
            AuditLog: self.audit,
        }


def _tenant(name: str) -> Tenant:
    return Tenant(name=name, slug=f"t-{uuid.uuid4().hex[:12]}")


async def _seed(session: AsyncSession, tenant: Tenant) -> Seeded:
    category = ProductCategory(tenant_id=tenant.id, name="بذور")
    brand = Brand(tenant_id=tenant.id, name=f"brand-{uuid.uuid4().hex[:6]}")
    product = Product(
        tenant_id=tenant.id,
        sku=f"SKU-{uuid.uuid4().hex[:10].upper()}",
        name_ar="بذور خيار",
        base_unit_id=unit_id("kilogram"),
        sale_price=Decimal("30.00"),
        minimum_stock=Decimal("1"),
    )
    spare_product = Product(
        tenant_id=tenant.id,
        sku=f"SKU-{uuid.uuid4().hex[:10].upper()}",
        name_ar="بذور فلفل",
        base_unit_id=unit_id("piece"),
        minimum_stock=Decimal("0"),
    )
    session.add_all([category, brand, product, spare_product])
    await session.flush()

    conversion = ProductUnitConversion(
        tenant_id=tenant.id,
        product_id=product.id,
        from_unit_id=unit_id("bag"),
        to_unit_id=unit_id("kilogram"),
        factor=Decimal("50"),
    )
    batch = ProductBatch(
        tenant_id=tenant.id,
        product_id=product.id,
        batch_number=f"B-{uuid.uuid4().hex[:6]}",
    )
    movement = StockMovement(
        tenant_id=tenant.id,
        product_id=product.id,
        movement_type=StockMovementType.OPENING_BALANCE,
        quantity=Decimal("10"),
        unit_id=unit_id("kilogram"),
        base_quantity=Decimal("10"),
    )
    balance = InventoryBalance(tenant_id=tenant.id, product_id=product.id, quantity=Decimal("10"))
    audit = AuditLog(
        tenant_id=tenant.id,
        action="product.created",
        entity_type="product",
        entity_id=product.id,
    )
    session.add_all([conversion, batch, movement, balance, audit])
    await session.commit()
    return Seeded(
        tenant,
        category,
        brand,
        product,
        spare_product,
        conversion,
        batch,
        movement,
        balance,
        audit,
    )


def _primary_key(obj: object) -> tuple[object, ...]:
    return tuple(
        getattr(obj, column.key)
        for column in obj.__table__.primary_key.columns  # type: ignore[attr-defined]
    )


@pytest.mark.parametrize("model", TENANT_TABLES, ids=lambda m: m.__tablename__)
async def test_other_tenants_rows_are_invisible(
    db_session: AsyncSession,
    owner_session: AsyncSession,
    model: type,
) -> None:
    tenant_a, tenant_b = _tenant("Alpha Agri"), _tenant("Beta Agri")
    owner_session.add_all([tenant_a, tenant_b])
    await owner_session.flush()
    seeded_a = await _seed(owner_session, tenant_a)
    seeded_b = await _seed(owner_session, tenant_b)

    await set_tenant_context(db_session, tenant_a.id)
    visible = list((await db_session.execute(select(model))).scalars())

    assert visible
    assert {row.tenant_id for row in visible} == {tenant_a.id}
    assert _primary_key(seeded_a.rows()[model]) in {_primary_key(row) for row in visible}
    assert _primary_key(seeded_b.rows()[model]) not in {_primary_key(row) for row in visible}


@pytest.mark.parametrize("model", TENANT_TABLES, ids=lambda m: m.__tablename__)
async def test_without_context_nothing_is_visible(
    db_session: AsyncSession,
    owner_session: AsyncSession,
    model: type,
) -> None:
    tenant = _tenant("No Context Ltd")
    owner_session.add(tenant)
    await owner_session.flush()
    await _seed(owner_session, tenant)

    count = (await db_session.execute(select(func.count()).select_from(model))).scalar_one()

    assert count == 0


@pytest.mark.parametrize("model", TENANT_TABLES, ids=lambda m: m.__tablename__)
async def test_an_unknown_tenant_context_behaves_like_none(
    db_session: AsyncSession,
    owner_session: AsyncSession,
    model: type,
) -> None:
    tenant = _tenant("Known Tenant")
    owner_session.add(tenant)
    await owner_session.flush()
    await _seed(owner_session, tenant)

    await set_tenant_context(db_session, uuid.uuid4())

    count = (await db_session.execute(select(func.count()).select_from(model))).scalar_one()
    assert count == 0


def _foreign_row(model: type, seeded: Seeded) -> object:
    """A valid-shaped row for ``seeded``'s tenant, unique where required.

    ``inventory_balances`` has a composite primary key, so it points at the
    spare product; every other table's unique columns are re-randomised so a
    duplicate-key error can never mask the RLS violation this test is after.
    """
    tenant_id = seeded.tenant.id
    suffix = uuid.uuid4().hex[:8]

    if model is Product:
        return Product(
            tenant_id=tenant_id,
            sku=f"SKU-{suffix.upper()}",
            name_ar="سماد يوريا",
            base_unit_id=unit_id("piece"),
            minimum_stock=Decimal("0"),
        )
    if model is ProductCategory:
        return ProductCategory(tenant_id=tenant_id, name=f"تصنيف-{suffix}")
    if model is Brand:
        return Brand(tenant_id=tenant_id, name=f"علامة-{suffix}")
    if model is ProductUnitConversion:
        return ProductUnitConversion(
            tenant_id=tenant_id,
            product_id=seeded.product.id,
            from_unit_id=unit_id("gram"),
            to_unit_id=unit_id("kilogram"),
            factor=Decimal("0.001"),
        )
    if model is ProductBatch:
        return ProductBatch(
            tenant_id=tenant_id,
            product_id=seeded.product.id,
            batch_number=f"B-{suffix}",
        )
    if model is StockMovement:
        return StockMovement(
            tenant_id=tenant_id,
            product_id=seeded.product.id,
            movement_type=StockMovementType.ADJUSTMENT_IN,
            quantity=Decimal("1"),
            unit_id=unit_id("kilogram"),
            base_quantity=Decimal("1"),
        )
    if model is InventoryBalance:
        return InventoryBalance(
            tenant_id=tenant_id, product_id=seeded.spare_product.id, quantity=Decimal("1")
        )
    if model is AuditLog:
        return AuditLog(
            tenant_id=tenant_id,
            action="brand.created",
            entity_type="brand",
            entity_id=seeded.brand.id,
        )
    raise AssertionError(f"unhandled model {model}")


@pytest.mark.parametrize("model", TENANT_TABLES, ids=lambda m: m.__tablename__)
async def test_a_row_for_another_tenant_cannot_be_inserted(
    db_session: AsyncSession,
    owner_session: AsyncSession,
    model: type,
) -> None:
    tenant_a, tenant_b = _tenant("Alpha Agri"), _tenant("Beta Agri")
    owner_session.add_all([tenant_a, tenant_b])
    await owner_session.flush()
    seeded_b = await _seed(owner_session, tenant_b)

    await set_tenant_context(db_session, tenant_a.id)
    db_session.add(_foreign_row(model, seeded_b))

    with pytest.raises(DBAPIError, match="row-level security"):
        await db_session.commit()
    await db_session.rollback()


async def test_own_tenant_writes_are_accepted(
    db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    tenant = _tenant("Writer Ltd")
    owner_session.add(tenant)
    await owner_session.commit()

    await set_tenant_context(db_session, tenant.id)
    db_session.add(
        Product(
            tenant_id=tenant.id,
            sku=f"SKU-{uuid.uuid4().hex[:10].upper()}",
            name_ar="سماد",
            base_unit_id=unit_id("piece"),
            minimum_stock=Decimal("0"),
        )
    )
    await db_session.commit()

    count = (await db_session.execute(select(func.count()).select_from(Product))).scalar_one()
    assert count == 1
