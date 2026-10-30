# ZAIN AGRI — Product Requirements

Status: Sprint 01 (foundation)
Last updated: 2026-10-30
Owner: Product / Architecture

> **Reading convention.** Every requirement carries a status:
> `[CONFIRMED]` — stated by the product owner.
> `[ASSUMPTION]` — inferred by engineering, not yet validated.
> `[OPEN]` — blocks further work; tracked in `OPEN_QUESTIONS.md`.

---

## 1. Product vision

**ZAIN AGRI is the operating system for agricultural retail businesses in Egypt.**

It replaces the notebook, the spreadsheet and the mental arithmetic that most
agricultural supply stores run on, with a system that tracks stock, batches,
expiry, credit and cash — in Arabic, at the speed of a counter sale.

The long-term goal is a commercial multi-tenant SaaS sold to many agricultural
retailers. The first customer is ZAIN, an existing single-branch store in Egypt.

`[CONFIRMED]` — stated in the Sprint 01 brief and the original product brief.

## 2. Target customers

| Segment | Description | Priority |
|---|---|---|
| Agricultural supply stores | Fertilizers, pesticides, seeds, chemicals, irrigation parts | Primary |
| Single-branch family businesses | 1–5 staff, owner-operated, low technical literacy | Primary |
| Multi-branch agri-retailers | 2+ branches, shared stock or transfers | Later |
| Agricultural cooperatives | Group purchasing, member credit | Not validated |

`[ASSUMPTION]` — segments 3 and 4 are inferred from the roadmap, not confirmed.

## 3. Business problems

| # | Problem | Evidence | Status |
|---|---|---|---|
| P1 | Stock is tracked in a notebook; nobody knows the real balance | Stated in brief | `[CONFIRMED]` |
| P2 | Batches and expiry of pesticides/chemicals are not tracked, causing expired stock to be sold | Inferred from the domain | `[ASSUMPTION]` |
| P3 | Customer credit (آجَل) is remembered verbally, leading to disputes and losses | Inferred from Egyptian retail norms | `[ASSUMPTION]` |
| P4 | Owner has no reliable view of daily profit | Inferred | `[ASSUMPTION]` |
| P5 | Agricultural products need domain metadata (active ingredient, dose, crop) that generic POS software lacks | Stated in brief | `[CONFIRMED]` |

## 4. Product modules

| Module | Sprint 01 | Roadmap |
|---|---|---|
| Identity & tenancy | Skeleton + RLS | Complete in Sprint 02 |
| Authentication & RBAC | Schema only | Sprint 02 |
| Products & categories | — | Sprint 02 |
| Agricultural product metadata | — | Sprint 03 |
| Units & conversions | — | Sprint 03 |
| Inventory & movement ledger | — | Sprint 03 |
| Batches & expiry | — | Sprint 03 |
| POS | — | Sprint 04 |
| Sales, invoices, returns | — | Sprint 04 |
| Customers & balances | — | Sprint 05 |
| Suppliers & balances | — | Sprint 05 |
| Purchasing | — | Sprint 05 |
| Cashbox & finance | — | Sprint 05 |
| Expenses & reporting | — | Sprint 06 |
| Analytics | — | Sprint 06 |
| Multi-branch | Schema-ready only | Sprint 06 |
| AI copilot / forecasting / RAG | — | Not scheduled |

`[CONFIRMED]` — module list from the product brief. Sprint assignment is an
engineering proposal `[ASSUMPTION]`.

## 5. MVP scope

**MVP = the smallest system that can run one real store's daily operations.**

In scope for the first usable release (not Sprint 01):

1. Log in as a tenant user.
2. Create products with units and categories.
3. Receive stock into batches with expiry dates.
4. Sell at the counter with stock deducted from the correct batch.
5. Record customer credit and partial payment.
6. See today's sales, profit and cash position.

Explicitly **out of scope** for MVP:

- AI features of any kind.
- Subscription billing and plan enforcement.
- Multi-currency.
- Mobile applications.
- E-commerce storefront.
- Supplier self-service portal.
- Accounting integration (e-invoicing is an open question, see `OPEN_QUESTIONS.md`).

## 6. Functional requirements

### Implemented in Sprint 01

