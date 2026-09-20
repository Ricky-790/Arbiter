"""Offline tests for the Redis event contract and worker spec mapping.

These do not need a running Redis or database: they pin the envelope shape
(``match_id`` must always be present), per-match channel naming, and the
translation from a persisted challenge to the Engine's ``ChallengeSpec``.
"""

import json
import unittest
from datetime import datetime, timezone
from uuid import uuid4

from app.broker.events import encode_match_event
from app.broker.redis import match_events_channel
from app.db.models import Challenge
from app.workers.match_worker import build_challenge_spec, default_timeout_seconds


class MatchEventEnvelopeTests(unittest.TestCase):
    def test_channel_is_scoped_by_match_id(self) -> None:
        first = str(uuid4())
        second = str(uuid4())

        self.assertIn(first, match_events_channel(first))
        self.assertNotEqual(
            match_events_channel(first), match_events_channel(second)
        )

    def test_envelope_carries_match_id_and_iso_timestamp(self) -> None:
        match_id = str(uuid4())

        payload = encode_match_event(
            match_id,
            {
                "type": "tool_result",
                "timestamp": datetime(2026, 1, 2, tzinfo=timezone.utc),
                "tool": "bash",
            },
        )

        self.assertEqual(
            json.loads(payload),
            {
                "match_id": match_id,
                "type": "tool_result",
                "timestamp": "2026-01-02T00:00:00+00:00",
                "tool": "bash",
            },
        )


class ChallengeSpecMappingTests(unittest.TestCase):
    def test_build_challenge_spec_maps_persisted_fields(self) -> None:
        challenge = Challenge(
            id=uuid4(),
            name="Protected secret",
            description="Find the flag",
            win_condition="prisoner_submits_flag",
            challenge_type="read_secret",
            verification_config={},
            flag={"value": "ARB{test}"},
            flag_structure={"value": "str"},
            verifier_script=None,
            sandbox_config={"cpu": 4, "mem_mb": 1024},
            files={"/root/secret.txt": "ARB{test}"},
            env_vars={"GREETING": "hi"},
        )

        spec = build_challenge_spec(challenge)

        self.assertEqual(spec.name, "Protected secret")
        self.assertEqual(spec.flag, {"value": "ARB{test}"})
        self.assertEqual(spec.flag_structure, {"value": "str"})
        self.assertIsNone(spec.verifier_script)
        self.assertEqual(spec.sandbox.cpu, 4)
        self.assertEqual(spec.sandbox.mem_mb, 1024)
        self.assertEqual(spec.sandbox.template, "base")
        self.assertEqual(spec.files, {"/root/secret.txt": "ARB{test}"})
        self.assertEqual(spec.environment, {"GREETING": "hi"})

    def test_build_challenge_spec_carries_verifier_script(self) -> None:
        challenge = Challenge(
            id=uuid4(),
            name="Stop the process",
            description="Stop the target process",
            win_condition="prisoner_submits_flag",
            challenge_type="stop_process",
            verification_config={},
            flag={"success": True, "process_id": "42"},
            flag_structure={"success": "bool", "process_id": "str"},
            verifier_script="pgrep -f target >/dev/null && echo '{\"success\": false}'",
            sandbox_config={},
            files={},
            env_vars={},
        )

        spec = build_challenge_spec(challenge)

        self.assertEqual(spec.flag_structure, {"success": "bool", "process_id": "str"})
        self.assertIn("pgrep", spec.verifier_script or "")

    def test_default_timeout_is_positive(self) -> None:
        self.assertGreater(default_timeout_seconds(), 0)


if __name__ == "__main__":
    unittest.main()
