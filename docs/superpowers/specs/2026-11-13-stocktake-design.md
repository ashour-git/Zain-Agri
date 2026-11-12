# Stocktake (جرد) - Design

Status: written 2026-11-13, awaiting owner review
Owner: ZAIN AGRI web + API

## 1. Purpose

Today a wrong quantity is fixed by working out the difference by hand and
entering an adjustment per product. A stocktake lets the storekeeper count
the shelves, see what is short or in surplus, and post every correction in
one confirmed step, with a record of what was counted and by whom.

It also gives the shop a safe way to load or correct starting quantities
before the Excel import exists.

### Decisions taken with the owner

| Topic | Decision |
|---|---|
| Order of work | Stocktake first, smart import second |
| Who | Roles holding `inventory.adjust` (owner, manager, storekeeper) |
| Where | A «جرد» button on the inventory screen, no new sidebar item |
| Device | Counting happens standing at the shelf: the count screen is designed for a phone first |

### Out of scope (this version)

- Counting by scanning with the camera (a typed barcode or name search is in).
- Creating a new batch during a count (add the batch on the inventory screen first).
- Counting several stocktakes at once, or cycle-count schedules.
- Assistant questions about stocktakes.
- Costs and stock valuation (still open, Q27).

## 2. Flow

1. **Start.** Choose the scope: all active products, or one category. Optional
   name, default «جرد 13 نوفمبر». The system snapshots one line per product
   (per batch for batch-tracked products that have stock). Only one open
   stocktake per shop at a time.
2. **Count.** A list of lines with search (name, code, barcode) and a quantity
   box per line. The quantity is entered in the product's sale unit or any
   unit with a configured conversion (the same rule as adjustments). Saving a
   line stores it immediately, so a closed browser loses nothing.
   Blind by default: the system quantity is not sent to the browser for a
   line until it has been counted, so the count is not copied from the screen.
3. **Review.** Every counted line shows system quantity, counted quantity,
   difference, and a reason for shortages: «عجز» (default), «تالف»,
   «منتهي الصلاحية». Uncounted lines are listed separately and are left
   untouched, never set to zero.
4. **Apply.** One confirmation posts all corrections in a single transaction:
   all or nothing. The stocktake becomes read-only history.
5. **Cancel.** An open stocktake can be cancelled; nothing is posted.

### Difference rule

The system quantity is recorded at the moment a line is counted
(`system_quantity_at_count`). The correction is
`counted_base - system_quantity_at_count`, applied to the current balance.
Stock that moved after the line was counted (a purchase, a correction) is
kept. If the correction would make the balance negative, apply stops with a
clear message naming the product, and nothing is posted.

## 3. Movements posted

| Difference | Movement type | Reason text |
|---|---|---|
| surplus | `adjustment_in` | «جرد: <name>» |
| shortage (عجز) | `adjustment_out` | «جرد: <name>» |
| shortage (تالف) | `damage` | «جرد: <name>» |
| shortage (منتهي) | `expiry` | «جرد: <name>» |

`damage` and `expiry` become writable outbound types (they already exist in
the movement type list). Each movement carries `reference_type = 'stocktake'`
and `reference_id`, and is audited by the existing path.

## 4. Fixes found while reviewing the stock logic

1. `record_movement` is split into a core that does not commit, so a stocktake
   can post many corrections in one transaction. Its behaviour and tests do
   not change.
2. Opening balance for a batch-tracked product is allowed once **per batch**
   (today a product with several batches can only load one).
3. A test asserts that every balance equals the sum of its movements.

## 5. Data model

`stocktakes` (RLS by tenant): `id`, `tenant_id`, `name`, `scope`
(`all` | `category`), `category_id`, `blind`, `status`
(`open` | `applied` | `cancelled`), `created_by`, `applied_by`, `created_at`,
`applied_at`. Partial unique index: one `open` row per tenant.

`stocktake_lines` (RLS by tenant): `id`, `tenant_id`, `stocktake_id`,
`product_id`, `batch_id` (nullable), `counted_quantity`, `unit_id`,
`counted_base_quantity`, `system_quantity_at_count`, `shortage_reason`
(`shortage` | `damage` | `expiry`, default `shortage`), `counted_by`,
`counted_at`. Unique `(stocktake_id, product_id, batch_id)`.

## 6. API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/stocktakes` | start (scope, name, blind) |
| GET | `/api/v1/stocktakes` | history |
| GET | `/api/v1/stocktakes/{id}` | header + counts summary |
| GET | `/api/v1/stocktakes/{id}/lines` | lines, search, paging; system quantity only when counted or not blind |
| PUT | `/api/v1/stocktakes/{id}/lines/{line_id}` | save one counted quantity (idempotent) |
| GET | `/api/v1/stocktakes/{id}/review` | differences and uncounted lines |
| POST | `/api/v1/stocktakes/{id}/apply` | post all corrections |
| POST | `/api/v1/stocktakes/{id}/cancel` | cancel |

All require `inventory.adjust`, except history and header which need
`inventory.read`. Errors use the existing envelope with Arabic messages.

## 7. Screens

- `/inventory/stocktake`: open count (continue) or history, and «بدء جرد جديد».
- `/inventory/stocktake/[id]`: count screen. Search box on top, one row per
  line with a large numeric box, progress «عدّدت 42 من 118». Sticky bottom bar:
  «مراجعة الفروق».
- Review screen: three groups, shortages, surpluses, uncounted. Shortage rows
  have the reason selector. Button «اعتماد الجرد» with a confirmation that
  states the number of corrections.
- Western digits, ledger look, RTL, keyboard friendly, loading and empty states.

## 8. Testing

- Core: counting a line stores base quantity through unit conversion.
- Difference rule: movements between count and apply are preserved.
- Apply is atomic: a failing line posts nothing.
- Surplus, shortage, damage and expiry post the right type and reference.
- Uncounted lines are never changed.
- One open stocktake per shop; cancelled and applied ones are read-only.
- Blind mode never returns the system quantity for an uncounted line.
- Permissions: cashier gets 403 everywhere; storekeeper can count and apply.
- Isolation: shop A cannot see or touch shop B's stocktake or lines.
- Balance equals sum of movements after a stocktake.
- Opening balance per batch allowed, second one for the same batch refused.

## 9. Risks

- Counting a big shop on a phone is long; saving each line immediately and
  resuming later is the mitigation.
- A shop with thousands of products needs paging on the lines list (page size
  50) and an apply that does not hold the connection open too long. Apply
  posts in one transaction and is limited to 2,000 corrections per
  stocktake; a larger count must be split by category.
