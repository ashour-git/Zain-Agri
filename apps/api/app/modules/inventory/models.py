"""Inventory ledger, batch metadata and balance projection.

The ledger is the source of truth. ``inventory_balances`` is a projection kept
in the same transaction as every appended movement, guarded by a row lock, so
listing stock never has to sum the ledger. Movements and balances can always be
reconciled; a mismatch is a bug, never a correction path.
"""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base, UUIDPrimaryKeyMixin


class StockMovementType(enum.StrEnum):
    """Canonical movement vocabulary.

    Every value is defined now so the ledger never needs a destructive enum
    migration; only the ones in ``IMPLEMENTED_MOVEMENT_TYPES`` are writable in
    Sprint 03. Sale/purchase/transfer workflows arrive with their modules.
    """

    OPENING_BALANCE = "opening_balance"
    PURCHASE = "purchase"
    SALE = "sale"
    CUSTOMER_RETURN = "customer_return"
    SUPPLIER_RETURN = "supplier_return"
    ADJUSTMENT_IN = "adjustment_in"
    ADJUSTMENT_OUT = "adjustment_out"
    DAMAGE = "damage"
    EXPIRY = "expiry"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"


# Writable in Sprint 03. Anything else is a future workflow with its own rules.
IMPLEMENTED_MOVEMENT_TYPES: frozenset[StockMovementType] = frozenset(
    {
        StockMovementType.OPENING_BALANCE,
        StockMovementType.ADJUSTMENT_IN,
        StockMovementType.ADJUSTMENT_OUT,
    }
)

INBOUND_MOVEMENT_TYPES: frozenset[StockMovementType] = frozenset(
    {
        StockMovementType.OPENING_BALANCE,
        StockMovementType.PURCHASE,
        StockMovementType.CUSTOMER_RETURN,
        StockMovementType.ADJUSTMENT_IN,
        StockMovementType.TRANSFER_IN,
    }
)


class ProductBatch(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "product_batches"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_product_batches_tenant_id"),
        UniqueConstraint(
            "tenant_id", "product_id", "batch_number", name="uq_product_batches_number"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_product_batches_product",
            ondelete="CASCADE",
        ),
        Index("ix_product_batches_tenant_expiry", "tenant_id", "expiry_date"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    batch_number: Mapped[str] = mapped_column(String(80), nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class StockMovement(UUIDPrimaryKeyMixin, Base):
    """Append-only ledger row.

    ``quantity`` is what the user entered in ``unit_id``; ``base_quantity`` is
    the signed change in the product's base unit, which is the only quantity the
    balance projection and every future report read.
    """

    __tablename__ = "stock_movements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_stock_movements_product",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["product_batches.tenant_id", "product_batches.id"],
            name="fk_stock_movements_batch",
            ondelete="RESTRICT",
        ),
        Index("ix_stock_movements_tenant_created", "tenant_id", "created_at"),
        Index("ix_stock_movements_tenant_product_created", "tenant_id", "product_id", "created_at"),
        Index("ix_stock_movements_tenant_batch", "tenant_id", "batch_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    movement_type: Mapped[StockMovementType] = mapped_column(
        Enum(
            StockMovementType,
            name="stock_movement_type",
            native_enum=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT"), nullable=False
    )
    base_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)

    # Cost per base unit, recorded for a future valuation module. No costing
    # method is implemented or inferred in Sprint 03.
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    reference_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class InventoryBalance(Base):
    """One row per (tenant, product); never edited outside the ledger service."""

    __tablename__ = "inventory_balances"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_inventory_balances_product",
            ondelete="CASCADE",
        ),
        Index("ix_inventory_balances_tenant_quantity", "tenant_id", "quantity"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
