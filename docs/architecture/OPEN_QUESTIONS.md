# ZAIN AGRI — Open Questions

Status: Sprint 03
Last updated: 2026-11-01

> **Rule.** Nothing in the "Blocks" column gets implemented on a guess. If a
> question below is unanswered when its sprint starts, the correct move is to ask,
> not to invent a default.

Legend — **Blocks:** what cannot proceed until answered. **Owner:** who can answer.

---

## A. Sprint 02 (authentication) — implemented

> **Outcome.** Sprint 02 shipped **option C**: self-service registration creates a
> tenant and an `OWNER` membership atomically. Invitations and email delivery are
> still absent, so a store with more than one user cannot yet be staffed through
> the product. The other questions below were answered by implementation as noted
> in `docs/security/AUTHENTICATION.md`; their text is kept for the reasoning.

### Q1 — Who creates a tenant, and how does the first owner exist?

**Why it matters.** The brief forbids building registration flows on unapproved
assumptions. Every auth design depends on this: self-service signup, invite-only,
or operator-provisioned tenants produce different tables (`invitations`,
`email_verification`), different endpoints, and different abuse controls.

**Options**

| Option | Shape | Cost |
|---|---|---|
| A. Operator-provisioned | Engineer/platform admin creates tenant + owner via a script or internal endpoint | Cheapest, no public signup surface, no abuse |
| B. Invite-only | Owner invites staff by email; tenant created by platform admin | Needs invitations + email delivery |
| C. Self-service signup | Anyone creates a tenant and becomes owner | Needs verification, rate limiting, anti-abuse, billing hooks later |

**Recommendation.** A for the pilot, then B. A commercial SaaS eventually needs C,
but launching a public signup before pricing and support exist creates obligations
nobody is staffed to meet.

**Current assumption in code:** option C — `POST /auth/register` creates the user,
the tenant and an `OWNER` membership in one transaction.

**Owner:** Product.

---

### Q2 — Can one user belong to more than one tenant?

**Why it matters.** It decides whether the session carries a single tenant id or a
list, whether a tenant switcher is needed, and whether `users.tenant_id` should
exist (currently it does not, see ADR-005).

**Options**

- One user, one tenant — simplest; add `UNIQUE (user_id)` on `memberships`.
- One user, many tenants — current schema; needs a tenant switcher and a session
  that records the *active* tenant.

**Recommendation.** Keep many-to-many in the schema (it is already correct) but
ship the UI for one active tenant per session. An accountant or a second branch
then becomes a UI change, not a migration.

**Owner:** Product.

---

### Q3 — What are the real roles and what may each do?

**Why it matters.** `owner` / `admin` / `member` are provisional. RBAC determines
whether a cashier can see cost prices, void an invoice, or open the cash drawer
report — all of which are financial controls, not UI preferences.

**Needed.** A permission matrix: role × action, for at least: sell, refund, void,
discount, view cost, edit product, adjust stock, view reports, manage users,
close day.

**Recommendation.** Start with three roles and an explicit permission list in code
(`can(role, "sales.refund")`), not scattered `if role == "owner"` checks.

**Owner:** Product + the pilot store owner.

---

### Q4 — Is a branch a first-class entity now?

**Why it matters.** The pilot has one branch, but stock, cashboxes and invoices are
branch-scoped in almost every retail system. Adding `branch_id` after inventory and
sales exist means backfilling every movement and rewriting every unique constraint.

**Options**

- Add `branches` in Sprint 02 and put `branch_id` on stock/cash tables from the
  start (nullable or defaulted to the single branch).
- Defer entirely and accept a painful migration.

**Recommendation.** Create `branches` in Sprint 02 with exactly one row per tenant
for the pilot. The table costs almost nothing; the retrofit costs weeks.

**Owner:** Product.

---

### Q5 — What happens when a user leaves?

**Why it matters.** Deleting a user would cascade-delete their memberships and
orphan the audit trail (once it exists). Deactivating keeps history.

**Recommendation.** `users.is_active = false` plus a revoked session. No hard
delete. Confirm whether the owner expects the account's email to be reusable
afterwards.

**Owner:** Product.

---

### Q6 — How is a password reset delivered?

**Why it matters.** Requires an email provider, a token table, and a public
endpoint. Without it, a locked-out cashier phones the owner.

**Recommendation.** For the pilot: owner-initiated reset (owner sets a temporary
password, user must change it on next login). Add email reset only when a
transactional email provider is chosen.

**Owner:** Product + Operations.

---

### Q7 — Session lifetime and device policy?

**Why it matters.** A POS terminal stays logged in all day on a shared machine. A
phone should not stay logged in for a month. This sets cookie expiry, idle timeout
and whether "remember this device" exists.

**Recommendation.** 12-hour absolute, 2-hour idle, one active session per device,
explicit logout. Adjust after watching real usage.

**Owner:** Product.

---

## B. Sprint 03 (products & inventory)

