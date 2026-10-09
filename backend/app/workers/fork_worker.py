"""Celery worker entrypoints for building forks.

A fork is a saved checkpoint: a match's state at one branch point, backed by a
Solari snapshot and the conversations each agent had up to there. Building one
is the whole job here -- this worker never starts a match. A match is started
later, from the fork, with whatever models and instructions the caller wants,
which is what makes a fork worth keeping.

All replaying happens here. The Engine runs in replay mode throughout, which
keeps per-event writes, spectator emission, and tracing off.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from dotenv import load_dotenv

from app.broker.models import ForkCreateMessage
from app.db import get_session_factory, reset_session_state
from app.db.models import Challenge
from app.db.services import match_forks_service, matches_service
from app.db.services.match_fork_service import fail_fork
from app.engine import Engine
from app.engine.models import ForkBuildPlan
from app.engine.resumability import load_fork_history, plan_fork_build
from app.logger import get_logger
from app.sandbox.manager import sandbox_manager
from app.sandbox.models import ChallengeSpec

from .celery_app import CREATE_FORK_TASK, celery_app
from .shared import build_challenge_spec, dispose_database

logger = get_logger()
load_dotenv()


@celery_app.task(name=CREATE_FORK_TASK, bind=True)
def create_fork_task(self: Any, **payload: Any) -> dict[str, Any]:
    """Celery task: rebuild one fork's sandbox and record its state."""
    message = ForkCreateMessage.model_validate(payload)
    logger.info(
        f"Fork worker picked up {message.fork_id} "
        f"(match={message.parent_match_id}, event={message.branch_event_id})"
    )
    # Each task runs in its own event loop, so never reuse a database engine
    # cached on a previous task's (now closed) loop.
    reset_session_state()
    return asyncio.run(build_fork(message))


async def build_fork(message: ForkCreateMessage) -> dict[str, Any]:
    """Rebuild a fork's state, then store the snapshot and conversations.

    The fork row was already created ``pending`` by the API; this fills it in
    and flips it to ``ready``. Nothing is enqueued on the match queue.
    """
    try:
        spec = await load_fork_spec(message)
        plan = await plan_fork_build(message.parent_match_id, message.branch_event_id)
        snapshot_id = await build_snapshot(message.parent_match_id, plan, spec)

        factory = get_session_factory()
        async with factory() as session:
            history = await load_fork_history(
                message.parent_match_id, plan.branch_event_id, session
            )
            await match_forks_service.mark_ready(
                message.fork_id,
                snapshot_id=snapshot_id,
                prisoner_messages=history.prisoner_messages,
                warden_messages=history.warden_messages,
                session=session,
            )

        summary = {
            "fork_id": str(message.fork_id),
            "snapshot_id": snapshot_id,
            "turns_replayed": len(plan.tool_calls),
        }
        logger.info(f"Fork {message.fork_id} ready: {summary}")
        return summary
    except Exception:
        logger.exception(f"Fork {message.fork_id} could not be built")
        await fail_fork(message.fork_id)
        raise
    finally:
        await dispose_database()


async def build_snapshot(
    match_id: UUID,
    plan: ForkBuildPlan,
    spec: ChallengeSpec,
) -> str:
    """Replay a branch point into a sandbox and return its snapshot id.

    The sandbox is keyed by the match being forked. This is its own process, so
    it cannot collide with a live sandbox for that match in the match worker --
    though Solari still serves one sandbox at a time, so this waits for a free
    slot like everything else.
    """
    sandbox_key = str(match_id)
    engine = Engine(
        match_id=sandbox_key, challenge=spec, sandbox_manager=sandbox_manager
    )
    try:
        await engine.start(from_snapshot=plan.base_snapshot_id)
        engine.begin_replay()
        for call in plan.tool_calls:
            await engine.execute_tool_call(
                call.actor, call.tool, replay_at=call.timestamp
            )
        return await sandbox_manager.save_snapshot(
            sandbox_key, name=f"fork-{match_id}-{plan.branch_event_id}"
        )
    finally:
        engine.end_replay()
        await sandbox_manager.destroy_sandbox(sandbox_key)


async def load_fork_spec(message: ForkCreateMessage) -> ChallengeSpec:
    """Load the challenge the forked match was played on."""
    factory = get_session_factory()
    async with factory() as session:
        parent = await matches_service.get_match(message.parent_match_id, session)
        if parent is None:
            raise ValueError(f"Parent match {message.parent_match_id} does not exist")
        challenge = await session.get(Challenge, parent.challenge_id)
        if challenge is None:
            raise ValueError(f"Challenge {parent.challenge_id} does not exist")
        return build_challenge_spec(challenge)
