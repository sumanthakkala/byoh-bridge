"""``register(ctx, AppConfig)`` — the single entrypoint a plugin calls.

Generalises what the old purpose-built plugin did in its ``__init__.py``:
probe dependencies, populate the schema, autodiscover the app's workflows, run
migrations, and spin up the relay dialer — but driven entirely by ``AppConfig``
so the framework knows nothing about any particular app.
"""

from __future__ import annotations

import importlib
import logging

from . import dependencies
from .app_config import AppConfig, ensure_active
from .bridge import register as _bridge_register
from .workflows import register_workflows

logger = logging.getLogger("byoh_bridge")

#: The framework's own hard dependencies. Declared in ``pyproject.toml`` too;
#: probed here as a safety net for the "forgot to install" case (Hermes does not
#: install plugin deps — see docs/byoa/03-HERMES-GAPS.md).
FRAMEWORK_REQUIREMENTS = ("sqlalchemy>=2.0,<3", "alembic>=1.13,<2", "websockets>=12")


def register(ctx, config: AppConfig) -> None:
    """Called once by the plugin's ``register(ctx)`` at Hermes startup."""
    cfg = ensure_active(config)
    logger.info("[byoh] register(%s)", cfg.name)

    requirements = [*FRAMEWORK_REQUIREMENTS, *cfg.extra_requirements]
    status = dependencies.check(requirements)
    if not status.ok:
        for line in dependencies.render_report(cfg.name, status).splitlines():
            logger.error("[byoh] %s", line)
        dependencies.install_help_command(ctx, cfg.name, requirements)
        logger.error("[byoh] short-circuiting register() — install deps and restart Hermes")
        return

    try:
        # Import the app's models so every class registers on Base.metadata
        # before migrations run / the first query.
        importlib.import_module(cfg.models_package)
        # Autodiscover workflows + apply pending migrations.
        register_workflows(ctx, cfg.workflows_package)
        # Start the outbound relay dialer.
        _bridge_register(ctx)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("[byoh] register(%s) failed: %s", cfg.name, exc)
        return

    logger.info("[byoh] register(%s) complete", cfg.name)
