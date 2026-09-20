"""Async database engine, session factory, and FastAPI session dependency."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from typing import Any

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.logger import get_logger

logger = get_logger()

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

load_dotenv()


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def get_engine() -> AsyncEngine:
    """Process-wide async engine, created lazily on first use."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(_database_url(), pool_pre_ping=True)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Process-wide session factory bound to :func:`get_engine`.

    ``expire_on_commit=False`` so objects returned from a route remain usable
    after commit within the same request.
    """
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _session_factory


def reset_session_state() -> None:
    """Drop cached engine/factory (tests and process reloads)."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    factory: Any = get_session_factory()
    async with factory() as session:
        yield session
