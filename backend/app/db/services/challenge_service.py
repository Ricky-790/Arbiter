"""Service for the `challenges` table."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Challenge


class ChallengeService:
    async def get_challenges_list(
        self, session: AsyncSession
    ) -> list[dict[str, Any]]:
        """Return id, name, description and win condition for all challenges."""
        result = await session.execute(
            select(
                Challenge.id,
                Challenge.name,
                Challenge.description,
                Challenge.win_condition,
            ).order_by(Challenge.created_at)
        )
        return [dict(row) for row in result.mappings()]

    async def get_challenge_by_id(
        self, challenge_id: UUID, session: AsyncSession
    ) -> Challenge | None:
        """Return the full challenge item for the given id"""
        return await session.get(Challenge, challenge_id)


challenges_service = ChallengeService()
