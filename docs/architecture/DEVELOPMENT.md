# ZAIN AGRI — Local Development

Status: Sprint 01
Last updated: 2026-10-30
Platform: Windows (PowerShell). macOS/Linux notes at the end.

---

## 1. Prerequisites

| Tool | Version used | Check |
|---|---|---|
| Node.js | 24+ | `node --version` |
| pnpm | 11.3.0 | `pnpm --version` |
| Python | 3.13.7 | `python --version` |
| uv | 0.12+ | `uv --version` |
| PostgreSQL | 17.5 binaries | `Test-Path "C:\Program Files\PostgreSQL\17\bin\postgres.exe"` |
| Git | any recent | `git --version` |

**Docker is not required and is not used.** The API, the web app and the database
all run as native Windows processes.

PostgreSQL 17 must be *installed* (for its binaries). It does **not** need to be
running, and its existing cluster on port 5432 is not touched.

## 2. First-time setup

```powershell
# from the repository root
Copy-Item .env.example .env

# 1. Database — isolated cluster on 127.0.0.1:5433
./scripts/db-start.ps1
./scripts/db-init.ps1

# 2. Backend
cd apps/api
uv sync
cd ../..

# 3. Frontend
pnpm install
```

`db-init.ps1` is idempotent: it starts the cluster, creates the `zain_app` role,
creates `zain_agri` and `zain_agri_test` if missing, runs `alembic upgrade head`,
and applies `infrastructure/db/grants.sql` to both databases.

### What `db-start.ps1` creates

| Item | Value |
|---|---|
| Data directory | `%LOCALAPPDATA%\zain-agri\pgdata` |
| Port | `5433`, bound to `127.0.0.1` only |
| Superuser | `zain`, `trust` auth (loopback development only) |
| Logs | `%LOCALAPPDATA%\zain-agri\pgdata\log\postgresql-YYYY-MM-DD.log` |

It uses the installed 17.5 binaries but a **separate** data directory, so it
cannot damage an existing installation. It does not need administrator rights.

## 3. Environment variables

All values live in `.env` at the repository root (git-ignored). `.env.example` is
the committed template with no real secrets.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `DATABASE_URL` | **yes** | — | Runtime SQLAlchemy URL, role `zain_app` |
| `MIGRATION_DATABASE_URL` | no | `DATABASE_URL` | Alembic URL, owner role. Set it; the runtime role cannot run DDL |
| `TEST_DATABASE_NAME` | no | `zain_agri_test` | Database rebuilt per test session |
| `ENVIRONMENT` | no | `development` | `development` / `test` / `production`; hides `/docs` in production |
| `LOG_LEVEL` | no | `INFO` | Root log level |
| `DB_ECHO` | no | `false` | Log every SQL statement |
| `DB_POOL_SIZE` | no | `5` | SQLAlchemy pool size |
| `DB_MAX_OVERFLOW` | no | `5` | Extra connections above the pool |
| `DB_POOL_RECYCLE_SECONDS` | no | `1800` | Recycle connections after N seconds |
| `CORS_ORIGINS` | no | empty | Comma-separated allow-list. No wildcards |
| `NEXT_PUBLIC_API_BASE_URL` | no | `http://localhost:8000` | Browser-visible API origin (read by the web app) |

The API refuses to start without `DATABASE_URL` — that is intentional, not a bug.

**Never** put a secret in a `NEXT_PUBLIC_*` variable; it is embedded in the
browser bundle.

## 4. Running

Three terminals.

```powershell
# Terminal 1 — database (safe to re-run; exits if already listening)
./scripts/db-start.ps1

# Terminal 2 — API
cd apps/api
uv run python run.py
# → http://127.0.0.1:8000  ·  docs at /docs

# Terminal 3 — web
pnpm --filter web dev
# → http://localhost:3000
```

**Do not use `uv run uvicorn app.main:app` directly on Windows.** psycopg's async
driver rejects the default Proactor event loop; `run.py` installs the selector
policy before uvicorn creates the loop. See ADR-007.

For a production-shaped frontend check:

```powershell
pnpm --filter web build
pnpm --filter web start
```

## 5. Database workflow

```powershell
cd apps/api

# Apply all migrations
uv run alembic upgrade head

# Create a migration after changing a model
uv run alembic revision --autogenerate -m "add products"
#   → review the generated file before committing it

# Roll back one revision
uv run alembic downgrade -1

# Current revision
uv run alembic current
```

Rules that have already bitten us once:

- **Import the model module in `alembic/env.py`.** `--autogenerate` only sees
  tables whose modules have been imported. A new module that is not imported
  produces an empty migration.
- **New tables need grants.** `ALTER DEFAULT PRIVILEGES` covers tables created
  by `zain` in `public`, so running `db-init.ps1` after a migration is the safe
  habit.
- **Re-run grants explicitly** after any migration that creates a table outside
  the default path:
  ```powershell
  & "C:\Program Files\PostgreSQL\17\bin\psql.exe" -h 127.0.0.1 -p 5433 -U zain `
      -d zain_agri -f infrastructure\db\grants.sql
  ```

### Reset the development database

Destroys all local data. Never run against anything but `127.0.0.1:5433`.

```powershell
$psql = "C:\Program Files\PostgreSQL\17\bin\psql.exe"
& $psql -h 127.0.0.1 -p 5433 -U zain -d zain_agri -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
cd apps/api
uv run alembic upgrade head
cd ../..
& $psql -h 127.0.0.1 -p 5433 -U zain -d zain_agri -f infrastructure\db\grants.sql
```

## 6. Verification

Run these before claiming any change works.

```powershell
# Backend
cd apps/api
uv run pytest -q                  # 9 passed at Sprint 01
uv run ruff check .               # All checks passed
uv run ruff format --check .
uv run mypy app                   # Success: no issues found in 18 source files

