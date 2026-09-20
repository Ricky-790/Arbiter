"""Pydantic response schemas mirroring the database tables.

All schemas use ``from_attributes=True`` so they can be built directly from
ORM objects via ``Model.model_validate(...)`` and used as FastAPI
``response_model`` targets.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ChallengeSummary(BaseModel):
    """List view: id, name, description and win condition only."""

    id: UUID
    name: str
    description: str
    win_condition: str

    model_config = ConfigDict(from_attributes=True)


class ChallengeSchema(BaseModel):
    """Full challenge row."""

    id: UUID
    name: str
    description: str
    win_condition: str
    sandbox_config: dict[str, Any]
    files: dict[str, Any]
    env_vars: dict[str, Any]
    setup_script: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MatchSchema(BaseModel):
    """Full match row."""

    id: UUID
    challenge_id: UUID
    prisoner_model: str
    prisoner_provider: str
    warden_model: str
    warden_provider: str
    status: str
    winner: str | None
    win_condition: str
    duration_seconds: float | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MatchEventSchema(BaseModel):
    """Full match event row."""

    id: UUID
    match_id: UUID
    actor: str
    event_type: str
    action: dict[str, Any]
    result: dict[str, Any] | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    latency_ms: float | None
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)


class StartMatchRequest(BaseModel):
    """Request body for ``POST /api/v1/matches/start-match``."""

    challenge_id: UUID
    prisoner_model: str
    warden_model: str


class StartMatchResponse(BaseModel):
    """Acknowledged match request; the worker hosts it asynchronously."""

    match_id: UUID
    status: str
