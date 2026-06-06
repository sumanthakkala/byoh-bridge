"""Automatic change notifications (PRD-04).

A SQLAlchemy session listener records which tables a transaction touched and,
on commit, calls a single registered listener with ``(table, op, row_ids)``.
The bridge sets that listener to fan ``byo.db.changed`` events out to subscribed
browsers — so **every** workflow's writes notify the UI for free, with no
per-workflow emit code.

Layering: storage knows nothing about the bridge; the bridge registers its
callback via ``set_change_listener``. With no listener (e.g. Alembic CLI, tests)
this is a no-op.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from sqlalchemy import event
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# (table, op, row_ids) -> None
ChangeListener = Callable[[str, str, list], None]

_listener: Optional[ChangeListener] = None
_lock = threading.Lock()


def set_change_listener(fn: Optional[ChangeListener]) -> None:
    """Register the process-wide change listener (the bridge does this once)."""
    global _listener
    with _lock:
        _listener = fn


def _pk(obj: object):
    return getattr(obj, "id", None)


@event.listens_for(Session, "after_flush")
def _collect(session: Session, _flush_context) -> None:
    bucket = session.info.setdefault("byo_changes", [])
    for obj in session.new:
        bucket.append((obj.__tablename__, "insert", _pk(obj)))
    for obj in session.dirty:
        bucket.append((obj.__tablename__, "update", _pk(obj)))
    for obj in session.deleted:
        bucket.append((obj.__tablename__, "delete", _pk(obj)))


@event.listens_for(Session, "after_commit")
def _emit(session: Session) -> None:
    changes = session.info.pop("byo_changes", None)
    if not changes:
        return
    fn = _listener
    if fn is None:
        return
    # Group by (table, op) → row_ids so the UI gets one event per change kind.
    grouped: dict[tuple[str, str], list] = {}
    for table, op, pk in changes:
        grouped.setdefault((table, op), []).append(pk)
    for (table, op), ids in grouped.items():
        try:
            fn(table, op, [i for i in ids if i is not None])
        except Exception as exc:  # never let a UI-notify failure break a write
            logger.warning("[changes] listener failed for %s/%s: %s", table, op, exc)


@event.listens_for(Session, "after_rollback")
def _discard(session: Session) -> None:
    session.info.pop("byo_changes", None)
