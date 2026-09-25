"""Service for the `match_agent_messages` table."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger

from ..db import get_session_factory
from ..models import MatchAgentMessages

logger = get_logger()


class MatchAgentMessagesService:
    async def store_messages(
        self,
        match_id: UUID,
        actor: str,
        messages: list[dict[str, Any]],
        session: AsyncSession,
    ) -> None:
        """Upsert one agent's conversation history for a match.

        An upsert rather than an insert so a redelivered task overwrites its
        own earlier write instead of failing on the unique constraint.
        """
        statement = (
            pg_insert(MatchAgentMessages)
            .values(
                id=uuid4(),
                match_id=match_id,
                actor=actor,
                messages=messages,
            )
            .on_conflict_do_update(
                constraint="uq_match_agent_messages_match_actor",
                set_={"messages": messages},
            )
        )
        await session.execute(statement)
        await session.commit()

    async def get_messages(
        self,
        match_id: UUID,
        actor: str,
        session: AsyncSession,
    ) -> list[dict[str, Any]] | None:
        """Return one agent's stored history, or ``None`` if none was saved."""
        result = await session.execute(
            select(MatchAgentMessages.messages).where(
                MatchAgentMessages.match_id == match_id,
                MatchAgentMessages.actor == actor,
            )
        )
        return result.scalar_one_or_none()


match_agent_messages_service = MatchAgentMessagesService()


async def store_agent_history(
    *,
    match_id: UUID,
    actor: str,
    messages: list[dict[str, Any]],
) -> None:
    """Persist one agent's history using its own session. Never raises.

    Called from the Engine's cleanup path, so it must not be able to fail a
    match that has already finished.
    """
    try:
        factory = get_session_factory()
        async with factory() as session:
            await match_agent_messages_service.store_messages(
                match_id, actor, messages, session
            )
    except Exception:
        logger.exception(
            f"Failed to store {actor} message history for match {match_id}"
        )
