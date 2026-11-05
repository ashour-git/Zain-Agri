"""Product catalog: units, categories, brands, products, conversions + RLS.

Revision ID: 0004_catalog
Revises: 0003_user_tenants
Create Date: 2026-10-31

Units of measure are platform reference data (no tenant_id, read-only for the
runtime role). Every other table is tenant-owned and gets its RLS policy in
this same migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_catalog"
down_revision: str | None = "0003_user_tenants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UNIT_DIMENSION = postgresql.ENUM(
    "count", "mass", "volume", name="unit_dimension", create_type=False
)
PRODUCT_STATUS = postgresql.ENUM("active", "archived", name="product_status", create_type=False)

_TENANT_MATCH = "nullif(current_setting('app.tenant_id', true), '')::uuid"

UNITS = [
    ("0192f000-0000-4000-8000-000000000001", "piece", "Piece", "قطعة", "count"),
    ("0192f000-0000-4000-8000-000000000002", "kilogram", "Kilogram", "كيلوجرام", "mass"),
    ("0192f000-0000-4000-8000-000000000003", "gram", "Gram", "جرام", "mass"),
    ("0192f000-0000-4000-8000-000000000004", "liter", "Liter", "لتر", "volume"),
    ("0192f000-0000-4000-8000-000000000005", "milliliter", "Milliliter", "مليلتر", "volume"),
    ("0192f000-0000-4000-8000-000000000006", "bag", "Bag", "شيكارة", "count"),
    ("0192f000-0000-4000-8000-000000000007", "bottle", "Bottle", "زجاجة", "count"),
    ("0192f000-0000-4000-8000-000000000008", "box", "Box", "كرتونة", "count"),
    ("0192f000-0000-4000-8000-000000000009", "pack", "Pack", "عبوة", "count"),
]


def _tenant_policy(table: str, column: str = "tenant_id") -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_isolation ON {table}
        USING ({column} = {_TENANT_MATCH})
        WITH CHECK ({column} = {_TENANT_MATCH})
        """
    )


