"""Reviewer service: parsing helpers, invariants, and the read-only boundary.

Offline. The SQL queries themselves are exercised against a real PostgreSQL in
development; what is pinned here is the logic that decides what a caller sees,
plus the constraints that must not drift (no writes, no caller-supplied SQL, one
trap-tool list).
"""

import inspect
import unittest
from datetime import datetime, timezone

from app.reviewer import service
from app.reviewer.models import ConversationEntry
from app.reviewer.service import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    _Breakdown,
    _check_actor,
    _conversation_entries,
    _extract_strategy,
    _page,
    _page_bounds,
    _side_stats,
    _traps_armed,
)

#: The opening message the match worker builds, with a strategy and a hint.
BRIEFING = (
    "Win the match by completing the challenge and submitting the answer.\n"
    "Challenge: The Hidden Artifact\n"
    "Win condition: prisoner_submits_flag\n"
    "Try this strategy: Read the assemble script before touching the vault.\n"
    "Briefing: The artifact is not stored as one readable file.\n"
    "Submit your answer with submit_flag as a JSON object whose fields "
    'match this structure: {"value": "str"}'
)


class ExtractStrategyTests(unittest.TestCase):
    def test_the_strategy_is_read_out_of_the_briefing(self) -> None:
        self.assertEqual(
            _extract_strategy(BRIEFING),
            "Read the assemble script before touching the vault.",
        )

    def test_a_multi_line_strategy_is_kept_whole(self) -> None:
        briefing = (
            "Challenge: X\n"
            "Try this strategy: First look at the log.\n"
            "Then follow the shard order.\n"
            "Briefing: hint"
        )

        self.assertEqual(
            _extract_strategy(briefing),
            "First look at the log.\nThen follow the shard order.",
        )

    def test_a_multi_line_strategy_without_a_following_section_runs_to_the_end(
        self,
    ) -> None:
        briefing = "Try this strategy: one\nstill the strategy"

        self.assertEqual(_extract_strategy(briefing), "one\nstill the strategy")

    def test_the_no_strategy_placeholder_reads_as_none(self) -> None:
        briefing = "Try this strategy: No strategy provided, try everything you can."

        self.assertIsNone(_extract_strategy(briefing))

    def test_a_briefing_without_the_marker_reads_as_none(self) -> None:
        self.assertIsNone(_extract_strategy("Challenge: X\nWin condition: y"))

    def test_an_empty_strategy_reads_as_none(self) -> None:
        self.assertIsNone(_extract_strategy("Try this strategy:   \nBriefing: h"))

    def test_the_strategy_stops_before_the_submit_instructions(self) -> None:
        briefing = (
            "Try this strategy: look around\n"
            "Submit your answer with submit_flag when you have it."
        )

        self.assertEqual(_extract_strategy(briefing), "look around")


class PageBoundsTests(unittest.TestCase):
    def test_the_limit_is_clamped_to_the_ceiling(self) -> None:
        self.assertEqual(_page_bounds(0, 10_000)[1], MAX_LIMIT)

    def test_a_non_positive_limit_becomes_one(self) -> None:
        self.assertEqual(_page_bounds(0, 0)[1], 1)
        self.assertEqual(_page_bounds(0, -5)[1], 1)

    def test_a_negative_offset_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _page_bounds(-1, DEFAULT_LIMIT)

    def test_an_ordinary_request_passes_through(self) -> None:
        self.assertEqual(_page_bounds(40, 10), (40, 10))


class PageTests(unittest.TestCase):
    def test_has_more_reports_whether_more_rows_remain(self) -> None:
        self.assertTrue(_page([1, 2], 5, 0, 2).has_more)
        self.assertFalse(_page([4, 5], 5, 3, 2).has_more)

    def test_a_short_last_page_ends_the_walk(self) -> None:
        page = _page([9], 10, 9, 20)

        self.assertEqual(page.total, 10)
        self.assertFalse(page.has_more)


class ActorValidationTests(unittest.TestCase):
    def test_both_sides_are_accepted(self) -> None:
        for actor in ("prisoner", "warden"):
            with self.subTest(actor=actor):
                self.assertEqual(_check_actor(actor), actor)

    def test_anything_else_is_rejected(self) -> None:
        """``actor`` is a choice, never a value handed to the database."""
        for actor in ("system", "PRISONER", "", "prisoner'; DROP TABLE matches--"):
            with self.subTest(actor=actor), self.assertRaises(ValueError):
                _check_actor(actor)


