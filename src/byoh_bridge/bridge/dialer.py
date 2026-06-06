"""BridgeDialer — owns the outbound WS lifecycle.

Single responsibility: connect, send, receive, reconnect. Knows nothing
about frame contents. Inbound frames are handed to ``on_message`` for
the router to interpret.

Reconnect policy:
- Normal disconnect: exponential backoff (1 → 2 → 4 → … → 30 s cap).
- Code 4001 ``already-bound``: another Hermes process owns this slot.
  Wait ``ALREADY_BOUND_STANDDOWN_SEC`` (60 s) before re-checking. This
  breaks the dashboard ⇄ chat-subprocess flap we hit during testing.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Optional

from ..config import (
    ALREADY_BOUND_STANDDOWN_SEC,
    INITIAL_BACKOFF_SEC,
    MAX_BACKOFF_SEC,
    WS_CLOSE_TIMEOUT_SEC,
    WS_OPEN_TIMEOUT_SEC,
)

logger = logging.getLogger(__name__)


class BridgeDialer:
    """Maintains one persistent outbound WS to the relay."""

    def __init__(
        self,
        on_message: Callable[[dict], None],
        on_connected: Callable[[], None],
        relay_url: str,
        agent_id: str,
    ) -> None:
        self._on_message = on_message
        self._on_connected = on_connected
        self._relay_url = relay_url
        self._agent_id = agent_id
        self._stop = threading.Event()
        self._ws_lock = threading.Lock()
        self._ws: Optional[Any] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        t = threading.Thread(target=self._run, name="byo-bridge-dialer", daemon=True)
        t.start()

    def stop(self) -> None:
        self._stop.set()
        with self._ws_lock:
            if self._ws is not None:
                try:
                    self._ws.close()
                except Exception:
                    pass

    # ── Send ──────────────────────────────────────────────────────────────

    def send(self, obj: dict) -> None:
        """Best-effort JSON send. Silently drops if disconnected."""
        with self._ws_lock:
            ws = self._ws
        if ws is None:
            return
        try:
            ws.send(json.dumps(obj, ensure_ascii=False))
        except Exception as exc:
            logger.warning("[bridge] send failed: %s", exc)

    # ── Connection loop ──────────────────────────────────────────────────

    def _run(self) -> None:
        backoff = INITIAL_BACKOFF_SEC
        while not self._stop.is_set():
            try:
                self._connect_and_pump()
                backoff = INITIAL_BACKOFF_SEC  # reset after a clean disconnect
            except Exception as exc:
                if self._is_already_bound(exc):
                    logger.info(
                        "[bridge] another process owns the relay slot for "
                        "agent_id=%s; standing by",
                        self._agent_id,
                    )
                    if self._stop.wait(timeout=ALREADY_BOUND_STANDDOWN_SEC):
                        break
                    continue
                logger.warning(
                    "[bridge] disconnect: %s; retry in %.0fs", exc, backoff,
                )
            if self._stop.is_set():
                break
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SEC)

    def _connect_and_pump(self) -> None:
        try:
            from websockets.sync.client import connect as ws_connect
        except ImportError:
            logger.error("[bridge] `websockets` not installed; dialer disabled")
            self._stop.set()
            return

        url = f"{self._relay_url}?agent_id={self._agent_id}"
        logger.info("[bridge] connecting to relay %s", url)
        ws = ws_connect(
            url,
            open_timeout=WS_OPEN_TIMEOUT_SEC,
            close_timeout=WS_CLOSE_TIMEOUT_SEC,
            max_size=None,
        )
        with self._ws_lock:
            self._ws = ws

        try:
            self._on_connected()
            for raw in ws:
                if self._stop.is_set():
                    break
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("[bridge] bad json from relay: %r", raw[:200])
                    continue
                try:
                    self._on_message(msg)
                except Exception as exc:
                    logger.exception("[bridge] on_message crashed: %s", exc)
        finally:
            with self._ws_lock:
                self._ws = None

    @staticmethod
    def _is_already_bound(exc: BaseException) -> bool:
        s = str(exc)
        return "already-bound" in s or "4001" in s
