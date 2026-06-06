"""Reusable Alembic ``env.py`` runner.

A plugin's ``alembic/env.py`` is a 3-liner::

    from my_app import APP_CONFIG
    from byoh_bridge.alembic_support import run_env
    run_env(APP_CONFIG)

Because the plugin is a real installed package, ``import my_app`` and
``import my_app.storage.models`` resolve from the bare ``alembic`` CLI with **no**
``sys.modules`` namespace fabrication — the hack the old plugin needed is gone.
"""

from __future__ import annotations

import importlib
import logging

from alembic import context

from .app_config import AppConfig, ensure_active
from .storage import Base
from .storage.engine import db_path

logger = logging.getLogger("alembic.env")


def run_env(app_config: AppConfig) -> None:
    """Configure + run migrations for ``app_config`` (online or offline)."""
    ensure_active(app_config)
    importlib.import_module(app_config.models_package)  # populate Base.metadata
    target_metadata = Base.metadata

    cfg = context.config
    url = cfg.get_main_option("sqlalchemy.url") or ""
    if not url.startswith("sqlite"):
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path()}")

    logger.info(
        "[byoh.alembic] %d table(s): %s",
        len(target_metadata.tables),
        ", ".join(sorted(target_metadata.tables)) or "(none)",
    )

    if context.is_offline_mode():
        _run_offline(cfg, target_metadata)
    else:
        _run_online(cfg, target_metadata)


def _run_offline(cfg, target_metadata) -> None:
    context.configure(
        url=cfg.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite needs batch mode for ALTER TABLE
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_online(cfg, target_metadata) -> None:
    from sqlalchemy import engine_from_config, pool

    connectable = engine_from_config(
        cfg.get_section(cfg.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