class ConversationEntryTests(unittest.TestCase):
    """The stored pydantic-ai dump is flattened into readable steps."""

    def test_each_part_becomes_one_indexed_entry(self) -> None:
        messages = [
            {
                "kind": "request",
                "parts": [
                    {"part_kind": "system-prompt", "content": "sys"},
                    {"part_kind": "user-prompt", "content": "go"},
                ],
            },
            {
                "kind": "response",
                "parts": [
                    {"part_kind": "text", "content": "looking around"},
                    {
                        "part_kind": "tool-call",
                        "tool_name": "bash",
                        "args": {"command": "id"},
                        "tool_call_id": "c1",
                    },
                ],
            },
            {
                "kind": "request",
                "parts": [
                    {
                        "part_kind": "tool-return",
                        "tool_name": "bash",
                        "content": "uid=0",
                        "tool_call_id": "c1",
                    }
                ],
            },
        ]

        entries = _conversation_entries(messages)

        self.assertEqual([entry.index for entry in entries], [0, 1, 2, 3, 4])
        self.assertEqual(
            [entry.kind for entry in entries],
            ["system-prompt", "user-prompt", "text", "tool-call", "tool-return"],
        )

    def test_a_tool_call_keeps_its_arguments_and_id(self) -> None:
        entries = _conversation_entries(
            [
                {
                    "parts": [
                        {
                            "part_kind": "tool-call",
                            "tool_name": "bash",
                            "args": {"command": "id"},
                            "tool_call_id": "c1",
                        }
                    ]
                }
            ]
        )

        self.assertEqual(entries[0].tool_name, "bash")
        self.assertEqual(entries[0].tool_call_id, "c1")
        self.assertEqual(entries[0].content, {"command": "id"})

    def test_an_unknown_part_kind_is_reported_not_dropped(self) -> None:
        entries = _conversation_entries([{"parts": [{"part_kind": "brand-new"}]}])

        self.assertEqual(entries[0].kind, "brand-new")

    def test_a_message_with_no_parts_is_tolerated(self) -> None:
        self.assertEqual(_conversation_entries([{"parts": None}]), [])

    def test_entries_are_json_safe(self) -> None:
        entry = ConversationEntry(index=0, kind="text", text="hi")

        self.assertEqual(entry.model_dump()["text"], "hi")


class SideStatsSourcingTests(unittest.TestCase):
    """The Engine's stored summary is the record; events are the fallback."""

    def breakdown(self) -> "_Breakdown":
        b = _Breakdown()
        b.by_name = {"bash": 2}
        b.successful = 2
        b.total = 2
        return b

    def test_the_stored_summary_is_preferred(self) -> None:
        stats = _side_stats(
            "prisoner",
            {"credits": 12, "tool_calls": 7, "times_trapped": 2},
            self.breakdown(),
            traps_triggered=99,
        )

        self.assertEqual(stats.credits_remaining, 12)
        self.assertEqual(stats.tool_calls, 7)
        self.assertEqual(stats.times_trapped, 2)

    def test_a_missing_summary_falls_back_to_counted_events(self) -> None:
        """Older matches have no summary, and must still report trap activity."""
        stats = _side_stats("prisoner", None, self.breakdown(), traps_triggered=3)

        self.assertIsNone(stats.credits_remaining)
        self.assertIsNone(stats.tool_calls)
        self.assertEqual(stats.times_trapped, 3)

    def test_the_warden_carries_the_traps_it_set(self) -> None:
        stats = _side_stats(
            "warden",
            {"credits": 40, "traps_armed": 2, "traps_triggered": 1},
            self.breakdown(),
            traps_triggered=9,
            traps_armed=9,
        )

        self.assertEqual(stats.traps_armed, 2)
        self.assertEqual(stats.traps_triggered, 1)
        # The Prisoner's counter is not the Warden's to report.
        self.assertIsNone(stats.times_trapped)

    def test_the_prisoner_carries_no_warden_counters(self) -> None:
        stats = _side_stats(
            "prisoner", {"times_trapped": 1}, self.breakdown(), traps_triggered=1
        )

        self.assertIsNone(stats.traps_armed)
        self.assertIsNone(stats.traps_triggered)

    def test_a_player_with_no_summary_still_gets_derived_trap_counts(self) -> None:
        warden = _side_stats(
            "warden", None, self.breakdown(), traps_triggered=4, traps_armed=2
        )

        self.assertEqual(warden.traps_armed, 2)
        self.assertEqual(warden.traps_triggered, 4)


