# ZAIN AGRI — Architecture Decisions

Status: Sprint 03
Last updated: 2026-10-31

> One record per decision that would be expensive to reverse, or that a new
> engineer would otherwise question. Rejected options are listed because "we
> didn't do X" is a decision too.

---

## ADR-001 — Modular monolith, not microservices

**Status:** Accepted · **Date:** 2026-10-30

**Context.** One pilot store, one branch, one owner. The roadmap covers POS,
inventory, purchasing, finance and reporting — domains that share entities
constantly (a sale needs stock, a batch, a customer and a price).

**Decision.** A single FastAPI application organised by business domain
(`app/modules/identity`, `tenancy`, `health`, and future `products`, `inventory`,
`sales`). One deployable, one database.

**Why.** With one team and one tenant, microservices would add network
boundaries, distributed transactions and deployment overhead in exchange for
isolation nobody needs yet. Shared entities across domains are a feature here,
not an accident.

**Consequences.** Module boundaries are conventions enforced by code review and
import direction, not by network calls. If a domain later needs independent
scaling (e.g. reporting), it can be extracted along its module boundary because
modules already talk through explicit functions rather than table joins across
boundaries.

---

## ADR-002 — Shared schema multi-tenancy with `tenant_id` + RLS

**Status:** Accepted · **Date:** 2026-10-30

**Context.** The product must serve many businesses. Three classic options:
database-per-tenant, schema-per-tenant, shared schema with a tenant column.

**Decision.** Shared schema. Every tenant-owned table carries `tenant_id`, and
PostgreSQL Row Level Security enforces the boundary in addition to application
filtering.

**Why.** Database-per-tenant multiplies migration and connection cost for a
business with a handful of tenants. Schema-per-tenant makes `search_path`
bugs catastrophic and complicates pooled connections. Shared schema is the
cheapest to operate and the easiest to reason about — provided isolation is
enforced by something stronger than developer discipline.

**Consequences.** A missing `WHERE tenant_id = ...` must not leak data, which is
exactly what RLS guarantees. Cross-tenant reporting becomes a deliberate,
privileged operation rather than an accident. Noisy-neighbour effects are
possible and accepted at this scale.

---

## ADR-003 — Two database roles: owner for migrations, non-superuser at runtime

**Status:** Accepted · **Date:** 2026-10-30

**Context.** RLS is silently ignored for superusers and for roles with
`BYPASSRLS`. It is also skipped for the table owner unless `FORCE ROW LEVEL
SECURITY` is set.

**Decision.** `zain` owns the schema and runs Alembic. `zain_app`
(`NOSUPERUSER NOBYPASSRLS`) serves all application traffic. Two URLs:
`MIGRATION_DATABASE_URL` and `DATABASE_URL`.

**Why.** A single role would make every isolation test meaningless: the app
could read every tenant's rows while the tests still passed, because the tests
would run under the same over-privileged role.

**Consequences.** DDL and runtime grants must be handled separately
(`grants.sql` + `ALTER DEFAULT PRIVILEGES`). A developer who runs Alembic
against the wrong URL gets a permission error — which is the correct outcome.
The first isolation test asserts the role's attributes so this cannot regress
quietly.

**Rejected.** `FORCE ROW LEVEL SECURITY` on the owner as an alternative — it
would prevent legitimate maintenance queries and does not remove the need for a
restricted runtime role.

---

## ADR-004 — Transaction-local tenant context via `set_config`

**Status:** Accepted · **Date:** 2026-10-30

**Context.** RLS policies need the current tenant. Options: a session variable
(`SET`), a transaction-local variable (`SET LOCAL`), or passing the tenant to
every query as a parameter (which defeats RLS, since the policy must read it).

**Decision.** `SELECT set_config('app.tenant_id', :tid, true)` inside the
request transaction. Policies read it with
`nullif(current_setting('app.tenant_id', true), '')::uuid`.

**Why.**
- `SET LOCAL` cannot take bind parameters, so it would require interpolating a
  UUID into SQL on a security boundary.
- Session-level `SET` persists on a pooled connection: one tenant's context could
  survive into the next request. Transaction-local is discarded at commit.
- `current_setting(..., true)` plus `nullif` makes "no context" mean "no rows"
  instead of an error or, worse, everything.

**Consequences.** Every request path that touches tenant data must set the
context before querying. Forgetting it fails closed. Long-running jobs must open
their own transaction per tenant rather than looping over tenants inside one.

