"""Service for the `match_events` table."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session

from ..models import EVENT_ACTORS, EVENT_TYPES, MatchEvent


class MatchEventService:
    def get_match_events(self, match_id:UUID, session: AsyncSession):
        """Get all events in a match"""
        pass
