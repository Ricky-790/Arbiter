"""Pydantic response schemas mirroring the database tables.

All schemas use ``from_attributes=True`` so they can be built directly from
ORM objects via ``Model.model_validate(...)`` and used as FastAPI
``response_model`` targets.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, SecretStr


class PaginationMeta(BaseModel):
    """Common paging envelope for list endpoints."""

    page: int
    page_size: int
    total: int
    pages: int


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
    challenge_type: str
    verification_config: dict[str, Any]
    flag: dict[str, Any]
    flag_structure: dict[str, Any]
    verifier_script: str | None
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
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)


class MatchListSchema(MatchSchema):
    """A match row plus the joined challenge name (archive list view)."""

    challenge_name: str | None = None


class MatchListResponse(PaginationMeta):
    """One page of matches, sorted by date."""

    items: list[MatchListSchema]


class MatchEventListResponse(PaginationMeta):
    """One page of a single match's events, sorted by date."""

    items: list[MatchEventSchema]


class StartMatchRequest(BaseModel):
    """Request body for ``POST /api/v1/matches/start-match``."""

    challenge_id: UUID
    prisoner_model: str
    warden_model: str
    #: Optional free-text tips appended to each agent's role instructions.
    prisoner_suggestions: str | None = None
    warden_suggestions: str | None = None
    #: BYOK provider keys for the side(s) using a BYOK model. Sent in the body,
    #: never stored on the match row, never logged, and never echoed back. They
    #: are held encrypted for the match only and handed to the worker by
    #: reference (see :mod:`app.secrets`).
    prisoner_api_key: SecretStr | None = None
    warden_api_key: SecretStr | None = None


class StartMatchResponse(BaseModel):
    """Acknowledged match request; the worker hosts it asynchronously."""

    match_id: UUID
    status: str


class AvailableModelsResponse(BaseModel):
    """Selectable models, split by whether the caller must supply a key.

    ``free_models`` run on this deployment's own provider keys; ``byok_models``
    need a key for that side in the start-match request.
    """

    free_models: list[str]
    byok_models: list[str]
