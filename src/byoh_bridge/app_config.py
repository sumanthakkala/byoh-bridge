"""Per-app configuration for a BYOH bridge plugin.

A plugin built on ``byoh-bridge`` describes itself with one ``AppConfig`` and
hands it to :func:`byoh_bridge.register`. Everything the framework needs to know
that is *app-specific* — the data dir, the workflows/models packages, the
migration directory, the relay/agent connection, the document store — lives here.

The resolved config is stored process-globally (one plugin per Hermes process)
so the many no-argument call sites (``db_path()``, ``db_dir()`` …) keep working
without threading config through every function. ``register()`` sets it; the
Alembic env (:mod:`byoh_bridge.alembic_support`) sets it too so the CLI works.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol, Sequence

DEFAULT_RELAY_URL = "ws://127.0.0.1:3000/ws/agent"


class DocumentStore(Protocol):
    """How an app persists uploaded files (the one domain seam in the bridge).

    The generic upload pipeline streams bytes to the local inbox; the *row* that
    represents a document is domain-specific, so the app supplies this. Pass
    ``document_store=None`` to keep files in the inbox without a DB row.
    """

    def on_committed(self, session, meta: dict, params: dict) -> str:
        """Persist a committed upload; return the document id."""

    def resolve(self, doc_id: str) -> Optional[dict]:
        """Look up a document → ``{"path": str, "mime": str}`` (or ``None``)."""

    def set_status(self, session, doc_id: str, status: str) -> None:
        """Update a document's processing status (best-effort)."""


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", ""}


def _hermes_home() -> Path:
    try:
        from hermes_constants import get_hermes_home  # provided by Hermes at runtime

        return get_hermes_home()
    except Exception:
        return Path.home() / ".hermes"


@dataclass(frozen=True)
class AppConfig:
    """What a plugin author writes. Only the first four fields are required."""

    name: str                       # data-dir + default agent-id slug, e.g. "tinybeat-pregnancy"
    workflows_package: str          # dotted path, e.g. "tinybeat_pregnancy.workflows"
    models_package: str             # dotted path, e.g. "tinybeat_pregnancy.storage.models"
    migrations_path: str            # alembic script_location (the app owns its versions/)
    db_filename: str = "app.db"
    data_dir: Optional[str] = None  # default <hermes_home>/<name>; BYOH_DATA_DIR overrides
    relay_url: Optional[str] = None # default ws://127.0.0.1:3000/ws/agent; BYOH_RELAY_URL overrides
    agent_id: Optional[str] = None  # default "<name>-local"; BYOH_AGENT_ID overrides
    bridge_enabled: Optional[bool] = None  # default True; BYOH_BRIDGE_ENABLED overrides
    extra_requirements: Sequence[str] = ()  # app deps the startup probe should also check
    document_store: Optional[DocumentStore] = None


@dataclass(frozen=True)
class ResolvedConfig:
    """``AppConfig`` after env overrides + defaults are applied."""

    name: str
    workflows_package: str
    models_package: str
    migrations_path: str
    db_filename: str
    data_dir: Path
    relay_url: str
    agent_id: str
    bridge_enabled: bool
    extra_requirements: tuple[str, ...]
    document_store: Optional[DocumentStore]


def resolve(cfg: AppConfig) -> ResolvedConfig:
    data_dir = (
        os.environ.get("BYOH_DATA_DIR", "").strip()
        or cfg.data_dir
        or str(_hermes_home() / cfg.name)
    )
    return ResolvedConfig(
        name=cfg.name,
        workflows_package=cfg.workflows_package,
        models_package=cfg.models_package,
        migrations_path=cfg.migrations_path,
        db_filename=cfg.db_filename,
        data_dir=Path(data_dir),
        relay_url=(os.environ.get("BYOH_RELAY_URL", "").strip() or cfg.relay_url or DEFAULT_RELAY_URL),
        agent_id=(os.environ.get("BYOH_AGENT_ID", "").strip() or cfg.agent_id or f"{cfg.name}-local"),
        bridge_enabled=_env_bool(
            "BYOH_BRIDGE_ENABLED", cfg.bridge_enabled if cfg.bridge_enabled is not None else True
        ),
        extra_requirements=tuple(cfg.extra_requirements),
        document_store=cfg.document_store,
    )


# ── Process-global active config ───────────────────────────────────────────
_active: Optional[ResolvedConfig] = None


def set_active(cfg: ResolvedConfig) -> None:
    global _active
    _active = cfg


def active() -> ResolvedConfig:
    if _active is None:
        raise RuntimeError(
            "byoh_bridge: no active app config. Call byoh_bridge.register(ctx, AppConfig(...)) "
            "at plugin startup, or byoh_bridge.alembic_support.run_env(APP_CONFIG) from alembic."
        )
    return _active


def ensure_active(cfg: AppConfig) -> ResolvedConfig:
    """Resolve ``cfg`` and make it active. Idempotent across register + alembic."""
    resolved = resolve(cfg)
    set_active(resolved)
    return resolved
