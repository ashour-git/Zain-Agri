# Sales, credit customers and WhatsApp invoices - Design

Status: approved in conversation 2026-11-15, awaiting spec review
Owner: ZAIN AGRI web + API

## 1. Purpose

The shop can track stock but cannot sell in the app. This adds the daily trade:
a counter screen that creates an invoice and takes the goods out of stock,
credit customers («آجل») with a running statement, payments received, sales
returns, a printable invoice, and a one-tap WhatsApp message with a link to the
invoice. It turns ZAIN AGRI from a stock list into the shop's daily tool.

### Decisions taken with the owner

| Topic | Decision |
|---|---|
| How customers pay | Cash in full, or credit for named regular customers («آجل») |
| Credit bookkeeping | A running statement (كشف حساب): append-only lines, balance = their sum |
| Price changes | Owner and manager may change a price or give a discount; the cashier may not |
| WhatsApp | Send the invoice after a sale, free: the app opens WhatsApp with the text ready, a person presses send |
| Printing | One invoice page that prints on A4 or an 80 mm receipt printer |

### Out of scope (this version)

- Purchases from suppliers, supplier statements.
- Profit and cost-of-goods reports (costing method still open, Q27).
- Debt reminders on WhatsApp; automatic (paid) WhatsApp sending.
- Mobile wallets and card payments as separate payment methods (all money is "cash").
- Tax (VAT), e-invoicing, receipt-printer settings (paper width, logo size).
- Editing or deleting an invoice after it is saved (corrections are returns).

## 2. Roles and permissions

| Action | Owner | Manager | Storekeeper | Cashier |
|---|---|---|---|---|
| Sell, see own invoices, print, WhatsApp | yes | yes | no | yes |
| Change a price or give a discount | yes | yes | no | no |
| See customers, add a customer at the counter | yes | yes | no | yes |
| Record a payment received | yes | yes | no | yes |
| Customer opening balance, statement correction | yes | yes | no | no |
| Sales return | yes | yes | no | no |

New permissions: `sales.discount` and `customers.adjust` (owner and manager).
Existing: `sales.operate` (sell, customers, payments), `sales.refund` (returns).
Every rule is enforced by the API; the web only hides what a role cannot use.

## 3. The counter «البيع»

New sidebar item at the top, for `sales.operate`.

1. **Search** by name, code or barcode; a barcode scanner types like a keyboard
   and Enter adds the line. Choosing a product adds a line (choosing it again adds 1).
2. **Line:** product, quantity, unit (base unit or any unit with a conversion),
   unit price, line total. The price is the product's `sale_price` in the chosen
   unit (base price × conversion factor).
3. **Price and discount:** with `sales.discount` the unit price can be changed and
   a discount amount can be set on the whole invoice. Without it the fields are
   read-only. A product with no sale price cannot be sold by a cashier:
   «لا يوجد سعر بيع لهذا الصنف. اطلب من المالك تحديده».
4. **Customer:** «زبون نقدي» by default; or pick a customer; or add one inline
   (name required, phone optional).
5. **Payment:** "paid" defaults to the total. With a named customer it may be less
   (the rest goes on credit) or zero. A cash customer must pay in full. Paid can
   never exceed the total on the invoice (overpayment is recorded as a separate
   payment, §4).
6. **Save** shows the saved invoice with «طباعة» and «إرسال واتساب».

### What one sale writes (one transaction, all or nothing)

- `sales_invoices` row: number, customer (nullable), subtotal, discount, total,
  paid, credit (total − paid), created_by, idempotency key.
- `sales_invoice_lines`: product, name snapshot, unit, quantity, base quantity,
  unit price, line total, and the batch lines it drew from.
- One `sale` stock movement per line per batch, through `apply_movement`
  (reference_type `sales_invoice`). Not enough stock: nothing is written and the
  error names the product.
- Batch-tracked products draw from the batch that expires first (no expiry date
  last), across several batches when one is not enough.
- If credit > 0: one statement line on the customer.
- Audit `sale.created`.

### Numbers and money

- Invoice numbers are per shop, start at 1, never repeat and never skip: a
  per-shop counter row is locked and incremented in the same transaction.
- Money is `NUMERIC(14,2)` in Egyptian pounds; quantities `NUMERIC(18,4)`.
  Line total = round(quantity × unit price, 2, half-up); total = sum of lines −
  discount; discount ≤ subtotal; nothing negative.

### Double submission

The browser creates one idempotency key per sale screen. The invoice table has a
unique `(tenant_id, idempotency_key)`. A repeated request with the same key and
the same body returns the first invoice (200); the same key with a different body
is refused (422). A request still in progress makes the duplicate wait on the
row lock, then return the result.

## 4. Customers, statement and payments

**`/customers`** (sidebar «العملاء», `sales.operate`): name, phone, balance;
search; filter «عليهم فلوس». Customers with statement lines are never deleted,
only hidden (`active = false`).

- Name required (unique per shop after normalization); phone optional, an
  Egyptian mobile (`01[0125]` + 8 digits, stored as `+201…`).
- Opening balance «رصيد سابق» when creating, with `customers.adjust` only.

**Statement lines** (`customer_ledger`, append-only like the stock ledger, guarded
by the same database trigger and revoked UPDATE/DELETE):

| Kind | Effect on balance | Source |
|---|---|---|
| `opening` | + | owner/manager when creating the customer |
| `invoice` | + credit part of an invoice | sale |
| `payment` | − | «تحصيل» |
| `return` | − returned value on a credit invoice | sales return |
| `correction` | ±, with a reason | owner/manager |

