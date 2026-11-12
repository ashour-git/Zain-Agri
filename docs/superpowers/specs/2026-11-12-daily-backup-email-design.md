# Daily Backup Email (per shop) — Design

Status: approved in conversation 2026-11-12, awaiting spec review
Owner: ZAIN AGRI web + API

## 1. Purpose

Each shop owner receives, every night, an Excel copy of their own shop's data
at an email address they chose and confirmed. The owner can open it in Excel
with no tools, keeps a copy outside ZAIN AGRI, and can see that the data is
theirs.

This is not the platform's disaster-recovery backup. That remains the
encrypted full-database dump (`.github/workflows/db-backup.yml`), which is
currently blocked by the GitHub billing lock and is tracked separately.

### Decisions taken with the owner

| Topic | Decision |
|---|---|
| Whose backup | Each shop owner, their own shop only (never the whole database) |
| Who configures it | Shop owner only (`tenant.settings.manage`) |
| Format | One `.xlsx` file, Arabic, right-to-left, Western digits |
| Delivery | Email attachment |
| Sender | A dedicated Gmail account via SMTP with an app password (free, no domain needed) |
| Schedule | Vercel Cron, once a night, between 03:00 and 04:00 Cairo time |
| Address check | Confirmation link, valid 24 hours, before any data is sent |

### Out of scope (this version)

- Restoring from the file. The Excel import feature will read the same layout later.
- Choosing which sheets to include, or a weekly/monthly schedule.
- More than one backup address per shop.
- A custom sender domain (needs a paid domain; revisit with password-reset emails).
- Backing up the whole database by email (rejected: one leaked inbox would expose every shop).

## 2. Settings screen: «النسخة اليومية»

- New page `/settings/backup`, a sidebar item next to «الحساب والأمان».
  Shown only to roles holding `tenant.settings.manage` (today: owner). The API
  enforces the same permission; hiding the link is not the guard.
- Contents:
  1. Email field, prefilled with the owner's sign-in email. Button
     «حفظ وإرسال رابط التأكيد».
  2. Status line, exactly one of:
     - «لم يُفعَّل بعد»
     - «في انتظار التأكيد، راجع بريدك»
     - «آخر نسخة أُرسلت: <weekday> <day> <month>، <time>»
     - «فشل الإرسال الأخير: <Arabic reason>»
  3. «أرسل نسخة الآن», enabled only when the address is confirmed. At most
     3 manual sends per shop per day (protects the shared Gmail quota).
  4. «إيقاف النسخة اليومية».
- After 3 consecutive failed nights, the app shell shows a red banner to the
  owner linking to this page until a send succeeds or backups are stopped.

### Confirmation flow

1. Save stores the address as *pending* and emails a link
   `/backup/confirm?token=…`. The token is 32 random bytes; only its SHA-256
   hash is stored. It expires after 24 hours and works once.
2. Opening the link confirms the address. It works without being signed in:
   the token alone identifies the shop.
3. Saving a different address replaces the old one and returns to *pending*.
   Nothing is sent to an unconfirmed address.
4. Save, confirm, stop and manual send are written to the audit log.

## 3. The Excel file

File name: `<shop-slug>-<YYYY-MM-DD>.xlsx`. Every sheet is right-to-left with
Arabic headers. Users, products and units appear by name, never by id.

| # | Sheet | Columns |
|---|---|---|
| 1 | «المنتجات» | الرمز، الباركود، الاسم، الاسم بالإنجليزية، التصنيف، العلامة التجارية، الوحدة الأساسية، سعر التكلفة، سعر البيع، حد التنبيه، تتبع الدفعات، الحالة |
| 2 | «الرصيد» | المنتج، الدفعة، الكمية، الوحدة، تحت الحد الأدنى |
| 3 | «الحركات» | التاريخ، المنتج، نوع الحركة، الكمية، الوحدة، الكمية بالوحدة الأساسية، التكلفة، الدفعة، ملاحظة، المستخدم |
| 4 | «الدفعات» | المنتج، رقم الدفعة، تاريخ الانتهاء |
| 5 | «التصنيفات والعلامات» | النوع، الاسم، التصنيف الرئيسي |
| 6 | «سجل النشاط» | التاريخ، المستخدم، الإجراء، العنصر |
| 7 | «عن الملف» | اسم المتجر، وقت الإنشاء، عدد صفوف كل ورقة، ملاحظة الاقتطاع إن وجدت |

Rules:
- Quantities and names match what the app screens show for the same data.
- Movement types and audit actions use the Arabic labels the web app already uses.
- Size cap 20 MB (Gmail attachment limit is 25 MB). If the full file exceeds
  it, «الحركات» and «سجل النشاط» are limited to the last 12 months and
  «عن الملف» says so. The other sheets are always complete.
- Built with `openpyxl` (new runtime dependency, write-only mode).

## 4. Nightly job and sending

### Trigger