class TrapEventDetailTests(unittest.TestCase):
    def test_a_firing_carries_its_target_and_turns(self) -> None:
        from uuid import uuid4

        from app.reviewer.models import TrapEvent

        event = TrapEvent(
            event_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            trap="auto_kill",
            target="worker",
            prisoner_turn=1,
            warden_turn=2,
        )

        self.assertEqual(event.target, "worker")
        self.assertEqual(event.prisoner_turn, 1)

    def test_the_detail_is_optional_for_older_rows(self) -> None:
        from uuid import uuid4

        from app.reviewer.models import TrapEvent

        event = TrapEvent(
            event_id=uuid4(), timestamp=datetime.now(timezone.utc), trap="watch_file"
        )

        self.assertIsNone(event.target)
        self.assertIsNone(event.prisoner_turn)


class TrapsArmedTests(unittest.TestCase):
    """A trap counts as armed only if arming it actually succeeded."""

    def test_a_successful_trap_tool_counts(self) -> None:
        warden = _Breakdown()
        warden.successful_by_name = {"auto_kill": 1}

        self.assertEqual(_traps_armed({"warden": warden}), 1)

    def test_a_rejected_arming_does_not_count(self) -> None:
        """The Engine refused it, so no trap was left behind."""
        warden = _Breakdown()
        warden.by_name = {"watch_file": 1}
        warden.rejected = 1

        self.assertEqual(_traps_armed({"warden": warden}), 0)

    def test_a_failed_arming_does_not_count(self) -> None:
        warden = _Breakdown()
        warden.by_name = {"auto_kill": 1}
        warden.failed = 1

        self.assertEqual(_traps_armed({"warden": warden}), 0)

    def test_a_non_trap_tool_does_not_count(self) -> None:
        warden = _Breakdown()
        warden.successful_by_name = {"bash": 5, "kill_process": 2}

        self.assertEqual(_traps_armed({"warden": warden}), 0)

    def test_only_the_warden_arms_traps(self) -> None:
        prisoner = _Breakdown()
        prisoner.successful_by_name = {"watch_file": 3}

        self.assertEqual(_traps_armed({"prisoner": prisoner}), 0)

    def test_an_empty_breakdown_is_zero(self) -> None:
        self.assertEqual(_traps_armed({}), 0)


class ReviewerIsReadOnlyTests(unittest.TestCase):
    """The boundary the whole package rests on, checked mechanically."""

    def test_no_function_commits_or_writes(self) -> None:
        source = inspect.getsource(service)
        for forbidden in ("commit(", "session.add(", "insert(", "update(", "delete("):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_no_function_takes_sql(self) -> None:
        """A caller picks the question, never how it is spelled."""
        for name in service.__all__:
            function = getattr(service, name, None)
            if function is None or not callable(function):
                continue
            parameters = inspect.signature(function).parameters
            with self.subTest(function=name):
                for banned in ("sql", "query", "where", "table", "column"):
                    self.assertNotIn(banned, parameters)

    def test_every_public_function_is_a_coroutine(self) -> None:
        for name in service.__all__:
            function = getattr(service, name, None)
            if function is None or not callable(function):
                continue
            with self.subTest(function=name):
                self.assertTrue(inspect.iscoroutinefunction(function))


class TrapToolNamesTests(unittest.TestCase):
    def test_the_copy_matches_the_engine(self) -> None:
        """Duplicated to keep the runtime out of a read-only reader.

        Importing ``app.engine`` pulls the whole match runtime in, so the list
        is copied instead. This is what stops the copy drifting.
        """
        from app.engine.traps import TRAP_TOOL_NAMES

        self.assertEqual(service.TRAP_TOOL_NAMES, TRAP_TOOL_NAMES)


if __name__ == "__main__":
    unittest.main()
