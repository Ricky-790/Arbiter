"""Shared SQLAlchemy declarative base for Arbiter's persistence layer."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Root base class; ``Base.metadata`` is Alembic's autogenerate target."""