- `vercel.json` gains `"crons": [{"path": "/api/v1/internal/backups/run", "schedule": "0 1 * * *"}]`
  (01:00 UTC; Hobby cron fires within that hour).
- The endpoint requires `Authorization: Bearer <CRON_SECRET>` (Vercel sends it
  when `CRON_SECRET` is set). Anything else: 401. Compared in constant time.
- First task of implementation: confirm Vercel Cron reaches a path routed to
  the `api` service through the rewrite. If it does not, the cron path moves
  to a tiny web route that forwards with the secret.

### Run

1. A narrow `SECURITY DEFINER` function (same pattern as migration 0003)
   returns only the ids of shops with a confirmed address and no successful
   backup for today's Cairo date. The runtime role cannot read other columns
   across tenants.
2. Each shop is then processed inside its own tenant context, with the same
   row-level security as a normal request.
3. A `backup_deliveries` row per shop per Cairo date, unique on
   `(tenant_id, delivery_date, kind)` where kind is `nightly` or `manual`,
   is claimed by insert before building the file. A duplicate cron call
   loses the insert and skips that shop: no double emails.
4. The run stops starting new shops after 4 minutes (function limit 5).
   Unreached shops are picked up by the next run.

### Sending

- `smtplib.SMTP_SSL("smtp.gmail.com", 465)` with `GMAIL_USER` and
  `GMAIL_APP_PASSWORD` from the environment, run in a worker thread so the
  event loop is not blocked. Standard library only.
- The same sender delivers confirmation links.
- Email subject «نسخة متجر <name> ليوم <date>», short Arabic body, one attachment.

### Failure handling

1. One retry after 30 seconds on a failed send.
2. A final failure stores status and an Arabic reason on the delivery row
   (for example: address rejected, mailbox full, attachment too large,
   sender not configured).
3. Three consecutive failed nights raise the banner in §2.
4. Every shop attempt logs `tenant_id`, duration, file size, rows per sheet and
   result. No email addresses or file contents in logs.
5. If `GMAIL_USER`/`GMAIL_APP_PASSWORD` are missing, the job records
   «الإرسال غير مُعدّ» and exits; the settings page still works.

## 5. Data model

New table `backup_settings` (one row per tenant, RLS-scoped like other tenant tables):
`tenant_id` (PK), `email`, `status` (`pending` | `active` | `stopped`),
`confirm_token_hash`, `confirm_expires_at`, `confirmed_at`, `updated_by`, timestamps.

New table `backup_deliveries` (RLS-scoped): `id`, `tenant_id`,
`delivery_date` (Cairo date), `kind`, `status` (`claimed` | `sent` | `failed`),
`error_reason_ar`, `file_bytes`, `row_counts` (jsonb), timestamps.
Unique `(tenant_id, delivery_date, kind)`. Manual sends use their own kind
and a count check (max 3 per day) instead of the unique key.

## 6. API

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/api/v1/tenants/current/backup` | owner | settings + last delivery status |
| PUT | `/api/v1/tenants/current/backup` | owner | set address → pending, sends link |
| POST | `/api/v1/tenants/current/backup/confirm` | anyone with token | body `{token}`; confirm address |
| POST | `/api/v1/tenants/current/backup/send` | owner | manual send now (max 3/day) |
| DELETE | `/api/v1/tenants/current/backup` | owner | stop |
| POST | `/api/v1/internal/backups/run` | cron secret | nightly run |

Errors use the existing envelope and get Arabic messages in `messages_ar.py`.

## 7. Testing

- Mailer is an interface; tests use a recording fake. No real email in CI.
- Isolation: with two shops configured, shop A's file contains no row of shop B.
- Idempotency: two concurrent runs send exactly one email per shop.
- Permissions: manager, storekeeper and cashier get 403 on every owner route.
- Token: expired, reused and wrong tokens are refused; nothing is sent while pending.
- Cron auth: missing or wrong secret is 401.
- Content: each sheet's rows and quantities match the API list endpoints for the same data.
- Size cap: an oversized fixture triggers 12-month trimming and the note in «عن الملف».
- Live check: one real send to the owner's address on production.

## 8. Owner setup (after build, about 5 minutes)

1. Create a Gmail account, e.g. `zain.agri.backup@gmail.com`.
2. Turn on 2-Step Verification, then create an App Password.
3. Add `GMAIL_USER`, `GMAIL_APP_PASSWORD` and `CRON_SECRET` to Vercel with
   `npx vercel env add` yourself. Never paste them into chat or files.

## 9. Risks

- Gmail may throttle or flag a new account that sends attachments daily.
  Volume is small (one email per shop per night); revisit with a real domain
  and a transactional provider when shops grow past ~100.
- Hobby cron timing is approximate (within the hour) and runs at most daily.
- Email is not encrypted at rest in the recipient's inbox. Acceptable because
  the file holds only that owner's own shop data and goes only to an address
  they confirmed.