---

## ADR-005 — `users` is global; tenancy is expressed by `memberships`

**Status:** Accepted, with reservations · **Date:** 2026-10-30

**Context.** The brief lists `users` alongside `tenants` and `memberships`, and
requires tenant-aware relationships. A user could plausibly belong to more than
one business (an accountant serving several stores), or be strictly
tenant-owned.

**Decision.** `users` has no `tenant_id`. Access to a tenant is granted by a
`memberships` row, unique per (tenant, user).

**Why.** Putting `tenant_id` on `users` makes a shared user impossible without
duplicating accounts and splitting their password history. The membership table
is the correct place for the relationship, and it is also where the role lives.

**Consequences.** `users` is **not** protected by RLS, so the application must
never return a user record without a membership check. This is the single
largest residual security risk in Sprint 01 and is recorded in
`OPEN_QUESTIONS.md` and the risk table in `SYSTEM_ARCHITECTURE.md`.

**If the business rule is "one user belongs to exactly one store"**, the correct
follow-up is a unique constraint on `user_id` in `memberships`, not a
`tenant_id` column on `users`.

---

## ADR-006 — psycopg 3 for both async runtime and sync migrations

**Status:** Accepted · **Date:** 2026-10-30

**Context.** SQLAlchemy needs an async driver for FastAPI and a driver for
Alembic (sync). The common pair is `asyncpg` + `psycopg2`.

**Decision.** `psycopg[binary]` 3 for both: `postgresql+psycopg://` async in the
app, the same URL sync in Alembic.

**Why.** One dependency, one URL format, one set of type behaviours. `asyncpg`
is faster on raw throughput, but Sprint 01 has no throughput problem and two
drivers means two sets of casting quirks (notably `uuid`, `numeric` and enums).

**Consequences.** On Windows, psycopg's async mode refuses the default
`ProactorEventLoop`. The selector policy must be installed before the loop is
created — encoded in `run.py` and `tests/conftest.py`. See ADR-007.

---

## ADR-007 — Explicit Windows event-loop policy in `run.py` and tests

**Status:** Accepted · **Date:** 2026-10-30

**Context.** `uvicorn app.main:app` on Windows raises
`psycopg.InterfaceError: Psycopg cannot use the 'ProactorEventLoop' to run in
async mode`.

**Decision.** A `run.py` entry point that calls
`asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())` at
module level on `win32`, then starts uvicorn with reload. The same policy is
installed at the top of `tests/conftest.py`.

**Why.** The policy must exist before uvicorn (or pytest-asyncio) creates the
loop, and uvicorn's reloader re-imports the module in a child process — module
level is the only place that covers both. Tests need it independently because
they do not go through `run.py`.

**Consequences.** The documented start command is `uv run python run.py`, not
`uvicorn ...`. A Linux deployment needs none of this; the guard is `win32`-only.

*Sprint 02 update:* uvicorn 0.54 stopped honouring the global event-loop policy
and builds its loop through `asyncio.run(..., loop_factory=...)`. `run.py` now
passes `loop="run:selector_loop_factory"` so the selector loop is still used;
setting the policy alone silently yields `503` readiness errors on Windows.

---

## ADR-008 — Opaque server-side sessions, not JWT

**Status:** Superseded by ADR-016 · **Date:** 2026-10-30

**Context.** The system will run a point of sale, where a fired cashier must lose
access immediately.

**Decision.** Opaque session ids stored in a database table, delivered in an
`httpOnly`, `Secure`, `SameSite=Lax` cookie. Not a JWT.

**Why.** A JWT cannot be revoked before expiry without a denylist, which
reintroduces the database lookup the JWT was meant to avoid. For a
low-traffic retail system, the lookup is free. `httpOnly` prevents token theft
via XSS; `localStorage` is not used.

**Consequences.** Session validation touches the database on every request, and
the sessions table becomes a hot path that needs an index and a cleanup job.

---

## ADR-009 — Design tokens in CSS (`@theme`), not a JS config

**Status:** Accepted · **Date:** 2026-10-30

**Context.** Tailwind v4 is CSS-first; `tailwind.config.js` is optional.

**Decision.** Brand palette, radii and semantic colours live in
`apps/web/src/app/globals.css` under `@theme`: `--color-brand-*`,
`--color-accent-*`, `--color-surface`, `--color-ink`, `--color-ink-muted`,
`--color-line`.

