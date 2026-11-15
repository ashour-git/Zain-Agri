"""Sales invoices, their lines and batch draws, returns, and per-shop counters.

All tables are RLS-scoped. Child rows reference their parent through
``(tenant_id, id)`` so a row can never point into another shop.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base, UUIDPrimaryKeyMixin

MONEY = Numeric(14, 2)
QUANTITY = Numeric(18, 4)


class ShopCounter(Base):
    """The last number used for invoices or returns in one shop."""

    __tablename__ = "shop_counters"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(20), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SalesInvoice(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "sales_invoices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_sales_invoices_tenant_id"),
        UniqueConstraint("tenant_id", "number", name="uq_sales_invoices_number"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_sales_invoices_idempotency"),
        UniqueConstraint("share_token_hash", name="uq_sales_invoices_share_token"),
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_sales_invoices_customer",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "subtotal >= 0 AND discount >= 0 AND discount <= subtotal"
            " AND total = subtotal - discount"
            " AND paid >= 0 AND paid <= total AND credit = total - paid",
            name="ck_sales_invoices_amounts",
        ),
        Index("ix_sales_invoices_tenant_created", "tenant_id", "created_at"),
        Index("ix_sales_invoices_customer", "tenant_id", "customer_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    subtotal: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    discount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    total: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    paid: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    credit: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    share_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = _created_at()


class SalesInvoiceLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "sales_invoice_lines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_sales_invoice_lines_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "invoice_id"],
            ["sales_invoices.tenant_id", "sales_invoices.id"],
            name="fk_sales_invoice_lines_invoice",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_sales_invoice_lines_product",
            ondelete="RESTRICT",
        ),
        CheckConstraint("quantity > 0 AND base_quantity > 0", name="ck_sales_invoice_lines_qty"),
        CheckConstraint("unit_price >= 0 AND line_total >= 0", name="ck_sales_invoice_lines_money"),
        Index("ix_sales_invoice_lines_invoice", "tenant_id", "invoice_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # Order the lines were entered in at the counter (1, 2, 3...).
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # Snapshot: a later rename or price change never alters an old invoice.
    name_ar: Mapped[str] = mapped_column(String(200), nullable=False)
    unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    base_quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False)


class SalesInvoiceLineBatch(UUIDPrimaryKeyMixin, Base):
    """Which batch a line drew from, so a return puts stock back in the same place."""

    __tablename__ = "sales_invoice_line_batches"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "line_id"],
            ["sales_invoice_lines.tenant_id", "sales_invoice_lines.id"],
            name="fk_sales_line_batches_line",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["product_batches.tenant_id", "product_batches.id"],
            name="fk_sales_line_batches_batch",
            ondelete="RESTRICT",
        ),
        CheckConstraint("base_quantity > 0", name="ck_sales_line_batches_qty"),
        Index("ix_sales_line_batches_line", "tenant_id", "line_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    line_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    base_quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)


class SalesReturn(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "sales_returns"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_sales_returns_tenant_id"),
        UniqueConstraint("tenant_id", "number", name="uq_sales_returns_number"),
        ForeignKeyConstraint(
            ["tenant_id", "invoice_id"],
            ["sales_invoices.tenant_id", "sales_invoices.id"],
            name="fk_sales_returns_invoice",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "total > 0 AND credit_reduction >= 0 AND cash_refund >= 0"
            " AND credit_reduction + cash_refund = total",
            name="ck_sales_returns_amounts",
        ),
        Index("ix_sales_returns_invoice", "tenant_id", "invoice_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    invoice_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    total: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    credit_reduction: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    cash_refund: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = _created_at()


class SalesReturnLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "sales_return_lines"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "return_id"],
            ["sales_returns.tenant_id", "sales_returns.id"],
            name="fk_sales_return_lines_return",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "line_id"],
            ["sales_invoice_lines.tenant_id", "sales_invoice_lines.id"],
            name="fk_sales_return_lines_line",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "quantity > 0 AND base_quantity > 0 AND amount >= 0", name="ck_sales_return_lines"
        ),
        Index("ix_sales_return_lines_line", "tenant_id", "line_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    return_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    line_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    base_quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
