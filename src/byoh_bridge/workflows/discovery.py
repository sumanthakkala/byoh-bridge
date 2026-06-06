"""Generic tool/RPC autodiscovery within a workflow.

Lifted from the per-workflow boilerplate that used to be copy-pasted into every
``tools/__init__.py`` and ``rpcs/__init__.py``. A workflow now just delegates::

    # my_app/workflows/weight/tools/__init__.py
    from byoh_bridge.workflows import register_tools as _rt
    def register_tools(ctx):
        return _rt(ctx, __name__)

Files starting with ``_`` are skipped (shared helpers). Each tool file exports a
``TOOL = Tool(...)`` constant; each RPC file an ``RPC = Rpc(...)`` constant.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Callable

from ._rpc import Rpc
from ._tool import Tool

logger = logging.getLogger("byoh_bridge.workflows")


def discover_tools(package: str) -> list[Tool]:
    pkg = importlib.import_module(package)
    tools: list[Tool] = []
    for mod_info in pkgutil.iter_modules(pkg.__path__):
        if mod_info.name.startswith("_"):
            continue
        full = f"{package}.{mod_info.name}"
        try:
            mod = importlib.import_module(full)
        except Exception as exc:
            logger.exception("[tools] failed to import %s: %s", full, exc)
            continue
        tool = getattr(mod, "TOOL", None)
        if isinstance(tool, Tool):
            tools.append(tool)
        elif tool is not None:
            logger.warning("[tools] %s.TOOL is %r, expected Tool", full, type(tool).__name__)
        else:
            logger.warning("[tools] %s has no TOOL export — skipping", full)
    return tools


def register_tools(ctx, package: str) -> list[Tool]:
    """Discover + register every tool in ``package`` with Hermes. Returns them."""
    tools = discover_tools(package)
    for tool in tools:
        ctx.register_tool(
            name=tool.name,
            toolset=tool.toolset,
            schema=tool.schema,
            handler=tool.handler,
            description=tool.description,
            emoji=tool.emoji,
        )
        logger.info("[tools] registered: %s (toolset=%s)", tool.name, tool.toolset)
    return tools


def discover_rpcs(package: str) -> list[Rpc]:
    pkg = importlib.import_module(package)
    rpcs: list[Rpc] = []
    for mod_info in pkgutil.iter_modules(pkg.__path__):
        if mod_info.name.startswith("_"):
            continue
        full = f"{package}.{mod_info.name}"
        try:
            mod = importlib.import_module(full)
        except Exception as exc:
            logger.exception("[rpcs] failed to import %s: %s", full, exc)
            continue
        rpc = getattr(mod, "RPC", None)
        if isinstance(rpc, Rpc):
            rpcs.append(rpc)
        elif rpc is not None:
            logger.warning("[rpcs] %s.RPC is %r, expected Rpc", full, type(rpc).__name__)
        else:
            logger.warning("[rpcs] %s has no RPC export — skipping", full)
    return rpcs


def collect_rpcs(package: str) -> dict[str, Callable[[dict], dict]]:
    """Return ``{method: handler}`` for every RPC in ``package``."""
    out: dict[str, Callable[[dict], dict]] = {}
    for rpc in discover_rpcs(package):
        if rpc.method in out:
            logger.warning("[rpcs] duplicate method within workflow: %s", rpc.method)
        out[rpc.method] = rpc.handler
        logger.info("[rpcs] registered: %s", rpc.method)
    return out