**Why.** One source of truth that is also the runtime CSS. A JS config would
duplicate values and require a build step to reach the browser. Semantic names
(`surface`, `ink`, `line`) keep dark mode or theming a token swap rather than a
component rewrite.

**Consequences.** No `tailwind.config.ts` exists. Designers read CSS, not JSON.
Utility classes such as `bg-surface` and `border-line` work directly.

---

## ADR-010 — RTL is structural, not a mirrored stylesheet

**Status:** Accepted · **Date:** 2026-10-30

**Context.** Arabic-first means RTL must be the default, not an afterthought
toggle.

**Decision.** `<html lang="ar" dir="rtl">` at the root, Arabic font
(IBM Plex Sans Arabic via `next/font`), and logical properties (`ms-*`, `me-*`,
`ps-*`, `pe-*`) instead of `left`/`right`.

**Why.** A mirrored "RTL theme" drifts from the LTR one on every change. Logical
properties make direction a document property, so components have exactly one
implementation.

**Consequences.** Physical direction utilities are avoided in components. A
future English locale would only need `dir="ltr"` and a locale switch, not a
second stylesheet.

---

## ADR-011 — No `next-intl` yet; single locale

**Status:** Accepted · **Date:** 2026-10-30

**Context.** Arabic is the only locale for the pilot. An i18n framework adds
routing, message files and a provider layer.

**Decision.** Arabic strings are inline. `next-intl` is not installed.

**Why.** Adding message extraction for one language produces indirection with no
user-visible benefit. When a second locale appears, the strings are already
isolated in a small number of components.

**Consequences.** Introducing i18n later is a real refactor, not a config change.
Accepted deliberately to keep Sprint 01 honest.

---

## ADR-012 — Defer libraries until a screen needs them

**Status:** Accepted · **Date:** 2026-10-30

**Context.** The confirmed stack includes shadcn/ui, React Hook Form, Zod and
Recharts.

**Decision.** Installed now: Next, React, Tailwind v4, `clsx`, `tailwind-merge`,
`class-variance-authority`, `lucide-react`. **Not** installed: shadcn/ui CLI
output, TanStack Query, Recharts, `next-intl`.

*Sprint 02 update:* React Hook Form, Zod and `@hookform/resolvers` were installed
when the first real forms (login, register, workspace creation) landed, which is
exactly the trigger this ADR defined.

**Why.** Sprint 01 has no forms, no client data fetching and no charts. Each of
those libraries would sit unused, and unused dependencies still get audited and
upgraded. The primitives that exist (`Card`, `Badge`, `cn`) follow shadcn/ui
conventions, so adopting shadcn components later is additive.

**Consequences.** The design system is hand-built for now. When the first form
lands, install shadcn/ui + React Hook Form + Zod together — they pay off in the
same screen.

---

## ADR-013 — Isolated local PostgreSQL cluster on port 5433

**Status:** Accepted · **Date:** 2026-10-30

**Context.** PostgreSQL 17.5 is installed at `C:\Program Files\PostgreSQL\17`,
but the cluster on 5432 has no Windows service, cannot be started without
elevation (`Access is denied`), has a stale `postmaster.pid`, and its password
is unknown.

**Decision.** Initialise a second cluster from the **same 17.5 binaries** at
`%LOCALAPPDATA%\zain-agri\pgdata`, listening on `127.0.0.1:5433`, with
`initdb -U zain --auth=trust --encoding=UTF8`. Managed by
`scripts/db-start.ps1`.

**Why.** Version parity with the future Neon PostgreSQL 17 is preserved, no
administrator rights are required, and the existing installation and its data
are untouched. Asking for a password we were not given, or resetting the
existing cluster, would have been a destructive guess.

**Consequences.** Two clusters may exist on one machine; port 5433 is not 5432,
so every command must specify `-p 5433` (scripts and `.env` do). `trust` auth is
acceptable for a loopback-only development cluster and must never be used in
production.

**Production.** Neon or managed PostgreSQL 17 with `scram-sha-256`, TLS and a
non-superuser application role.

---

## ADR-014 — Hand-written Next.js scaffold instead of `create-next-app`

**Status:** Accepted · **Date:** 2026-10-30

**Context.** `create-next-app` is interactive, picks its own versions, and writes
a starter page that is immediately deleted.

