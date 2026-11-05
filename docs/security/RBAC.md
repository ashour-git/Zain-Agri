# ZAIN AGRI — RBAC

Status: Sprint 03
Last updated: 2026-11-01

Authorisation answers "may this person perform this action in this workspace?".
It is enforced **only on the server**, from live database state. The web UI
hides controls it knows the user cannot use, but that is a usability feature,
not a security boundary.

---

## 1. Model

```
User ──< Membership >── Tenant
              │
              └── role: owner | manager | cashier | inventory_manager
                        │
                        └── permissions (fixed policy table)
```

- A role is **tenant-scoped**: the same person can be `owner` in one workspace
  and `cashier` in another.
- Roles are not global flags on `users`.
- The JWT carries `rol` for rendering, but `get_current_tenant()` re-reads the
  membership row. A demotion applies to the next request, not the next refresh.
- Business modules never compare roles. They declare a permission, and the
  policy table decides which roles hold it.

## 2. Permission matrix

| Permission | OWNER | MANAGER | CASHIER | INVENTORY_MANAGER |
|---|:---:|:---:|:---:|:---:|
| `tenant.settings.manage` | ✅ | — | — | — |
| `users.manage` | ✅ | — | — | — |
| `finance.view` | ✅ | — | — | — |
| `products.read` | ✅ | ✅ | ✅ | ✅ |
| `products.create` | ✅ | ✅ | — | ✅ |
| `products.update` | ✅ | ✅ | — | ✅ |
| `products.archive` | ✅ | ✅ | — | ✅ |
| `categories.manage` | ✅ | ✅ | — | ✅ |
| `inventory.read` | ✅ | ✅ | ✅ | ✅ |
| `inventory.adjust` | ✅ | ✅ | — | ✅ |
| `inventory.view_cost` | ✅ | — | — | — |
| `batches.manage` | ✅ | ✅ | — | ✅ |
| `audit.read` | ✅ | — | — | — |
| `purchases.manage` | ✅ | ✅ | — | — |
| `sales.operate` | ✅ | ✅ | ✅ | — |
| `sales.refund` | ✅ | ✅ | — | — |
| `reports.view` | ✅ | ✅ | — | ✅ |

Source of truth: `apps/api/app/modules/authorization/permissions.py` (17
permissions).

### Role intent

| Role | Intent | Deliberate exclusions |
|---|---|---|
| `OWNER` | Full control of the business | — |
| `MANAGER` | Runs day-to-day operations, including the catalog and stock | Cannot change workspace settings, manage users, see cost or financials, or read the audit trail |
| `CASHIER` | Sells at the counter and looks up products/stock | No catalog edits, no stock adjustments, no cost, no refunds |
| `INVENTORY_MANAGER` | Owns the catalog and the stock room | No sales, no refunds, no cost, no financials |

`finance.view`, `inventory.view_cost` and `audit.read` are owner-only by design.
The brief asks for restricted financial visibility for cashiers and inventory
managers; the strictest correct reading of "restricted" for a pilot is "none".
Widening any of them is a one-line policy change once the owner confirms what
staff should see.

Cost visibility is enforced twice: the API returns `cost_price: null` for
callers without `inventory.view_cost`, and rejects a write to `cost_price` that
the role may not see. The frontend hides the column, which is a usability
feature only.

## 3. Enforcement

### 3.1 Dependencies

```python
CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]
CurrentTenant    = Annotated[TenantContext, Depends(get_current_tenant)]

def require_permission(permission: Permission):
    async def _dependency(context: CurrentTenant) -> TenantContext:
        if not context.allows(permission):
            raise ForbiddenError(
                "Your role does not allow this action",
                details={"permission": permission.value},
            )
        return context
    return _dependency
```

Usage:

```python
SettingsManager = Annotated[
    TenantContext, Depends(require_permission(Permission.TENANT_SETTINGS_MANAGE))
]

@router.patch("/current")
async def update_current_tenant(context: SettingsManager, ...): ...
```

`get_current_tenant` resolves the tenant, validates membership and tenant status,
binds the RLS context and computes the permission set once per request.
`require_permission` adds no query.

### 3.2 Failure contract

| Situation | Status | `error.code` | `details` |
|---|---|---|---|
| No token | `401` | `unauthorized` | — |
| Revoked/expired token, disabled user | `401` | `unauthorized` | — |
| No workspace on the session | `403` | `forbidden` | — |
| Workspace not a membership | `403` | `forbidden` | — |
| Membership/tenant not active | `403` | `forbidden` | — |
| Role lacks the permission | `403` | `forbidden` | `{"permission": "…"}` |

The error body never includes the caller's role, the required role, or any other
user's data.

### 3.3 No scattered role checks