Sprint 03 was implemented on the **minimum defensible model**, because five of
these questions are still unanswered. Each section records what shipped, so the
next sprint can change it deliberately rather than discover it.

### Q8 — What defines an agricultural product?

**Status: partially answered — universal columns only.**

Shipped: `name_ar` (required), `name`, SKU, barcode, description, category,
brand, base unit, prices, minimum stock, `tracks_batches`. **Not** shipped:
active ingredient, concentration, formulation, target pest/crop, dose,
pre-harvest interval, safety class, germination rate, N-P-K composition.

Rationale: those fields are category-specific and must be confirmed against real
products. A 40-column sparse table would have been invented, not designed. The
schema supports adding a category-specific attribute table without touching
`products`.

**Still needed from the store owner.** Real examples for each category:
- Fertilizer: composition (N-P-K), weight, form (granular/liquid).
- Pesticide: active ingredient, concentration, formulation, target pest/crop,
  pre-harvest interval, safety precautions.
- Seed: variety, germination rate, season, supplier lot.
- Chemical/other: unit, hazard class.

**Recommendation.** One `products` table with a small set of universal columns plus
a category-specific attribute table, not a 40-column sparse table. Confirm against
5 real products per category before writing the migration.

**Owner:** Product + agronomist / store owner.

---

### Q9 — Which units exist, and are conversions needed?

**Status: answered for v1 — nine seeded units, explicit product conversions.**

Shipped: global `units_of_measure` (`piece`, `pack`, `box`, `bag`, `bottle` =
`count`; `kilogram`, `gram` = `mass`; `liter`, `milliliter` = `volume`), one base
unit per product, and explicit `product_unit_conversions` that must involve the
base unit. No conversion chain is inferred.

**Still open.** Whether purchase and sale units differ per product in practice,
and whether a packaging unit whose weight varies (a 25 kg sack that is sometimes
20 kg) must be modelled per delivery. Today it must be a conversion of the
product's base unit.

**Recommendation unchanged.** One base unit per product; arbitrary chains remain
out of scope.

**Owner:** Store owner.

---

### Q10 — Batch and expiry rules

**Status: partially answered — storage only, no enforcement.**

Shipped: `tracks_batches` per product, `product_batches` with optional
`expiry_date`, batch-level balance rejection when a movement would take a batch
negative, and duplicate batch numbers rejected per product.

**Not shipped:** FEFO allocation, expiry warnings, blocking the sale of expired
stock, or automatic expiry movements. Batch tracking is opt-in per product, not
mandatory by category.

**Still needed.** Is a batch mandatory for every product or only for chemicals? Is
FEFO enforced or advisory? Is selling expired stock blocked, warned, or allowed
with a reason? Are returns re-entered into the original batch?

**Recommendation.** Batch mandatory for chemicals/pesticides/seeds, optional for
hardware; expiry warning at 90/30/0 days; sale of expired stock blocked for
pesticides and allowed only with an explicit override for others.

**Owner:** Store owner + regulatory knowledge.

---

### Q11 — Negative stock: allowed or blocked?

**Status: answered for v1 — blocked, with no override.**

Shipped: the API and the balance projection both reject a negative product
balance, and a negative batch balance is rejected under the same row lock.
Concurrent debits cannot oversell (`test_concurrent_adjustments_cannot_oversell`).

**Still open.** Whether an owner-only override is needed at the counter. No
override exists, because an override without a costing and reconciliation model
would hide real shortages.

**Recommendation.** Keep blocking. If an override is approved, it must be its own
permission, require a reason, and be visible in the audit feed.

---

## C. Blocking Sprint 04–05 (sales & money)

### Q12 — Invoice numbering and legal requirements in Egypt

**Why it matters.** Sequential, gap-free invoice numbers are often legally required
and are per-tenant, per-branch, per-year. Retrofitting numbering onto existing
invoices is a data migration.

**Needed.** Is a specific format required? Must numbers be gapless? Is e-invoicing
(ETA) mandatory for this business size, and does it apply to B2C retail?

**Recommendation.** Per-tenant, per-branch, per-year counters allocated inside the
same transaction as the invoice. Confirm ETA obligations with an accountant before
integration work.

**Owner:** Store owner + accountant.

---

### Q13 — Tax handling

**Why it matters.** Whether prices are tax-inclusive changes every calculation,
receipt and report. It cannot be a display setting.

**Needed.** Is VAT applicable, at what rate, and are shelf prices inclusive? Are
there exempt categories (some agricultural inputs are exempt or zero-rated)?

**Recommendation.** Store a tax rate per product and a flag on the invoice; compute
from a single pricing function. Never compute tax in the UI.

**Owner:** Accountant.

---

### Q14 — Credit sales (آجَل): limits and enforcement

**Why it matters.** The core pain the product solves. It needs a customer ledger,
aging, and a rule for what happens when a customer exceeds their limit.

**Needed.** Is a credit limit per customer? Blocked or warned? Are partial payments
normal? Are payments allocated to a specific invoice or to the account balance?

