# Stocktake Implementation Plan

> Executed natively, task by task, test first. Spec: `docs/superpowers/specs/2026-11-13-stocktake-design.md`

**Goal:** Storekeepers count shelves, review differences and post all corrections in one confirmed step.

**Stack:** FastAPI, SQLAlchemy async, Alembic, RLS, Next.js 16.

## Global Constraints

- Every tenant table has RLS exactly like `0007_backup.py`; routes require `Permission.INVENTORY_ADJUST` (history/header: `INVENTORY_READ`).
- Arabic user-facing errors in `app/core/messages_ar.py` (guard test enforces).
- Quantities are `Decimal`, rounded with `_q4`; base-unit conversion only through `_conversion_factor`.
- Western digits, ledger look, no em-dashes in UI copy.
- Commits: `git -c user.name="ZAIN AGRI" -c user.email="dev@zain-agri.local"`, trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Movement between count and apply is preserved (difference rule). Test in Task 3.
2. Apply that fails on one product posts nothing. Test in Task 3.
3. Blind mode never leaks the system quantity of an uncounted line. Test in Task 3.
4. A batch-tracked product counted per batch. Test in Task 3.
5. Cancelled/applied stocktakes cannot be changed. Test in Task 3.

## Tasks

1. **Stock-logic fixes** (`inventory/service.py`, `models.py`, `schemas.py`): split `record_movement` into a non-committing core `apply_movement`; allow `damage`/`expiry` (outbound); opening balance once per batch; test balance == sum of movements.
2. **Tables** (`alembic/versions/0009_stocktake.py`, `modules/stocktake/models.py`): `stocktakes`, `stocktake_lines`, RLS, one open per tenant.
3. **Service and routes** (`modules/stocktake/{service,router,schemas}.py`, `tests/test_stocktake.py`): start, lines, save line, review, apply, cancel.
4. **Screens** (`apps/web/src/app/(app)/inventory/stocktake/**`, `lib/stocktake.ts`, «جرد» button on inventory page).
5. **Deploy**: migrate Neon (script reading `.env.neon-owner`), merge, push, live check.
