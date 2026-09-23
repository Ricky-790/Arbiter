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
    prisoner_model: str
    warden_model: str
    #: Optional operator tips, forwarded verbatim to the worker and appended to
    #: the matching agent's role instructions.
    prisoner_suggestions: str | None = None
    warden_suggestions: str | None = None
    #: Whether that side is using a BYOK model with a user-supplied key. The
    #: key itself never travels here -- only this reference does; the worker
    #: redeems it from :mod:`app.secrets` by ``match_id``.
    prisoner_byok: bool = False
    warden_byok: bool = False
    timeout_seconds: float | None = None
