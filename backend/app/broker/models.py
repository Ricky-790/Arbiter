"""Message contracts passed over Redis between the API and the workers."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class MatchStartMessage(BaseModel):
    """A queued request to host one match.

    The API assigns ``match_id`` before enqueueing so it can hand the id back
    to the caller immediately; spectators subscribe to that id while the
    worker is still booting the sandbox.
    """

    match_id: UUID
    challenge_id: UUID
    #: Provider and bare model name per side, kept separate as the API receives
    #: and the ``matches`` row stores them. The worker joins them into the
    #: canonical ``provider:model`` the agent runtime resolves.
    prisoner_provider: str
    prisoner_model: str
    warden_provider: str
    warden_model: str
    #: Optional operator tips, forwarded verbatim to the worker and appended to
    #: the matching agent's role instructions.
    prisoner_suggestions: str | None = None
    warden_suggestions: str | None = None
    #: The API stores one key per side before enqueueing. The keys themselves
    #: never travel here; the worker redeems them from :mod:`app.secrets` by
    #: ``match_id``.
    timeout_seconds: float | None = None


class ForkCreateMessage(BaseModel):
    """A queued request to build one saved fork.

    Consumed by the fork worker, which is separate from the match worker: it
    rebuilds a match's state at a branch point, snapshots it, and records the
    conversations each agent had up to there. It never starts a match -- a
    match is started later, from the fork.
    """

    fork_id: UUID
    parent_match_id: UUID
    branch_event_id: UUID
