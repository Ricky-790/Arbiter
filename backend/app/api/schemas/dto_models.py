"""Pydantic response schemas mirroring the database tables.

All schemas use ``from_attributes=True`` so they can be built directly from
ORM objects via ``Model.model_validate(...)`` and used as FastAPI
``response_model`` targets.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.reviewer.models import AgentBriefing, MatchOverview, Page, SideStats

#: The two sides of a match, as the API names them. Used wherever a request
#: or response is scoped to one side.
MatchSide = Literal["prisoner", "warden"]


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
    #: Optional strategy ids from the library. A side given one is started with
    #: that strategy instead of its suggestions, and the strategy is copied onto
    #: the new match so it can be promoted again later.
    prisoner_strategy_id: UUID | None = None
    warden_strategy_id: UUID | None = None
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
    prisoner_strategy_id: UUID | None = None
    warden_strategy_id: UUID | None = None
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


class SaveStrategyRequest(BaseModel):
    """Request body for ``POST /api/v1/strategies/save-strategy``.

    Promotes one side's strategy out of a match into the library. The strategy
    text is not sent: it is read off the match row, so what is saved is exactly
    what the match ran.
    """

    match_id: UUID
    user: MatchSide


class StrategySchema(BaseModel):
    """One saved strategy, promoted from one side of one match.

    ``origin_strat_id`` is the strategy this one evolved from, when the match
    was itself started from a library strategy.

    ``challenge_name`` is joined in for display, because a strategy is only
    meaningful against the challenge it was played on and an id alone does not
    say which one that is.
    """

    id: UUID
    match_id: UUID
    challenge_id: UUID
    challenge_name: str | None = None
    user: str
    one_line_description: str
    strategy: str
    origin_strat_id: UUID | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StrategyMatchSummary(BaseModel):
    """The few facts about a match that a strategy's lineage needs.

    Deliberately not the whole match: a strategy can be used many times, and a
    lineage view wants to list them, not carry each one's history. A model pair,
    the challenge it was played on, and who won is enough to tell the runs apart
    and to see which wording is actually winning.
    """

    match_id: UUID
    challenge_name: str | None = None
    prisoner_model: str
    warden_model: str
    winner: str | None = None


class StrategyDetailResponse(BaseModel):
    """One saved strategy, the match it came from, and where it has been used.

    ``parent_match`` is the match the strategy was promoted *from*, so its
    wording can be read in context. ``used_in_matches`` is a page of the matches
    that were started from it, newest first -- the parent is not among them.

    ``used_in_matches`` is paged like every other listing: a strategy can be
    reused indefinitely, and this endpoint would otherwise grow without bound.
    """

    strategy: StrategySchema
    parent_match: StrategyMatchSummary | None = None
    used_in_matches: Page[StrategyMatchSummary]


class ReviewStrategyRequest(BaseModel):
    """Request body for ``POST /api/v1/strategies/review``.

    Names the strategy to improve and the match to review it against, plus the
    model and key that will do the reviewing. The reviewer is BYOK like every
    other model here, and the key travels in the body rather than the query
    string so it cannot reach a URL, a log, or browser history.

    The result is streamed and never stored: the caller decides what to do with
    the proposed strategy.
    """

    strategy_id: UUID
    match_id: UUID
    provider: str
    model: str
    api_key: SecretStr | None = None


class MatchSummaryResponse(BaseModel):
    """One call's worth of the *small* things a reviewer needs about one side.

    Everything here is per-match and bounded: the match row, one side's totals,
    its strategy, and its opening message. Nothing that grows with the length of
    the match is included -- conversations, tool calls, narration, trap firings
    and raw events each have their own paginated endpoint -- so a dashboard can
    render its summary without pulling a whole match into memory, and a reviewer
    agent can ask for only the detail it needs.

    ``user`` is the side this entry is about, and everything here is that side's:
    there is deliberately no opponent block. When a caller wants both sides,
    ``/summary`` returns one entry per side, so the comparison is two entries of
    the same shape rather than two differently-scoped fields on one object.
    ``match`` is the shared match row, carrying the full ``strategy`` map for
    context.
    """

    match: MatchOverview
    user: MatchSide
    #: This side's spend and activity.
    stats: SideStats
    #: This side's strategy, exactly as the match ran it. ``None`` when it was
    #: started without one. A convenience view of ``match.strategy[user]``,
    #: which holds both sides.
    strategy: str | None = None
    #: Which trap tool fired, and how often. Shared, not per-side: a firing is
    #: one event that both sides appear in.
    triggered_trap_tools: dict[str, int] = Field(default_factory=dict)
    #: The opening message that side was given, when its conversation is stored.
    #: Carries the challenge's role hint as well as the strategy.
    briefing: AgentBriefing | None = None
