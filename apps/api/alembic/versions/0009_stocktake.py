"""Stocktake (جرد): header and counted lines, with RLS.

Revision ID: 0009_stocktake
Revises: 0008_password_reset
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_stocktake"
down_revision: str | None = "0008_password_reset"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_MATCH = "nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "stocktakes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("blind", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("applied_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_stocktakes"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_stocktakes_tenant_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_stocktakes_tenant_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_stocktakes_created_by", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["applied_by"], ["users.id"], name="fk_stocktakes_applied_by", ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "status IN ('open', 'applied', 'cancelled')", name="ck_stocktakes_status"
        ),
        sa.CheckConstraint("scope IN ('all', 'category')", name="ck_stocktakes_scope"),
    )
    op.create_index(
        "uq_stocktakes_one_open",
        "stocktakes",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index("ix_stocktakes_tenant_created", "stocktakes", ["tenant_id", "created_at"])

    op.create_table(
        "stocktake_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("stocktake_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=True),
        sa.Column("counted_quantity", sa.Numeric(18, 4), nullable=True),
        sa.Column("unit_id", sa.Uuid(), nullable=True),
        sa.Column("counted_base_quantity", sa.Numeric(18, 4), nullable=True),
        sa.Column("system_quantity_at_count", sa.Numeric(18, 4), nullable=True),
        sa.Column(
            "shortage_reason", sa.String(length=16), nullable=False, server_default="shortage"
        ),
        sa.Column("counted_by", sa.Uuid(), nullable=True),
        sa.Column("counted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_stocktake_lines"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_stocktake_lines_tenant_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "stocktake_id"],
            ["stocktakes.tenant_id", "stocktakes.id"],
            name="fk_stocktake_lines_stocktake",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_stocktake_lines_product",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["product_batches.tenant_id", "product_batches.id"],
            name="fk_stocktake_lines_batch",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"],
            ["units_of_measure.id"],
            name="fk_stocktake_lines_unit",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["counted_by"], ["users.id"], name="fk_stocktake_lines_counted_by", ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "shortage_reason IN ('shortage', 'damage', 'expiry')", name="ck_stocktake_lines_reason"
        ),
        sa.CheckConstraint(
            "counted_quantity IS NULL OR counted_quantity >= 0", name="ck_stocktake_lines_qty"
        ),
    )
    op.create_index(
        "uq_stocktake_lines_item",
        "stocktake_lines",
        ["stocktake_id", "product_id", "batch_id"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )
    op.create_index(
        "ix_stocktake_lines_stocktake", "stocktake_lines", ["tenant_id", "stocktake_id"]
    )

    for table in ("stocktakes", "stocktake_lines"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_isolation ON {table}
            USING (tenant_id = {_TENANT_MATCH})
            WITH CHECK (tenant_id = {_TENANT_MATCH})
            """
        )


def downgrade() -> None:
    for table in ("stocktake_lines", "stocktakes"):
        op.execute(f"DROP POLICY IF EXISTS {table}_isolation ON {table}")
    op.drop_table("stocktake_lines")
    op.drop_table("stocktakes")
