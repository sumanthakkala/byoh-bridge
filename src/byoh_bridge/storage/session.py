"""Session context manager — what handlers actually use.

Typical use::

    from .... import storage
    from ...models.weight_log import WeightLog

    with storage.session() as s:
        row = s.scalar(select(WeightLog).where(WeightLog.id == 1))

The context manager auto-commits on clean exit, rolls back on exception,
closes either way.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session, sessionmaker

from .engine import engine

logger = logging.getLogger(__name__)

# Bound to the engine lazily on first use so import-time work stays cheap.
_session_factory: sessionmaker[Session] | None = None


def _factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=engine(),
            expire_on_commit=False,
            future=True,
        )
    return _session_factory


@contextmanager
def session() -> Iterator[Session]:
    """Yield a session; commit on clean exit, rollback on exception."""
    s = _factory()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
