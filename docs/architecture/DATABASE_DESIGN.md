# ZAIN AGRI — Database Design

Status: Sprint 01
Last updated: 2026-10-30
Engine: PostgreSQL 17.5 (local dev cluster, port 5433)

---

## 1. Principles

| # | Principle | Consequence |
|---|---|---|
| 1 | PostgreSQL is the source of truth | Constraints live in the database, not only in Python |
| 2 | Every tenant-owned row carries `tenant_id` | Isolation is a data property, not a query convention |
| 3 | Tenant isolation is enforced twice | Application filter **and** Row Level Security |
| 4 | The application never runs as the schema owner | RLS cannot be bypassed by the code path that serves requests |
| 5 | Schema changes only through Alembic | No manual DDL in any environment |
| 6 | UTC everywhere | `TIMESTAMPTZ`, written as UTC, rendered in Africa/Cairo |
| 7 | No speculative tables | Only what Sprint 01 can justify exists today |

## 2. Roles and connections

Two roles, two URLs, on purpose.

| Role | Used by | Attributes | Purpose |
|---|---|---|---|
| `zain` | Alembic, `scripts/db-init.ps1` | superuser, owns `public` | migrations and bootstrap only |
| `zain_app` | FastAPI runtime, tests | `NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE` | all application queries |

```
DATABASE_URL           → zain_app   (app + tests)
MIGRATION_DATABASE_URL → zain       (Alembic only)
```

If the runtime role were a superuser, or owned the tables it queries, PostgreSQL
would skip every policy and the isolation tests would be theatre. That is why the
first isolation test asserts `rolsuper = false` and `rolbypassrls = false`.

**Grants.** `infrastructure/db/grants.sql` runs after migrations and grants
`SELECT, INSERT, UPDATE, DELETE` on all tables plus `ALTER DEFAULT PRIVILEGES`, so
tables created by future migrations are covered automatically. Grants are kept
out of Alembic because role names differ per environment.

## 3. Schema

```mermaid
erDiagram
    TENANTS ||--o{ MEMBERSHIPS : "has"
    USERS   ||--o{ MEMBERSHIPS : "belongs to"

    TENANTS {
        uuid id PK
        varchar(200) name
        varchar(80) slug UK
        tenant_status status
        timestamptz created_at
        timestamptz updated_at
    }

    USERS {
        uuid id PK
        varchar(320) email UK
        varchar(255) password_hash
        varchar(200) full_name
        boolean is_active
        timestamptz last_login_at
        timestamptz created_at
        timestamptz updated_at
    }

    MEMBERSHIPS {
        uuid id PK
        uuid tenant_id FK
        uuid user_id FK
        membership_role role
        timestamptz created_at
    }
```

Three tables. Nothing else is justified yet.

### 3.1 `tenants`

| Column | Type | Constraints |
|---|---|---|
| `id` | `uuid` | PK `pk_tenants`, generated in the application |
| `name` | `varchar(200)` | NOT NULL |
| `slug` | `varchar(80)` | NOT NULL, `uq_tenants_slug` |
| `status` | `tenant_status` | NOT NULL, default `'active'` |
| `created_at` | `timestamptz` | NOT NULL, default `now()` |
| `updated_at` | `timestamptz` | NOT NULL, default `now()` |

`slug` is the human-readable identifier (subdomain, support lookup). It is
unique globally, so it is also a first-come reservation across the platform.

`status` is a native enum: `active`, `suspended`. Suspension is a business state,
not a delete. There is no soft-delete column — an actual deletion path is a
Sprint 02+ decision (see `OPEN_QUESTIONS.md`).

### 3.2 `users`

| Column | Type | Constraints |
|---|---|---|
| `id` | `uuid` | PK `pk_users` |
| `email` | `varchar(320)` | NOT NULL, `uq_users_email` |
| `password_hash` | `varchar(255)` | NOT NULL |
| `full_name` | `varchar(200)` | NOT NULL |
| `is_active` | `boolean` | NOT NULL, default `true` |
| `last_login_at` | `timestamptz` | NULL |
| `created_at` | `timestamptz` | NOT NULL, default `now()` |
| `updated_at` | `timestamptz` | NOT NULL, default `now()` |

Index `ix_users_email_lower` is unique on `lower(email)`, so
`Owner@Store.com` and `owner@store.com` cannot both exist. The application
normalises to lowercase before insert; the functional index is the backstop.

`password_hash` stores an Argon2id hash (Sprint 02). Plaintext passwords are
never written, logged, or accepted by any column here.

**`users` is deliberately not tenant-scoped.** A person can be a member of more
than one tenant, so a `tenant_id` on this table would be wrong by construction.
Access is mediated by `memberships`, and the API must never expose a user record
outside a membership check. This is the least settled part of the model and is
tracked in `OPEN_QUESTIONS.md`.

### 3.3 `memberships`

| Column | Type | Constraints |
|---|---|---|
| `id` | `uuid` | PK `pk_memberships` |
| `tenant_id` | `uuid` | NOT NULL, FK → `tenants.id` ON DELETE CASCADE |
| `user_id` | `uuid` | NOT NULL, FK → `users.id` ON DELETE CASCADE |
| `role` | `membership_role` | NOT NULL, default `'member'` |
| `created_at` | `timestamptz` | NOT NULL, default `now()` |

