"""Application configuration.

All values come from environment variables (or a local .env file).
Never create database connections here — this module only parses settings.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# .../apps/api/app/core/config.py -> repository root
_PARENTS = Path(__file__).resolve().parents
# Locally: <repo>/apps/api/app/core/config.py -> <repo>. On hosts that deploy
# only apps/api (Vercel services) the tree is shallower; fall back to the
# filesystem root so import never fails. Missing .env files are simply skipped.
REPO_ROOT = _PARENTS[4] if len(_PARENTS) > 4 else _PARENTS[-1]

# Deliberately public: the application refuses to start with it in production.
_DEV_JWT_SECRET = "dev-only-insecure-jwt-secret-change-before-deploy"  # noqa: S105


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

    # --- Authentication ----------------------------------------------------
    jwt_secret_key: SecretStr = SecretStr(_DEV_JWT_SECRET)
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_issuer: str = "zain-agri"
    jwt_audience: str = "zain-agri-api"

    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30

    # Refresh token cookie. HttpOnly, path-scoped to the auth routes.
    refresh_cookie_name: str = "zain_refresh"
    refresh_cookie_path: str = "/api/v1/auth"
    refresh_cookie_secure: bool = False

    # Blocks login until an email is verified. There is no email delivery yet,
    # so this must stay False until one is configured. See AUTHENTICATION.md.
    require_email_verification: bool = False

    # Simple in-process throttling. Per worker, not shared. See AUTHENTICATION.md.
    auth_rate_limit_attempts: int = 10
    auth_rate_limit_window_seconds: int = 300
    # Session refresh happens on every page load, from every till and phone
    # behind the shop's single IP. Same window, far higher ceiling.
    refresh_rate_limit_attempts: int = 120
    # Behind Vercel or a load balancer, read the client IP from proxy headers
    # (app/core/client_ip.py). Never enable when clients can reach the API directly.
    trust_proxy_headers: bool = False

    # Shop assistant (Groq). Without a key the feature is off and invisible.
    groq_api_key: SecretStr | None = None
    # Order from the live evaluation (spec §2): gpt-oss-120b 15/15, qwen 12/15.
    assistant_models: str = "openai/gpt-oss-120b,qwen/qwen3.8-27b"
    assistant_daily_limit: int = 100
    assistant_timeout_seconds: float = 20

    # Daily backup email (spec 2026-11-12). Without both Gmail values the
    # feature reports "not configured" instead of sending.
    gmail_user: str | None = None
    gmail_app_password: SecretStr | None = None
    # Vercel Cron sends "Authorization: Bearer <CRON_SECRET>".
    cron_secret: SecretStr | None = None
    # Base of links in emails (confirmation page).
    public_app_url: str = "http://localhost:3000"

    # Argon2id parameters. Memory cost is in KiB.
    argon2_time_cost: int = 3
    argon2_memory_cost: int = 65536
    argon2_parallelism: int = 4

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def assistant_model_list(self) -> list[str]:
        return [model.strip() for model in self.assistant_models.split(",") if model.strip()]

    @property
    def assistant_enabled(self) -> bool:
        return self.groq_api_key is not None and bool(self.groq_api_key.get_secret_value().strip())

    @property
    def mail_configured(self) -> bool:
        return bool(self.gmail_user and self.gmail_user.strip()) and bool(
            self.gmail_app_password and self.gmail_app_password.get_secret_value().strip()
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def alembic_url(self) -> str:
        return self.migration_database_url or self.database_url

    @model_validator(mode="after")
    def _validate_security_posture(self) -> "Settings":
        secret = self.jwt_secret_key.get_secret_value()
        if self.is_production:
            if secret == _DEV_JWT_SECRET or len(secret) < 32:
                raise ValueError(
                    "JWT_SECRET_KEY must be set to at least 32 characters in production"
                )
            if not self.refresh_cookie_secure:
                raise ValueError("REFRESH_COOKIE_SECURE must be true in production")
            if not self.cors_origin_list:
                raise ValueError("CORS_ORIGINS must list explicit origins in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
