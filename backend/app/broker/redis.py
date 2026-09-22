"""Redis connection settings shared by the API and the match workers."""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from redis.asyncio import Redis

load_dotenv()

DEFAULT_REDIS_URL = "redis://localhost:6379/0"

#: How long a pub/sub subscriber waits for a message before the SSE layer emits a keep-alive comment
HEARTBEAT_SECONDS = 15.0


def redis_url() -> str:
    """Return the configured Redis URL (Celery broker and pub/sub backend)."""
    return os.getenv("REDIS_URL", DEFAULT_REDIS_URL)


def match_events_channel(match_id: str) -> str:
    """Per-match channel name; the match id is what isolates one stream."""
    return f"arbiter:match:{match_id}:events"


_async_client: Redis | None = None
_async_client_loop: asyncio.AbstractEventLoop | None = None


def get_async_redis() -> Redis:
    """Async Redis client for the event loop that is currently running.

    A worker serves every match in its own ``asyncio.run()`` loop, and a
    client's connection pool is tied to the loop it first ran on. Reusing a
    client cached from a previous, now-closed loop would silently fail
    publishing, so the cache is keyed by the running loop and rebuilt when it
    changes. The API process runs one long-lived loop and keeps a single
    client, as before.
    """
    global _async_client, _async_client_loop
    loop = asyncio.get_running_loop()
    if _async_client is None or _async_client_loop is not loop:
        _async_client = Redis.from_url(redis_url(), decode_responses=True)
        _async_client_loop = loop
    return _async_client


async def close_async_redis() -> None:
    """Close the cached client (worker/task shutdown and tests)."""
    global _async_client, _async_client_loop
    if _async_client is not None:
        await _async_client.aclose()
        _async_client = None
    _async_client_loop = None