**Decision.** Every file in `apps/web` was written explicitly: `package.json`,
`tsconfig.json`, `next.config.ts`, `postcss.config.mjs`, `eslint.config.mjs`,
`globals.css`, `layout.tsx`, `page.tsx` and the state files.

**Why.** Deterministic content, no unused starter assets, no interactive prompt
in an automated run, and strict TypeScript from the first commit.

**Consequences.** Upgrades are manual. The ESLint config uses
`eslint-config-next`'s flat exports directly, because the `FlatCompat` shim
throws `TypeError: Converting circular structure to JSON` with ESLint 9 on
`eslint-config-next` 16.

---

## ADR-015 — Python pinned to 3.13, not 3.14

**Status:** Accepted · **Date:** 2026-10-30

**Context.** `uv` selected a downloaded CPython 3.14 when `requires-python` was
`>=3.13`, while the rest of the toolchain (mypy, pytest plugins) targets 3.13.

**Decision.** `requires-python = ">=3.13,<3.14"` plus `apps/api/.python-version`
containing `3.13`.

**Why.** An implicit interpreter upgrade in the middle of a sprint is an
unreviewed dependency change. The venv is now CPython 3.13.7.

**Consequences.** Upgrading to 3.14 becomes a deliberate change with a lockfile
refresh and a test run.

---

## ADR-016 — JWT access tokens + rotating opaque refresh tokens

**Status:** Accepted · **Date:** 2026-10-31 · **Supersedes:** ADR-008

**Context.** Sprint 02 requires access-token authentication and refresh-token
rotation. ADR-008 proposed opaque sessions only, on the argument that a JWT
cannot be revoked before expiry without a denylist.

**Decision.** A short-lived HS256 JWT (15 minutes) is the access credential,
sent as `Authorization: Bearer` and held in memory by the web client. The refresh
credential is an opaque random token, stored only as a SHA-256 digest, delivered
in an `HttpOnly`, `SameSite=Lax` cookie. Every access token carries a `sid` claim
naming its `refresh_sessions` row, and that row is checked on every request.

**Why.** The brief mandates access tokens; the revocation concern that drove
ADR-008 is answered by the per-request session check. The JWT therefore buys a
standard credential format and cheap claim parsing, while revocation stays
immediate. Putting the refresh token in an HttpOnly cookie and the access token
in memory means JavaScript can never read either long-lived secret.

**Consequences.** The JWT does not save a database round trip — the session check
is deliberate. Roles and tenant ids in the token are advisory only; authorisation
reloads membership from the database. ADR-008's sessions table survives as
`refresh_sessions`, with rotation, families and reuse detection layered on top.

---

## ADR-017 — Re-apply tenant context after every commit

**Status:** Accepted · **Date:** 2026-10-31

**Context.** `set_config('app.tenant_id', :id, true)` is transaction-local. A
service that commits mid-request (login, onboarding) would silently start its
next transaction with no tenant context, and RLS would return zero rows instead
of raising.

**Decision.** `set_tenant_context()` records the tenant id in `session.info` and
also sets it in the current transaction. A SQLAlchemy `after_begin` listener on
`Session` re-applies the setting for every subsequent transaction on that bound
session.

**Why.** The alternative — calling `set_tenant_context()` manually after every
commit — is exactly the kind of step a reviewer cannot verify and a refactor can
drop. Centralising it in the session lifecycle makes "bound session" mean what it
says.

**Consequences.** The hook only acts on sessions explicitly bound through
`set_tenant_context()`; a fresh pooled session remains unbound and fails closed.
Long-lived background jobs must still open one transaction per tenant.

---

## ADR-018 — One `SECURITY DEFINER` function for pre-tenant membership lookup

**Status:** Accepted · **Date:** 2026-10-31

**Context.** Login and tenant selection must list a user's workspaces while
`tenants` and `memberships` are protected by RLS and no tenant context exists yet.

**Decision.** Add `app_user_tenants(p_user_id uuid)`, `LANGUAGE sql`, `STABLE`,
`SECURITY DEFINER`, `SET search_path = public, pg_temp`, returning only the
caller-supplied user's memberships. Revoke `EXECUTE` from `PUBLIC`; grant it to
`zain_app` in `grants.sql`.

**Why.** The alternatives were worse: a permissive RLS branch for "my own
memberships" would weaken every query on the table; reading as the owner role
would put a superuser path in the request process; duplicating membership data
would create a second source of truth.

