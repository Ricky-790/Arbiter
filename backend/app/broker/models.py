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
    timeout_seconds: float | None = None
