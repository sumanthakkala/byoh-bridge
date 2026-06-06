"""Per-session tool subsetting — execution-time enforcement (PRD-06).

Hermes 0.15.1's ``pre_llm_call`` hook is **context-injection only** (it cannot
filter the tool list the model is shown — verified in the agent source). So we
enforce subsetting where it counts, at execution, via the ``pre_tool_call`` hook:
a tool call in a *bridge-scoped* session that isn't on that session's allowlist
is **blocked** (returns ``{"action": "block", "message": ...}``).

This is the real determinism + security boundary — a scoped checklist session
cannot reach ``bash``/``shell`` or another workflow's tools. The SKILL prompt
still names the allowed tools (so the model rarely tries others); def-level
invisibility isn't available in this Hermes version (a candidate upstream
contribution — MASTER-PLAN §9). Sessions Hermes owns (the user's own dashboard
chat) are never restricted — only sessions in our registry.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from .sessions import BridgeSession, SessionRegistry

logger = logging.getLogger(__name__)


def block_message(sess: BridgeSession, tool_name: str) -> Optional[str]:
    """Block reason if ``tool_name`` isn't allowed in this scoped session, else None."""
    if not sess.allowed_tools:
        return None  # unrestricted session
    if tool_name in sess.allowed_tools:
        return None
    allowed = ", ".join(sess.allowed_tools)
    return (
        f"'{tool_name}' is not available in the '{sess.workflow}' workflow. "
        f"Only these tools are available here: {allowed}."
    )


def make_pre_tool_call_hook(sessions: SessionRegistry) -> Callable[..., Optional[dict]]:
    """Build the pre_tool_call callback bound to the session registry."""

    def pre_tool_call(*, tool_name: str = "", session_id: str = "", **_: Any) -> Optional[dict]:
        if not tool_name or not session_id:
            return None
        sess = sessions.get_by_tui(session_id)
        if sess is None:
            return None  # not a bridge-scoped session — don't touch the user's own sessions
        msg = block_message(sess, tool_name)
        if msg is None:
            return None
        logger.info(
            "[bridge] blocked tool '%s' in scoped session %s (workflow=%s)",
            tool_name, session_id, sess.workflow,
        )
        return {"action": "block", "message": msg}

    return pre_tool_call
