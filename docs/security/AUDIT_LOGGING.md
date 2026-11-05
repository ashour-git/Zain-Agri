# ZAIN AGRI — Audit Logging

Status: Sprint 03
Last updated: 2026-11-01
Code: `apps/api/app/modules/audit/`, migration `0006_audit`

The audit trail answers three questions after the fact: **who** changed
something, **what** it looked like before and after, and **which operation** it
belonged to. It is written in the same transaction as the change, so there is no
state where the business succeeded and the trail did not.

---

## 1. Table

`audit_logs`:

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` | PK |
| `tenant_id` | `uuid` | FK → `tenants.id`; RLS scope |
| `actor_id` | `uuid` | FK → `users.id` ON DELETE SET NULL — a deleted user must not erase history |
| `action` | `varchar(80)` | Dotted verb, e.g. `product.updated` |
| `entity_type` | `varchar(60)` | e.g. `product`, `stock_movement` |
| `entity_id` | `uuid` | Nullable for future non-row events |
| `before_state` | `jsonb` | `null` for creates |
| `after_state` | `jsonb` | `null` for deletes |
| `metadata` | `jsonb` | Context: reason, balance before/after, request id |
| `created_at` | `timestamptz` | Server clock |

Indexes: `(tenant_id, created_at)` for the feed and `(tenant_id, entity_type,
entity_id)` for an entity's history.

The Python attribute is `meta` because `metadata` is reserved by SQLAlchemy; the
column keeps the documented name.

## 2. Actions recorded

| Action | Entity | Written by |
|---|---|---|
| `product.created` | `product` | create |
| `product.updated` | `product` | update (before/after) |
| `product.archived` | `product` | archive |
| `product.restored` | `product` | restore |
| `product_conversion.created` | `product_unit_conversion` | add conversion |
| `category.created` / `category.updated` | `product_category` | taxonomy |
| `brand.created` | `brand` | taxonomy |
| `batch.created` | `product_batch` | batch creation |
| `inventory.movement.created` | `stock_movement` | any ledger append |

`inventory.movement.created` carries `meta.balance_before` and
`meta.balance_after` and the operator's `reason`, which is what makes a stock
discrepancy explainable months later.

## 3. Atomicity

```python
# catalog / inventory service
await audit.record(db, ...)   # flushes only
...
await db.commit()             # business row + audit row together
```

- `audit.record` never commits. The caller owns the transaction.
- If the audit insert fails, the business change rolls back — a mutation cannot
  exist without its trail.
- A rejected business operation (e.g. negative stock) raises before the audit
  call, so no orphan audit row exists. Proven by
  `test_a_rejected_operation_leaves_no_audit_row`.

## 4. Reads

`GET /api/v1/audit` requires `audit.read` (OWNER-only in the Sprint 03 matrix).

Filters: `page`, `page_size`, `entity_type`, `entity_id`, `action`, `actor_id`,
`created_from`, `created_to`. Ordered by `created_at DESC, id DESC` so paging is
deterministic when timestamps collide.

The service filters by `tenant_id` explicitly even though RLS already does:
defence in depth, and it keeps the query plan on the tenant index.

There is deliberately **no write endpoint**. The only way to append is a service
call inside another module's transaction.

## 5. Hardening

| Control | Effect |
|---|---|
| RLS with `USING` + `WITH CHECK` | A request bound to tenant A cannot read or write tenant B's rows |
| `app_block_mutation()` trigger | `UPDATE`/`DELETE` raise for every role, including the owner path |
| `REVOKE UPDATE, DELETE, TRUNCATE` in `grants.sql` | The runtime role has no privilege to try |
| No API write path | Nothing in the application can append outside a service call |
| Actor FK `ON DELETE SET NULL` | Removing a user leaves the event intact |

### 5.1 Sensitive values

`audit.record` drops any key whose name contains `password`, `token`, `secret`,
`authorization`, `cookie`, `api_key` or similar, at any depth. Values are
dropped rather than masked, so a secret cannot be recovered from the column.
`test_audit_states_never_contain_credentials` asserts the serialised feed
contains none of those fragments.

State snapshots are built from explicit field lists in the services, never from
`model.__dict__`, so new columns do not leak automatically.

## 6. Tests

| Test | Proves |
|---|---|
| `test_writes_are_attributed_to_the_actor` | Actor id/name and `after_state` |
| `test_movement_audit_records_the_balance_transition` | `meta.balance_before/after`, reason |
| `test_update_and_archive_keep_before_and_after` | Before/after, newest-first order |
| `test_a_rejected_operation_leaves_no_audit_row` | Atomicity with business failure |
| `test_audit_is_owner_only` | Manager/cashier/inventory manager get 403 |
| `test_audit_is_tenant_scoped` | Another workspace sees zero rows |
| `test_catalog_audit_covers_categories_brands_and_conversions` | Catalog actions |
| `test_audit_rows_cannot_be_edited_or_deleted_by_the_runtime_role` | Trigger + revokes |
| `test_audit_states_never_contain_credentials` | No secrets in the feed |
| `test_audit_filter_by_actor` | Filtering and empty result |

## 7. Deliberate gaps

- **No read endpoint for a single event** (`/audit/{id}`); the feed with filters
  is enough while the UI has no audit screen.
- **No UI.** The trail is API-only in Sprint 03.
- **No retention or partitioning policy.** Volume will be small for a pilot;
  a monthly partition plus a retention decision is a launch task
  (`OPEN_QUESTIONS.md`).
- **No system/anonymous actions.** Every recorded action has a real user behind
  it; a future background job will need an explicit service actor concept.
- **No diff algorithm.** Before/after snapshots are stored whole; deriving a
  field-level diff is a read-time concern that does not need code yet.
