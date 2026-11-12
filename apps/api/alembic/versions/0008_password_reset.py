"""Forgot password: emailed single-use reset links.

Revision ID: 0008_password_reset
Revises: 0007_backup
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_password_reset"
down_revision: str | None = "0007_backup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Like users and refresh_sessions, not tenant-scoped: no RLS.
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_password_reset_tokens"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_password_reset_tokens_user_id", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
    )
    op.create_index(
        "ix_password_reset_tokens_user_created", "password_reset_tokens", ["user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_password_reset_tokens_user_created", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
