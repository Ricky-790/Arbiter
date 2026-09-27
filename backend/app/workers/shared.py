"""Helpers shared by the match worker and the fork worker.

The two pools are separate Celery queues but load the same challenge specs and
own the same database lifecycle, so those live here rather than in either one.
"""

from __future__ import annotations

import os
from uuid import UUID

from app.db import get_engine, get_session_factory, reset_session_state
from app.db.models import Challenge
from app.db.services import matches_service
from app.logger import get_logger
from app.sandbox.models import ChallengeSpec, SandboxConfig

logger = get_logger()

DEFAULT_MATCH_TIMEOUT_SECONDS = 200.0


def build_challenge_spec(challenge: Challenge) -> ChallengeSpec:
    """Map a persisted challenge onto the sandbox/Engine challenge contract."""
    return ChallengeSpec(
        name=challenge.name,
        description=challenge.description,
        win_condition=challenge.win_condition,
        sandbox=SandboxConfig(**(challenge.sandbox_config or {})),
        files=dict(challenge.files or {}),
        environment=dict(challenge.env_vars or {}),
        flag=dict(challenge.flag or {}),
        flag_structure=dict(challenge.flag_structure or {}),
        verifier_script=challenge.verifier_script,
        setup_script=challenge.setup_script,
    )


def default_timeout_seconds() -> float:
    raw = os.getenv(
        "ARBITER_MATCH_TIMEOUT_SECONDS", str(DEFAULT_MATCH_TIMEOUT_SECONDS)
    )
    try:
        return float(raw)
    except (TypeError, ValueError):
        return DEFAULT_MATCH_TIMEOUT_SECONDS


async def mark_match_failed(match_id: UUID) -> None:
    """Close a match that failed before a worker could take it over."""
    factory = get_session_factory()
    async with factory() as session:
        await matches_service.set_status(session, match_id, "failed")


async def dispose_database() -> None:
    """Drop this task's loop-bound database engine before the loop closes."""
    try:
        await get_engine().dispose()
    except Exception:
        logger.exception("Failed to dispose the database engine after the task")
    finally:
        reset_session_state()
