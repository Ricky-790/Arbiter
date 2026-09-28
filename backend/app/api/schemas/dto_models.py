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
    """Request body for ``POST /api/v1/matches/start-match``.

    Each side names a provider and a model separately, matching how the picker
    asks for them and how the ``matches`` row stores them.
    """

    challenge_id: UUID
    prisoner_provider: str
    prisoner_model: str
    warden_provider: str
    warden_model: str
    #: Optional free-text tips appended to each agent's role instructions.
    prisoner_suggestions: str | None = None
    warden_suggestions: str | None = None
    #: Provider keys, one per side. Every model is BYOK, so both are required.
    #: Sent in the body, never stored on the match row, never logged, and never
    #: echoed back. They are held encrypted for the match only and handed to the
    #: worker by reference (see :mod:`app.secrets`).
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
    conversations are what each agent already knew there. The provider/model
    fields are the *parent match's* choices, offered as a starting point for the
    picker — the fork itself has none, and the caller is free to choose
    different ones.
    """

    challenge_id: UUID
    prisoner_provider: str | None = None
    prisoner_model: str | None = None
    warden_provider: str | None = None
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
    prisoner_provider: str
    prisoner_model: str
    warden_provider: str
    warden_model: str
    prisoner_suggestions: str | None = None
    warden_suggestions: str | None = None
    prisoner_api_key: SecretStr | None = None
    warden_api_key: SecretStr | None = None


class ProviderModels(BaseModel):
    """One provider and the models it offers, in display order."""

    provider: str
    models: list[str]


class AvailableModelsResponse(BaseModel):
    """The selectable catalogue: providers, each with its own models.

    The picker chooses a provider first and then a model from that provider's
    list, so the two are kept separate rather than flattened into combined
    names. These models are *suggestions*: the picker also accepts a pasted
    name, which is confirmed with the provider by ``POST /matches/verify-model``.
    """

    providers: list[ProviderModels]


class ModelCheckRequest(BaseModel):
    """Request body for ``POST /api/v1/matches/verify-model``.

    Asks whether a provider serves a given model. Sent in the body, never as a
    query parameter, so the key cannot end up in a URL, a log or browser
    history.
    """

    provider: str
    model: str
    api_key: SecretStr


class ModelCheckResponse(BaseModel):
    """Whether a pasted model name was confirmed with its provider.

    ``exists`` false is a normal answer rather than an error, so the UI can show
    the reason beside the field. ``reason`` is ``not_found`` (the provider
    answered and does not serve it), ``key_rejected`` (the credential was
    refused) or ``unreachable`` (the provider could not be asked). Never carries
    the key, or any text echoed back from the provider.
    """

    exists: bool
    reason: str | None = None
    detail: str | None = None
