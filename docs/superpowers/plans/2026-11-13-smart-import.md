# Smart Import Implementation Plan

> Executed natively, task by task, test first. Spec: `docs/superpowers/specs/2026-11-13-smart-import-design.md`

**Goal:** Upload any product sheet, get an assistant-proposed column mapping, preview, and create products with opening stock in one transaction.

**Stack:** FastAPI, openpyxl (read-only), Groq via the existing `GroqClient`, Next.js 16. No new database tables (the flow is stateless).

## Global Constraints

- Permissions: `products.create` AND `inventory.adjust` on every route; cost only with `inventory.view_cost`.
- Arabic user-facing errors in `app/core/messages_ar.py` (guard test enforces).
- Formulas never evaluated: `load_workbook(read_only=True, data_only=True)`.
- Data sent to the model: header text and up to 3 sample values per column; phone/email-like values redacted. Model output is data: only the fixed field names are accepted.
- Commit refuses rows with problems unless `skip_errors` is set (addition to the spec, stated in the UI).
- Row limit is set from a measured timing (target: well under the function time limit); the spec is updated if it differs from 2,000.
- Commits: `git -c user.name="ZAIN AGRI" -c user.email="dev@zain-agri.local"`, trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Hostile text in a header or cell (prompt injection, unknown field names) cannot change the mapping outside the allowed fields. Test in Task 3.
2. A second import of the same sheet creates nothing. Test in Task 4.
3. One bad row with `skip_errors` off creates nothing. Test in Task 4.
4. Generated SKUs never collide with existing ones or each other. Test in Task 4.
5. Arabic digits, currency text, thousands separators and totals rows. Test in Task 2.

## Tasks

1. **Split product creation** (`catalog/service.py`): `create_product_core` without commit; `create_product` unchanged in behaviour.
2. **Reading and cleaning** (`modules/importer/{parser,normalize}.py`, tests): xlsx/csv reading, header detection, numbers, text, units, totals rows.
3. **Mapping** (`modules/importer/mapping.py`, tests): header rules, redaction, model prompt and strict parsing, merge of rules and model.
4. **Service and routes** (`modules/importer/{service,schemas,router}.py`, `tests/test_importer.py`): analyze, preview, commit, template; timing measurement.
5. **Screen** (`apps/web/src/app/(app)/products/import/page.tsx`, `lib/importer.ts`, button on the products page).
6. **Mapping evaluation** (`tests/evals/importer_cases.json`, runner) over at least ten generated layouts, run live.
7. **Deploy** (no migration), live check.
