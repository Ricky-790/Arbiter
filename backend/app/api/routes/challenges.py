"""Challenge endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.dto_models import ChallengeSchema, ChallengeSummary
from app.db import get_session
from app.db.services import challenges_service

router = APIRouter(prefix="/api/v1/challenges", tags=["challenges"])


@router.get("/", response_model=list[ChallengeSummary])
async def list_challenges(
    session: AsyncSession = Depends(get_session),
) -> list[ChallengeSummary]:
    challenges = await challenges_service.get_challenges_list(session=session)
    return [ChallengeSummary.model_validate(c) for c in challenges]


@router.get("/challenge", response_model=ChallengeSchema)
async def get_challenge(
    challenge_id: UUID = Query(...),
    session: AsyncSession = Depends(get_session),
) -> ChallengeSchema:
    """Return the full challenge row for ``challenge_id``."""
    challenge = await challenges_service.get_challenge_by_id(
        challenge_id, session=session
    )
    if challenge is None:
        raise HTTPException(status_code=404, detail="Challenge not found")
    return ChallengeSchema.model_validate(challenge)
