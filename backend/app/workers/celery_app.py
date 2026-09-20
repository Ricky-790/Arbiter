"""Celery application for Arbiter's match workers.

Run a worker with::

    celery -A app.workers.celery_app worker \
        --queues=arbiter.matches --concurrency=1 --loglevel=INFO

V1 deliberately runs one match at a time (one worker, one sandbox); the queue
and pub/sub design already carry ``match_id`` everywhere so scaling to
multiple workers/sandboxes later is a deployment change, not a rewrite.
"""

from __future__ import annotations

import os

from celery import Celery
from dotenv import load_dotenv

load_dotenv()

DEFAULT_REDIS_URL = "redis://localhost:6379/0"

#: Queue consumed by the match worker pool.
MATCH_QUEUE = "arbiter.matches"

#: Task name registered by ``app.workers.match_worker``.
START_MATCH_TASK = "arbiter.start_match"


def redis_url() -> str:
    """Celery broker/result backend URL (same Redis as the event pub/sub)."""
    return os.getenv("REDIS_URL", DEFAULT_REDIS_URL)


celery_app = Celery(
    "arbiter",
    broker=redis_url(),
    backend=redis_url(),
    include=["app.workers.match_worker"],
)

celery_app.conf.update(
    task_default_queue=MATCH_QUEUE,
    # A match must not be lost if a worker dies mid-run, and one worker
    # process should only hold one match at a time.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    result_expires=3600,
)
