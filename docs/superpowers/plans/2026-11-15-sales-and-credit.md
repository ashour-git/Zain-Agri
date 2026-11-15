# Sales, Credit Customers and WhatsApp Invoices Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sell at the counter (cash or credit), keep a running statement per customer, take payments, process returns, and share a printable invoice on WhatsApp.

**Architecture:** Two new API modules: `customers` (customers, append-only ledger, payments, corrections) and `sales` (invoices, lines, batch draws, returns, share links, numbering). Sales write stock through the existing non-committing `apply_movement` and customer debt through `customers.ledger.post_entry`, all in one transaction per request. Web: a counter screen, invoice page with print CSS, customers list and statement, and a public read-only invoice page.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, PostgreSQL RLS, Next.js 16, Tailwind 4.

**Spec:** `docs/superpowers/specs/2026-11-15-sales-and-credit-design.md`

## Global Constraints

- Money `NUMERIC(14,2)`, rounding `ROUND_HALF_UP` to `0.01`; quantities `NUMERIC(18,4)` via the existing `_q4`.
- Every tenant table: RLS policy `tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid` (copy from `0009_stocktake.py`).
- `customer_ledger` is append-only: trigger `app_block_mutation()` (from 0005) and `REVOKE UPDATE, DELETE, TRUNCATE` in `infrastructure/db/grants.sql`.
- Permissions: new `sales.discount`, `customers.adjust` on OWNER (all) and MANAGER; CASHIER keeps `sales.operate` only; INVENTORY_MANAGER gets none of the sales permissions.
- Every English error message gets Arabic in `app/core/messages_ar.py` (guard test enforces); audit action labels added to `backup/labels.py` and `audit/page.tsx` (label-parity test enforces).
- Public invoice route is rate-limited with `auth_limiter` (scope `"invoice-link"`, 60 per 5 min per IP).
- UI copy Arabic, Western digits, no em-dashes; new forms use `Field`/`SelectField` with `info` where a term needs explaining.
- Commits: `git -c user.name="ZAIN AGRI" -c user.email="dev@zain-agri.local"`, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **The same product on two lines** (cashier adds it twice in different units): stock must be checked against the combined quantity, not each line alone. Test in Task 4: `test_same_product_twice_checks_combined_stock`.
2. **Price for a converted unit when the product has a base price only**: unit price = base sale price × factor, rounded to 0.01. Test in Task 4: `test_converted_unit_price_uses_the_factor`.
3. **Return after a partial payment on a credit invoice**: credit is reduced first, never below zero, the rest is cash refund. Test in Task 6: `test_return_reduces_credit_first_then_cash`.
4. **Customer deactivated after buying on credit**: statement and payments still work; the counter cannot pick an inactive customer. Test in Task 3: `test_inactive_customer_keeps_statement_but_cannot_buy`.
5. **Public link token for a shop whose owner revoked it, then shared again**: the old token is dead, a new one works. Test in Task 7: `test_reshare_after_revoke_gives_a_new_token`.

---

### Task 1: Permissions and migration 0010

**Files:**
- Modify: `apps/api/app/modules/authorization/permissions.py`, `apps/web/src/lib/types.ts` (PERMISSION_LABELS)
- Create: `apps/api/alembic/versions/0010_sales.py`, `apps/api/app/modules/customers/{__init__,models}.py`, `apps/api/app/modules/sales/{__init__,models}.py`
- Modify: `apps/api/alembic/env.py`, `infrastructure/db/grants.sql`
- Test: `apps/api/tests/test_sales_schema.py`

**Interfaces:**
- Produces: `Permission.SALES_DISCOUNT = "sales.discount"`, `Permission.CUSTOMERS_ADJUST = "customers.adjust"`.
- Models (columns exactly as spec §8): `ShopCounter`, `Customer`, `CustomerLedgerEntry` (`kind`: `opening|invoice|payment|return|correction`), `SalesInvoice`, `SalesInvoiceLine`, `SalesInvoiceLineBatch`, `SalesReturn`, `SalesReturnLine`.
- SQL `app_invoice_by_share_token(p_hash text) RETURNS TABLE (tenant_id uuid, invoice_id uuid)`, STABLE SECURITY DEFINER, `search_path = public, pg_temp`, EXECUTE revoked from PUBLIC, granted to `zain_app` in grants.sql.

