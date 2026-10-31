# ZAIN AGRI

Multi-tenant SaaS for agricultural retail businesses in Egypt - fertilizers,
pesticides, seeds, agricultural chemicals and farming supplies.

Arabic-first, RTL, modular monolith.

## Repository layout

```
apps/web        Next.js 16 (App Router) + Tailwind v4, Arabic RTL shell
apps/api        FastAPI + SQLAlchemy 2 + Alembic
docs/           Architecture, security, decisions, open questions
infrastructure/ Database bootstrap SQL, future deployment config
scripts/        Local development helpers (PowerShell)
```

## Prerequisites

| Tool | Version |
|---|---|
| Node.js | 24+ |
| pnpm | 11+ |
| Python | 3.13 |
| uv | 0.12+ |
| PostgreSQL | 17 (binaries only; the server is not touched) |

## Quick start

```powershell
# 1. Local database - isolated cluster on port 5433, no Docker, no admin rights
./scripts/db-start.ps1
./scripts/db-init.ps1        # creates roles + databases, runs migrations, grants

# 2. Backend - separate terminal
cd apps/api
uv sync
uv run python run.py         # http://127.0.0.1:8000

# 3. Frontend - separate terminal
pnpm install
pnpm --filter web dev        # http://localhost:3000
```

`db-init.ps1` already applies migrations, so `uv run alembic upgrade head` is only
needed after pulling new revisions.

`uv run uvicorn app.main:app` will **not** work on Windows: psycopg's async driver
cannot use the default Proactor event loop. uvicorn 0.54 builds its loop through
an explicit factory, so `run.py` passes a selector-loop factory — that is why it
is the documented entry point.

Open <http://localhost:3000>. API docs at <http://localhost:8000/docs>.

Full instructions: [docs/architecture/DEVELOPMENT.md](docs/architecture/DEVELOPMENT.md).

## Verification

```powershell
# Backend
cd apps/api
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy app

# Frontend
pnpm --filter web typecheck
pnpm --filter web lint
pnpm --filter web build
```

## Architecture

- [System architecture](docs/architecture/SYSTEM_ARCHITECTURE.md)
- [Database design](docs/architecture/DATABASE_DESIGN.md)
- [Architecture decisions](docs/architecture/ARCHITECTURE_DECISIONS.md)
- [Product requirements](docs/architecture/PRODUCT_REQUIREMENTS.md)
- [Open questions](docs/architecture/OPEN_QUESTIONS.md)

## Security

- [Authentication](docs/security/AUTHENTICATION.md)
- [Tenant isolation](docs/security/TENANT_ISOLATION.md)
- [RBAC](docs/security/RBAC.md)

## Status

Sprint 02 — authentication and multi-tenant security. The identity/tenancy
schema, Row Level Security, JWT access tokens with rotating refresh sessions,
RBAC, tenant onboarding, and the Arabic auth UI (login, register, workspace
selection, security settings) exist. No business modules are implemented yet.
