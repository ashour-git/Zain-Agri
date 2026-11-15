"""Sales, credit customers and shareable invoices.

Revision ID: 0010_sales
Revises: 0009_stocktake
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_sales"
down_revision: str | None = "0009_stocktake"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_MATCH = "nullif(current_setting('app.tenant_id', true), '')::uuid"
TABLES = (
    "customers",
    "customer_ledger",
    "shop_counters",
    "sales_invoices",
    "sales_invoice_lines",
    "sales_invoice_line_batches",
    "sales_returns",
    "sales_return_lines",
)

# A public invoice link is opened without a session; the token alone names the
# invoice. Returns ids only; the page then reads under that shop's RLS context.
SHARE_LOOKUP = """
CREATE OR REPLACE FUNCTION app_invoice_by_share_token(p_hash text)
RETURNS TABLE (tenant_id uuid, invoice_id uuid)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT i.tenant_id, i.id FROM sales_invoices AS i WHERE i.share_token_hash = p_hash
$$
"""


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("name_key", sa.String(length=120), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_customers_tenant_id"),
        sa.UniqueConstraint("tenant_id", "name_key", name="uq_customers_name"),
    )
    op.create_index("ix_customers_tenant_name", "customers", ["tenant_id", "name"], unique=False)
    op.create_table(
        "shop_counters",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=20), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id", "name"),
    )
    op.create_table(
        "customer_ledger",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("reference_type", sa.String(length=40), nullable=True),
        sa.Column("reference_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('opening', 'invoice', 'payment', 'return', 'correction')",
            name="ck_customer_ledger_kind",
        ),
        sa.CheckConstraint("amount <> 0", name="ck_customer_ledger_amount"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_customer_ledger_customer",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_customer_ledger_customer",
        "customer_ledger",
        ["tenant_id", "customer_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "sales_invoices",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=True),
        sa.Column("subtotal", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("discount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("total", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("paid", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("credit", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("idempotency_key", sa.String(length=80), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("share_token_hash", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "subtotal >= 0 AND discount >= 0 AND discount <= subtotal"
            " AND total = subtotal - discount"
            " AND paid >= 0 AND paid <= total AND credit = total - paid",
            name="ck_sales_invoices_amounts",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_sales_invoices_customer",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("share_token_hash", name="uq_sales_invoices_share_token"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_sales_invoices_tenant_id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_sales_invoices_idempotency"),
        sa.UniqueConstraint("tenant_id", "number", name="uq_sales_invoices_number"),
    )
    op.create_index(
        "ix_sales_invoices_customer", "sales_invoices", ["tenant_id", "customer_id"], unique=False
    )
    op.create_index(
        "ix_sales_invoices_tenant_created",
        "sales_invoices",
        ["tenant_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "sales_invoice_lines",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("name_ar", sa.String(length=200), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("base_quantity", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("line_total", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("quantity > 0 AND base_quantity > 0", name="ck_sales_invoice_lines_qty"),
        sa.CheckConstraint(
            "unit_price >= 0 AND line_total >= 0", name="ck_sales_invoice_lines_money"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "invoice_id"],
            ["sales_invoices.tenant_id", "sales_invoices.id"],
            name="fk_sales_invoice_lines_invoice",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_sales_invoice_lines_product",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["unit_id"], ["units_of_measure.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_sales_invoice_lines_tenant_id"),
    )
    op.create_index(
        "ix_sales_invoice_lines_invoice",
        "sales_invoice_lines",
        ["tenant_id", "invoice_id"],
        unique=False,
    )
    op.create_table(
        "sales_returns",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("total", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("credit_reduction", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("cash_refund", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("reason", sa.String(length=300), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "total > 0 AND credit_reduction >= 0 AND cash_refund >= 0"
            " AND credit_reduction + cash_refund = total",
            name="ck_sales_returns_amounts",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "invoice_id"],
            ["sales_invoices.tenant_id", "sales_invoices.id"],
            name="fk_sales_returns_invoice",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_sales_returns_tenant_id"),
        sa.UniqueConstraint("tenant_id", "number", name="uq_sales_returns_number"),
    )
    op.create_index(
        "ix_sales_returns_invoice", "sales_returns", ["tenant_id", "invoice_id"], unique=False
    )
    op.create_table(
        "sales_invoice_line_batches",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("line_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("base_quantity", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("base_quantity > 0", name="ck_sales_line_batches_qty"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["product_batches.tenant_id", "product_batches.id"],
            name="fk_sales_line_batches_batch",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "line_id"],
            ["sales_invoice_lines.tenant_id", "sales_invoice_lines.id"],
            name="fk_sales_line_batches_line",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sales_line_batches_line",
        "sales_invoice_line_batches",
        ["tenant_id", "line_id"],
        unique=False,
    )
    op.create_table(
        "sales_return_lines",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("return_id", sa.Uuid(), nullable=False),
        sa.Column("line_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("base_quantity", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "quantity > 0 AND base_quantity > 0 AND amount >= 0", name="ck_sales_return_lines"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "line_id"],
            ["sales_invoice_lines.tenant_id", "sales_invoice_lines.id"],
            name="fk_sales_return_lines_line",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "return_id"],
            ["sales_returns.tenant_id", "sales_returns.id"],
            name="fk_sales_return_lines_return",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sales_return_lines_line", "sales_return_lines", ["tenant_id", "line_id"], unique=False
    )

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_isolation ON {table}
            USING (tenant_id = {_TENANT_MATCH})
            WITH CHECK (tenant_id = {_TENANT_MATCH})
            """
        )

    # app_block_mutation() is created by 0005_inventory.
    op.execute(
        """
        CREATE TRIGGER customer_ledger_append_only
        BEFORE UPDATE OR DELETE ON customer_ledger
        FOR EACH ROW EXECUTE FUNCTION app_block_mutation()
        """
    )
    op.execute(SHARE_LOOKUP)
    op.execute("REVOKE ALL ON FUNCTION app_invoice_by_share_token(text) FROM PUBLIC")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app_invoice_by_share_token(text)")
    op.execute("DROP TRIGGER IF EXISTS customer_ledger_append_only ON customer_ledger")
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_isolation ON {table}")
    op.drop_index("ix_sales_return_lines_line", table_name="sales_return_lines")
    op.drop_table("sales_return_lines")
    op.drop_index("ix_sales_line_batches_line", table_name="sales_invoice_line_batches")
    op.drop_table("sales_invoice_line_batches")
    op.drop_index("ix_sales_returns_invoice", table_name="sales_returns")
    op.drop_table("sales_returns")
    op.drop_index("ix_sales_invoice_lines_invoice", table_name="sales_invoice_lines")
    op.drop_table("sales_invoice_lines")
    op.drop_index("ix_sales_invoices_tenant_created", table_name="sales_invoices")
    op.drop_index("ix_sales_invoices_customer", table_name="sales_invoices")
    op.drop_table("sales_invoices")
    op.drop_index("ix_customer_ledger_customer", table_name="customer_ledger")
    op.drop_table("customer_ledger")
    op.drop_table("shop_counters")
    op.drop_index("ix_customers_tenant_name", table_name="customers")
    op.drop_table("customers")
