"""Authentication: email verification, membership status, RBAC roles, refresh sessions.

Revision ID: 0002_auth
Revises: 0001_identity
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_auth"
down_revision: str | None = "0001_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MEMBERSHIP_STATUS = postgresql.ENUM(
    "active", "invited", "suspended", name="membership_status", create_type=False
)


def upgrade() -> None:
    # --- users -------------------------------------------------------------
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )

    # --- memberships -------------------------------------------------------
    MEMBERSHIP_STATUS.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "memberships",
        sa.Column(
            "status",
            MEMBERSHIP_STATUS,
            server_default="active",
            nullable=False,
        ),
    )

    # Role vocabulary changes from the provisional owner/admin/member to the
    # real RBAC roles. PostgreSQL cannot drop enum values, so the type is
    # rebuilt and existing rows are mapped explicitly.
    op.execute(
        "CREATE TYPE membership_role_new AS ENUM "
        "('owner', 'manager', 'cashier', 'inventory_manager')"
    )
    op.execute("ALTER TABLE memberships ALTER COLUMN role DROP DEFAULT")
    op.execute(
        """
        ALTER TABLE memberships
        ALTER COLUMN role TYPE membership_role_new
        USING (
            CASE role::text
                WHEN 'owner' THEN 'owner'
                WHEN 'admin' THEN 'manager'
                ELSE 'cashier'
            END
        )::membership_role_new
        """
    )
    op.execute("ALTER TABLE memberships ALTER COLUMN role SET DEFAULT 'cashier'")
    op.execute("DROP TYPE membership_role")
    op.execute("ALTER TYPE membership_role_new RENAME TO membership_role")

    # Membership lookups are always (tenant, user) or (user) with a status filter.
    op.create_index("ix_memberships_user_status", "memberships", ["user_id", "status"])

    # --- refresh_sessions --------------------------------------------------
    op.create_table(
        "refresh_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_family_id", sa.Uuid(), nullable=False),
        sa.Column("user_agent", sa.String(length=400), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_sessions"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_refresh_sessions_user_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_refresh_sessions_tenant_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by_id"],
            ["refresh_sessions.id"],
            name="fk_refresh_sessions_replaced_by_id",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("token_hash", name="uq_refresh_sessions_token_hash"),
    )
    op.create_index("ix_refresh_sessions_user_id", "refresh_sessions", ["user_id"])
    op.create_index("ix_refresh_sessions_tenant_id", "refresh_sessions", ["tenant_id"])
    op.create_index(
        "ix_refresh_sessions_user_expires", "refresh_sessions", ["user_id", "expires_at"]
    )
    op.create_index("ix_refresh_sessions_family", "refresh_sessions", ["token_family_id"])

    # refresh_sessions is deliberately NOT under RLS: token rotation happens
    # before a tenant is known. Every query filters by user_id, and the row is
    # never exposed through the API. See docs/security/TENANT_ISOLATION.md.


def downgrade() -> None:
    op.drop_index("ix_refresh_sessions_family", table_name="refresh_sessions")
    op.drop_index("ix_refresh_sessions_user_expires", table_name="refresh_sessions")
    op.drop_index("ix_refresh_sessions_tenant_id", table_name="refresh_sessions")
    op.drop_index("ix_refresh_sessions_user_id", table_name="refresh_sessions")
    op.drop_table("refresh_sessions")

    op.drop_index("ix_memberships_user_status", table_name="memberships")

    op.execute("CREATE TYPE membership_role_old AS ENUM ('owner', 'admin', 'member')")
    op.execute("ALTER TABLE memberships ALTER COLUMN role DROP DEFAULT")
    op.execute(
        """
        ALTER TABLE memberships
        ALTER COLUMN role TYPE membership_role_old
        USING (
            CASE role::text
                WHEN 'owner' THEN 'owner'
                WHEN 'manager' THEN 'admin'
                ELSE 'member'
            END
        )::membership_role_old
        """
    )
    op.execute("ALTER TABLE memberships ALTER COLUMN role SET DEFAULT 'member'")
    op.execute("DROP TYPE membership_role")
    op.execute("ALTER TYPE membership_role_old RENAME TO membership_role")

    op.drop_column("memberships", "status")
    MEMBERSHIP_STATUS.drop(op.get_bind(), checkfirst=True)

    op.drop_column("users", "email_verified_at")
