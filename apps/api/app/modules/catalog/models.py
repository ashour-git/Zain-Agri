"""Product catalog models.

Units of measure are platform reference data, not tenant-owned: every store
sells kilograms and bottles, and a per-tenant copy would only create divergence
(and a conversion problem). Everything else here is scoped to one tenant and
protected by RLS.

Cross-tenant references are blocked twice: RLS hides the other tenant's rows, and
composite foreign keys ``(tenant_id, <parent_id>)`` make a mismatched pair
impossible even for code that bypasses the application predicates.
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UnitDimension(enum.StrEnum):
    """Physical dimension. Conversions are only allowed within a dimension."""

    COUNT = "count"
    MASS = "mass"
    VOLUME = "volume"


class ProductStatus(enum.StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class UnitOfMeasure(UUIDPrimaryKeyMixin, Base):
    """Global unit vocabulary, seeded by migration and read-only at runtime."""

    __tablename__ = "units_of_measure"

    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    name_ar: Mapped[str] = mapped_column(String(80), nullable=False)
    dimension: Mapped[UnitDimension] = mapped_column(
        Enum(
            UnitDimension,
            name="unit_dimension",
            native_enum=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProductCategory(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "product_categories"
    __table_args__ = (
        # Composite FK target: a child must share its parent's tenant.
        UniqueConstraint("tenant_id", "id", name="uq_product_categories_tenant_id"),
        UniqueConstraint(
            "tenant_id", "parent_id", "name", name="uq_product_categories_sibling_name"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["product_categories.tenant_id", "product_categories.id"],
            name="fk_product_categories_parent",
            ondelete="RESTRICT",
        ),
        Index("ix_product_categories_tenant_parent", "tenant_id", "parent_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    name_ar: Mapped[str | None] = mapped_column(String(120), nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Brand(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "brands"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_brands_tenant_id"),
        UniqueConstraint("tenant_id", "name", name="uq_brands_tenant_name"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    name_ar: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Product(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sku", name="uq_products_tenant_sku"),
        UniqueConstraint("tenant_id", "id", name="uq_products_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["product_categories.tenant_id", "product_categories.id"],
            name="fk_products_category",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "brand_id"],
            ["brands.tenant_id", "brands.id"],
            name="fk_products_brand",
            ondelete="RESTRICT",
        ),
        Index("ix_products_tenant_status", "tenant_id", "status"),
        Index("ix_products_tenant_name_ar", "tenant_id", "name_ar"),
        Index(
            "uq_products_tenant_barcode",
            "tenant_id",
            "barcode",
            unique=True,
            postgresql_where=text("barcode IS NOT NULL"),
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    barcode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name_ar: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    category_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    brand_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    base_unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT"), nullable=False
    )
    purchase_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT"), nullable=True
    )
    sale_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT"), nullable=True
    )

    # Money is NUMERIC, never float. Two decimals = EGP piastres.
    cost_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    sale_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    minimum_stock: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0"), server_default="0"
    )

    tracks_batches: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    status: Mapped[ProductStatus] = mapped_column(
        Enum(
            ProductStatus,
            name="product_status",
            native_enum=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=ProductStatus.ACTIVE,
        server_default=ProductStatus.ACTIVE.value,
    )


class ProductUnitConversion(UUIDPrimaryKeyMixin, Base):
    """An explicit, product-specific conversion between two units.

    A chain is never inferred: at least one side must be the product's base
    unit, which is what the inventory ledger stores. See
    docs/modules/PRODUCT_CATALOG.md.
    """

    __tablename__ = "product_unit_conversions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "product_id",
            "from_unit_id",
            "to_unit_id",
            name="uq_product_unit_conversions_pair",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_product_unit_conversions_product",
            ondelete="CASCADE",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    from_unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT"), nullable=False
    )
    to_unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT"), nullable=False
    )
    # 1 from-unit = factor to-units. Six decimals allow gram-level factors.
    factor: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
