"""Bridge package — outbound WS dialer, frame router, byo.* handlers.

Wires together:
- ``dialer.BridgeDialer``     — maintains the WS connection to the relay
- ``router.FrameRouter``      — dispatches inbound frames by type
- ``handlers``                — implements built-in ``byo.*`` methods
- ``transport.BridgeTransport`` — adapts Hermes's Transport to our WS
- ``sessions.SessionRegistry`` — tracks browser_session ↔ tui session

Public surface — just ``register(ctx)``. Called once at plugin load.
"""

from __future__ import annotations

import logging
from typing import Optional

from .. import storage
from ..app_config import active
from ..workflows.registry import workflow_registry
from .dialer import BridgeDialer
from .handlers import make_handlers
from .policy import make_pre_tool_call_hook
from .router import FrameRouter
from .sessions import SessionRegistry
from .subscriptions import SubscriptionRegistry
from .uploads import UploadRegistry

logger = logging.getLogger(__name__)

_bridge: Optional["Bridge"] = None


class Bridge:
    """Composition root for the bridge subsystem.

    Owns the dialer, router, session registry, and handler map. One
    instance per plugin load — see ``register()``.
    """

    def __init__(self, ctx=None) -> None:
        self.ctx = ctx
        self.sessions = SessionRegistry()
        self.subscriptions = SubscriptionRegistry()
        self.uploads = UploadRegistry()
        cfg = active()
        self.dialer = BridgeDialer(
            on_message=self._on_relay_message,
            on_connected=self._on_connected,
            relay_url=cfg.relay_url,
            agent_id=cfg.agent_id,
        )
        self.byo_handlers = make_handlers(
            sessions=self.sessions,
            workflows=workflow_registry,
            send_upstream=self.dialer.send,
            subscriptions=self.subscriptions,
            uploads=self.uploads,
        )
        self.router = FrameRouter(
            byo_handlers=self.byo_handlers,
            workflow_rpcs=workflow_registry.rpcs(),
            sessions=self.sessions,
            send_upstream=self.dialer.send,
        )
        # Any committed DB write (any workflow) → byo.db.changed to subscribers.
        storage.set_change_listener(self._emit_change)

        # Per-session tool subsetting: block tools outside a scoped session's
        # allowlist at execution time (PRD-06). Only restricts bridge-managed
        # sessions; the user's own Hermes sessions are untouched.
        if ctx is not None and hasattr(ctx, "register_hook"):
            try:
                ctx.register_hook("pre_tool_call", make_pre_tool_call_hook(self.sessions))
                logger.info("[bridge] pre_tool_call subsetting hook registered")
            except Exception as exc:
                logger.warning("[bridge] could not register pre_tool_call hook: %s", exc)

    # ── Dialer callbacks ──────────────────────────────────────────────────

    def _on_relay_message(self, msg: dict) -> None:
        self.router.on_relay_message(msg)

    def _emit_change(self, table: str, op: str, row_ids: list) -> None:
        """Fan a committed DB change out to every browser subscribed to ``table``."""
        frame = {
            "jsonrpc": "2.0",
            "method": "event",
            "params": {"type": "byo.db.changed", "payload": {"table": table, "op": op, "row_ids": row_ids}},
        }
        for browser_session in self.subscriptions.browsers_for(table):
            self.dialer.send({"type": "agent.frame", "browser_session": browser_session, "frame": frame})

    def _on_connected(self) -> None:
        self.dialer.send({
            "type": "agent.hello",
            "agent_id": active().agent_id,
            "workflows": [
                {
                    "name": name,
                    "allowed_tools": wf.allowed_tools,
                    "schema_version": wf.schema_version,
                    "tool_version": wf.tool_version,
                }
                for name, wf in workflow_registry.items()
            ],
        })

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        cfg = active()
        self.dialer.start()
        logger.info(
            "[bridge] dialer started -> %s (agent_id=%s)", cfg.relay_url, cfg.agent_id,
        )

    def stop(self) -> None:
        self.dialer.stop()


def register(ctx) -> None:
    """Spawn the bridge subsystem. Called from the plugin's top-level ``register``."""
    global _bridge
    if not active().bridge_enabled:
        logger.info("[bridge] BYOH_BRIDGE_ENABLED=0, skipping dialer")
        return
    if _bridge is not None:
        logger.info("[bridge] already started")
        return
    _bridge = Bridge(ctx)
    _bridge.start()
