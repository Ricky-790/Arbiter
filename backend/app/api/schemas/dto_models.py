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


class ForkMatchRequest(BaseModel):
    """Request body for ``POST /api/v1/matches/fork``.

    Only the branch point is given: a fork captures the match's state there,
    and the models are chosen later when a match is started from it.
    """

    parent_match_id: UUID
    match_event_id: UUID


class ForkSchema(BaseModel):
    """One saved fork: a point in a match a new match can be started from.

    A fork carries no models and never runs. It is a checkpoint — the match's
    sandbox at ``branch_event_id`` plus each agent's conversation up to there —
    which the fork page turns into whatever experiment the caller wants.
    """

    id: UUID
    parent_match_id: UUID
    branch_event_id: UUID
    branch_event_timestamp: datetime
    #: ``pending`` while the fork worker rebuilds it, then ``ready``/``failed``.
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ForkListResponse(PaginationMeta):
    """One page of saved forks, newest first."""

    items: list[ForkSchema]


class ForkDetailSchema(ForkSchema):
    """A fork plus everything the fork page needs to start a match from it.

    ``latest_turns`` is the tool-call history behind the fork point and the two
    conversations are what each agent already knew there. ``prisoner_model`` /
    ``warden_model`` are the *parent match's* models, offered as a starting
    point for the picker — the fork itself has none, and the caller is free to
    choose different ones.
    """

    challenge_id: UUID
    prisoner_model: str | None = None
    warden_model: str | None = None
    latest_turns: list[MatchEventSchema]
    prisoner_messages: list[dict[str, Any]] | None = None
    warden_messages: list[dict[str, Any]] | None = None


class StartForkMatchRequest(BaseModel):
    """Request body for ``POST /api/v1/matches/start-from-fork``.

    Same choices as ``start-match`` — models, tips, keys — but the challenge
    and the resumed state come from the fork, so there is no ``challenge_id``
    and no branch point.
    """

    fork_id: UUID
    prisoner_model: str
    warden_model: str
    prisoner_suggestions: str | None = None
    warden_suggestions: str | None = None
    prisoner_api_key: SecretStr | None = None
    warden_api_key: SecretStr | None = None


class AvailableModelsResponse(BaseModel):
    """Selectable models, split by whether the caller must supply a key.

    ``free_models`` run on this deployment's own provider keys; ``byok_models``
    need a key for that side in the start-match request.
    """

    free_models: list[str]
    byok_models: list[str]
