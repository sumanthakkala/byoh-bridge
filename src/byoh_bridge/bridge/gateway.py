"""Thin wrapper around ``tui_gateway.server.dispatch``.

All in-process calls to Hermes's agent gateway go through here so the
JSON-RPC envelope shape stays in one place. Importing ``tui_gateway`` is
done lazily so module import doesn't have a hard dependency on Hermes
being already initialised.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from .transport import BridgeTransport

logger = logging.getLogger(__name__)


def make_request_id(prefix: str = "byo") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def call(
    method: str,
    params: dict,
    transport: BridgeTransport,
    *,
    request_id: Optional[str] = None,
) -> Optional[dict]:
    """Dispatch a tui_gateway RPC, returning the response dict.

    Returns ``None`` for long-running handlers (e.g. ``prompt.submit``)
    that schedule work on a pool and respond asynchronously via the
    transport.
    """
    from tui_gateway import server as tg_server

    req = {
        "jsonrpc": "2.0",
        "id": request_id or make_request_id(),
        "method": method,
        "params": params,
    }
    return tg_server.dispatch(req, transport)
