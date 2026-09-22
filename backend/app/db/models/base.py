"""Shared SQLAlchemy declarative base for Arbiter's persistence layer."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
