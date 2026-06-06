"""SQLAlchemy engine + DB path resolution.

One process-wide engine. Threads share it; SQLAlchemy + SQLite WAL mode
make that safe. Sessions (segment ``storage/session.py``) are the
short-lived per-call objects callers actually use.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

from sqlalchemy import Engine, create_engine, event

from ..app_config import active

logger = logging.getLogger(__name__)

_engine: Optional[Engine] = None
_engine_lock = threading.Lock()


def db_dir() -> Path:
    """Return the active app's data directory, creating it if needed.

    The path was resolved from ``AppConfig`` (default ``<hermes_home>/<name>``,
    overridable via ``BYOH_DATA_DIR``) when ``register()`` / ``run_env()`` ran.
    """
    base = active().data_dir
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path() -> Path:
    return db_dir() / active().db_filename


def inbox_dir() -> Path:
    """Local inbox for uploaded files (PRD-07). Bytes live here, never in the cloud."""
    d = db_dir() / "inbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def engine() -> Engine:
    """Return the cached process-wide Engine, creating on first call."""
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is not None:
            return _engine
        _engine = _build_engine()
    return _engine


def _build_engine() -> Engine:
    url = f"sqlite:///{db_path()}"
    eng = create_engine(
        url,
        # SQLite in single-process mode benefits from check_same_thread=False
        # since SQLAlchemy's pool already serializes writes via the GIL +
        # connection lifecycle. We mirror what we had with the raw sqlite3
        # connections.
        connect_args={"check_same_thread": False},
        # No echo by default — would dump every SQL statement to logs.
        # Flip via env var if debugging.
        future=True,
    )
    _attach_pragmas(eng)
    logger.info("[storage] engine ready at %s", url)
    return eng


def _attach_pragmas(eng: Engine) -> None:
    """Apply SQLite pragmas to every new connection in the pool.

    WAL = concurrent reads + one write.
    Foreign keys = off by default in SQLite (footgun). Turn on.
    """

    @event.listens_for(eng, "connect")
    def _set_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()
