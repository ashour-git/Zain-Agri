"""Application configuration.

All values come from environment variables (or a local .env file).
Never create database connections here — this module only parses settings.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# .../apps/api/app/core/config.py -> repository root
REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", REPO_ROOT / "apps" / "api" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ZAIN AGRI API"
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "production"] = "development"

    # Runtime role. Must NOT be a superuser, otherwise RLS is bypassed.
    database_url: str = Field(..., description="SQLAlchemy URL for the app role")
    # Owner role, used only by Alembic.
    migration_database_url: str | None = None

    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_recycle_seconds: int = 1800

    log_level: str = "INFO"

    # Comma separated, explicit. No wildcards in production.
    cors_origins: str = ""

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def alembic_url(self) -> str:
        return self.migration_database_url or self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
