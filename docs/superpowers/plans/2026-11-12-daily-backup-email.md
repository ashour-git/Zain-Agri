# Daily Backup Email Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each shop owner can confirm an email address and receive a nightly Excel copy of their own shop's data.

**Architecture:** A new API module `app/modules/backup/` owns two RLS-scoped tables, an Excel builder, a Gmail SMTP mailer behind a protocol, owner-only settings routes and a cron-secret route that Vercel Cron calls nightly. Cross-tenant discovery goes through two narrow `SECURITY DEFINER` functions; all shop data is read inside that shop's tenant context. The web app gets a settings page, a public confirm page, a nav item and a failure banner.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, PostgreSQL RLS, openpyxl, smtplib, Next.js 16, Vercel Cron.

**Spec:** `docs/superpowers/specs/2026-11-12-daily-backup-email-design.md`

## Global Constraints

- New runtime dependencies go in `[project].dependencies` (Vercel installs nothing else): `openpyxl>=3.1`, `tzdata>=2024.1` (Windows has no system tz database; `ZoneInfo("Africa/Cairo")` fails without it).
- "Today" always means the Cairo date: `datetime.now(ZoneInfo("Africa/Cairo")).date()`.
- Cron: `"crons": [{"path": "/api/v1/internal/backups/run", "schedule": "0 1 * * *"}]`.
- Owner-only routes use `require_permission(Permission.TENANT_SETTINGS_MANAGE)`.
- Confirmation token: `secrets.token_urlsafe(32)`, store `hashlib.sha256(token).hexdigest()` only, 24 h expiry, single use.
- Manual sends: max 3 per shop per Cairo day. Size cap 20 MB (`20 * 1024 * 1024`). Run deadline 240 s. Retry once after 30 s.
- Every English error message raised gets an Arabic entry in `app/core/messages_ar.py` (`tests/test_arabic_errors.py` enforces).
- Logs never contain email addresses or file contents.
- Copy is Arabic, no em-dashes or middle dots in UI text; Western digits.
- Secrets (`GMAIL_USER`, `GMAIL_APP_PASSWORD`, `CRON_SECRET`) only via env; never in code, files or chat.
- Commits: `git -c user.name="ZAIN AGRI" -c user.email="dev@zain-agri.local" commit`, message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Run API commands from `apps/api` with `uv run`; web from `apps/web` with `pnpm`.

## Review Focus

1. **Owner changes the address while a nightly run is mid-way.** The send must go to the address read at claim time and must not go to a still-pending new address. Test in Task 6: `test_run_skips_shop_whose_address_went_back_to_pending`.
2. **Confirm link opened twice, or after a newer link was issued.** Second use and the older token both refused with the same Arabic message. Test in Task 4: `test_old_token_dies_when_address_changes`.
3. **Shop with zero products and zero movements.** File still builds, every sheet has headers, «عن الملف» shows zeros. Test in Task 3: `test_empty_shop_builds_valid_workbook`.
4. **Arabic and Excel-hostile text in names** (`=SUM(...)` as a product name, leading `+`/`-`/`@`). Must be written as text, not a formula. Test in Task 3: `test_formula_like_text_is_not_a_formula`.
5. **Gmail not configured in production.** Owner can still save and see «الإرسال غير مُعدّ»; nothing crashes. Test in Task 4: `test_save_without_mailer_config_reports_not_configured`.

---

### Task 1: Dependencies, settings and cron config

**Files:**
- Modify: `apps/api/pyproject.toml` (dependencies), `apps/api/uv.lock`
- Modify: `apps/api/app/core/config.py` (Settings fields)
- Modify: `vercel.json`
- Test: `apps/api/tests/test_deploy_config.py`

**Interfaces:**
- Produces: `Settings.gmail_user: str | None = None`, `Settings.gmail_app_password: SecretStr | None = None`, `Settings.cron_secret: SecretStr | None = None`, `Settings.public_app_url: str = "http://localhost:3000"`, property `Settings.mail_configured -> bool` (both gmail fields set).

