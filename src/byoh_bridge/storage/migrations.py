"""Alembic integration — programmatic upgrade + config builder.

Plugin startup calls ``upgrade_to_head()`` which is equivalent to running
``alembic upgrade head`` from the CLI but in-process. No subprocess.

``alembic_config()`` builds a configured ``Config`` instance pointing at
this plugin's ``alembic/`` directory + live database. Useful both at
runtime (for the upgrade) and from the optional ``hermes byo migrate``
CLI wrapper that calls ``alembic.command.revision()`` etc.
"""

from __future__ import annotations

import logging

from .engine import db_path

logger = logging.getLogger(__name__)


def alembic_config():
    """Build a configured Alembic ``Config`` for the active app.

    ``script_location`` comes from ``AppConfig.migrations_path`` (the app owns
    its ``versions/``); the URL points at the resolved local SQLite file.
    """
    from alembic.config import Config

    from ..app_config import active

    cfg = Config()
    cfg.set_main_option("script_location", active().migrations_path)
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path()}")
    return cfg


def upgrade_to_head() -> None:
    """Run pending migrations against the live database. Idempotent."""
    from alembic import command

    cfg = alembic_config()
    logger.info("[storage] running `alembic upgrade head` against %s", db_path())
    command.upgrade(cfg, "head")
    logger.info("[storage] migrations up to date")
