"""byoh-bridge — Bring Your Own Hermes.

The reusable bridge runtime for BYOA ("agent-as-backend") Hermes plugins: an
outbound relay dialer, per-session tool sandbox, autodiscovered typed-tool /
RPC workflows, a local-SQLite storage engine with automatic change-events, and
programmatic migrations — all driven by one :class:`AppConfig`.

A plugin is then tiny::

    # my_app/__init__.py
    from byoh_bridge import register as byoh_register, AppConfig

    APP_CONFIG = AppConfig(
        name="my-app",
        workflows_package="my_app.workflows",
        models_package="my_app.storage.models",
        migrations_path=__path__[0] + "/alembic",
    )

    def register(ctx):
        byoh_register(ctx, APP_CONFIG)
"""

from __future__ import annotations

from .app_config import AppConfig, DocumentStore, ResolvedConfig, active, resolve
from .runtime import register
from .storage import (
    Base,
    db_dir,
    db_path,
    inbox_dir,
    session,
    upgrade_to_head,
)
from .workflows import (
    Field,
    Rpc,
    Tool,
    Workflow,
    collect_rpcs,
    make_list_rpc,
    make_log_tool,
    register_tools,
    register_workflows,
    workflow_registry,
)

__version__ = "0.1.0"

__all__ = [
    "AppConfig",
    "DocumentStore",
    "ResolvedConfig",
    "active",
    "resolve",
    "register",
    "register_workflows",
    "register_tools",
    "collect_rpcs",
    "Base",
    "session",
    "db_dir",
    "db_path",
    "inbox_dir",
    "upgrade_to_head",
    "Tool",
    "Rpc",
    "Workflow",
    "Field",
    "make_log_tool",
    "make_list_rpc",
    "workflow_registry",
    "__version__",
]
