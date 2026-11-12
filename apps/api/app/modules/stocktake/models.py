"""Stocktake header and counted lines. Both tables are tenant-scoped by RLS."""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base, UUIDPrimaryKeyMixin


class StocktakeStatus(enum.StrEnum):
    OPEN = "open"
    APPLIED = "applied"
    CANCELLED = "cancelled"


class StocktakeScope(enum.StrEnum):
    ALL = "all"
    CATEGORY = "category"


class ShortageReason(enum.StrEnum):
    SHORTAGE = "shortage"
    DAMAGE = "damage"
    EXPIRY = "expiry"


def _one_of(column: str, values: type[enum.StrEnum]) -> str:
    return f"{column} IN ({', '.join(repr(member.value) for member in values)})"


class Stocktake(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "stocktakes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_stocktakes_tenant_id"),
        CheckConstraint(_one_of("status", StocktakeStatus), name="ck_stocktakes_status"),
        CheckConstraint(_one_of("scope", StocktakeScope), name="ck_stocktakes_scope"),
        # One count at a time per shop.
        Index(
            "uq_stocktakes_one_open",
            "tenant_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_stocktakes_tenant_created", "tenant_id", "created_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    blind: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    applied_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StocktakeLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "stocktake_lines"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "stocktake_id"],
            ["stocktakes.tenant_id", "stocktakes.id"],
            name="fk_stocktake_lines_stocktake",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_stocktake_lines_product",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["product_batches.tenant_id", "product_batches.id"],
            name="fk_stocktake_lines_batch",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            _one_of("shortage_reason", ShortageReason), name="ck_stocktake_lines_reason"
        ),
        CheckConstraint(
            "counted_quantity IS NULL OR counted_quantity >= 0", name="ck_stocktake_lines_qty"
        ),
        # NULLS NOT DISTINCT: a product without a batch has exactly one line.
        Index(
            "uq_stocktake_lines_item",
            "stocktake_id",
            "product_id",
            "batch_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_stocktake_lines_stocktake", "tenant_id", "stocktake_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    stocktake_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    counted_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT"), nullable=True
    )
    counted_base_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    system_quantity_at_count: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    shortage_reason: Mapped[str] = mapped_column(String(16), nullable=False, default="shortage")
    counted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    counted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
