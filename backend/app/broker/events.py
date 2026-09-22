from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from redis.asyncio import Redis

from app.logger import get_logger

from .redis import HEARTBEAT_SECONDS, get_async_redis, match_events_channel

logger = get_logger()

#: Event types after which the live stream is complete.
_TERMINAL_EVENT_TYPES = frozenset({"match_finished"})


def encode_match_event(match_id: str, event: dict[str, Any]) -> str:
    """Serialize one Engine event into the pub/sub envelope.

    The envelope always carries ``match_id`` alongside the event's own fields
    so a subscriber can tell which match an event belongs to.
    """
    envelope = {"match_id": match_id, **_jsonable(event)}
    return json.dumps(envelope)


def _jsonable(event: dict[str, Any]) -> dict[str, Any]:
    serialized: dict[str, Any] = {}
    for key, value in event.items():
        if isinstance(value, datetime):
            serialized[key] = value.isoformat()
        else:
            serialized[key] = value
    return serialized


async def publish_match_event(
    match_id: str,
    event: dict[str, Any],
    *,
    client: Redis | None = None,
) -> None:
    """Publish one event to the match's channel."""
    client = client or get_async_redis()
    await client.publish(
        match_events_channel(match_id), encode_match_event(match_id, event)
    )


async def subscribe_match_events(
    match_id: str,
    *,
    client: Redis | None = None,
) -> AsyncIterator[str | None]:
    """Yield raw JSON payloads for one match's event channel.

    ``None`` is yielded when no event arrived within the heartbeat interval, so
    the SSE layer can emit a comment and detect a dead client. The stream ends
    after the terminal ``match_finished`` event.
    """
    client = client or get_async_redis()
    channel = match_events_channel(match_id)
    pubsub = client.pubsub()
    await pubsub.subscribe(channel)
    try:
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=HEARTBEAT_SECONDS
            )
            if message is None:
                yield None
                continue
            data = message.get("data")
            if not isinstance(data, str):
                continue
            yield data
            if _is_terminal(data):
                return
    finally:
        try:
            await pubsub.unsubscribe(channel)
        finally:
            await pubsub.aclose()


def _is_terminal(payload: str) -> bool:
    try:
        decoded = json.loads(payload)
    except (TypeError, ValueError):
        return False
    return isinstance(decoded, dict) and decoded.get("type") in _TERMINAL_EVENT_TYPES


class MatchEventPublisher:
    """Bridge a synchronous Engine event sink onto async Redis pub/sub.

    ``Engine`` calls its ``event_sink`` synchronously from the running event
    loop, so the sink side just enqueues; a single background task drains the
    queue in order. Used as an async context manager so the worker can flush
    the tail of the stream before finishing the task.
    """

    def __init__(self, match_id: str, *, client: Redis | None = None) -> None:
        self.match_id = match_id
        self._client = client
        self._queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    def __call__(self, event: dict[str, Any]) -> None:
        """Engine event sink: enqueue without blocking the match."""
        self._queue.put_nowait(dict(event))

    async def __aenter__(self) -> "MatchEventPublisher":
        self._task = asyncio.create_task(
            self._drain(), name=f"match-events-{self.match_id}"
        )
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self._queue.put_nowait(None)
        if self._task is not None:
            await self._task
            self._task = None

    async def _drain(self) -> None:
        """Publish queued events until the sentinel arrives.

        Never raises: event delivery must not be able to fail a match.
        """
        try:
            client = self._client or get_async_redis()
            while True:
                event = await self._queue.get()
                if event is None:
                    return
                try:
                    await publish_match_event(self.match_id, event, client=client)
                except Exception:
                    logger.exception(
                        f"Failed to publish event for match {self.match_id}"
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(f"Match event publisher stopped for {self.match_id}")
