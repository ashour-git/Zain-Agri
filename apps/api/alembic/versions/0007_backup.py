"""Daily backup email: settings, delivery log, RLS and two lookup functions.

Revision ID: 0007_backup
Revises: 0006_audit
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_backup"
down_revision: str | None = "0006_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_MATCH = "nullif(current_setting('app.tenant_id', true), '')::uuid"

# The nightly job needs "which shops are due today?" without reading any
# other column across tenants. Returns ids only.
DUE_TENANTS = """
CREATE OR REPLACE FUNCTION app_backup_due_tenants(p_date date)
RETURNS TABLE (tenant_id uuid)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT s.tenant_id
    FROM backup_settings AS s
    JOIN tenants AS t ON t.id = s.tenant_id
    WHERE s.status = 'active'
      AND t.status = 'active'
      AND NOT EXISTS (
          SELECT 1 FROM backup_deliveries AS d
          WHERE d.tenant_id = s.tenant_id
            AND d.delivery_date = p_date
            AND d.kind = 'nightly'
            -- One attempt per night: sent, in progress or failed all count.
            AND d.status IN ('sent', 'claimed', 'failed')
      )
    ORDER BY s.tenant_id
$$
"""

# A confirmation link is opened without a session; the token alone names the
# shop. Expiry and single use are checked afterwards under RLS.
CONFIRM_LINK_TENANT = """
CREATE OR REPLACE FUNCTION app_backup_token_tenant(p_token_hash text)
RETURNS uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT s.tenant_id
    FROM backup_settings AS s
    WHERE s.confirm_token_hash = p_token_hash
      AND s.status = 'pending'
$$
"""


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "backup_settings",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("confirm_token_hash", sa.String(length=64), nullable=True),
        sa.Column("confirm_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("tenant_id", name="pk_backup_settings"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_backup_settings_tenant_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name="fk_backup_settings_updated_by", ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'stopped')", name="ck_backup_settings_status"
        ),
    )
    op.create_index(
        "ix_backup_settings_token", "backup_settings", ["confirm_token_hash"], unique=True
    )

    op.create_table(
        "backup_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("delivery_date", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("error_reason_ar", sa.String(length=300), nullable=True),
        sa.Column("file_bytes", sa.Integer(), nullable=True),
        sa.Column("row_counts", postgresql.JSONB(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_backup_deliveries"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_backup_deliveries_tenant_id", ondelete="CASCADE"
        ),
        sa.CheckConstraint("kind IN ('nightly', 'manual')", name="ck_backup_deliveries_kind"),
        sa.CheckConstraint(
            "status IN ('claimed', 'sent', 'failed')", name="ck_backup_deliveries_status"
        ),
    )
    op.create_index(
        "uq_backup_deliveries_nightly",
        "backup_deliveries",
        ["tenant_id", "delivery_date"],
        unique=True,
        postgresql_where=sa.text("kind = 'nightly'"),
    )
    op.create_index(
        "ix_backup_deliveries_tenant_created", "backup_deliveries", ["tenant_id", "created_at"]
    )

    for table in ("backup_settings", "backup_deliveries"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_isolation ON {table}
            USING (tenant_id = {_TENANT_MATCH})
            WITH CHECK (tenant_id = {_TENANT_MATCH})
            """
        )

    op.execute(DUE_TENANTS)
    op.execute(CONFIRM_LINK_TENANT)
    # PostgreSQL grants EXECUTE to PUBLIC by default; grants.sql gives it to
    # the runtime role only.
    op.execute("REVOKE ALL ON FUNCTION app_backup_due_tenants(date) FROM PUBLIC")
    op.execute("REVOKE ALL ON FUNCTION app_backup_token_tenant(text) FROM PUBLIC")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app_backup_token_tenant(text)")
    op.execute("DROP FUNCTION IF EXISTS app_backup_due_tenants(date)")
    for table in ("backup_deliveries", "backup_settings"):
        op.execute(f"DROP POLICY IF EXISTS {table}_isolation ON {table}")
    op.drop_table("backup_deliveries")
    op.drop_table("backup_settings")
