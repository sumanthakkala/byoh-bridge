"""Declarative base shared by every model in every workflow.

Each workflow's ``models/<name>.py`` file defines a class like::

    from ....storage import Base
    from sqlalchemy.orm import Mapped, mapped_column

    class WeightLog(Base):
        __tablename__ = "weight_logs"
        id: Mapped[int] = mapped_column(primary_key=True)
        ...

All such classes share the same ``Base.metadata``. Alembic's autogenerate
compares this metadata against the live DB schema to produce migrations.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Common declarative base. Add cross-table mixins here if needed."""
