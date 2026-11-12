"""Backup settings (one row per shop) and the delivery log.

Both tables are tenant-scoped by RLS. The nightly job discovers due shops
through ``app_backup_due_tenants`` and confirms links through
``app_backup_token_tenant`` (migration 0007); everything else runs inside the
shop's own tenant context.
"""

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class BackupStatus(enum.StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    STOPPED = "stopped"


class DeliveryKind(enum.StrEnum):
    NIGHTLY = "nightly"
    MANUAL = "manual"


class DeliveryStatus(enum.StrEnum):
    CLAIMED = "claimed"
    SENT = "sent"
    FAILED = "failed"


def _one_of(column: str, values: type[enum.StrEnum]) -> str:
    listed = ", ".join(f"'{member.value}'" for member in values)
    return f"{column} IN ({listed})"


class BackupSettings(TimestampMixin, Base):
    __tablename__ = "backup_settings"
    __table_args__ = (
        CheckConstraint(_one_of("status", BackupStatus), name="ck_backup_settings_status"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    confirm_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confirm_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class BackupDelivery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "backup_deliveries"
    __table_args__ = (
        CheckConstraint(_one_of("kind", DeliveryKind), name="ck_backup_deliveries_kind"),
        CheckConstraint(_one_of("status", DeliveryStatus), name="ck_backup_deliveries_status"),
        # One nightly delivery per shop per Cairo day: the claim is this insert.
        Index(
            "uq_backup_deliveries_nightly",
            "tenant_id",
            "delivery_date",
            unique=True,
            postgresql_where=text("kind = 'nightly'"),
        ),
        Index("ix_backup_deliveries_tenant_created", "tenant_id", "created_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    delivery_date: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # The address this delivery went to, as read when it was claimed.
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    error_reason_ar: Mapped[str | None] = mapped_column(String(300), nullable=True)
    file_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    row_counts: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
