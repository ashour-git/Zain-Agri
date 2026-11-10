# Deploying ZAIN AGRI (free tier)

Total time for a first deploy: about **60–90 minutes**.

| Part | Service | Free limits that matter |
|---|---|---|
| Website | **Vercel** Hobby | Non-commercial use only. Move to Cloudflare or Vercel Pro before shops pay (see §8). |
| API | **Northflank** free service | Always on. Check the current free terms when you sign up. |
| Database | **Neon** Free | 1 GB per project, 100 compute-hours/month, sleeps after 5 min idle (~1 s to wake), 6 h restore history. |
| AI assistant | **Groq** free | 1,000 requests/day and 8k tokens/min per model; about 1–2 questions/min per model. |
| Backups | **GitHub Actions** | Nightly encrypted dump kept 30 days (§6). |

## How the pieces connect

```
Browser ──► Vercel (Next.js)  ──/api/* proxy──►  Northflank (FastAPI)  ──►  Neon (PostgreSQL)
                                                        └──►  Groq (assistant)
```

The browser only ever talks to the Vercel domain. `/api/*` is forwarded to the
API by `apps/web/next.config.ts`. This is required: the login refresh cookie is
`HttpOnly; SameSite=Lax`, and it is only sent when the website and the API look
like one site. **Do not point the browser at the Northflank URL directly**, or
every page reload logs the user out.

---

## 1. Push the code (2 min)

```bash
git push origin main
```

## 2. Database on Neon (15 min)

1. Sign up at neon.com, **New project**: Postgres **18** (the backup job uses pg_dump 18), region **AWS Europe
   (Frankfurt)** (closest to Egypt).
2. Copy the **owner** connection string from *Connect* (role `neondb_owner`,
   **direct** connection, not the `-pooler` host). Keep it private.
3. Open **SQL Editor**, paste `infrastructure/db/neon-roles.sql`, replace
   `CHANGE-ME` with a long random password, run it.
4. From your PC, create the tables and grants. Use the `postgresql+psycopg://`
   prefix for both URLs:

   ```bash
   cd apps/api
   MIGRATION_DATABASE_URL="postgresql+psycopg://neondb_owner:OWNER_PASS@ep-xxx.eu-central-1.aws.neon.tech/neondb?sslmode=require" \
   DATABASE_URL="postgresql+psycopg://zain_app:APP_PASS@ep-xxx.eu-central-1.aws.neon.tech/neondb?sslmode=require" \
   uv run python migrate.py
   ```

   Expected last line: `Done.` Re-run this after every release that adds a
   migration.

## 3. API on Northflank (20 min)

1. Sign up at northflank.com, create a project (region: Europe).
2. **Add service → Combined service**, connect the GitHub repo, branch `main`.
3. Build: **Dockerfile**, path `apps/api/Dockerfile`, build context `/`
   (repository root).
4. Networking: port **8000**, HTTP, **public**.
5. Health check: HTTP `GET /health/ready` on port 8000.
6. Runtime variables (mark secrets as secret):

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | `postgresql+psycopg://zain_app:APP_PASS@ep-xxx…/neondb?sslmode=require` |
   | `JWT_SECRET_KEY` | output of `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
   | `REFRESH_COOKIE_SECURE` | `true` |
   | `CORS_ORIGINS` | your Vercel URL, e.g. `https://zain-agri.vercel.app` (set after step 4) |
   | `GROQ_API_KEY` | a **new** Groq key (leave empty to turn the assistant off) |
   | `LOG_LEVEL` | `INFO` |

   `ENVIRONMENT=production` is already set in the image. In production the API
   **refuses to start** without a 32+ character `JWT_SECRET_KEY`,
   `REFRESH_COOKIE_SECURE=true` and explicit `CORS_ORIGINS`. That is
   intentional.
7. Deploy. Open `https://<service-url>/health/ready`; expect
   `{"status":"ok","database":"ok","environment":"production"}`.

## 4. Website on Vercel (10 min)

1. vercel.com, **Add New → Project**, import the GitHub repo.
2. **Root Directory:** `apps/web`. Framework: Next.js (detected).
3. Environment variable: `API_ORIGIN` = the Northflank URL, e.g.
   `https://api--zain--xxxx.code.run` (no trailing slash).
   Do **not** set `NEXT_PUBLIC_API_BASE_URL`.
4. Deploy, then note the site URL.

## 5. Connect them (3 min)

1. In Northflank set `CORS_ORIGINS` to the exact Vercel URL from step 4
   (`https://…`, no trailing slash) and redeploy the API.
2. Smoke test on a phone and a laptop:
   - [ ] Register, create a shop, add a product, record an opening balance.
   - [ ] **Reload the page: you must stay logged in.**
   - [ ] Dashboard shows the product; inventory gauge matches.
   - [ ] «اسأل المساعد» answers «إيه الأصناف اللي محتاج أطلبها؟» (if the key is set).
   - [ ] Audit log lists the product and the movement.

## 6. Backups (10 min)

The workflow `.github/workflows/db-backup.yml` runs nightly at 03:00 Cairo.

1. GitHub repo, **Settings → Secrets and variables → Actions**, add:
   - `BACKUP_DATABASE_URL`: the **owner** URL with the `postgresql://` prefix
     (not `+psycopg`).
   - `BACKUP_PASSPHRASE`: a long random passphrase. **Store a copy outside
     GitHub**; without it the backups cannot be opened.
2. **Actions → db-backup → Run workflow** once; check that an artifact named
   `db-backup-…` appears.

### Restore a backup

```bash
gpg --decrypt zain-2026-11-10.dump.gpg > zain.dump            # asks for BACKUP_PASSPHRASE
pg_restore --no-owner --no-privileges --clean --if-exists \
  --dbname="postgresql://neondb_owner:OWNER_PASS@HOST/neondb?sslmode=require" zain.dump
cd apps/api && uv run python migrate.py                        # re-apply grants
```

Practise this once on a spare Neon branch before you need it.

## 7. Releasing an update

1. `git push origin main`. Vercel and Northflank rebuild automatically.
2. If the release adds a migration, run `uv run python migrate.py` (step 2.4)
   **before** the new API version goes live.

## 8. Known limits and when to pay

- **Vercel Hobby forbids commercial use.** Before the first shop pays, either
  upgrade to Vercel Pro ($20/month) or move the website to Cloudflare. On
  Cloudflare the `/api` proxy must be kept (a Worker or Pages Function that
  forwards `/api/*`); plain static hosting would break login (see "How the
  pieces connect").
- **One API instance.** Login rate limits and the assistant's daily quota are
  in memory: they reset when the API restarts and are not shared between
  instances. Do not scale the API beyond one instance without moving them to a
  shared store.
- **Client IP behind proxies.** The API trusts `X-Forwarded-For` (uvicorn
  `--forwarded-allow-ips '*'`) so each shop gets its own rate-limit bucket
  instead of all shops sharing Vercel's IP. A client that forges this header
  could dodge the per-IP login limit (the per-email limit still applies).
  Not verified yet: whether Vercel's proxy overwrites a forged header. Check
  it after the first deploy, and restrict `--forwarded-allow-ips` if the API
  is ever reachable without the proxy in front.
- **Neon sleeps** after 5 minutes idle; the first request after that waits
  about a second.
- **Groq free tier** is shared by every shop. Watch for «المساعد مش متاح» during
  busy hours; a paid Groq plan or a lower `ASSISTANT_DAILY_LIMIT` fixes it.
- Rough paid budget once shops pay: **$7–25/month** (always-on API + Neon
  Launch + Vercel Pro or Cloudflare $5).
