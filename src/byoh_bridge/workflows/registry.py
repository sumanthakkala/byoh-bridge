"""WorkflowRegistry — module-level singleton populated at plugin load.

Each workflow contributes a ``Workflow`` instance describing its name,
SKILL text, allowed-tool list, and UI-callable RPCs. The bridge and
router consult this registry at request time.

**Schema migrations are NOT tracked here.** Alembic manages the
plugin-wide migration history under ``alembic/versions/``. Workflows
only contribute *models*, which are imported as a side effect of the
workflow loading its ``models/`` package (see segment 1.7-style
autodiscovery).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Iterator

logger = logging.getLogger(__name__)


@dataclass
class Workflow:
    """One registered workflow.

    Attributes:
        name           Stable identifier ("weight_logging", "notes", …).
        skill          SKILL.md text — prepended to the first prompt.
        allowed_tools  Tool names the agent is steered toward.
        rpcs           Map of ``byo.*`` method → handler for the UI.
    """

    name: str
    skill: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    rpcs: dict[str, Callable[[dict], dict]] = field(default_factory=dict)
    # Versions for the UI compatibility handshake (PRD-06). Bump schema_version
    # when this workflow's table shape changes; tool_version on a tool signature
    # change. The UI's compat matrix decides render vs. prompt-to-update.
    schema_version: int = 1
    tool_version: int = 1


class WorkflowRegistry:
    """Map of workflow name → Workflow, plus aggregation helpers."""

    def __init__(self) -> None:
        self._workflows: dict[str, Workflow] = {}

    def register(self, wf: Workflow) -> None:
        if wf.name in self._workflows:
            logger.warning("[workflows] duplicate registration: %s", wf.name)
        self._workflows[wf.name] = wf

    def get(self, name: str) -> Workflow | None:
        return self._workflows.get(name)

    def items(self) -> Iterator[tuple[str, Workflow]]:
        return iter(sorted(self._workflows.items()))

    def names(self) -> list[str]:
        return sorted(self._workflows.keys())

    # ── Aggregations ─────────────────────────────────────────────────────

    def rpcs(self) -> dict[str, Callable[[dict], dict]]:
        """Merged dict of every workflow's UI-callable RPCs."""
        merged: dict[str, Callable] = {}
        for wf in self._workflows.values():
            for method, handler in wf.rpcs.items():
                if method in merged:
                    logger.warning("[workflows] duplicate RPC: %s", method)
                merged[method] = handler
        return merged


# Module-level singleton — workflows register into this at load time.
workflow_registry = WorkflowRegistry()
