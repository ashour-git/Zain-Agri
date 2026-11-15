"""Customers and their append-only statement. Both tables are RLS-scoped.

A balance is never stored: it is the sum of the customer's ledger amounts
(positive = the customer owes the shop). Corrections are new lines; a database
trigger rejects UPDATE and DELETE on ``customer_ledger``.
"""

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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class LedgerKind(enum.StrEnum):
    OPENING = "opening"
    INVOICE = "invoice"
    PAYMENT = "payment"
    RETURN = "return"
    CORRECTION = "correction"


class Customer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_customers_tenant_id"),
        UniqueConstraint("tenant_id", "name_key", name="uq_customers_name"),
        Index("ix_customers_tenant_name", "tenant_id", "name"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # normalize_name(name): «الحاج  محمود» and «الحاج محمود» are one customer.
    name_key: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class CustomerLedgerEntry(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "customer_ledger"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_customer_ledger_customer",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "kind IN ('opening', 'invoice', 'payment', 'return', 'correction')",
            name="ck_customer_ledger_kind",
        ),
        CheckConstraint("amount <> 0", name="ck_customer_ledger_amount"),
        Index("ix_customer_ledger_customer", "tenant_id", "customer_id", "created_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # Positive: the customer owes more. Negative: owes less (payment, return).
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
