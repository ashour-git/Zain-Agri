"""Cross-tenant membership lookup function.

Login and tenant selection need to answer "which workspaces does this user
belong to?" while ``tenants`` and ``memberships`` are behind RLS. Rather than
weakening the RLS policies with a permissive ``user_id = ...`` branch, this
adds one narrow SECURITY DEFINER function that the runtime role may execute.

Revision ID: 0003_user_tenants
Revises: 0002_auth
Create Date: 2026-10-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_user_tenants"
down_revision: str | None = "0002_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION_NAME = "app_user_tenants"

CREATE_FUNCTION = """
CREATE OR REPLACE FUNCTION app_user_tenants(p_user_id uuid)
RETURNS TABLE (
    tenant_id uuid,
    tenant_name text,
    tenant_slug text,
    tenant_status tenant_status,
    role membership_role,
    membership_status membership_status
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT t.id, t.name, t.slug, t.status, m.role, m.status
    FROM memberships AS m
    JOIN tenants AS t ON t.id = m.tenant_id
    WHERE m.user_id = p_user_id
    ORDER BY t.name
$$
"""


def upgrade() -> None:
    op.execute(CREATE_FUNCTION)
    # PostgreSQL grants EXECUTE to PUBLIC by default. Lock it down; the runtime
    # role is granted explicitly in infrastructure/db/grants.sql.
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION_NAME}(uuid) FROM PUBLIC")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION_NAME}(uuid)")
