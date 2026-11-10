# ZAIN AGRI API — production image.
#
# Build from the repository root:
#   docker build -f apps/api/Dockerfile -t zain-api .
#
# The app lives at /srv/zain/apps/api to mirror the repository layout:
# app/core/config.py locates the repo root four directories up.

FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /bin/uv

WORKDIR /srv/zain/apps/api

# Dependencies first, so code changes don't reinstall them.
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY apps/api/alembic.ini ./
COPY apps/api/alembic ./alembic
COPY apps/api/app ./app
COPY infrastructure/db/grants.sql /srv/zain/infrastructure/db/grants.sql
COPY apps/api/migrate.py ./

RUN useradd --system --no-create-home zain
USER zain

ENV PATH="/srv/zain/apps/api/.venv/bin:$PATH" \
    ENVIRONMENT=production \
    PORT=8000

EXPOSE 8000

# --proxy-headers: the API sits behind the platform load balancer and the
# web app's /api proxy; rate limits need the real client IP from
# X-Forwarded-For. No --reload, one worker: quota and rate limits are
# in-process (docs/security/AUTHENTICATION.md §10).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips '*' --no-server-header"]
