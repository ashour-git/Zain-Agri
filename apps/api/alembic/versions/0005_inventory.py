"""Inventory ledger: batches, movements, balance projection + RLS.

Movements are append-only: a trigger rejects UPDATE/DELETE for every role, and
``grants.sql`` additionally revokes those privileges from the runtime role.
Corrections are compensating movements.

Revision ID: 0005_inventory
Revises: 0004_catalog
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_inventory"
down_revision: str | None = "0004_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MOVEMENT_TYPE = postgresql.ENUM(
    "opening_balance",
    "purchase",
    "sale",
    "customer_return",
    "supplier_return",
    "adjustment_in",
    "adjustment_out",
    "damage",
    "expiry",
    "transfer_in",
    "transfer_out",
    name="stock_movement_type",
    create_type=False,
)

_TENANT_MATCH = "nullif(current_setting('app.tenant_id', true), '')::uuid"

BLOCK_MUTATION = """
CREATE OR REPLACE FUNCTION app_block_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'append-only table %: % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;
"""


def _tenant_policy(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_isolation ON {table}
        USING (tenant_id = {_TENANT_MATCH})
        WITH CHECK (tenant_id = {_TENANT_MATCH})
        """
    )


def upgrade() -> None:
    MOVEMENT_TYPE.create(op.get_bind(), checkfirst=True)

    # --- batches -----------------------------------------------------------
    op.create_table(
        "product_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("batch_number", sa.String(length=80), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_product_batches"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_product_batches_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "product_id", "batch_number", name="uq_product_batches_number"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_product_batches_tenant_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_product_batches_product",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("batch_number <> ''", name="ck_product_batches_number_not_empty"),
    )
    op.create_index(
        "ix_product_batches_tenant_expiry", "product_batches", ["tenant_id", "expiry_date"]
    )
    op.create_index(
        "ix_product_batches_tenant_product", "product_batches", ["tenant_id", "product_id"]
    )

    # --- ledger ------------------------------------------------------------
    op.create_table(
        "stock_movements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=True),
        sa.Column("movement_type", MOVEMENT_TYPE, nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("base_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_cost", sa.Numeric(18, 6), nullable=True),
        sa.Column("reference_type", sa.String(length=40), nullable=True),
        sa.Column("reference_id", sa.Uuid(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stock_movements"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_stock_movements_tenant_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_stock_movements_product",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["product_batches.tenant_id", "product_batches.id"],
            name="fk_stock_movements_batch",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"],
            ["units_of_measure.id"],
            name="fk_stock_movements_unit",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_stock_movements_created_by", ondelete="SET NULL"
        ),
        sa.CheckConstraint("quantity > 0", name="ck_stock_movements_positive_quantity"),
        sa.CheckConstraint("base_quantity <> 0", name="ck_stock_movements_non_zero_base"),
        sa.CheckConstraint(
            "unit_cost IS NULL OR unit_cost >= 0", name="ck_stock_movements_unit_cost"
        ),
    )
    op.create_index(
        "ix_stock_movements_tenant_created", "stock_movements", ["tenant_id", "created_at"]
    )
    op.create_index(
        "ix_stock_movements_tenant_product_created",
        "stock_movements",
        ["tenant_id", "product_id", "created_at"],
    )
    op.create_index("ix_stock_movements_tenant_batch", "stock_movements", ["tenant_id", "batch_id"])

    # --- balance projection ------------------------------------------------
    op.create_table(
        "inventory_balances",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("tenant_id", "product_id", name="pk_inventory_balances"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_inventory_balances_tenant_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_inventory_balances_product",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("quantity >= 0", name="ck_inventory_balances_non_negative"),
    )
    op.create_index(
        "ix_inventory_balances_tenant_quantity", "inventory_balances", ["tenant_id", "quantity"]
    )

    for table in ("product_batches", "stock_movements", "inventory_balances"):
        _tenant_policy(table)

    # Append-only enforcement lives in the database, not in a service method.
    op.execute(BLOCK_MUTATION)
    op.execute(
        """
        CREATE TRIGGER stock_movements_append_only
        BEFORE UPDATE OR DELETE ON stock_movements
        FOR EACH ROW EXECUTE FUNCTION app_block_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS stock_movements_append_only ON stock_movements")
    op.execute("DROP FUNCTION IF EXISTS app_block_mutation()")

    for table in ("inventory_balances", "stock_movements", "product_batches"):
        op.execute(f"DROP POLICY IF EXISTS {table}_isolation ON {table}")

    op.drop_index("ix_inventory_balances_tenant_quantity", table_name="inventory_balances")
    op.drop_table("inventory_balances")
    op.drop_index("ix_stock_movements_tenant_batch", table_name="stock_movements")
    op.drop_index("ix_stock_movements_tenant_product_created", table_name="stock_movements")
    op.drop_index("ix_stock_movements_tenant_created", table_name="stock_movements")
    op.drop_table("stock_movements")
    op.drop_index("ix_product_batches_tenant_product", table_name="product_batches")
    op.drop_index("ix_product_batches_tenant_expiry", table_name="product_batches")
    op.drop_table("product_batches")

    MOVEMENT_TYPE.drop(op.get_bind(), checkfirst=True)
