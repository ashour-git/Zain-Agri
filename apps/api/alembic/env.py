"""Alembic environment.

Runs with the *owner* role (MIGRATION_DATABASE_URL), never the runtime role,
because DDL requires ownership.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.config import get_settings
from app.infrastructure.db.base import Base
from app.modules.audit import models as _audit_models  # noqa: F401  (registers metadata)
from app.modules.auth import models as _auth_models  # noqa: F401  (registers metadata)
from app.modules.backup import models as _backup_models  # noqa: F401  (registers metadata)
from app.modules.catalog import models as _catalog_models  # noqa: F401  (registers metadata)
from app.modules.identity import models as _models  # noqa: F401  (registers metadata)
from app.modules.inventory import models as _inventory_models  # noqa: F401  (registers metadata)

config = context.config

if config.config_file_name is not None:
    # Keep loggers created before migrations (e.g. "zain.*") enabled.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    return get_settings().alembic_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _url()

    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
