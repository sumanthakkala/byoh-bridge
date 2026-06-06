"""Tool definition shared across workflows.

Each tool file in a workflow's ``tools/`` package exports a ``TOOL``
constant of this type. The workflow's ``tools/__init__.py`` walks the
package and registers every ``TOOL`` via ``ctx.register_tool(...)``.

Co-locating schema, handler, and metadata in one dataclass means a tool
is one file — no split between ``schemas.py`` and ``tools.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Tool:
    """One agent-callable tool.

    Fields map 1:1 to ``ctx.register_tool(...)`` parameters so the
    autodiscovery loop can pass them straight through.

    Attributes:
        name         Tool name the model sees. Must match the schema's
                     ``name`` field and ``^[a-zA-Z0-9_-]+$``.
        toolset      Hermes toolset key. Use ``"hermes-cli"`` to join
                     the default toolset heydoc already enables.
        schema       Full JSON Schema (with top-level ``name`` and
                     ``description``).
        handler      Callable invoked when the model picks this tool.
                     Receives the model's validated args dict and any
                     kwargs Hermes passes (parent_agent, task_id, etc.).
                     Returns a JSON string per Hermes convention.
        description  Surfaced in ``hermes tools list``. Defaults to the
                     schema's ``description`` when registered.
        emoji        Cosmetic; shown in some Hermes UIs.
    """

    name: str
    toolset: str
    schema: dict
    handler: Callable[..., str]
    description: str = ""
    emoji: str = ""
