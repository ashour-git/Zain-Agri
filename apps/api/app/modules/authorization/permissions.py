"""Central authorisation policy.

Roles are tenant-scoped. Business modules never compare roles directly; they
require a permission, so changing what a role may do is one edit here.
"""

import enum

from app.modules.identity.models import MembershipRole


class Permission(enum.StrEnum):
    # Workspace administration
    TENANT_SETTINGS_MANAGE = "tenant.settings.manage"
    USERS_MANAGE = "users.manage"
    FINANCE_VIEW = "finance.view"
    # Catalog
    PRODUCTS_READ = "products.read"
    PRODUCTS_CREATE = "products.create"
    PRODUCTS_UPDATE = "products.update"
    PRODUCTS_ARCHIVE = "products.archive"
    CATEGORIES_MANAGE = "categories.manage"
    # Inventory
    INVENTORY_READ = "inventory.read"
    INVENTORY_ADJUST = "inventory.adjust"
    INVENTORY_VIEW_COST = "inventory.view_cost"
    BATCHES_MANAGE = "batches.manage"
    AUDIT_READ = "audit.read"
    # Reserved for the modules that follow Sprint 03.
    PURCHASES_MANAGE = "purchases.manage"
    SALES_OPERATE = "sales.operate"
    SALES_REFUND = "sales.refund"
    REPORTS_VIEW = "reports.view"


ALL_PERMISSIONS: frozenset[Permission] = frozenset(Permission)

_CATALOG_EDIT = {
    Permission.PRODUCTS_READ,
    Permission.PRODUCTS_CREATE,
    Permission.PRODUCTS_UPDATE,
    Permission.PRODUCTS_ARCHIVE,
    Permission.CATEGORIES_MANAGE,
}

# Defaults. Per-tenant overrides ("configurable by the owner") are not built yet;
# see docs/security/RBAC.md.
ROLE_PERMISSIONS: dict[MembershipRole, frozenset[Permission]] = {
    MembershipRole.OWNER: ALL_PERMISSIONS,
    MembershipRole.MANAGER: frozenset(
        {
            Permission.SALES_OPERATE,
            Permission.SALES_REFUND,
            Permission.PURCHASES_MANAGE,
            Permission.REPORTS_VIEW,
            Permission.INVENTORY_READ,
            Permission.INVENTORY_ADJUST,
            Permission.BATCHES_MANAGE,
            *_CATALOG_EDIT,
        }
    ),
    # Sells at the counter: may look up products and stock, nothing more.
    MembershipRole.CASHIER: frozenset(
        {
            Permission.SALES_OPERATE,
            Permission.PRODUCTS_READ,
            Permission.INVENTORY_READ,
        }
    ),
    # Stock and catalog, no money: cost visibility stays with the owner.
    MembershipRole.INVENTORY_MANAGER: frozenset(
        {
            Permission.REPORTS_VIEW,
            Permission.INVENTORY_READ,
            Permission.INVENTORY_ADJUST,
            Permission.BATCHES_MANAGE,
            *_CATALOG_EDIT,
        }
    ),
}


def permissions_for(role: MembershipRole) -> frozenset[Permission]:
    return ROLE_PERMISSIONS.get(role, frozenset())


def has_permission(role: MembershipRole, permission: Permission) -> bool:
    return permission in permissions_for(role)
