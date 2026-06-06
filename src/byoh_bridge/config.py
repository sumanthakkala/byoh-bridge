"""Framework-internal constants: relay reconnect backoff + WS timeouts.

App-specific configuration (data dir, relay URL, agent id, bridge on/off) lives
in :mod:`byoh_bridge.app_config` (``AppConfig`` + ``BYOH_*`` env vars), not here.
"""

from __future__ import annotations

# ── Reconnect / backoff ───────────────────────────────────────────────────
INITIAL_BACKOFF_SEC: float = 1.0
MAX_BACKOFF_SEC: float = 30.0

# When the relay rejects us with code 4001 ("already-bound"), another Hermes
# process already owns this agent_id. Wait long enough that we don't thrash,
# short enough that we recover quickly if the incumbent dies.
ALREADY_BOUND_STANDDOWN_SEC: float = 60.0

WS_OPEN_TIMEOUT_SEC: float = 5.0
WS_CLOSE_TIMEOUT_SEC: float = 5.0
