"""FrameRouter — dispatches inbound relay messages.

Two layers of dispatch:

1. **Top-level** by ``msg["type"]``: ``browser.frame``, ``ping``,
   ``agent.welcome``, etc. Anything unknown is logged and dropped.

2. **For ``browser.frame``**, by ``frame["method"]``:
   - ``byo.*`` → look up in ``byo_handlers`` or ``workflow_rpcs``.
   - anything else → passthrough to tui_gateway (requires an existing
     session for the browser).

Responses for ``byo.*`` are wrapped in an ``agent.frame`` envelope and
sent upstream so the relay can route to the originating browser.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from . import gateway
from .sessions import SessionRegistry

logger = logging.getLogger(__name__)


class FrameRouter:
    def __init__(
        self,
        *,
        byo_handlers: dict[str, Callable[[str, dict], dict]],
        workflow_rpcs: dict[str, Callable[[dict], dict]],
        sessions: SessionRegistry,
        send_upstream: Callable[[dict], None],
    ) -> None:
        self._byo_handlers = byo_handlers
        self._workflow_rpcs = workflow_rpcs
        self._sessions = sessions
        self._send_upstream = send_upstream

        # Per-type handlers for top-level dispatch. Mutable so callers
        # can extend the registry without subclassing the router.
        self._top_handlers: dict[str, Callable[[dict], None]] = {
            "browser.frame": self._on_browser_frame,
            "ping": self._on_ping,
            "agent.welcome": self._noop,
        }

    # ── Public entry point ────────────────────────────────────────────────

    def on_relay_message(self, msg: dict) -> None:
        mtype = msg.get("type")
        if mtype is None:
            return
        handler = self._top_handlers.get(mtype)
        if handler is None:
            logger.debug("[bridge] no handler for relay type=%s", mtype)
            return
        handler(msg)

    # ── Top-level type handlers ──────────────────────────────────────────

    def _on_ping(self, _msg: dict) -> None:
        self._send_upstream({"type": "pong"})

    def _noop(self, _msg: dict) -> None:
        pass

    # ── browser.frame dispatch ──────────────────────────────────────────

    def _on_browser_frame(self, msg: dict) -> None:
        browser_session = str(msg.get("browser_session") or "")
        frame = msg.get("frame") or {}
        method = frame.get("method", "")
        rid = frame.get("id")
        params = frame.get("params") or {}

        if not method:
            return

        if method.startswith("byo."):
            response = self._dispatch_byo(browser_session, method, params)
            if rid is not None:
                self._reply(browser_session, rid, response)
            return

        # Non-byo method: passthrough to tui_gateway.
        self._passthrough(browser_session, frame)

    def _dispatch_byo(self, browser_session: str, method: str, params: dict) -> dict:
        # 1. Built-in bridge handlers (session lifecycle, meta).
        handler = self._byo_handlers.get(method)
        if handler is not None:
            try:
                return handler(browser_session, params)
            except Exception as exc:
                logger.exception("[bridge] byo handler %s crashed", method)
                return _error(5001, str(exc))

        # 2. Workflow-supplied read RPCs.
        rpc = self._workflow_rpcs.get(method)
        if rpc is not None:
            try:
                return {"result": rpc(params)}
            except Exception as exc:
                logger.exception("[bridge] workflow RPC %s crashed", method)
                return _error(5001, str(exc))

        return _error(-32601, f"unknown byo method: {method}")

    def _passthrough(self, browser_session: str, frame: dict) -> None:
        """Forward a non-byo method to ``tui_gateway`` if a session exists."""
        sess = self._sessions.get(browser_session)
        if sess is None:
            logger.warning(
                "[bridge] passthrough method %s dropped — no session for browser=%s",
                frame.get("method"), browser_session,
            )
            return
        gateway.call(
            frame.get("method", ""),
            frame.get("params") or {},
            sess.transport,
            request_id=frame.get("id"),
        )

    # ── Replying back to the browser ─────────────────────────────────────

    def _reply(self, browser_session: str, rid: Any, response: dict) -> None:
        if "error" in response:
            payload = {"jsonrpc": "2.0", "id": rid, "error": response["error"]}
        else:
            payload = {"jsonrpc": "2.0", "id": rid, "result": response.get("result")}
        self._send_upstream(
            {
                "type": "agent.frame",
                "browser_session": browser_session,
                "frame": payload,
            }
        )


def _error(code: int, message: str) -> dict:
    return {"error": {"code": code, "message": message}}
