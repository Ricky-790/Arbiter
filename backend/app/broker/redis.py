"""Redis connection settings shared by the API and the match workers."""

from __future__ import annotations

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


def get_async_redis() -> Redis:
    """Process-wide async Redis client, created lazily on first use.

    Safe to call from the API process and from a worker's event loop. Each
    process gets its own client; ``redis.asyncio`` manages the connection pool.
    """
    global _async_client
    if _async_client is None:
        _async_client = Redis.from_url(redis_url(), decode_responses=True)
    return _async_client


async def close_async_redis() -> None:
    """Close the cached client (worker/task shutdown and tests)."""
    global _async_client
    if _async_client is not None:
        await _async_client.aclose()
        _async_client = None
