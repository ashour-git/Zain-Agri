"""Authentication models.

Only the refresh session is persisted. Access tokens are stateless JWTs and are
never stored anywhere; refresh tokens are stored as SHA-256 hashes, never raw.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base, UUIDPrimaryKeyMixin


class RefreshSession(UUIDPrimaryKeyMixin, Base):
    """One rotated refresh token.

    A login creates the first row of a *family*. Every rotation adds a row in
    the same family and revokes its predecessor. Presenting a revoked token is
    treated as theft: the whole family is revoked.
    """

    __tablename__ = "refresh_sessions"
    __table_args__ = (
        Index("ix_refresh_sessions_user_expires", "user_id", "expires_at"),
        Index("ix_refresh_sessions_family", "token_family_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Nullable: a session exists between registration and tenant selection.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # SHA-256 hex of the opaque token. The token itself is never stored.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    token_family_id: Mapped[uuid.UUID] = mapped_column(nullable=False)

    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("refresh_sessions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PasswordResetToken(UUIDPrimaryKeyMixin, Base):
    """One emailed "forgot password" link: hashed, short-lived, single use.

    Not tenant-scoped: a password belongs to the person, like ``users``.
    """

    __tablename__ = "password_reset_tokens"
    __table_args__ = (Index("ix_password_reset_tokens_user_created", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # SHA-256 hex of the token in the link. The token itself is never stored.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
