from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.logger import get_logger

from .db import get_session_factory
from .models import Match, MatchEvent

logger = get_logger()

#: Columns of ``matches`` the Engine is allowed to supply.
_MATCH_COLUMNS = (
    "challenge_id",
    "prisoner_model",
    "prisoner_provider",
    "warden_model",
    "warden_provider",
    "status",
    "winner",
    "win_condition",
    "duration_seconds",
    "started_at",
    "finished_at",
)


async def store_match_activity(
    *,
    match_id: str,
    event_type: str,
    actor: str = "system",
    action: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
    match: dict[str, Any] | None = None,
) -> None:
    """Persist one match activity, optionally upserting its parent match row.

    ``actor``, ``event_type``, ``action``, ``result`` and ``timestamp`` become
    one ``match_events`` row. ``timestamp`` defaults to "now" but callers
    should pass the moment the activity actually happened.

    ``match`` is the Engine's authoritative snapshot of the parent ``matches``
    row. When supplied, the row is upserted, so ``match_started`` creates it and
    ``match_finished`` closes it out. Unknown keys are ignored.

    This function never raises.
    """

    occurred_at = timestamp or datetime.now(UTC)

    try:
        match_uuid = UUID(str(match_id))
    except (TypeError, ValueError):
        logger.error(
            f"Cannot persist match activity for non-UUID match id {match_id!r}"
        )
        return

    try:
        factory = get_session_factory()
        async with factory() as session:
            if match:
                values = {
                    key: value for key, value in match.items() if key in _MATCH_COLUMNS
                }
                statement = pg_insert(Match).values(id=match_uuid, **values)
                if values:
                    statement = statement.on_conflict_do_update(
                        index_elements=[Match.id],
                        set_={key: statement.excluded[key] for key in values},
                    )
                await session.execute(statement)
            session.add(
                MatchEvent(
                    match_id=match_uuid,
                    actor=actor,
                    event_type=event_type,
                    action=action or {},
                    result=result,
                    timestamp=occurred_at,
                )
            )
            await session.commit()
    except Exception:
        logger.exception(f"Failed to persist match activity for match {match_id}")