**Consequences.** There is now exactly one function the runtime role may execute,
and it must remain read-only. Any SQL injection in the app could call it with
another user id and enumerate workspace names — accepted because all queries are
parameter-bound, and documented in `TENANT_ISOLATION.md`. `PUBLIC` execute and a
pinned `search_path` are tested.

---

## ADR-019 — Units of measure are global reference data

**Status:** Accepted · **Date:** 2026-11-01

**Context.** Every tenant needs kilograms, grams, litres and pieces. Two options:
copy the unit rows per tenant, or keep one global vocabulary.

**Decision.** `units_of_measure` has no `tenant_id`. It is seeded by migration
`0004_catalog`, and `grants.sql` revokes `INSERT/UPDATE/DELETE` from `zain_app`.
A unit carries a `dimension` (`count`, `mass`, `volume`).

**Why.** A per-tenant copy produces divergent ids for the same physical unit, no
way to compare stock across workspaces, and a seeding bug per signup. Units are
not business data the store should own.

**Consequences.** Adding a unit is a migration, not an admin action. A future
custom unit (e.g. "sack") must either become global or introduce a tenant-owned
extension — and that decision needs the owner's real packaging.

---

## ADR-020 — Product conversions are explicit and must involve the base unit

**Status:** Accepted · **Date:** 2026-11-01

**Context.** A product may be bought in sacks and sold in kilograms. Chaining
conversions (bag → kg → g) is ambiguous when packaging varies.

**Decision.** `product_unit_conversions(tenant_id, product_id, from_unit_id,
to_unit_id, factor)` where `1 from = factor to`. At least one side must be the
product's base unit; both units must share a dimension. No chain is inferred.

**Why.** The ledger stores one quantity: `base_quantity`. Inferring a chain would
mean trusting a factor nobody typed for this product.

**Consequences.** A user who wants "1 sack = 25 kg" and "1 kg = 1000 g" records
the sack conversion against the base unit directly. Adding a chain resolver later
is additive, but existing rows stay valid.

---

## ADR-021 — Inventory is an append-only ledger with a same-transaction projection

**Status:** Accepted · **Date:** 2026-11-01

**Context.** Stock must be explainable months later, and must survive concurrent
adjustments from two devices.

**Decision.** `stock_movements` is append-only and authoritative;
`inventory_balances` is a projection written only by `inventory/service.py`, in
the same transaction, after `SELECT … FOR UPDATE` on the balance row. Negative
product and batch balances are rejected.

**Why.** A mutable stock number cannot answer "why is it 3?". A projection keeps
listing cheap without making the ledger optional. The row lock is the smallest
mechanism that makes the read-check-write sequence race-free per product.

**Consequences.** Corrections are compensating movements; there is no update or
delete path. Future modules (purchases, sales) must call `record_movement` rather
than write balances. Reconciliation is a query, not a repair endpoint.

---

## ADR-022 — Append-only is enforced by trigger *and* revoked privileges

**Status:** Accepted · **Date:** 2026-11-01

**Context.** "Do not update history" is a convention until the database enforces
it. The runtime role is the only role the request process can use.

**Decision.** `app_block_mutation()` raises on `UPDATE`/`DELETE` for
`stock_movements` and `audit_logs`; `grants.sql` additionally revokes
`UPDATE, DELETE, TRUNCATE` from `zain_app`.

**Why.** The two controls fail differently: the revoke stops the statement before
it runs, the trigger stops it even if a future grant is too broad. Migrations
still can — deliberately — drop the trigger.

**Consequences.** A data-fix script must run as the owner, with a migration, and
is therefore reviewable. A test asserts the runtime role is refused.

---

## ADR-023 — Audit is written inside the business transaction; reads are permission-gated

**Status:** Accepted · **Date:** 2026-11-01

**Context.** An audit trail that can be missing a row, or written after commit, is
not evidence.

**Decision.** `audit.record()` flushes only; the caller commits. Every catalog and
inventory mutation writes one row with actor, action, entity, before/after and
metadata. There is no write endpoint. `GET /audit` requires `audit.read`
(OWNER-only). Sensitive keys are dropped at any depth.

**Why.** Same-transaction writing means a business change cannot exist without its
trail, and a rejected operation leaves no row. Dropping keys rather than masking
them means a secret cannot be recovered from the column.

**Consequences.** Every new module takes an `audit` dependency. Volume grows with
mutations, so retention and partitioning are launch tasks.
