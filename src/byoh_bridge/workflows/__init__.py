"""Workflow autodiscovery + the workflow-authoring contracts.

``register_workflows(ctx, package)`` walks every subpackage of the app's
workflows package; for each it calls ``build_workflow(ctx) -> Workflow`` and
registers the result. After all workflows are registered it runs Alembic to
bring the schema up to ``head``.

Adding a workflow = drop a subdirectory with an ``__init__.py`` exporting
``build_workflow``. No further wiring. The authoring contracts (``Tool``,
``Rpc``, ``Workflow``, the metric factory) are re-exported here so a workflow
imports them from one place::

    from byoh_bridge.workflows import Tool, Rpc, Workflow, make_log_tool, Field
"""

from __future__ import annotations

import importlib
import logging
import pkgutil

from .. import storage
from ._metric import Field, make_list_rpc, make_log_tool
from ._rpc import Rpc
from ._tool import Tool
from .discovery import collect_rpcs, discover_rpcs, discover_tools, register_tools
from .registry import Workflow, WorkflowRegistry, workflow_registry

logger = logging.getLogger("byoh_bridge.workflows")

__all__ = [
    "register_workflows",
    "register_tools",
    "collect_rpcs",
    "discover_tools",
    "discover_rpcs",
    "Tool",
    "Rpc",
    "Workflow",
    "WorkflowRegistry",
    "workflow_registry",
    "Field",
    "make_log_tool",
    "make_list_rpc",
]


def register_workflows(ctx, package: str) -> None:
    """Discover, register, and migrate every workflow under ``package``."""
    pkg = importlib.import_module(package)

    for mod_info in pkgutil.iter_modules(pkg.__path__):
        if not mod_info.ispkg:
            continue
        _load_workflow(package, mod_info.name, ctx)

    # Apply pending migrations. Models are already imported (the framework
    # imports AppConfig.models_package before this, and each workflow imports
    # its own models), so Alembic has the full target schema.
    storage.upgrade_to_head()

    logger.info(
        "[workflows] %d workflow(s) registered (%d UI RPCs)",
        len(workflow_registry.names()),
        len(workflow_registry.rpcs()),
    )


def _load_workflow(package: str, name: str, ctx) -> None:
    full = f"{package}.{name}"
    try:
        mod = importlib.import_module(full)
    except Exception as exc:
        logger.exception("[workflows] failed to import %s: %s", full, exc)
        return

    builder = getattr(mod, "build_workflow", None)
    if not callable(builder):
        logger.warning("[workflows] %s has no build_workflow(ctx); skipping", full)
        return

    try:
        wf = builder(ctx)
    except Exception as exc:
        logger.exception("[workflows] build_workflow(%s) crashed: %s", full, exc)
        return

    if not isinstance(wf, Workflow):
        logger.warning(
            "[workflows] %s.build_workflow returned %r, expected Workflow",
            full, type(wf).__name__,
        )
        return

    workflow_registry.register(wf)
    logger.info(
        "[workflows] %s registered (rpcs=%d, tools=%d)",
        wf.name, len(wf.rpcs), len(wf.allowed_tools),
    )
