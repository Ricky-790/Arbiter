"""Challenge endpoints (boilerplate; no logic yet)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.dto_models import ChallengeSummary
from app.db import get_session
from app.db.services import challenges_service

router = APIRouter(prefix="/api/v1/challenges", tags=["challenges"])


@router.get("/", response_model=list[ChallengeSummary])
async def list_challenges(
    session: AsyncSession = Depends(get_session),
) -> list[ChallengeSummary]:
    challenges = await challenges_service.get_challenges_list(session=session)
    return [ChallengeSummary.model_validate(c) for c in challenges]
