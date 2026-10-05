"""Opt-in live test: which escalations actually reach root, and for whom.

Privileges are enforced by the sandbox's own OS — sudoers and `/etc/shadow` —
so the only honest way to test them is against a real sandbox. A mocked one
would pass whatever the test believed.

Run only when deliberately authorized, because it creates a real sandbox:

    ARBITER_LIVE_SANDBOX=1 E2B_API_KEY=... \
        python -m unittest tests.test_privilege_boundaries -v

No model or provider key is needed: the calls are scripted, so this stays
deterministic and costs one sandbox rather than a whole match.
"""

import os
import unittest

from dotenv import load_dotenv

from app.agents.models import AgentType
from app.agents.tools import ToolCall
from app.engine import Engine
from app.sandbox.manager import SandboxManager
from app.sandbox.models import ChallengeSpec

load_dotenv()

MATCH_ID = "live-privilege-boundaries"

#: Payload every attempt ends with. ``id -u`` prints ``0`` only for root, so one
#: string is both the escalation and its own proof -- there is no way for an
#: error message to be mistaken for success.
PROOF = "id -u"

#: Escalations that reach root through ``sudo`` alone.
#:
#: Setup grants the Warden a ``NOPASSWD:ALL`` rule, which covers *all* of these:
#: they are not different privileges, only different spellings of the same
#: command. That is the point of the test -- a grant cannot be enforced by
#: matching the word "sudo" in a command string, because bash lets a command be
#: spelled an unbounded number of ways.
SUDO_ESCALATIONS: list[tuple[str, str]] = [
    ("plain", "sudo -n id -u"),
    ("without -n", "sudo id -u </dev/null"),
    ("absolute path", "/usr/bin/sudo -n id -u"),
    ("env wrapper", "env sudo -n id -u"),
    ("command builtin", "command sudo -n id -u"),
    ("quoted token", "s'u'do -n id -u"),
    ("backslash escape", "s\\udo -n id -u"),
    ("variable indirection", "X=sudo; $X -n id -u"),
    ("command substitution", "$(printf 'su')do -n id -u"),
    ("nested shell", "sh -c 'sudo -n id -u'"),
]

#: Escalations that reach root through ``su``, which no sudoers rule covers.
#: These work only if root can authenticate, so they are the check that setup
#: actually locked root's password rather than merely granting the Warden sudo.
SU_ESCALATIONS: list[tuple[str, str]] = [
    ("su, no password", "su -c 'id -u' root </dev/null"),
    ("su, absolute path", "/usr/bin/su -c 'id -u' root </dev/null"),
    ("su, variable indirection", "X=su; $X -c 'id -u' root </dev/null"),
]


def _live_test_skip_reason() -> str | None:
    """Why this test should not run, or ``None`` when it should.

    Deliberately gated on an explicit flag rather than on the key alone: the
    key sits in a developer's ``.env``, so keying off it would quietly create a
    real sandbox on every ordinary test run.
    """
    if os.getenv("ARBITER_LIVE_SANDBOX") != "1":
        return "set ARBITER_LIVE_SANDBOX=1 to run the live sandbox privilege test"
    if not os.getenv("E2B_API_KEY"):
        return "E2B_API_KEY is required for the live sandbox"
    return None


_SKIP_REASON = _live_test_skip_reason()


@unittest.skipIf(_SKIP_REASON is not None, _SKIP_REASON or "Live test disabled")
class PrivilegeBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.manager = SandboxManager()
        self.engine = Engine(
            match_id=MATCH_ID,
            challenge=ChallengeSpec(
                name="Privilege boundaries",
                description="Nothing to solve; the setup alone is under test.",
            ),
            sandbox_manager=self.manager,
            # Privileges are what is under test, so pacing must not be what
            # decides whether a call ever reaches the sandbox.
            cooldown_seconds=0,
        )
        await self.engine.start()

    async def asyncTearDown(self) -> None:
        await self.manager.destroy_sandbox(MATCH_ID)

    async def run_as(self, actor: AgentType, command: str) -> tuple[bool, str, str]:
        """One scripted tool call, through the real authorization path."""
        result = await self.engine.execute_tool_call(
            actor, ToolCall(name="bash", arguments={"command": command})
        )
        return result.success, result.output.strip(), (result.error or "").strip()

    async def test_each_side_runs_commands_as_itself(self) -> None:
        """Positive control: the shell works, and neither side starts as root."""
        for actor in (AgentType.PRISONER, AgentType.WARDEN):
            with self.subTest(side=actor.value):
                ok, out, err = await self.run_as(actor, PROOF)
                self.assertTrue(ok, f"{actor.value} could not run anything: {err}")
                # A uid, but not root's. Hardcoding 1001/1002 would break on an
                # image that numbers its default user differently.
                self.assertTrue(out.isdigit(), f"unexpected id output {out!r}")
                self.assertNotEqual(
                    out, "0", f"{actor.value} started the match as root"
                )

    async def test_the_warden_reaches_root_through_every_spelling_of_sudo(
        self,
    ) -> None:
        for label, command in SUDO_ESCALATIONS:
            with self.subTest(spelling=label):
                ok, out, err = await self.run_as(AgentType.WARDEN, command)
                self.assertTrue(ok, f"warden could not sudo ({label}): {err}")
                self.assertEqual(
                    out,
                    "0",
                    f"warden did not reach root via {label!r} ({command!r})",
                )

    async def test_the_prisoner_never_reaches_root_through_sudo(self) -> None:
        """The other half: the same spellings must all fail for the Prisoner."""
        for label, command in SUDO_ESCALATIONS:
            with self.subTest(spelling=label):
                ok, out, _ = await self.run_as(AgentType.PRISONER, command)
                self.assertFalse(ok, f"prisoner's sudo succeeded ({label})")
                self.assertNotEqual(
                    out, "0", f"prisoner reached root via {label!r} ({command!r})"
                )

    async def test_neither_side_reaches_root_through_su(self) -> None:
        """``su`` bypasses the sudoers policy, so it must be closed for both.

        This is what makes the Warden's sudo grant meaningful: without locking
        root's password, the Prisoner would simply run ``su root`` and the
        sudoers rule would never come into it.
        """
        for actor in (AgentType.PRISONER, AgentType.WARDEN):
            for label, command in SU_ESCALATIONS:
                with self.subTest(side=actor.value, spelling=label):
                    _, out, _ = await self.run_as(actor, command)
                    self.assertNotEqual(
                        out,
                        "0",
                        f"{actor.value} reached root via {label!r} ({command!r})",
                    )


if __name__ == "__main__":
    unittest.main()