- [ ] **Step 1: Failing tests:** `test_role_permissions` (owner and manager have both new permissions, cashier neither, inventory_manager none of `sales.*`); `test_sales_tables_are_tenant_isolated` (rows of shop B invisible under shop A context for all 8 tables, pattern `test_backup_isolation.py`); `test_customer_ledger_is_append_only` (UPDATE and DELETE raise as `zain_app`); `test_share_token_function_is_secured` (copy the definer check from `test_backup_isolation.py`); `test_invoice_number_unique_per_shop` (same number in two shops allowed, twice in one shop raises `IntegrityError`).
- [ ] **Step 2:** `uv run pytest tests/test_sales_schema.py -q` → FAIL.
- [ ] **Step 3:** Implement models, migration (down_revision `0009_stocktake`), grants, permissions, web labels («تعديل الأسعار والخصم», «تعديل حسابات العملاء»).
- [ ] **Step 4:** Tests PASS; full suite green; local DB migrated with `scripts/db-init.ps1`.
- [ ] **Step 5:** Commit `feat(sales): schema, RLS and permissions`.

### Task 2: Money helpers and the customer ledger core

**Files:**
- Create: `apps/api/app/modules/customers/ledger.py`, `apps/api/app/core/money.py`
- Test: `apps/api/tests/test_customer_ledger.py`

**Interfaces:**
- Produces: `money(value: Decimal) -> Decimal` (quantize 0.01 half-up); `async def post_entry(db, *, tenant_id, customer_id, kind: LedgerKind, amount: Decimal, actor_id, reference_type: str | None = None, reference_id: uuid.UUID | None = None, note: str | None = None) -> CustomerLedgerEntry` (no commit; `amount` signed: positive owes); `async def balance(db, tenant_id, customer_id) -> Decimal`; `async def balances(db, tenant_id, customer_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]`.

- [ ] **Step 1: Failing tests:** `test_money_rounds_half_up` (`Decimal("2.345") -> 2.35`, `Decimal("2.344") -> 2.34`); `test_balance_is_the_sum_of_entries` (opening 100, invoice 50, payment −120 → 30); `test_zero_amount_is_refused` (`UnprocessableError`).
- [ ] **Step 2–4:** red, implement, green.
- [ ] **Step 5:** Commit `feat(customers): ledger core`.

### Task 3: Customers API

**Files:**
- Create: `apps/api/app/modules/customers/{schemas,service,router}.py`; modify `app/main.py`, `messages_ar.py`, labels (`customer.created`, `customer.updated`, `customer.payment`, `customer.correction`)
- Test: `apps/api/tests/test_customers.py`

**Interfaces:**
- Produces routes (spec §7). `CustomerOut(id, name, phone, active, balance: Decimal)`; `StatementLineOut(id, kind, amount, balance_after, reference_type, reference_id, note, created_at, created_by_name)`; `CustomerCreate(name: str 1..120, phone: str | None, opening_balance: Decimal | None)`; `PaymentIn(amount: Decimal > 0, note: str | None)`; `CorrectionIn(amount: Decimal != 0, reason: str 3..300)`.
- `normalize_phone(raw: str) -> str` (Egyptian mobile `01[0125]\d{8}`, accepts `+20`/`0020`/spaces/Arabic digits, returns `+201…`; `ValueError` otherwise) in `customers/service.py`.

