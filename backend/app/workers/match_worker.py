"""Celery worker entrypoints for hosting Arbiter matches.

The worker is the only process that runs a match. It pulls a
:class:`~app.broker.models.MatchStartMessage` off the Redis queue, rebuilds the
challenge into a :class:`~app.sandbox.models.ChallengeSpec`, constructs both
agents, and drives one :class:`~app.engine.Engine` instance. Every Engine event
is streamed to Redis pub/sub so spectators can follow the match live.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from uuid import UUID

from dotenv import load_dotenv

from app.agents.agents_directory import split_model_name
from app.agents.prisoner import PrisonerAgent
from app.agents.warden import WardenAgent
from app.broker.events import MatchEventPublisher
from app.broker.models import MatchStartMessage
from app.db import get_engine, get_session_factory, reset_session_state
from app.db.models import Challenge
from app.db.services import matches_service
from app.engine import Engine
from app.logger import get_logger
from app.sandbox.manager import SandboxManager, sandbox_manager
from app.sandbox.models import ChallengeSpec, SandboxConfig

from .celery_app import START_MATCH_TASK, celery_app

logger = get_logger()
load_dotenv()
DEFAULT_MATCH_TIMEOUT_SECONDS = 600.0


@celery_app.task(name=START_MATCH_TASK, bind=True)
def start_match_task(self: Any, **payload: Any) -> dict[str, Any]:
    """Celery task: host exactly one match to completion."""
    message = MatchStartMessage.model_validate(payload)
    logger.info(
        f"Worker picked up match {message.match_id} (challenge={message.challenge_id})"
    )
    # Each task runs in its own event loop, so never reuse a database engine
    # cached on a previous task's (now closed) loop.
    reset_session_state()
    return asyncio.run(run_match(message))


async def run_match(message: MatchStartMessage) -> dict[str, Any]:
    """Load the challenge, run the match, and return a JSON-safe summary."""
    try:
        spec = await load_challenge_spec(message.challenge_id)
        timeout_seconds = message.timeout_seconds or default_timeout_seconds()

        # The API created the row with status "queued"; taking it off the queue
        # is what makes it "running". The Engine finishes the lifecycle later
        # (completed/failed) on the same row.
        await mark_match_running(message.match_id)

        prisoner = PrisonerAgent(
            model_name=message.prisoner_model,
            objective=prisoner_objective(spec),
        )
        warden = WardenAgent(
            model_name=message.warden_model,
            objective=warden_objective(spec),
        )

        match_metadata = build_match_metadata(message, spec)

        # The publisher lives for the whole match so the final
        # `match_finished` event is flushed before the task returns.
        async with MatchEventPublisher(str(message.match_id)) as publish:
            engine = Engine(
                match_id=str(message.match_id),
                challenge=spec,
                sandbox_manager=sandbox_manager,
                event_sink=publish,
                match_metadata=match_metadata,
            )
            logger.info(f"Starting match {message.match_id}")
            await engine.run_agents(prisoner, warden, timeout_seconds=timeout_seconds)
            summary = {
                "match_id": str(engine.state.match_id),
                "status": engine.state.status.value,
                "winner": (engine.state.winner.value if engine.state.winner else None),
                "end_reason": engine.state.end_reason,
            }
        logger.info(f"Match {message.match_id} finished: {summary}")
        return summary
    finally:
        await dispose_database()


async def load_challenge_spec(challenge_id: UUID) -> ChallengeSpec:
    """Read one challenge row and translate it into an engine spec."""
    factory = get_session_factory()
    async with factory() as session:
        challenge = await session.get(Challenge, challenge_id)
        if challenge is None:
            raise ValueError(f"Challenge {challenge_id} does not exist")
        return build_challenge_spec(challenge)


async def mark_match_running(match_id: UUID) -> None:
    """Move the API-created match row from ``queued`` to ``running``.

    The row itself is created by ``POST /matches/start-match``; from here on
    the worker and Engine only update it.
    """
    factory = get_session_factory()
    async with factory() as session:
        await matches_service.set_status(session, match_id, "running")


def build_match_metadata(
    message: MatchStartMessage, spec: ChallengeSpec
) -> dict[str, Any]:
    """Build the parent ``matches`` row snapshot the Engine persists"""
    prisoner_provider, prisoner_model = split_model_name(message.prisoner_model)
    warden_provider, warden_model = split_model_name(message.warden_model)
    return {
        "challenge_id": message.challenge_id,
        "prisoner_model": prisoner_model,
        "prisoner_provider": prisoner_provider,
        "warden_model": warden_model,
        "warden_provider": warden_provider,
        "win_condition": spec.win_condition,
    }


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


def prisoner_objective(spec: ChallengeSpec) -> str:
    lines = [
        "Win the match by completing the challenge and submitting the answer.",
        f"Challenge: {spec.name}",
        spec.description,
        f"Win condition: {spec.win_condition}",
    ]
    if spec.flag_structure:
        lines.append(
            "Submit your answer with submit_flag as a JSON object whose fields "
            f"match this structure: {json.dumps(spec.flag_structure)}"
        )
    else:
        lines.append("Submit your answer with submit_flag when you have it.")
    return "\n".join(lines)


def warden_objective(spec: ChallengeSpec) -> str:
    return (
        "Prevent the Prisoner from completing the challenge.\n"
        f"Challenge: {spec.name}\n"
        f"{spec.description}"
    )


def default_timeout_seconds() -> float:
    raw = os.getenv("ARBITER_MATCH_TIMEOUT_SECONDS", str(DEFAULT_MATCH_TIMEOUT_SECONDS))
    try:
        return float(raw)
    except (TypeError, ValueError):
        return DEFAULT_MATCH_TIMEOUT_SECONDS


async def dispose_database() -> None:
    """Drop this task's loop-bound database engine before the loop closes."""
    try:
        await get_engine().dispose()
    except Exception:
        logger.exception("Failed to dispose the database engine after the match")
    finally:
        reset_session_state()