- [ ] **Step 1: Write the failing test** in `test_deploy_config.py`:

```python
def test_nightly_backup_cron_is_scheduled() -> None:
    config = json.loads(VERCEL_JSON.read_text(encoding="utf-8"))
    assert config.get("crons") == [
        {"path": "/api/v1/internal/backups/run", "schedule": "0 1 * * *"}
    ]
```

- [ ] **Step 2:** `uv run pytest tests/test_deploy_config.py -v` → FAIL (`None != [...]`).
- [ ] **Step 3:** Add `crons` to `vercel.json` after `regions`; `uv add openpyxl tzdata`; add the Settings fields above.
- [ ] **Step 4:** `uv run pytest tests/test_deploy_config.py tests/test_runtime_dependencies.py -v` → PASS.
- [ ] **Step 5:** Commit `build: openpyxl, tzdata and nightly backup cron`.

### Task 2: Tables, RLS and the two definer functions

**Files:**
- Create: `apps/api/alembic/versions/0007_backup.py`
- Create: `apps/api/app/modules/backup/__init__.py`, `apps/api/app/modules/backup/models.py`
- Modify: `infrastructure/db/grants.sql` (grant EXECUTE on both functions, same block style as `app_user_tenants`)
- Modify: model registry wherever `app/modules/*/models.py` are imported for metadata (follow `audit`)
- Test: `apps/api/tests/test_backup_isolation.py`

**Interfaces:**
- Produces:
  - `class BackupStatus(StrEnum): PENDING="pending"; ACTIVE="active"; STOPPED="stopped"`
  - `class DeliveryKind(StrEnum): NIGHTLY="nightly"; MANUAL="manual"`
  - `class DeliveryStatus(StrEnum): CLAIMED="claimed"; SENT="sent"; FAILED="failed"`
  - `BackupSettings` table `backup_settings`: `tenant_id` PK/FK cascade, `email`, `status`, `confirm_token_hash`, `confirm_expires_at`, `confirmed_at`, `updated_by` (FK users, set null), `created_at`, `updated_at`.
  - `BackupDelivery` table `backup_deliveries`: `id` uuid PK, `tenant_id`, `delivery_date` date, `kind`, `status`, `email`, `error_reason_ar`, `file_bytes`, `row_counts` jsonb, `created_at`, `updated_at`. Partial unique index `uq_backup_deliveries_nightly` on `(tenant_id, delivery_date) WHERE kind = 'nightly'`. Index `(tenant_id, created_at)`.
  - SQL `app_backup_due_tenants(p_date date) RETURNS TABLE (tenant_id uuid)`: tenants with `status='active'` settings and no `sent` nightly delivery on `p_date`, tenant `status` active.
  - SQL `app_backup_token_tenant(p_token_hash text) RETURNS uuid`: tenant whose pending row has that hash (expiry checked in Python after tenant context is set).
  - Both `STABLE SECURITY DEFINER SET search_path = public, pg_temp`, `REVOKE ALL ... FROM PUBLIC`.

- [ ] **Step 1: Write the failing tests** (pattern: `tests/test_tenant_isolation.py`):
  - `test_backup_tables_hide_other_tenants_rows`: rows for tenant A and B; with context A, `select(BackupSettings)` returns only A, same for `BackupDelivery`.
  - `test_due_tenants_lists_only_active_unsent`: A active unsent → listed; B pending → not; C active with `sent` nightly today → not; D active with only `failed` today → listed.
  - `test_token_lookup_returns_tenant_for_hash_only`: known hash → A; unknown → `None`.
  - `test_second_nightly_claim_same_day_violates_unique`: second insert raises `IntegrityError`; two `manual` rows same day do not.
  - `test_backup_functions_not_executable_by_public` (copy the `app_user_tenants` privilege check).
