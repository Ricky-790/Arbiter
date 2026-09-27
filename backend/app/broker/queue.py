"""Enqueue match and fork requests for the Celery workers.

The API never runs a match inline: it validates the request, assigns an id, and
hands the work to the Celery worker pools through Redis. Forks go to a separate
queue, so building one cannot occupy a match worker.
"""

from __future__ import annotations

from app.workers.celery_app import (
    CREATE_FORK_TASK,
    FORK_QUEUE,
    MATCH_QUEUE,
    START_MATCH_TASK,
    celery_app,
)

from .models import ForkCreateMessage, MatchStartMessage


def enqueue_match_start(message: MatchStartMessage) -> None:
    """Push one match request onto the worker queue.

    Synchronous (Celery's client is blocking); call it from a threadpool when
    invoked from an async request handler.
    """
    celery_app.send_task(
        START_MATCH_TASK,
        kwargs=message.model_dump(mode="json"),
        queue=MATCH_QUEUE,
    )


def enqueue_fork_create(message: ForkCreateMessage) -> None:
    """Push one fork-build request onto the fork worker queue.

    Synchronous, like :func:`enqueue_match_start`. The fork worker only builds
    the fork's state; starting a match from it is a separate request.
    """
    celery_app.send_task(
        CREATE_FORK_TASK,
        kwargs=message.model_dump(mode="json"),
        queue=FORK_QUEUE,
    )