Balance = sum of amounts; positive = owes the shop, negative = «له» (shop owes him).
The statement shows each line with date, reference and running balance.

**Payment «تحصيل»:** amount > 0, optional note, by anyone with `sales.operate`.
Overpaying is allowed and leaves a negative balance.

## 5. Sales returns «مرتجع»

`sales.refund` only. Open an invoice, choose lines and quantities; quantity ≤ sold
minus already returned for that line. One transaction:

- `sales_returns` row with its own per-shop number, and its lines.
- `customer_return` stock movements back into the same batches the sale drew from.
- Money: the returned value is first taken off what is still owed on that invoice
  (a `return` statement line); any rest is cash to hand back, shown on screen and
  stored on the return.
- Audit `sale.returned`.

## 6. Invoice page, printing and WhatsApp

- **`/sales/[id]`** in the app: shop name and logo, invoice number and date, lines,
  discount, total, paid, remaining on this invoice, returns if any.
- **Print:** a «طباعة» button and a size switch A4 / 80 mm (remembered in the
  browser). Print CSS hides the app shell; the 80 mm layout is one column.
- **Public link** `/i/<token>`: read-only page of that one invoice, without
  signing in. Token: 32 random bytes, url-safe, stored as SHA-256; resolved by a
  narrow SECURITY DEFINER function returning the invoice id only, then read under
  the invoice's tenant context. Shows the invoice only, never the customer's
  other invoices or balance. `noindex`. The owner can turn a link off (revoke).
- **WhatsApp:** `https://wa.me/<phone>?text=<message>` (or `https://wa.me/?text=` with
  no phone). Message:
  «مؤسسة زين: فاتورة رقم 123، الإجمالي 1,250 جنيه، المدفوع 1,000، الباقي 250.
  التفاصيل: <link>». Western digits.

## 7. API

| Method | Path | Who |
|---|---|---|
| POST | `/api/v1/sales` | sales.operate (+ sales.discount for price/discount changes) |
| GET | `/api/v1/sales` | sales.operate (cashier sees own, others all), paging, search |
| GET | `/api/v1/sales/{id}` | sales.operate |
| POST | `/api/v1/sales/{id}/returns` | sales.refund |
| POST | `/api/v1/sales/{id}/share` | sales.operate: creates or returns the public link |
| DELETE | `/api/v1/sales/{id}/share` | sales.discount (owner/manager): revoke link |
| GET | `/api/v1/public/invoices/{token}` | public, rate-limited |
| GET/POST | `/api/v1/customers` | sales.operate (opening balance needs customers.adjust) |
| GET/PATCH | `/api/v1/customers/{id}` | sales.operate / customers.adjust |
| GET | `/api/v1/customers/{id}/statement` | sales.operate |
| POST | `/api/v1/customers/{id}/payments` | sales.operate |
| POST | `/api/v1/customers/{id}/corrections` | customers.adjust |

Request bodies carry quantities and prices as strings (decimals). Errors use the
existing envelope with Arabic messages. List endpoints page like the others.

## 8. Data model (migration 0010)

All tables tenant-scoped by RLS like the rest.

- `shop_counters(tenant_id, name, value)` - invoice and return numbers.
- `customers(id, tenant_id, name, name_key, phone, active, created_by, timestamps)`,
  unique `(tenant_id, name_key)`.
- `customer_ledger(id, tenant_id, customer_id, kind, amount, reference_type,
  reference_id, note, created_by, created_at)` - append-only.
- `sales_invoices(id, tenant_id, number, customer_id, subtotal, discount, total,
  paid, credit, idempotency_key, request_hash, share_token_hash, created_by,
  created_at)`, unique `(tenant_id, number)` and `(tenant_id, idempotency_key)`.
- `sales_invoice_lines(id, tenant_id, invoice_id, product_id, name_ar, unit_id,
  quantity, base_quantity, unit_price, line_total)`.
- `sales_invoice_line_batches(line_id, batch_id, base_quantity)` - where each
  line was drawn from, for returns.
- `sales_returns(id, tenant_id, number, invoice_id, total, credit_reduction,
  cash_refund, reason, created_by, created_at)` and `sales_return_lines`.
- SECURITY DEFINER `app_invoice_by_share_token(text) -> (tenant_id, invoice_id)`.

## 9. Testing

- Sale: lines, unit conversion, rounding, discount ≤ subtotal, stock movement per
  line, not enough stock → nothing written and product named, FEFO across batches.
- Permissions: cashier cannot change price/discount, cannot return, cannot
  correct a statement; storekeeper cannot sell; every rule through the API.
- Credit: cash customer must pay in full; credit line written; statement balance =
  sum; overpayment → «له»; opening balance only with customers.adjust.
- Returns: limit per line including earlier returns; stock back to the same batches;
  credit reduced first, rest as cash refund.
- Numbers: concurrent sales get distinct consecutive numbers.
- Idempotency: same key + same body → one invoice; same key + other body → 422.
- Public link: token works without login, shows only that invoice, revoke works,
  wrong token 404, other shop's invoice never reachable.
- Isolation: shop A never sees shop B's sales, customers or statements.
- Balance check: stock balances equal the sum of movements after sales and returns.
- Browser: sell at phone width, print preview in both sizes, WhatsApp link format.
- Live timing: a 20-line sale saved in under 1 s on production (measured, reported).

## 10. Risks

- A shop with many batch products pays extra queries per line for FEFO; measured
  in the live timing check.
- Anyone who receives a forwarded invoice link can read that invoice; the page
  holds no other customer data and the owner can revoke it.
- Credit without limits: a customer's debt can grow without a warning. A credit
  limit per customer is a likely next step, not in this version.