# Frontend
pnpm --filter web typecheck
pnpm --filter web lint
pnpm --filter web build

# Live endpoints
(Invoke-RestMethod http://127.0.0.1:8000/health)       | ConvertTo-Json -Compress
(Invoke-RestMethod http://127.0.0.1:8000/health/ready) | ConvertTo-Json -Compress
```

Expected:

```json
{"status":"ok","service":"ZAIN AGRI API","version":"0.1.0","environment":"development"}
{"status":"ok","database":"ok","environment":"development"}
```

Tests rebuild the `zain_agri_test` schema from the real Alembic migrations on
every session — they never use `Base.metadata.create_all()`.

## 7. Project layout

```
apps/api
├── app/
│   ├── core/                 config, logging, errors, middleware
│   ├── infrastructure/db/    base, session (lazy engine)
│   ├── modules/
│   │   ├── health/           router
│   │   ├── identity/         Tenant, User, Membership
│   │   └── tenancy/          set_tenant_context, current_tenant_id
│   └── main.py               create_app()
├── alembic/
│   ├── env.py
│   └── versions/0001_identity_foundation.py
├── tests/                    conftest, health, tenant isolation
├── run.py                    Windows-safe uvicorn entry point
└── pyproject.toml            deps, ruff, mypy, pytest

apps/web/src
├── app/                      layout, page, loading, error, not-found, globals.css
├── components/               brand, shell/, dashboard/, ui/
└── lib/utils.ts              cn()
```

## 8. Troubleshooting

### `psycopg cannot use the 'ProactorEventLoop'`

You started uvicorn directly. Use `uv run python run.py`. For scripts, install
the policy first:

```python
import asyncio, sys
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```

### PostgreSQL will not start / `Access is denied` / stale `postmaster.pid`

You are pointing at the existing 5432 cluster. Do not fight it. Use
`./scripts/db-start.ps1`, which runs its own cluster on 5433 from a separate data
directory and needs no elevation.

### `connection refused` on 5433

```powershell
& "C:\Program Files\PostgreSQL\17\bin\pg_ctl.exe" status -D "$env:LOCALAPPDATA\zain-agri\pgdata"
Get-Content "$env:LOCALAPPDATA\zain-agri\pgdata\log\postgresql-$(Get-Date -Format yyyy-MM-dd).log" -Tail 30
```

### `ERR_PNPM_IGNORED_BUILDS` / `unrs-resolver`

```powershell
pnpm approve-builds unrs-resolver
pnpm install
```

`allowBuilds` in `pnpm-workspace.yaml` records the approval so CI and fresh
clones are non-interactive.

### pnpm registry timeouts / `ERR_PNPM_META_FETCH_FAIL`

The registry was slow on the original network. `.npmrc` raises timeouts; adding
`--network-concurrency 4` avoids parallel-request throttling.

### `invalid input value for enum tenant_status: "ACTIVE"`

SQLAlchemy is sending the enum *name* instead of its *value*. Every native enum
column needs
`values_callable=lambda e: [m.value for m in e]`. Already applied to
`tenant_status` and `membership_role`.

### Queries return zero rows unexpectedly

That is RLS failing closed: the transaction has no `app.tenant_id`. Call
`set_tenant_context(session, tenant_id)` inside the transaction before querying.
It is the intended behaviour, not a bug.

### PowerShell reports `Exit code 1` but the tool printed success

PowerShell treats anything a native command writes to stderr as an error record.
`uv`, `pnpm` and `git` write progress to stderr. Read the actual text before
concluding a command failed.

### `next build` rewrites `tsconfig.json`

Expected on first build (Next adds `.next/dev/types` and sets `jsx: react-jsx`).
Commit the result.

## 9. Code conventions

| Area | Convention |
|---|---|
| Python formatting | `ruff format`, line length 100, target 3.13 |
| Python lint | `ruff check` with `E,F,I,B,ASYNC,S,C4,SIM,UP`; `S101` ignored |
| Typing | `mypy --strict`; no `Any` without a reason |
| Imports | Absolute (`from app.modules...`), never relative |
| DB access | Async sessions only; never create an engine at import time |
| Tenant data | Always `set_tenant_context` before querying tenant-owned tables |
| Frontend | TypeScript strict + `noUncheckedIndexedAccess` |
| Styling | Tailwind utilities with `@theme` tokens; logical properties for RTL |
| Commits | Imperative subject, explain the *why* in the body |

## 10. macOS / Linux

The application code is portable; only the development scripts are
PowerShell-specific.

- `run.py` still works (the `win32` guard is a no-op).
- Replace `scripts/db-start.ps1` with an `initdb` + `pg_ctl start` for a local
  cluster, or point `DATABASE_URL` at an existing PostgreSQL 17.
- `run.py`'s selector policy is unnecessary; psycopg uses the default loop.

## 11. Production direction

Not implemented in Sprint 01. When it is:

- Managed PostgreSQL 17 (Neon or equivalent) with TLS and `scram-sha-256`.
- A dedicated non-superuser application role, as locally.
- Migrations run as a separate release step with the owner role — never at app
  startup, and never concurrently from multiple instances.
- Secrets from the platform's secret store, not `.env`.
- `/docs` and `/openapi.json` are already disabled when
  `ENVIRONMENT=production`.