**Recommendation.** Account-level balance with payment allocation to oldest invoice
first, overridable. Limit is a warning, not a block, for v1.

**Owner:** Store owner.

---

### Q15 — Returns and voids

**Why it matters.** A return can restock, quarantine, or discard. A void is not a
return. Both affect cash and stock differently, and both are fraud vectors.

**Needed.** Can a cashier void a completed invoice, or only an owner? Is a return
allowed without the original invoice? Does returned pesticide go back into stock?

**Recommendation.** Void only before the day is closed and only by owner/admin.
Returns require the original invoice, are a separate document, and restock only if
the batch is unopened.

**Owner:** Store owner.

---

### Q16 — Payment methods

**Why it matters.** Cash-only is simpler. InstaPay / Vodafone Cash / bank transfer
each need a reference and a reconciliation view.

**Recommendation.** Model `payment_method` as an enum with `cash` and `other`
(reference text) in v1; add specific methods when the store actually uses them.

**Owner:** Store owner.

---

### Q17 — Day close and cash reconciliation

**Why it matters.** A cashier shift that is never closed means the cashbox balance
drifts and nobody can explain a shortfall.

**Needed.** Is there a daily close? Is expected cash compared to counted cash? Who
may close?

**Recommendation.** A `cash_sessions` concept in Sprint 05: open with a float,
close with a counted amount and a variance. Variance is visible to the owner only.

**Owner:** Store owner.

---

## D. Non-blocking but must be answered before launch

| # | Question | Why it matters | Owner |
|---|---|---|---|
| Q18 | Production hosting: Neon region, API host, web host? | Latency to Egypt and data residency | Engineering |
| Q19 | Backup and point-in-time recovery target (RPO/RTO)? | Financial data loss tolerance | Product |
| Q20 | Error tracking / log retention vendor? | Diagnosing production faults | Engineering |
| Q21 | Offline POS behaviour during internet loss? | Egyptian connectivity is not guaranteed; offline-first is a major architectural fork | Product |
| Q22 | Arabic terminology glossary (e.g. صنف vs منتج, عميل vs زبون) | Inconsistent terms across screens confuse non-technical staff | Product |
| Q23 | Data retention and export on tenant suspension/cancellation? | Egyptian PDPL (Law 151/2018) obligations and customer trust | Product + legal |
| Q24 | Import of existing data — is there an Excel/notebook to migrate? | Determines whether an importer is needed in Sprint 02–03. No schema is invented before the real file is seen | Product |
| Q25 | Scale expectations: products, invoices/day, concurrent users | Sizing, indexing, and whether projections are needed | Product |
| Q26 | Supplier returns and damaged goods flow | Affects purchasing and stock valuation | Store owner |
| Q27 | **Stock valuation / costing method** — FIFO, weighted average, or standard cost? Is stock value reported at cost or at sale price? Is COGS needed per sale? | `unit_cost` is recorded on every inbound movement, but nothing computes a value, a margin or COGS. Reporting stock value or profit before this is answered would be a guess | Store owner + accountant |
| Q28 | Is a per-branch stock split needed in Sprint 04? | The ledger has no `branch_id`; adding it later is a schema and backfill change | Store owner |
| Q29 | Does the pilot need an audit viewer UI, or is the API feed enough? | `GET /audit` exists; no screen consumes it | Product |

---

## E. Assumptions currently embedded in code

These are **not** confirmed requirements. Each must be validated or changed.

| Assumption | Where | If wrong |
|---|---|---|
| A user may belong to multiple tenants | `memberships` has no `UNIQUE (user_id)` | Add the constraint, drop the switcher |
| Role vocabulary is `owner`/`manager`/`cashier`/`inventory_manager` | `membership_role` enum, `authorization/permissions.py` | Renaming or adding a role is an enum migration plus a policy row |
| Tenants are either `active` or `suspended` | `tenant_status` enum | Add values (e.g. `trial`, `closed`) |
| One branch per tenant for the pilot | No `branches` table | Add a `branch_id` to the ledger and its balances, with a backfill |
| Email is the login identifier | `users.email` unique | Add `username` or phone login |
| Arabic is the only locale | No i18n framework | Introduce `next-intl` |
| Money will be `NUMERIC(14,2)` EGP | `products.cost_price`, `sale_price` | Currency decision |
| One base unit per product, conversions only to/from it | `product_unit_conversions` | A chain resolver plus a migration of stored factors |
| Quantities are `NUMERIC(18,4)` in the base unit | `stock_movements.base_quantity`, `inventory_balances` | Precision or unit-model change, with a data migration |
| Cost is visible to OWNER only | `ROLE_PERMISSIONS`, `inventory.view_cost` | One-line policy change |
| Batch tracking is opt-in per product | `products.tracks_batches` | Making it mandatory per category is a data and UI change |
| `unit_cost` is informational, not a valuation | `stock_movements.unit_cost` | Q27 must be answered before any valuation feature |
| Local dev port 5433 is acceptable | `.env`, scripts | Change port, scripts and docs |
