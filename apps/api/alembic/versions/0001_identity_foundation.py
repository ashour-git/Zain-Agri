"""Identity foundation: tenants, users, memberships + RLS.

Revision ID: 0001_identity
Revises:
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_identity"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_STATUS = postgresql.ENUM("active", "suspended", name="tenant_status", create_type=False)
MEMBERSHIP_ROLE = postgresql.ENUM(
    "owner", "admin", "member", name="membership_role", create_type=False
)

# A missing or empty setting yields NULL, so every comparison is NULL (false).
# The policy therefore fails closed: no tenant context means no rows.
_TENANT_MATCH = "nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    bind = op.get_bind()
    TENANT_STATUS.create(bind, checkfirst=True)
    MEMBERSHIP_ROLE.create(bind, checkfirst=True)

    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("status", TENANT_STATUS, server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_tenants"),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email_lower", "users", [sa.text("lower(email)")], unique=True)

    op.create_table(
        "memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", MEMBERSHIP_ROLE, server_default="member", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_memberships"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_memberships_tenant_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_memberships_user_id", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_user"),
    )
    op.create_index("ix_memberships_tenant_id", "memberships", ["tenant_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    # --- Tenant isolation boundary -----------------------------------------
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenants_isolation ON tenants
        USING (id = {_TENANT_MATCH})
        WITH CHECK (id = {_TENANT_MATCH})
        """
    )

    op.execute("ALTER TABLE memberships ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY memberships_isolation ON memberships
        USING (tenant_id = {_TENANT_MATCH})
        WITH CHECK (tenant_id = {_TENANT_MATCH})
        """
    )

    # `users` is intentionally NOT tenant-scoped: a person can belong to more
    # than one tenant. Access is mediated by memberships in the application
    # layer. See OPEN_QUESTIONS.md (identity model).


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS memberships_isolation ON memberships")
    op.execute("DROP POLICY IF EXISTS tenants_isolation ON tenants")
    op.drop_index("ix_memberships_user_id", table_name="memberships")
    op.drop_index("ix_memberships_tenant_id", table_name="memberships")
    op.drop_table("memberships")
    op.drop_index("ix_users_email_lower", table_name="users")
    op.drop_table("users")
    op.drop_table("tenants")
    MEMBERSHIP_ROLE.drop(op.get_bind(), checkfirst=True)
    TENANT_STATUS.drop(op.get_bind(), checkfirst=True)