- `uq_memberships_tenant_user` — one membership per (tenant, user).
- `ix_memberships_tenant_id`, `ix_memberships_user_id` — both directions are queried
  (list a tenant's staff; resolve a user's tenants).

`membership_role` is a native enum: `owner`, `admin`, `member`. **Provisional** —
the real role vocabulary is a business decision (see `OPEN_QUESTIONS.md`). Adding
a value later is an `ALTER TYPE ... ADD VALUE` migration.

The cascade means deleting a tenant or a user removes its memberships. It does
**not** delete the user's other memberships, which is the intended behaviour.

## 4. Row Level Security

Both tenant-owned tables (`tenants`, `memberships`) have RLS enabled.

```sql
-- tenants
USING      (id = nullif(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (id = nullif(current_setting('app.tenant_id', true), '')::uuid)

-- memberships
USING      (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
```

Three properties matter more than the SQL:

1. **`current_setting(..., true)` returns NULL when unset.** Comparing anything to
   NULL is unknown, so the policy rejects every row. Unbound queries return zero
   rows — never all rows.
2. **`nullif(..., '')` handles the reset case.** `set_config(..., '')` is how the
   context is cleared; a plain cast of `''` to `uuid` would raise instead.
3. **`WITH CHECK` covers writes.** A tenant cannot insert a membership addressed
   to a different tenant; the database raises
   `new row violates row-level security policy`.

`tenants` uses `id = ...` because the tenant's own row is its tenancy scope. A
tenant can therefore read and update only itself, which is what the API needs.

`users` has no policy: it is not tenant-owned. See §3.2 and `OPEN_QUESTIONS.md`.

## 5. Tenant context protocol

```python
async def set_tenant_context(session, tenant_id):
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
    )
```

- `set_config(..., true)` is **transaction-local**. It is discarded at commit or
  rollback, so a pooled connection cannot carry one tenant's identity into the
  next request.
- The value is bound as a parameter. `SET LOCAL app.tenant_id = ...` cannot take
  bind parameters and would require string interpolation — not acceptable on a
  security boundary.
- The tenant id must come from the authenticated server-side identity. A
  `tenant_id` in a request body, query string or header is ignored by design.
- Every request that touches tenant data must set the context **inside its
  transaction**, before the first query.

Failing to set the context is fail-closed: the request sees nothing, and it
breaks loudly in development rather than leaking silently.

## 6. Migrations

| Rule | Detail |
|---|---|
| Tool | Alembic (`apps/api/alembic`) |
| URL | `MIGRATION_DATABASE_URL`, resolved in `alembic/env.py` |
| Naming | `NNNN_slug`, explicit revision ids (`0001_identity`) |
| DDL inside a migration | Always via `op.*`, plus `op.execute` for policies |
| Enum creation | Explicit `postgresql.ENUM(..., create_type=False)` + `.create(bind)` |
| Downgrades | Written, not stubbed — including dropping policies |

The first migration is `0001_identity`: enums, three tables, indexes, RLS
policies. It is applied to both `zain_agri` and `zain_agri_test`.

`alembic/env.py` imports `app.modules.identity.models` so `Base.metadata` is
populated. Any new model module must be imported there before `--autogenerate`
will see it.

## 7. Connection management

| Setting | Value | Note |
|---|---|---|
| Driver | `psycopg` 3 | async for the app, sync for Alembic |
| Pool | `pool_size=5`, `max_overflow=5` | per process |
| `pool_pre_ping` | on | survives a restarted cluster |
| `pool_recycle` | 1800 s | avoids stale server-side connections |
| Isolation | PostgreSQL default (READ COMMITTED) | sufficient for current writes |
| Session | `expire_on_commit=False`, `autoflush=False` | explicit, predictable |

The engine is created lazily through `lru_cache`, so importing `app.main` opens
no sockets. `dispose_engine()` runs on application shutdown and clears the caches.

Test fixture rebuilds the schema per session: drop `public`, recreate, migrate,
apply grants. Tests therefore run against the real migration, not
`create_all()` — a schema drift between models and migrations cannot hide.

## 8. Test database

`zain_agri_test` is recreated per test session (schema only, database kept).
Credentials match the app role, so isolation tests run under exactly the same
privileges as production requests.

## 9. Deliberately absent

Not forgotten — excluded because nothing in Sprint 01 justifies the shape:

- Products, categories, units, batches, stock movements.
- Sales, invoices, payments, cashbox.
- Customers, suppliers, branches.
- Audit log, `created_by` columns.
- Soft deletes, `deleted_at`.
- Sessions table for auth (Sprint 02, once login flows are approved).
- Partitioning, materialised views, read replicas.

## 10. Known limitations

| Limitation | Impact | Plan |
|---|---|---|
| `updated_at` is set by the ORM (`onupdate`), not a trigger | Raw SQL updates leave it stale | Add a `moddatetime`/trigger migration when admin tooling appears |
| `memberships` has no `updated_at` | A role change is not timestamped | Add with the audit log in Sprint 02 |
| No audit trail | Mutations are unattributable | Audit table alongside sales/finance |
| `users` is not RLS-protected | Requires application-level discipline | Revisit in Sprint 02 with the auth design |
| Role enum is provisional | Possible rename migration | Confirm vocabulary before coding RBAC |
| Case-insensitive email relies on app normalisation + functional index | Two indexes on the same column | Acceptable; simplifies to `citext` or a normalised column later if needed |