| ID | Requirement | Status |
|---|---|---|
| FR-01 | The API exposes `GET /health` that returns without touching the database | Done |
| FR-02 | The API exposes `GET /health/ready` that fails with 503 when PostgreSQL is unreachable | Done |
| FR-03 | Every response carries an `X-Request-ID` header; logs are structured JSON | Done |
| FR-04 | Configuration is read from environment variables; the app refuses to start without `DATABASE_URL` | Done |
| FR-05 | Tenants, users and memberships exist with UUID keys, UTC timestamps and FK constraints | Done |
| FR-06 | A user may hold at most one membership per tenant | Done |
| FR-07 | Tenant-owned rows are protected by PostgreSQL RLS and fail closed without tenant context | Done |
| FR-08 | A non-superuser runtime role is used, so RLS is not bypassed | Done |
| FR-09 | The web app renders an Arabic RTL shell with design tokens and a responsive layout | Done |
| FR-10 | The web app exposes loading, error and not-found states | Done |

### Planned — Sprint 02

| ID | Requirement | Status |
|---|---|---|
| FR-11 | A user can log in with email and password | Not started |
| FR-12 | Sessions are server-side, revocable, and stored in httpOnly cookies | Not started |
| FR-13 | Tenant context is derived from the session, never from the request body | Not started |
| FR-14 | Passwords are hashed with Argon2id | Not started |
| FR-15 | Admin can create and list products | Not started |

## 7. Non-functional requirements

| ID | Requirement | Target | Status |
|---|---|---|---|
| NFR-01 | Tenant isolation | Zero cross-tenant reads/writes; enforced at DB level | Met (tests) |
| NFR-02 | Local setup | Reproducible without Docker | Met |
| NFR-03 | Type safety | `mypy --strict` clean, TypeScript `strict` clean | Met |
| NFR-04 | Health latency | `/health` < 50 ms; `/health/ready` < 200 ms locally | Met locally |
| NFR-05 | POS interaction latency | Product search < 150 ms at 10k SKUs | Not yet measurable |
| NFR-06 | Arabic-first | Every UI string Arabic; layout correct in RTL | Met (shell) |
| NFR-07 | Accessibility | Keyboard navigable, visible focus, AA contrast | Partial |
| NFR-08 | Auditability | Every financial/inventory mutation attributable to a user | Not started |
| NFR-09 | Data durability | Point-in-time recovery on production database | Not started |

## 8. User stories — Sprint 01

### US-01 — Health check

> As an operator, I want a readiness endpoint so that a load balancer stops
> routing traffic to an instance that lost its database.

**Acceptance criteria**

- `GET /health/ready` returns HTTP 200 and `{"status":"ok","database":"ok"}` when PostgreSQL is reachable.
- It returns HTTP 503 and `{"status":"unavailable"}` when PostgreSQL is not reachable.
- `GET /health` returns 200 even when PostgreSQL is down.

### US-02 — Tenant isolation

> As a tenant, I want certainty that no other business can read my data.

**Acceptance criteria**

- A query executed without tenant context returns zero rows from tenant-owned tables.
- A query executed with tenant A's context returns only tenant A's rows.
- Inserting a row for tenant B while tenant A is bound raises a database error.
- The runtime role is neither superuser nor `BYPASSRLS`.

### US-03 — Arabic shell

> As an Arabic-speaking owner, I want the application to open in Arabic, right-to-left,
> and look like professional software.

**Acceptance criteria**

- `<html lang="ar" dir="rtl">` on every page.
- Navigation, headings and body copy are Arabic.
- Layout mirrors correctly: sidebar on the right, content flows right-to-left.
- No fabricated business numbers are displayed.

## 9. Confirmed vs assumed — summary

| Confirmed | Assumed |
|---|---|
| Multi-tenant SaaS, Arabic-first | Tenant count and growth rate |
| Fertilizers/pesticides/seeds/chemicals retail | Exact product taxonomy |
| One branch, one owner initially | Staff roles and permissions |
| FastAPI + SQLAlchemy + PostgreSQL | Hosting provider for production |
| No AI in the first phase | Timeline for AI phase |
| Local PostgreSQL 17.5, no Docker required | Production will run PostgreSQL 17 |

Anything not in the "Confirmed" column must not be turned into schema without
validation. See `OPEN_QUESTIONS.md`.
