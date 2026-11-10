"""Apply database migrations, then the runtime-role grants.

    MIGRATION_DATABASE_URL=postgresql+psycopg://OWNER@HOST/DB?sslmode=require \\
    DATABASE_URL=postgresql+psycopg://zain_app@HOST/DB?sslmode=require \\
    uv run python migrate.py

Runs as the *owner* role (MIGRATION_DATABASE_URL). Grants must be re-applied
after every migration so the runtime role can use new tables; both steps are
idempotent and safe to repeat. Used locally against Neon and inside the
production image (`python migrate.py`).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, text

from alembic import command
from app.core.config import get_settings

API_ROOT = Path(__file__).resolve().parent
GRANTS = API_ROOT.parents[1] / "infrastructure" / "db" / "grants.sql"


def main() -> None:
    if sys.platform == "win32":
        # Alembic's env.py runs async psycopg; Windows' Proactor loop is refused.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    settings = get_settings()
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    print("Applying migrations...")
    command.upgrade(config, "head")

    print(f"Applying grants from {GRANTS.name}...")
    engine = create_engine(settings.alembic_url)
    try:
        with engine.begin() as conn:
            conn.execute(text(GRANTS.read_text(encoding="utf-8")))
    finally:
        engine.dispose()
    print("Done.")


if __name__ == "__main__":
    main()
