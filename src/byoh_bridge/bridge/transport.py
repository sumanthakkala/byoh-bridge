"""BridgeTransport — adapts Hermes's Transport protocol to our relay WS.

Hermes's ``tui_gateway`` accepts any object with a ``write(obj) -> bool``
method as a Transport. The stdio transport writes to stdout; the WS
transport writes to a websocket. Ours wraps every emitted frame in an
``agent.frame`` envelope so the relay can route it to the correct
browser by ``browser_session``.

One transport instance is bound per active session (see ``sessions.py``).
"""

from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)


class BridgeTransport:
    """Implements the ``Transport`` protocol from ``tui_gateway/transport.py``."""

    def __init__(
        self,
        send_upstream: Callable[[dict], None],
        browser_session: str,
    ) -> None:
        self._send = send_upstream
        self._browser_session = browser_session
        self._closed = False

    @property
    def browser_session(self) -> str:
        return self._browser_session

    def write(self, obj: dict) -> bool:
        """Wrap ``obj`` in an ``agent.frame`` envelope and ship upstream."""
        if self._closed:
            return False
        try:
            self._send(
                {
                    "type": "agent.frame",
                    "browser_session": self._browser_session,
                    "frame": obj,
                }
            )
            return True
        except Exception as exc:
            logger.warning(
                "[bridge] transport.write failed for browser=%s: %s",
                self._browser_session, exc,
            )
            self._closed = True
            return False

    def close(self) -> None:
        self._closed = True
