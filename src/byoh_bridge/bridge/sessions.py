"""SessionRegistry — thread-safe ``browser_session → tui session`` map.

Each active conversation is one ``BridgeSession``. Browser frames look
up by ``browser_session`` to find the bound tui_gateway session id
and transport.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from threading import Lock
from typing import Optional

from .transport import BridgeTransport

logger = logging.getLogger(__name__)


@dataclass
class BridgeSession:
    """One active conversation between a browser tab and the local agent."""

    browser_session: str
    tui_session_id: str
    transport: BridgeTransport
    workflow: str
    allowed_tools: list[str] = field(default_factory=list)
    # Cleared after first ``prompt.submit`` — see handlers.py::_build_prompt.
    primed_skill: Optional[str] = None


class SessionRegistry:
    """Thread-safe map of browser_session → BridgeSession."""

    def __init__(self) -> None:
        self._sessions: dict[str, BridgeSession] = {}
        # Secondary index: tui_session_id → BridgeSession, so the pre_tool_call
        # hook (which sees the tui session id) can resolve the allowlist (PRD-06).
        self._by_tui: dict[str, BridgeSession] = {}
        self._lock = Lock()

    def add(self, sess: BridgeSession) -> None:
        with self._lock:
            existing = self._sessions.get(sess.browser_session)
            if existing is not None:
                logger.info(
                    "[bridge] replacing existing session for browser=%s",
                    sess.browser_session,
                )
                self._by_tui.pop(existing.tui_session_id, None)
                existing.transport.close()
            self._sessions[sess.browser_session] = sess
            self._by_tui[sess.tui_session_id] = sess

    def get(self, browser_session: str) -> Optional[BridgeSession]:
        with self._lock:
            return self._sessions.get(browser_session)

    def get_by_tui(self, tui_session_id: str) -> Optional[BridgeSession]:
        with self._lock:
            return self._by_tui.get(tui_session_id)

    def pop(self, browser_session: str) -> Optional[BridgeSession]:
        with self._lock:
            sess = self._sessions.pop(browser_session, None)
            if sess is not None:
                self._by_tui.pop(sess.tui_session_id, None)
        if sess is not None:
            sess.transport.close()
        return sess

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)
