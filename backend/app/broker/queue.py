"""Enqueue match requests for the Celery workers.

The API never runs a match inline: it validates the request, assigns a
``match_id``, and hands the work to the Celery worker pool through Redis.
"""

from __future__ import annotations

from app.workers.celery_app import MATCH_QUEUE, START_MATCH_TASK, celery_app

from .models import MatchStartMessage


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