def upgrade() -> None:
    bind = op.get_bind()
    UNIT_DIMENSION.create(bind, checkfirst=True)
    PRODUCT_STATUS.create(bind, checkfirst=True)

    # --- reference data ----------------------------------------------------
    op.create_table(
        "units_of_measure",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("name_ar", sa.String(length=80), nullable=False),
        sa.Column("dimension", UNIT_DIMENSION, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_units_of_measure"),
        sa.UniqueConstraint("code", name="uq_units_of_measure_code"),
    )
    for unit_id, code, name, name_ar, dimension in UNITS:
        op.execute(
            sa.text(
                """
                INSERT INTO units_of_measure (id, code, name, name_ar, dimension)
                VALUES (
                    CAST(:id AS uuid),
                    :code,
                    :name,
                    :name_ar,
                    CAST(:dimension AS unit_dimension)
                )
                ON CONFLICT (code) DO NOTHING
                """
            ).bindparams(id=unit_id, code=code, name=name, name_ar=name_ar, dimension=dimension)
        )

    # --- categories --------------------------------------------------------
    op.create_table(
        "product_categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("name_ar", sa.String(length=120), nullable=True),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_product_categories"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_product_categories_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "parent_id", "name", name="uq_product_categories_sibling_name"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_product_categories_tenant_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["product_categories.tenant_id", "product_categories.id"],
            name="fk_product_categories_parent",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_product_categories_tenant_parent", "product_categories", ["tenant_id", "parent_id"]
    )
    # NULLs are distinct in a UNIQUE constraint, so root names need their own
    # partial index to stay unique per tenant.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_product_categories_root_name
        ON product_categories (tenant_id, name)
        WHERE parent_id IS NULL
        """
    )

    # --- brands ------------------------------------------------------------
    op.create_table(
        "brands",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("name_ar", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_brands"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_brands_tenant_id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_brands_tenant_name"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_brands_tenant_id", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_brands_tenant_id", "brands", ["tenant_id"])

    # --- products ----------------------------------------------------------
    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("barcode", sa.String(length=64), nullable=True),
        sa.Column("name_ar", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("brand_id", sa.Uuid(), nullable=True),
        sa.Column("base_unit_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_unit_id", sa.Uuid(), nullable=True),
        sa.Column("sale_unit_id", sa.Uuid(), nullable=True),
        sa.Column("cost_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("sale_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("minimum_stock", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("tracks_batches", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("status", PRODUCT_STATUS, server_default="active", nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_products"),
        sa.UniqueConstraint("tenant_id", "sku", name="uq_products_tenant_sku"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_products_tenant_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_products_tenant_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["product_categories.tenant_id", "product_categories.id"],
            name="fk_products_category",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "brand_id"],
            ["brands.tenant_id", "brands.id"],
            name="fk_products_brand",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["base_unit_id"],
            ["units_of_measure.id"],
            name="fk_products_base_unit",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_unit_id"],
            ["units_of_measure.id"],
            name="fk_products_purchase_unit",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sale_unit_id"],
            ["units_of_measure.id"],
            name="fk_products_sale_unit",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("cost_price IS NULL OR cost_price >= 0", name="ck_products_cost_price"),
        sa.CheckConstraint("sale_price IS NULL OR sale_price >= 0", name="ck_products_sale_price"),
        sa.CheckConstraint("minimum_stock >= 0", name="ck_products_minimum_stock"),
        sa.CheckConstraint(
            "barcode IS NULL OR barcode <> ''", name="ck_products_barcode_not_empty"
        ),
    )
    op.create_index("ix_products_tenant_status", "products", ["tenant_id", "status"])
    op.create_index("ix_products_tenant_name_ar", "products", ["tenant_id", "name_ar"])
    op.create_index("ix_products_tenant_category", "products", ["tenant_id", "category_id"])
    op.execute(
        """
        CREATE UNIQUE INDEX uq_products_tenant_barcode
        ON products (tenant_id, barcode)
        WHERE barcode IS NOT NULL
        """
    )

    # --- conversions -------------------------------------------------------
    op.create_table(
        "product_unit_conversions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("from_unit_id", sa.Uuid(), nullable=False),
        sa.Column("to_unit_id", sa.Uuid(), nullable=False),
        sa.Column("factor", sa.Numeric(18, 6), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_product_unit_conversions"),
        sa.UniqueConstraint(
            "tenant_id",
            "product_id",
            "from_unit_id",
            "to_unit_id",
            name="uq_product_unit_conversions_pair",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_product_unit_conversions_tenant_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_product_unit_conversions_product",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["from_unit_id"],
            ["units_of_measure.id"],
            name="fk_product_unit_conversions_from_unit",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_unit_id"],
            ["units_of_measure.id"],
            name="fk_product_unit_conversions_to_unit",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("factor > 0", name="ck_product_unit_conversions_factor"),
        sa.CheckConstraint(
            "from_unit_id <> to_unit_id", name="ck_product_unit_conversions_distinct_units"
        ),
    )
    op.create_index(
        "ix_product_unit_conversions_tenant_product",
        "product_unit_conversions",
        ["tenant_id", "product_id"],
    )

    for table in ("product_categories", "brands", "products", "product_unit_conversions"):
        _tenant_policy(table)


def downgrade() -> None:
    for table in ("product_unit_conversions", "products", "brands", "product_categories"):
        op.execute(f"DROP POLICY IF EXISTS {table}_isolation ON {table}")

    op.drop_index(
        "ix_product_unit_conversions_tenant_product", table_name="product_unit_conversions"
    )
    op.drop_table("product_unit_conversions")
    op.drop_index("uq_products_tenant_barcode", table_name="products")
    op.drop_index("ix_products_tenant_category", table_name="products")
    op.drop_index("ix_products_tenant_name_ar", table_name="products")
    op.drop_index("ix_products_tenant_status", table_name="products")
    op.drop_table("products")
    op.drop_index("ix_brands_tenant_id", table_name="brands")
    op.drop_table("brands")
    op.drop_index("uq_product_categories_root_name", table_name="product_categories")
    op.drop_index("ix_product_categories_tenant_parent", table_name="product_categories")
    op.drop_table("product_categories")
    op.drop_table("units_of_measure")

    PRODUCT_STATUS.drop(op.get_bind(), checkfirst=True)
    UNIT_DIMENSION.drop(op.get_bind(), checkfirst=True)
