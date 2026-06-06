"""Plugin-owned SQLite layer — SQLAlchemy-backed.

Public surface — import from ``..storage``::

    from .. import storage

    storage.db_path()                 # -> Path
    storage.engine()                  # -> SQLAlchemy Engine (cached)
    storage.Base                      # -> declarative base for models
    storage.session()                 # -> context-managed Session
    storage.upgrade_to_head()         # -> runs `alembic upgrade head` programmatically

Models live in ``storage.models.*`` — global to the plugin, not
per-workflow. ForeignKey relationships across feature domains work
naturally because every model class is in the same ``Base.metadata``.
"""

from .base import Base
from .changes import set_change_listener  # noqa: F401 — import also registers the Session change listeners
from .engine import db_dir, db_path, engine, inbox_dir
from .migrations import alembic_config, upgrade_to_head
from .session import session

# NOTE: the app's models are imported by the framework at register() time
# (AppConfig.models_package) so they register on Base.metadata before
# migrations run — the framework owns no domain models itself.

__all__ = [
    "Base",
    "alembic_config",
    "db_dir",
    "db_path",
    "engine",
    "inbox_dir",
    "session",
    "set_change_listener",
    "upgrade_to_head",
]
