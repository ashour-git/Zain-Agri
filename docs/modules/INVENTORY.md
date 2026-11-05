# ZAIN AGRI — Inventory

Status: Sprint 03
Last updated: 2026-11-01
Code: `apps/api/app/modules/inventory/`, `apps/web/src/app/(app)/inventory/`

Inventory answers one question at a time: **what is on hand, and why?**
The "why" is an append-only movement ledger; the "what" is a projection of that
ledger. Correctness rules live in `docs/architecture/INVENTORY_LEDGER.md`.

---

## 1. Tables

| Table | Tenant-owned | Purpose |
|---|---|---|
| `stock_movements` | yes | Append-only ledger; the source of truth |
| `inventory_balances` | yes | One row per (tenant, product); projection written in the same transaction |
| `product_batches` | yes | Batch number and optional expiry, per product |

### 1.1 `stock_movements`

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` | PK, generated in the application |
| `tenant_id` | `uuid` | FK → `tenants.id` |
| `product_id` | `uuid` | Composite FK `(tenant_id, product_id)` |
| `batch_id` | `uuid` | Composite FK; required iff the product tracks batches |
| `movement_type` | `stock_movement_type` | 11 values defined, 3 writable |
| `quantity` | `NUMERIC(18,4)` | Always positive, in `unit_id` |
| `unit_id` | `uuid` | FK → `units_of_measure.id` |
| `base_quantity` | `NUMERIC(18,4)` | Signed delta in the product's base unit |
| `unit_cost` | `NUMERIC(18,6)` | Per base unit; informational only |
| `reference_type` / `reference_id` | text / uuid | Reserved for purchases and sales |
| `notes` | text | The operator's reason, required by the API |
| `created_by` | `uuid` | FK → `users.id` ON DELETE SET NULL |
| `created_at` | `timestamptz` | Server clock |

Movement vocabulary:

| Value | Writable in Sprint 03 | Direction |
|---|:---:|---|
| `opening_balance` | ✅ | in |
| `adjustment_in` | ✅ | in |
| `adjustment_out` | ✅ | out |
| `purchase`, `customer_return`, `transfer_in` | — | in |
| `sale`, `supplier_return`, `damage`, `expiry`, `transfer_out` | — | out |

The full enum exists now so adding purchasing or sales later never requires a
destructive enum migration; only the three adjustment types are accepted by the
API today (anything else is a 422).

### 1.2 `inventory_balances`

`PRIMARY KEY (tenant_id, product_id)`, `quantity NUMERIC(18,4)`. It is written
only by the inventory service, in the same transaction as the movement that
changes it, after taking a row lock. Nothing else in the codebase may update it.

### 1.3 `product_batches`

Unique per `(tenant_id, product_id, batch_number)`; `expiry_date` is optional.
Batch stock is not stored: it is `SUM(base_quantity)` of the movements that
reference the batch.

## 2. Rules the API enforces

| Rule | Failure |
|---|---|
| Quantity must be > 0 | 422 |
| A reason of at least 3 characters is required | 422 |
| `opening_balance` only while the product has no movements | 409 |
| Only `opening_balance`, `adjustment_in`, `adjustment_out` are writable | 422 |
| Stock may never go negative | 409 with `details.available` / `details.requested` |
| A batch-level balance may never go negative | 409 |
| A unit must convert to the product's base unit | 422 |
| `tracks_batches` ⇒ a batch is required | 422 |
| `!tracks_batches` ⇒ a batch is forbidden | 422 |
| Archived products cannot receive movements | 409 |
| `unit_cost` requires `inventory.view_cost` | 403 |

Corrections are **new, opposite movements**. There is no update or delete path
in the API, and the database rejects both for the runtime role.

## 3. API

| Method | Path | Permission |
|---|---|---|
| GET | `/inventory` | `inventory.read` |
| GET | `/inventory/{product_id}` | `inventory.read` |
| GET | `/inventory/movements` | `inventory.read` |
| POST | `/inventory/adjustments` | `inventory.adjust` |
| GET | `/inventory/batches` | `inventory.read` |
| POST | `/inventory/batches` | `batches.manage` |

Static paths (`/movements`, `/batches`, `/adjustments`) are declared before
`/{product_id}` so they are never parsed as a UUID.

`GET /inventory` filters by `q`, `category_id`, `stock`, with `page` /
`page_size`. `GET /inventory/{id}` returns the balance row, all batches, and the
most recent movements. `GET /inventory/movements` filters by `product_id`,
`movement_type`, `batch_id`, and a `created_from`/`created_to` window.

`POST /inventory/adjustments` returns the created movement **and** the balance
before/after, which is what the UI shows in its confirmation panel.

`unit_cost` is omitted (`null`) from responses unless the caller holds
`inventory.view_cost`.

## 4. Frontend

`/inventory`:

- Search, stock-state filter (`نفد` / `قارب النفاد` / `متوفر`), category filter,
  pagination.
- Table: product, category, quantity with status badge, minimum stock, sale
  price, last movement, actions.
- A row expands into a detail card: batches (quantity, expiry) and the most
  recent movements (type, signed quantity, actor, timestamp, reason).
- `AdjustmentDialog` shows **الرصيد الحالي / التغيير المتوقع / الرصيد بعد
  التأكيد** before confirmation, and refuses to submit a negative result locally
  (the server refuses it anyway).
- `BatchDialog` creates a batch for a product that tracks batches; it explains
  that a new batch starts at zero until a movement is recorded.
- Actions are gated by `inventory.adjust` / `batches.manage`; the API re-checks.

## 5. Tests

| Suite | Covers |
|---|---|
| `tests/test_inventory.py` | Opening balance once, negative-stock rejection, conversion to base unit, unknown conversion, unwritable types, cashier denial, cost gating, batch requirements, batch negative stock, duplicate batch number, concurrent oversell, ledger↔projection reconciliation, immutability, list filters, detail payload, tenant scoping |
| `tests/test_catalog_isolation.py` | RLS for movements, balances, batches |
| `tests/test_audit.py` | `inventory.movement.created` attribution and balance transition |

## 6. Deliberate gaps

- **No valuation or costing method.** `unit_cost` is recorded for future use;
  there is no FIFO/LIFO/weighted-average calculation, no COGS, no stock-value
  metric. `OPEN_QUESTIONS.md` Q27 must be answered first.
- **No FEFO/expiry automation.** Expiry dates are stored and displayed only.
  Nothing warns, blocks, or auto-consumes a batch.
- **No stock transfer between branches** (no `branches` table yet).
- **No multi-line stock documents.** A purchase or sale will append its own
  movements inside its module's transaction, using the same service primitive.
- **No physical-count workflow.** The pilot uses an adjustment with a reason of
  `جرد`.
