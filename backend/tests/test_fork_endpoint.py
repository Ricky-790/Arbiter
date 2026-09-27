"""Fork endpoint tests.

The finished-only rule is a state check on the parent row, so it needs no
Redis, no Postgres, and nothing queued: a stub session that answers the parent
lookup is enough to drive the route up to its first real write.
"""

import unittest
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException

from app.api.routes.matches import fork_match
from app.api.schemas.dto_models import ForkMatchRequest
from app.db.models import MATCH_STATUSES, MATCH_TERMINAL_STATUSES, Match


class FakeSession:
    """Only what the fork route reads before it reaches the queue."""

    def __init__(self, match: object) -> None:
        self._match = match

    async def get(self, model: object, key: object) -> object:
        if model is Match:
            return self._match
        # Any later lookup (the branch event) misses.
        return None


def payload() -> ForkMatchRequest:
    return ForkMatchRequest(parent_match_id=uuid4(), match_event_id=uuid4())


def parent(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": uuid4(),
        "status": "completed",
        "challenge_id": uuid4(),
        "prisoner_model": "glm-5.3",
        "prisoner_provider": "nvidia",
        "warden_model": "glm-5.3",
        "warden_provider": "nvidia",
        "win_condition": "w",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class ForkableStatusVocabularyTests(unittest.TestCase):
    def test_the_forkable_statuses_are_exactly_the_finished_ones(self) -> None:
        """Pins the set: widening it later must be a deliberate edit here."""
        self.assertEqual(
            MATCH_TERMINAL_STATUSES, {"completed", "failed", "cancelled"}
        )
        self.assertTrue(MATCH_TERMINAL_STATUSES <= set(MATCH_STATUSES))


class ForkStatusGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_unknown_parent_is_not_found(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            await fork_match(payload(), session=FakeSession(None))

        self.assertEqual(raised.exception.status_code, 404)

    async def test_a_running_match_cannot_be_forked(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            await fork_match(payload(), session=FakeSession(parent(status="running")))

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("has finished", raised.exception.detail)

    async def test_a_fork_still_building_its_snapshot_cannot_be_forked(self) -> None:
        """``pending`` is unfinished work, not a settled parent."""
        with self.assertRaises(HTTPException) as raised:
            await fork_match(payload(), session=FakeSession(parent(status="pending")))

        self.assertEqual(raised.exception.status_code, 409)

    async def test_a_finished_match_passes_the_gate(self) -> None:
        """Stops at the missing branch event (400), having cleared the status."""
        with self.assertRaises(HTTPException) as raised:
            await fork_match(
                payload(), session=FakeSession(parent(status="completed"))
            )

        self.assertEqual(raised.exception.status_code, 400)

    async def test_every_terminal_status_clears_the_gate(self) -> None:
        for status in sorted(MATCH_TERMINAL_STATUSES):
            with self.subTest(status=status):
                with self.assertRaises(HTTPException) as raised:
                    await fork_match(
                        payload(), session=FakeSession(parent(status=status))
                    )

                self.assertEqual(raised.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
