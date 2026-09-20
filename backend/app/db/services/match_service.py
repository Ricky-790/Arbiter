"""Service for the `matches` table."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session

from ..models import MATCH_STATUSES, MATCH_WINNERS, Match


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MatchService:
    def save_match_record(self, session: AsyncSession):
        pass
