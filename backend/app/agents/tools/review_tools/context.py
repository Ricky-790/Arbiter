"""What the review tools are allowed to know: which match is under review.

The model never supplies a match id. It is fixed here before the agent runs and
handed to every tool, so nothing the model writes can point a review at another
match, or at none.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ReviewContext:
    """The one match a review run may read.

    Deliberately just an id: the tools go through ``app.reviewer`` for every
    read, and that package is the thing that decides what is readable. Nothing
    here grants access to anything else.
    """

    match_id: UUID
