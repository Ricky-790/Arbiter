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

from app.agents.agents_directory import (
    BYOK_MODEL_NAMES,
    agent_mapper,
    join_model_name,
    split_model_name,
)
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
        "prisoner_model": "nvidia/glm-5.3",
        "warden_model": "nvidia/glm-5.3",
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


#: Names offered as both ``provider/model`` (free) and ``provider:model``
#: (BYOK), so a match row's split pair cannot say which one it came from.
AMBIGUOUS_NAMES = {"google:gemini-3.1-flash-lite"}


class ForkModelInheritanceTests(unittest.TestCase):
    """A fork inherits models, so the row's split columns must rejoin exactly.

    This is the regression guard for free models being refused a fork: the join
    used to check the BYOK form first, and ``provider:model`` parses for any
    known provider prefix, so free OpenRouter and Google models came back as
    BYOK and were rejected as unforkable.
    """

    def test_every_free_model_round_trips(self) -> None:
        for name in agent_mapper:
            with self.subTest(name=name):
                provider, model = split_model_name(name)
                self.assertEqual(join_model_name(provider, model), name)

    def test_every_unambiguous_byok_model_round_trips(self) -> None:
        for name in BYOK_MODEL_NAMES:
            if name in AMBIGUOUS_NAMES:
                continue
            with self.subTest(name=name):
                provider, model = split_model_name(name)
                self.assertEqual(join_model_name(provider, model), name)

    def test_a_pair_in_both_catalogues_resolves_to_the_free_model(self) -> None:
        """Pins a known limitation: the row stores only the split halves.

        Derived from the catalogues rather than hardcoded, so adding or
        removing a model does not make this fail for the wrong reason.
        """
        collisions = []
        for name in BYOK_MODEL_NAMES:
            provider, _, model = name.partition(":")
            if provider and model and f"{provider}/{model}" in agent_mapper:
                collisions.append((provider, model))
        if not collisions:
            self.skipTest("no name is offered as both free and BYOK")

        for provider, model in collisions:
            with self.subTest(name=f"{provider}:{model}"):
                self.assertEqual(
                    join_model_name(provider, model), f"{provider}/{model}"
                )

    def test_a_model_that_left_the_catalogue_joins_to_nothing(self) -> None:
        self.assertIsNone(join_model_name("nvidia", "not-a-real-model"))


if __name__ == "__main__":
    unittest.main()