- [ ] **Step 1: Failing tests:** `test_create_with_opening_balance_needs_customers_adjust` (cashier 403 with opening balance, 201 without); `test_names_are_unique_after_normalization` («الحاج محمود» vs «الحاج  محمود» → 409); `test_phone_is_normalized` (`"٠١٠١٢٣٤٥٦٧٨"` → `"+201012345678"`; `"12345"` → 422 Arabic); `test_payment_lowers_balance_and_overpay_goes_negative`; `test_correction_needs_a_reason_and_customers_adjust`; `test_statement_shows_running_balance` (balance_after per line in date order); `test_list_filter_owes` (only balance > 0); `test_inactive_customer_keeps_statement_but_cannot_buy` (PATCH active false → statement 200, payment 201; sale with that customer is refused in Task 4); `test_storekeeper_has_no_access` (403); isolation test (shop B cannot read or pay shop A's customer: 404).
- [ ] **Step 2–4:** red, implement, green; Arabic messages added.
- [ ] **Step 5:** Commit `feat(customers): customers, statement, payments, corrections`.

### Task 4: Creating a sale

**Files:**
- Create: `apps/api/app/modules/sales/{schemas,numbering,pricing,service,router}.py`; modify `app/main.py`, `messages_ar.py`, labels (`sale.created`)
- Test: `apps/api/tests/test_sales.py`

**Interfaces:**
- Consumes: `apply_movement` (inventory), `_conversion_factor`, `post_entry`, `money`.
- Produces: `async def next_number(db, tenant_id, name: Literal["invoice","return"]) -> int` (row lock on `shop_counters`, insert-on-conflict then `UPDATE ... RETURNING value`); `SaleIn(customer_id: uuid | None, lines: list[SaleLineIn] 1..200, discount: Decimal = 0, paid: Decimal, idempotency_key: str 16..80)`; `SaleLineIn(product_id, quantity > 0, unit_id | None, unit_price: Decimal | None)`; `SaleOut(id, number, customer, lines, subtotal, discount, total, paid, credit, returned_total, created_at, created_by_name, share_url: str | None)`; `async def create_sale(db, context, actor_id, payload) -> SaleOut`.
- FEFO draw: `async def draw_batches(db, tenant_id, product_id, base_quantity) -> list[tuple[uuid.UUID, Decimal]]` ordered by `expiry_date NULLS LAST, batch_number`, only batches with stock > 0.
- Idempotency: `request_hash = sha256(canonical JSON of payload without the key)`; existing key + same hash → return existing `SaleOut` (200); different hash → 422 «هذا الطلب أُرسل من قبل ببيانات مختلفة.».

- [ ] **Step 1: Failing tests:** `test_cash_sale_creates_invoice_and_takes_stock` (balance 10 → 7, movement type `sale`, reference to invoice, number 1); `test_numbers_are_consecutive_per_shop` (1, 2; another shop starts at 1); `test_concurrent_sales_get_distinct_numbers` (`asyncio.gather` of 5 sales → {1..5}); `test_not_enough_stock_writes_nothing_and_names_the_product`; `test_same_product_twice_checks_combined_stock` (stock 5, lines 3 + 3 → 409); `test_converted_unit_price_uses_the_factor` (base price 12.50, box = 12 → line price 150.00); `test_rounding` (qty 3 × 0.335 → 1.01); `test_cashier_cannot_change_price_or_discount` (403 with `unit_price` differing or `discount` > 0); `test_owner_can_discount_up_to_subtotal` (> subtotal → 422); `test_product_without_price_blocks_the_cashier` (422 Arabic per spec §3); `test_cash_customer_must_pay_in_full` (422); `test_credit_sale_posts_statement_line` (paid 0 → customer balance = total); `test_paid_more_than_total_is_refused`; `test_inactive_customer_cannot_buy`; `test_fefo_across_batches` (batches expiring 2027-01 qty 2 and 2026-12 qty 2, sell 3 → 2 from 2026-12, 1 from 2027-01); `test_same_key_same_body_returns_the_same_invoice` (one invoice, one stock drop); `test_same_key_other_body_is_refused`; `test_storekeeper_cannot_sell`; `test_archived_product_cannot_be_sold`; isolation (shop B's product id in shop A's sale → 404); `test_balances_equal_movements_after_sales`.
- [ ] **Step 2–4:** red, implement, green.
- [ ] **Step 5:** Commit `feat(sales): create a sale with stock, credit, numbering and idempotency`.

### Task 5: Reading sales

**Files:** modify `sales/service.py`, `sales/router.py`; test `tests/test_sales.py`

**Interfaces:** `GET /sales` → `SaleListOut(items: list[SaleSummaryOut(id, number, customer_name, total, credit, created_at, created_by_name)], total, page, page_size)` with `q` (number or customer name) and `customer_id`; `GET /sales/{id}` → `SaleOut`.

- [ ] **Step 1: Failing tests:** `test_cashier_lists_only_own_invoices`; `test_owner_lists_all_and_searches_by_number_and_customer`; `test_invoice_detail_shows_lines_and_batches_and_returns`.
- [ ] **Step 2–5:** red, implement, green, commit `feat(sales): invoice list and detail`.

### Task 6: Returns

**Files:** create `sales/returns.py`; modify router, `messages_ar.py`, labels (`sale.returned`); test `tests/test_sales_returns.py`

**Interfaces:** `ReturnIn(lines: list[ReturnLineIn(line_id, quantity > 0)] 1.., reason: str 3..300)`; `ReturnOut(id, number, total, credit_reduction, cash_refund)`; `async def create_return(db, context, actor_id, invoice_id, payload) -> ReturnOut`. Stock back with `customer_return` into the batches recorded in `sales_invoice_line_batches`, most recent draw first. Credit reduction = min(return total, invoice credit − earlier credit reductions).

- [ ] **Step 1: Failing tests:** `test_return_puts_stock_back_to_the_same_batches`; `test_cannot_return_more_than_sold_minus_returned` (two returns of 2 on a line of 3 → second 422); `test_return_reduces_credit_first_then_cash` (total 100, paid 60, credit 40; return 70 → credit_reduction 40, cash_refund 30, customer balance 40 → 0); `test_cash_invoice_return_is_all_cash`; `test_return_numbers_are_separate_and_consecutive`; `test_cashier_cannot_return` (403); isolation.
- [ ] **Step 2–5:** red, implement, green, commit `feat(sales): returns`.

### Task 7: Share link and public invoice

**Files:** create `sales/sharing.py`, public router `sales/public_router.py`; modify `main.py`, `messages_ar.py`; test `tests/test_sales_sharing.py`

**Interfaces:** `POST /sales/{id}/share` → `{url}` (`{PUBLIC_APP_URL}/i/{token}`, token `secrets.token_urlsafe(32)`, stored as sha256; if a token exists a new one is issued and the old one dies, because the clear token is not stored); `DELETE /sales/{id}/share` (sales.discount); `GET /api/v1/public/invoices/{token}` → `PublicInvoiceOut(shop_name, number, created_at, lines, subtotal, discount, total, paid, remaining)` with no customer phone and no balance; header `X-Robots-Tag: noindex`.

- [ ] **Step 1: Failing tests:** `test_public_invoice_works_without_login`; `test_public_invoice_hides_balance_and_phone` (keys exactly as above); `test_revoke_kills_the_link` (404 after DELETE); `test_reshare_after_revoke_gives_a_new_token`; `test_wrong_token_is_404`; `test_cashier_cannot_revoke`; `test_public_route_is_rate_limited` (61st call → 429).
- [ ] **Step 2–5:** red, implement, green, commit `feat(sales): shareable invoice link`.

### Task 8: Web: counter, invoice page, print, WhatsApp

**Files:** create `apps/web/src/lib/sales.ts`, `app/(app)/sales/page.tsx` (counter), `app/(app)/sales/[id]/page.tsx` (invoice + return dialog), `app/(app)/sales/history/page.tsx`, `app/i/[token]/page.tsx` (public, outside the app shell), `components/sales/invoice-view.tsx` (shared by both invoice pages), print rules in `app/globals.css`; modify nav (`البيع` first item, `sales.operate`) and app-shell titles.

**Interfaces:** `whatsappUrl(phone: string | null, text: string): string` in `lib/sales.ts` (`https://wa.me/<digits without +>?text=<encodeURIComponent>`, no phone → `https://wa.me/?text=`); idempotency key `crypto.randomUUID()` created when the counter opens and renewed after a saved sale.

- [ ] **Step 1:** Build pages; print CSS: `@media print` hides shell (`[data-print-hide]`), `.receipt-80` sets `width: 72mm` single column; size choice stored in `localStorage` key `zain.printSize`.
- [ ] **Step 2:** `pnpm exec tsc --noEmit`, `pnpm lint`, `pnpm build` exit 0.
- [ ] **Step 3:** Browser at 420 px and 1200 px: sell 2 products (one by box), credit sale to a new customer, open invoice, print preview both sizes, WhatsApp button href matches the spec message, public link opens logged out.
- [ ] **Step 4:** Commit `feat(web): counter, invoice page, print and WhatsApp`.

### Task 9: Web: customers and statement

**Files:** create `lib/customers.ts`, `app/(app)/customers/page.tsx`, `app/(app)/customers/[id]/page.tsx`; nav item «العملاء».

- [ ] **Step 1:** List with search and «عليهم فلوس» filter; add customer (opening balance field only with `customers.adjust`, with `info`); statement with running balance, «تحصيل» and «تصحيح» dialogs; link to invoices.
- [ ] **Step 2:** tsc, lint, build exit 0; browser check at 420 px: payment lowers balance, overpay shows «له».
- [ ] **Step 3:** Commit `feat(web): customers and statement`.

### Task 10: Live check and deploy

- [ ] **Step 1:** Full API suite, ruff, mypy, web checks: all exit 0.
- [ ] **Step 2:** Migrate Neon to 0010 (the `.env.neon-owner` Python helper), verify tables and `has_function_privilege`.
- [ ] **Step 3:** Merge, push, wait for Ready; on a throwaway shop measure a 20-line sale (target < 1 s) and report the number; open a public link logged out.
- [ ] **Step 4:** Update memory `zain-open-issues` and the spec status line; commit `docs: sales live`.
