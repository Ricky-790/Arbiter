"""Worker entrypoint smoke tests.

The Celery task bodies are the one part of the worker path nothing else
exercises: a missing import or a renamed symbol there only shows up when a real
match is queued. These call the task functions directly with the work they hand
off stubbed out, so they need no Redis, Postgres, or worker process.

``reset_session_state()`` is deliberately *not* stubbed. It touches no I/O, and
leaving it real is what makes this catch a dropped import -- the exact mistake
these tests exist for.
"""

import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.agents.agents_directory import PROVIDER_MODELS, join_model_name
from app.workers import fork_worker, match_worker
from app.workers.celery_app import (
    CREATE_FORK_TASK,
    FORK_QUEUE,
    MATCH_QUEUE,
    START_MATCH_TASK,
    celery_app,
)


def match_payload() -> dict[str, str]:
    return {
        "match_id": str(uuid4()),
        "challenge_id": str(uuid4()),
        "prisoner_provider": "openai",
        "prisoner_model": "gpt-4o-mini",
        "warden_provider": "google",
        "warden_model": "gemini-2.0-flash",
    }


def fork_payload() -> dict[str, str]:
    return {
        "fork_id": str(uuid4()),
        "parent_match_id": str(uuid4()),
        "branch_event_id": str(uuid4()),
    }


class MatchTaskEntrypointTests(unittest.TestCase):
    def test_start_match_task_reaches_the_match_body(self) -> None:
        """Guards every name the task body touches before it does any work."""
        with patch.object(
            match_worker, "run_match", new=AsyncMock(return_value={"status": "ok"})
        ) as run_match:
            result = match_worker.start_match_task(**match_payload())

        self.assertEqual(result, {"status": "ok"})
        run_match.assert_awaited_once()


class ForkTaskEntrypointTests(unittest.TestCase):
    def test_create_fork_task_reaches_the_build_body(self) -> None:
        with patch.object(
            fork_worker,
            "build_fork",
            new=AsyncMock(return_value={"snapshots_built": 0}),
        ) as build_fork:
            result = fork_worker.create_fork_task(**fork_payload())

        self.assertEqual(result, {"snapshots_built": 0})
        build_fork.assert_awaited_once()


class WorkerRoutingTests(unittest.TestCase):
    def test_each_pool_has_its_own_queue_and_task(self) -> None:
        """The fork pool must not share a queue with the match pool."""
        self.assertNotEqual(MATCH_QUEUE, FORK_QUEUE)
        self.assertEqual(
            celery_app.conf.task_routes[CREATE_FORK_TASK]["queue"], FORK_QUEUE
        )
        self.assertIn(START_MATCH_TASK, celery_app.tasks)
        self.assertIn(CREATE_FORK_TASK, celery_app.tasks)


class ForkModelInheritanceTests(unittest.TestCase):
    """A fork inherits models, so the row's split columns must rejoin exactly.

    The match row stores the provider and the bare model separately, and the
    agent runtime resolves the joined ``provider:model``. A fork reads the
    parent's two columns back, so the join has to round-trip every pair the
    catalogue offers.
    """

    def test_every_catalogue_pair_round_trips(self) -> None:
        for provider, models in PROVIDER_MODELS.items():
            for model in models:
                with self.subTest(provider=provider, model=model):
                    self.assertEqual(
                        join_model_name(provider, model), f"{provider}:{model}"
                    )

    def test_an_openrouter_pair_keeps_its_slash(self) -> None:
        name = join_model_name("openrouter", "meta-llama/llama-3.3-70b-instruct")

        self.assertEqual(name, "openrouter:meta-llama/llama-3.3-70b-instruct")

    def test_an_unknown_provider_joins_to_nothing(self) -> None:
        self.assertIsNone(join_model_name("nvidia", "not-a-real-model"))

    def test_an_uncurated_model_still_joins(self) -> None:
        """The curated list is suggestions; the provider decides what is real."""
        self.assertEqual(
            join_model_name("openai", "a-model-we-have-not-curated"),
            "openai:a-model-we-have-not-curated",
        )


if __name__ == "__main__":
    unittest.main()