- [ ] **Step 2:** `uv run pytest tests/test_backup_isolation.py -v` → FAIL (no tables).
- [ ] **Step 3:** Write migration 0007 (down_revision = 0006's revision id; RLS policy text as in 0006 with `_TENANT_MATCH`), models, grants.
- [ ] **Step 4:** Tests PASS; full `uv run pytest -q` still green.
- [ ] **Step 5:** Commit `feat(backup): settings and delivery tables with RLS`.

### Task 3: Arabic labels and the workbook builder

**Files:**
- Create: `apps/api/app/modules/backup/labels.py`, `apps/api/app/modules/backup/workbook.py`
- Test: `apps/api/tests/test_backup_workbook.py`

**Interfaces:**
- Produces:
  - `MOVEMENT_LABELS_AR: dict[str, str]` (identical to `MOVEMENT_LABELS` in `apps/web/src/lib/catalog.ts`), `AUDIT_ACTION_LABELS_AR: dict[str, str]` (identical to `ACTION_LABELS` in `apps/web/src/app/(app)/audit/page.tsx`), `SHEET_NAMES: tuple[str, ...]` = the seven names in spec §3 order.
  - `@dataclass(frozen=True) class BuiltWorkbook: content: bytes; filename: str; row_counts: dict[str, int]; trimmed: bool`
  - `async def build_workbook(db: AsyncSession, *, tenant_id: uuid.UUID, now: datetime, size_cap_bytes: int = 20 * 1024 * 1024) -> BuiltWorkbook` — caller has already set tenant context.

- [ ] **Step 1: Write the failing tests** (seed with `tests/support.py` helpers):
  - `test_sheets_in_spec_order_and_rtl`: `load_workbook(BytesIO(b.content)).sheetnames == list(SHEET_NAMES)`; every `ws.sheet_view.rightToLeft is True`.
  - `test_headers_match_spec`: row 1 of «المنتجات» equals the 12 headers from spec §3, verbatim; same for the other sheets.
  - `test_filename_is_slug_and_cairo_date`: `now=datetime(2026,11,11,23,30,tzinfo=UTC)` → `filename == f"{slug}-2026-11-12.xlsx"`.
  - `test_balances_match_inventory_api`: after `adjust_api` calls, «الرصيد» quantities equal `GET /api/v1/inventory` balances for the same products.
  - `test_movement_types_are_arabic`: an `opening_balance` row shows `"رصيد افتتاحي"`.
  - `test_labels_match_web`: parse both TS objects with `re.findall(r'(\w+): "([^"]+)"', block)` and compare to the Python dicts.
  - `test_only_own_shop_rows`: two shops seeded; workbook for A has no product SKU of B.
  - `test_empty_shop_builds_valid_workbook` (Review Focus 3): «عن الملف» counts are all 0.
  - `test_formula_like_text_is_not_a_formula` (Review Focus 4): product `name_ar="=SUM(A1:A2)"` → cell `data_type == "s"`.
  - `test_size_cap_trims_to_twelve_months`: `size_cap_bytes=1` with a movement 400 days old → `trimmed is True`, old movement absent, «عن الملف» contains «آخر 12 شهرًا».
- [ ] **Step 2:** `uv run pytest tests/test_backup_workbook.py -v` → FAIL (import error).
- [ ] **Step 3:** Implement. openpyxl `Workbook(write_only=True)`; set `ws.sheet_view.rightToLeft = True`; write text cells starting with `= + - @` with `data_type="s"` (prefix not altered). Join names via SQL joins, not per-row lookups. Build once; if `len(content) > size_cap_bytes`, rebuild with movements/audit filtered to `now - 365 days`.
- [ ] **Step 4:** Tests PASS.
- [ ] **Step 5:** Commit `feat(backup): Arabic Excel export of one shop`.

### Task 4: Mailer, settings service and owner routes

**Files:**
- Create: `apps/api/app/modules/backup/mailer.py`, `schemas.py`, `service.py`, `router.py`
- Modify: `apps/api/app/main.py` (include router), `apps/api/app/core/messages_ar.py`
- Create: `apps/api/tests/backup_fakes.py` (`RecordingMailer`)
- Test: `apps/api/tests/test_backup_settings_api.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class OutgoingEmail: to: str; subject: str; body: str; attachment: tuple[str, bytes] | None = None`
  - `class Mailer(Protocol): async def send(self, message: OutgoingEmail) -> None` — raises `MailError(reason_ar: str)` on failure.
  - `class GmailMailer(Mailer)` — `smtplib.SMTP_SSL("smtp.gmail.com", 465)` inside `asyncio.to_thread`; maps `SMTPRecipientsRefused` → «عنوان البريد مرفوض.», size error → «حجم الملف أكبر من المسموح.», other → «تعذّر الإرسال. سنحاول في الليلة القادمة.»
  - `def get_mailer(settings: Settings) -> Mailer | None` (None when `not settings.mail_configured`); FastAPI dependency `MailerDep` overridable in tests.
  - Schemas: `BackupSettingsIn(email: EmailStr)`, `ConfirmIn(token: str)`, `BackupStatusOut(email: str | None, status: BackupStatus | None, last_sent_at: datetime | None, last_error_ar: str | None, consecutive_failures: int, manual_sends_left: int, mail_configured: bool)`.
  - Service: `get_status(db, ctx) -> BackupStatusOut`, `set_address(db, ctx, actor_id, email, mailer, settings) -> BackupStatusOut`, `confirm(db, token) -> None`, `stop(db, ctx, actor_id) -> None`.
  - Routes (spec §6): `GET|PUT|DELETE /api/v1/tenants/current/backup`, `POST /api/v1/backup/confirm`.
  - In `app/core/errors.py`: `class BackupMailNotConfiguredError(AppError): status_code = 503; code = "backup_mail_not_configured"` (add its code to `FALLBACK_BY_CODE`). Bad/expired token: `AppError` (400). Unconfirmed: `ConflictError` (409). Manual limit: `TooManyRequestsError(retry_after=<seconds to Cairo midnight>)`.
  - Audit actions: `backup.address_set`, `backup.confirmed`, `backup.stopped`, `backup.manual_send`.
  - Error messages (English, add Arabic): `"Invalid or expired confirmation link"` → «رابط التأكيد غير صالح أو انتهت صلاحيته. احفظ العنوان مرة أخرى لإرسال رابط جديد.», `"Backup email is not confirmed"` → «أكّد عنوان البريد أولًا.», `"Daily manual backup limit reached"` → «وصلت للحد اليومي: 3 نسخ يدوية. حاول غدًا.», `"Backup email sending is not configured"` → «الإرسال غير مُعدّ.»

- [ ] **Step 1: Write the failing tests:**
  - `test_owner_saves_address_and_gets_link`: PUT → 200, `status == "pending"`, `RecordingMailer.sent[0].to == email`, body contains `f"{public_app_url}/backup/confirm?token="`, no attachment.
  - `test_non_owner_roles_forbidden`: manager, inventory_manager, cashier → 403 on GET, PUT, DELETE.
  - `test_confirm_activates`: token from the recorded email → POST confirm 204; GET shows `active`.
  - `test_confirm_twice_refused`: second POST → 400 with the Arabic message.
  - `test_expired_token_refused`: freeze `confirm_expires_at` in the past → 400.
  - `test_old_token_dies_when_address_changes` (Review Focus 2).
  - `test_stop_sets_stopped_and_audits`: DELETE → 204, `status == "stopped"`, audit row `backup.stopped`.
  - `test_save_without_mailer_config_reports_not_configured` (Review Focus 5): mailer dependency returns None → PUT 503 with «الإرسال غير مُعدّ.», nothing stored as pending.
  - `test_token_never_stored_in_clear`: DB `confirm_token_hash != token` and `== sha256(token)`.
- [ ] **Step 2:** `uv run pytest tests/test_backup_settings_api.py -v` → FAIL.
- [ ] **Step 3:** Implement. `confirm` resolves tenant via `app_backup_token_tenant`, then `set_tenant_context`, then checks expiry and hash under RLS.
- [ ] **Step 4:** Tests PASS plus `tests/test_arabic_errors.py`.
- [ ] **Step 5:** Commit `feat(backup): owner settings, confirmation link and Gmail mailer`.

### Task 5: Sending one shop's backup (manual send)

**Files:**
- Create: `apps/api/app/modules/backup/delivery.py`
- Modify: `router.py` (`POST /api/v1/tenants/current/backup/send`), `service.py` (`get_status` failure counting)
- Test: `apps/api/tests/test_backup_delivery.py`

**Interfaces:**
- Consumes: `build_workbook` (Task 3), `Mailer`, `OutgoingEmail`, `MailError` (Task 4), models (Task 2).
- Produces:
  - `async def deliver(db: AsyncSession, *, tenant_id: uuid.UUID, kind: DeliveryKind, mailer: Mailer, now: datetime, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep, retry_delay: float = 30) -> BackupDelivery | None` — claims by inserting the row (a nightly unique violation means another run owns it: return `None`), re-reads settings and returns `None` unless status is `active`, builds, sends with one retry, sets `sent` or `failed` with `error_reason_ar`, `file_bytes`, `row_counts`. Email subject: `f"نسخة متجر {tenant.name} ليوم {date.isoformat()}"`.
  - `consecutive_failures` = count of most recent nightly deliveries with `failed` before the latest `sent`.

- [ ] **Step 1: Write the failing tests:**
  - `test_manual_send_emails_attachment`: active shop → POST send 200, one email with `.xlsx` attachment whose filename matches the workbook; delivery row `sent`, `file_bytes > 0`.
  - `test_manual_send_requires_confirmed_address`: pending → 409 «أكّد عنوان البريد أولًا.»
  - `test_fourth_manual_send_same_day_refused`: 4th → 429 with the Arabic limit message.
  - `test_retry_once_then_succeed`: mailer fails once then succeeds → `sent`, `sleep` called once with 30.
  - `test_two_failures_record_arabic_reason`: mailer always raises `MailError("عنوان البريد مرفوض.")` → row `failed`, `error_reason_ar` equals it; GET status shows it.
  - `test_three_failed_nights_counted`: three `failed` nightly rows on consecutive dates → `consecutive_failures == 3`; a later `sent` resets to 0.
  - `test_delivery_logs_have_no_address`: `caplog` records contain no `@`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat(backup): send one shop's backup with retry and status`.

### Task 6: Nightly run endpoint

**Files:**
- Modify: `delivery.py` (`run_nightly`), `router.py` (`POST /api/v1/internal/backups/run`)
- Test: `apps/api/tests/test_backup_nightly.py`

**Interfaces:**
- Consumes: `deliver` (Task 5), `app_backup_due_tenants` (Task 2).
- Produces: `async def run_nightly(session_factory, *, mailer: Mailer | None, now: datetime, deadline_seconds: float = 240, clock: Callable[[], float] = time.monotonic) -> RunSummary` with `@dataclass class RunSummary: sent: int; failed: int; skipped: int; remaining: int; configured: bool`. One DB session per shop; tenant context set per shop.

- [ ] **Step 1: Write the failing tests:**
  - `test_run_requires_cron_secret`: no header → 401; wrong secret → 401 (compare with `hmac.compare_digest`); right → 200.
  - `test_run_sends_each_due_shop_once`: shops A, B active, C pending → emails to A and B only; second call same day → 0 new emails.
  - `test_concurrent_runs_send_once`: `asyncio.gather(run_nightly(...), run_nightly(...))` → 2 emails total for 2 shops.
  - `test_deadline_leaves_remaining`: `clock` that jumps past 240 after the first shop → `remaining == 1`; next run sends it.
  - `test_run_skips_shop_whose_address_went_back_to_pending` (Review Focus 1).
  - `test_run_without_mailer_reports_not_configured`: `configured is False`, no rows claimed, 200.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. Endpoint logs `RunSummary` fields as `extra`.
- [ ] **Step 4:** Full suite `uv run pytest -q`, `uv run ruff check .`, `uv run mypy app` all clean.
- [ ] **Step 5:** Commit `feat(backup): nightly cron run, idempotent and time-boxed`.

### Task 7: Web settings page, confirm page, nav and banner

**Files:**
- Create: `apps/web/src/lib/backup.ts` (typed client for spec §6 routes, `BackupStatus` type mirroring `BackupStatusOut`)
- Create: `apps/web/src/app/(app)/settings/backup/page.tsx`
- Create: `apps/web/src/app/backup/confirm/page.tsx` (public, outside `(app)`, no AuthGuard)
- Modify: `apps/web/src/components/shell/nav.tsx` (item «النسخة اليومية», icon `DatabaseBackup`, `href: "/settings/backup"`, `permission: "tenant.settings.manage"`), `apps/web/src/components/shell/app-shell.tsx` (title map + banner)

**Interfaces:**
- Consumes: routes from Tasks 4–6.
- UI copy exactly as spec §2 status lines and buttons. Status date formatted `ar-EG` with `numberingSystem: "latn"`, timezone `Africa/Cairo`.
- Banner: owner only, when `consecutive_failures >= 3`: «لم تصل النسخة اليومية منذ 3 ليالٍ.» with link «راجع الإعدادات». Fetch status once per shell mount for owners only.
- Confirm page: reads `token` from the query, POSTs once, shows «تم تأكيد البريد. ستصلك أول نسخة الليلة.» or the API's Arabic error, plus a link to sign in.

- [ ] **Step 1:** Build the pages per the design system (ledger look, brand-800, hairlines, Readex Pro). Loading uses skeleton bars like `ShellSkeleton`; errors inline.
- [ ] **Step 2:** `pnpm -C apps/web exec tsc --noEmit && pnpm -C apps/web lint && pnpm -C apps/web build` → all exit 0.
- [ ] **Step 3:** Run API on 8765 (with `GMAIL_USER`/`GMAIL_APP_PASSWORD` of the owner's backup Gmail in the local shell env, never in a file) and `next start -p 3200`. In the browser as owner: save own address → pending line; open the link from the received email → confirm page success, settings show active; «أرسل نسخة الآن» enabled and delivers. As a cashier: no nav item, `/settings/backup` shows the forbidden state. Check at 400 px width.
- [ ] **Step 4:** Commit `feat(web): daily backup settings, confirm page and failure banner`.

### Task 8: Deploy and live check

**Files:**
- Modify: `docs/deploy/DEPLOY.md` (short "Daily backup email" section: env vars, Gmail app password steps from spec §8)

- [ ] **Step 1:** Owner adds env vars themselves: `npx -y vercel@65.14.0 env add GMAIL_USER production`, same for `GMAIL_APP_PASSWORD`, `CRON_SECRET` (any 40+ char random string), `PUBLIC_APP_URL=https://zain-agri.vercel.app`.
- [ ] **Step 2:** Run migration 0007 against Neon with the owner URL from `.env.neon-owner` (as for earlier migrations); re-apply `infrastructure/db/grants.sql`.
- [ ] **Step 3:** Merge to main, push, wait for the production deploy.
- [ ] **Step 4:** Verify cron routing: Vercel dashboard → Settings → Cron Jobs → Run on `/api/v1/internal/backups/run`; logs show the run summary with 200. If the request never reaches the api service, add `apps/web/src/app/api-cron/backup/route.ts` that forwards with the bearer secret and point the cron path at it; re-verify.
- [ ] **Step 5:** As the owner account on production: set address, confirm from the real email, «أرسل نسخة الآن», open the attachment in Excel; record file size and sheet counts.
- [ ] **Step 6:** Update `zain-open-issues` memory; commit docs `docs: daily backup email setup`.
