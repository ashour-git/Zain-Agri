"""Central authorisation policy.

Roles are tenant-scoped. Business modules never compare roles directly; they
require a permission, so changing what a role may do is one edit here.
"""

import enum

from app.modules.identity.models import MembershipRole


class Permission(enum.StrEnum):
    TENANT_SETTINGS_MANAGE = "tenant.settings.manage"
    USERS_MANAGE = "users.manage"
    FINANCE_VIEW = "finance.view"
    INVENTORY_MANAGE = "inventory.manage"
    PURCHASES_MANAGE = "purchases.manage"
    SALES_OPERATE = "sales.operate"
    SALES_REFUND = "sales.refund"
    REPORTS_VIEW = "reports.view"


ALL_PERMISSIONS: frozenset[Permission] = frozenset(Permission)

# Defaults. Per-tenant overrides ("configurable by the owner") are not built in
# Sprint 02; see docs/security/RBAC.md.
ROLE_PERMISSIONS: dict[MembershipRole, frozenset[Permission]] = {
    MembershipRole.OWNER: ALL_PERMISSIONS,
    MembershipRole.MANAGER: frozenset(
        {
            Permission.SALES_OPERATE,
            Permission.SALES_REFUND,
            Permission.INVENTORY_MANAGE,
            Permission.PURCHASES_MANAGE,
            Permission.REPORTS_VIEW,
        }
    ),
    MembershipRole.CASHIER: frozenset({Permission.SALES_OPERATE}),
    # Restricted financial visibility: no finance.view, no refunds.
    MembershipRole.INVENTORY_MANAGER: frozenset(
        {Permission.INVENTORY_MANAGE, Permission.REPORTS_VIEW}
    ),
}


def permissions_for(role: MembershipRole) -> frozenset[Permission]:
    return ROLE_PERMISSIONS.get(role, frozenset())


def has_permission(role: MembershipRole, permission: Permission) -> bool:
    return permission in permissions_for(role)