The rule for reviewers: a business module may import `Permission` and
`require_permission`, never `ROLE_PERMISSIONS` or `MembershipRole` for an
authorisation decision. If a check needs a role comparison, the policy table is
missing a permission — add one there.

Current protected surface:

| Endpoint | Permission |
|---|---|
| `PATCH /api/v1/tenants/current` | `tenant.settings.manage` |
| `GET /api/v1/tenants/current/members` | `users.manage` |
| `GET /api/v1/tenants/current` | any active membership |
| `GET /api/v1/tenants/current/permissions` | any active membership |
| `GET /api/v1/units` | `products.read` |
| `GET /api/v1/categories` | `products.read` |
| `POST /api/v1/categories` | `categories.manage` |
| `PATCH /api/v1/categories/{id}` | `categories.manage` |
| `GET /api/v1/brands` | `products.read` |
| `POST /api/v1/brands` | `categories.manage` |
| `GET /api/v1/products`, `GET /api/v1/products/{id}` | `products.read` |
| `POST /api/v1/products` | `products.create` |
| `PATCH /api/v1/products/{id}` | `products.update` |
| `POST /api/v1/products/{id}/conversions` | `products.update` |
| `DELETE /api/v1/products/{id}`, `POST /api/v1/products/{id}/restore` | `products.archive` |
| `GET /api/v1/inventory`, `GET /api/v1/inventory/{product_id}` | `inventory.read` |
| `GET /api/v1/inventory/movements`, `GET /api/v1/inventory/batches` | `inventory.read` |
| `POST /api/v1/inventory/adjustments` | `inventory.adjust` |
| `POST /api/v1/inventory/batches` | `batches.manage` |
| `GET /api/v1/audit` | `audit.read` |
| `GET/POST /api/v1/auth/*` | authentication, not RBAC |

Cost visibility is a **field-level** rule on top of these permissions, not a
separate endpoint: `cost_price` and `unit_cost` are `null` unless the caller
holds `inventory.view_cost`.

## 4. Role changes take effect immediately

| Change | Effect |
|---|---|
| Role changed (owner → cashier) | Next request uses the new permission set |
| Membership suspended | Next request `403`; refresh refused |
| Tenant suspended | Next request `403`; refresh refused |
| User deactivated | Next request `401` |
| Session revoked | Next request `401` |

The tests that prove this:

- `test_demoting_a_role_takes_effect_immediately`
- `test_deactivating_a_membership_takes_effect_immediately`
- `test_suspending_a_workspace_takes_effect_immediately`
- `test_deactivating_the_account_invalidates_the_token`
- `test_role_in_one_workspace_does_not_grant_it_in_another`
- `test_non_owners_cannot_change_workspace_settings` (parametrised over the three
  non-owner roles)
- `test_permissions_endpoint_reflects_the_role` (parametrised over all four roles)

## 5. What is not built yet

The brief allows MANAGER permissions to be "configurable by the owner". The
current policy table is **fixed**. The reason: building an override UI and
storage before the owner confirms which staff should see cost and financial data
would be speculative, and an override system that is wrong is worse than a small
correct matrix.

When overrides are needed, the intended shape is:

```
role_permission_overrides(tenant_id, role, permission, allowed)
```

with the effective set computed as `defaults[role] ∪/∖ overrides[tenant][role]`,
still resolved on the server and still cached per request. Owner must remain
non-reducible (see below).

Other deliberate gaps:

1. **No invitation or member-management write endpoints.** `OWNER` can list
   members; adding or removing them needs its own audit requirements.
2. **No last-owner protection.** Nothing in the schema prevents a tenant from
   ending up with zero owners, because no endpoint can currently change roles.
   Add a partial unique index or a transaction-level check with the invite flow.
3. **No ownership transfer.** Needs an explicit, audited operation.
4. **No per-user permission grants.** Permissions are role-derived only.
5. **Cost and audit permissions are owner-only.** `inventory.view_cost` and
   `audit.read` are not granted to MANAGER or INVENTORY_MANAGER. This is the
   strictest reading of "restricted financial visibility" and is easy to widen
   once the owner decides.
6. **No audit screen.** The catalog and inventory UIs gate their controls with
   `permissions` from the session, but the audit feed (`audit.read`) is API-only.

The frontend reads `permissions` from `/auth/me` and hides links and buttons —
which remains a usability feature, never the enforcement point.

## 6. Adding a permission

1. Add the value to `Permission`.
2. Decide which roles hold it in `ROLE_PERMISSIONS`.
3. Apply it with `require_permission(Permission.NEW)` on the endpoint.
4. Add a case to `tests/test_rbac.py` (allowed role + at least one denied role).
5. Update the matrix in this document.

Never add `if membership.role == …` to an endpoint. If the matrix cannot express
the rule, the permission vocabulary is wrong.
