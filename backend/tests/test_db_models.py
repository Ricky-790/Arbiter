"""DB model tests: metadata shape + PostgreSQL DDL validity (no live DB)."""

import unittest

from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db.models import (
    Base,
    Challenge,
    Match,
    MatchAgentMessages,
    MatchEvent,
    MatchFork,
    Strategy,
)


class DbModelTests(unittest.TestCase):
    def test_all_tables_registered(self) -> None:
        self.assertEqual(
            set(Base.metadata.tables),
            {
                "challenges",
                "match_agent_messages",
                "match_events",
                "match_forks",
                "matches",
                "strategies",
            },
        )

    def test_challenges_columns(self) -> None:
        cols = Challenge.__table__.columns
        self.assertEqual(
            [c.name for c in cols],
            [
                "id",
                "name",
                "description",
                "win_condition",
                "challenge_type",
                "verification_config",
                "flag",
                "flag_structure",
                "verifier_script",
                "sandbox_config",
                "files",
                "env_vars",
                "setup_script",
                "created_at",
                "updated_at",
                "prisoner_hint",
                "warden_hint",
            ],
        )
        self.assertFalse(cols["setup_script"].nullable is False)
        self.assertTrue(cols["verifier_script"].nullable)
        # The role briefings are optional, so a challenge need not author them.
        self.assertTrue(cols["prisoner_hint"].nullable)
        self.assertTrue(cols["warden_hint"].nullable)
        for name in (
            "verification_config",
            "flag",
            "flag_structure",
            "sandbox_config",
            "files",
            "env_vars",
        ):
            self.assertIsInstance(cols[name].type, postgresql.JSONB)

    def test_matches_columns_and_fks(self) -> None:
        cols = Match.__table__.columns
        self.assertTrue(cols["challenge_id"].nullable is False)
        self.assertTrue(cols["parent_match_id"].nullable)
        self.assertTrue(cols["branch_event_id"].nullable)
        fks = {fk.parent.name: fk.column.table.name for fk in Match.__table__.foreign_keys}
        self.assertEqual(
            fks,
            {
                "challenge_id": "challenges",
                "parent_match_id": "matches",
                "branch_event_id": "match_events",
            },
        )
        self.assertTrue(cols["winner"].nullable)
        self.assertTrue(cols["duration_seconds"].nullable)
        for indexed in (
            "challenge_id",
            "status",
            "winner",
            "created_at",
            "parent_match_id",
            "branch_event_id",
        ):
            self.assertTrue(cols[indexed].index, indexed)
        # status/winner stay plain VARCHAR until asked to change.
        self.assertIsInstance(cols["status"].type, type(cols["winner"].type))

    def test_match_strategy_columns_are_nullable_jsonb(self) -> None:
        """Both are written after the row exists, so neither can be NOT NULL."""
        cols = Match.__table__.columns
        for name in ("strategy", "strategy_id"):
            self.assertIsInstance(cols[name].type, postgresql.JSONB, name)
            self.assertTrue(cols[name].nullable, name)

    def test_strategy_table_columns_and_unique_key(self) -> None:
        table = Strategy.__table__
        self.assertFalse(table.columns["match_id"].nullable)
        self.assertFalse(table.columns["challenge_id"].nullable)
        self.assertFalse(table.columns["user"].nullable)
        self.assertFalse(table.columns["one_line_description"].nullable)
        self.assertFalse(table.columns["strategy"].nullable)
        # Lineage is optional: the first strategy of a line has no ancestor.
        self.assertTrue(table.columns["origin_strat_id"].nullable)
        self.assertEqual(
            {fk.parent.name: fk.column.table.name for fk in table.foreign_keys},
            {
                "match_id": "matches",
                "challenge_id": "challenges",
                "origin_strat_id": "strategies",
            },
        )
        self.assertEqual(
            {
                tuple(column.name for column in constraint.columns)
                for constraint in table.constraints
                if isinstance(constraint, UniqueConstraint)
            },
            {("match_id", "user")},
        )

    def test_match_events_columns_and_composite_index(self) -> None:
        cols = MatchEvent.__table__.columns
        fks = {fk.parent.name: fk.column.table.name for fk in MatchEvent.__table__.foreign_keys}
        self.assertEqual(fks, {"match_id": "matches"})
        self.assertFalse(cols["action"].nullable)
        self.assertTrue(cols["result"].nullable)
        index_cols = {
            tuple(i.columns.keys())
            for i in MatchEvent.__table__.indexes
        }
        self.assertIn(("match_id", "timestamp"), index_cols)

    def test_fork_tables_columns_and_unique_keys(self) -> None:
        forks = MatchFork.__table__
        self.assertFalse(forks.columns["parent_match_id"].nullable)
        self.assertFalse(forks.columns["branch_event_id"].nullable)
        self.assertFalse(forks.columns["status"].nullable)
        # A fork exists before its snapshot does.
        self.assertTrue(forks.columns["solari_snapshot_id"].nullable)
        self.assertIsInstance(forks.columns["prisoner_messages"].type, postgresql.JSONB)
        self.assertIsInstance(forks.columns["warden_messages"].type, postgresql.JSONB)
        self.assertEqual(
            {fk.parent.name: fk.column.table.name for fk in forks.foreign_keys},
            {
                "parent_match_id": "matches",
                "branch_event_id": "match_events",
            },
        )
        self.assertEqual(
            {
                tuple(column.name for column in constraint.columns)
                for constraint in forks.constraints
                if isinstance(constraint, UniqueConstraint)
            },
            {("parent_match_id", "branch_event_id")},
        )
        self.assertTrue(forks.columns["parent_match_id"].index)
        self.assertTrue(forks.columns["branch_event_id"].index)

        messages = MatchAgentMessages.__table__
        self.assertIsInstance(messages.columns["messages"].type, postgresql.JSONB)
        self.assertFalse(messages.columns["messages"].nullable)
        self.assertTrue(messages.columns["match_id"].index)
        self.assertEqual(
            {
                tuple(column.name for column in constraint.columns)
                for constraint in messages.constraints
                if isinstance(constraint, UniqueConstraint)
            },
            {("match_id", "actor")},
        )

    def test_relationships(self) -> None:
        self.assertIn("matches", Challenge.__mapper__.relationships)
        self.assertIn("challenge", Match.__mapper__.relationships)
        self.assertIn("events", Match.__mapper__.relationships)
        self.assertIn("match", MatchEvent.__mapper__.relationships)

    def test_postgres_ddl_compiles(self) -> None:
        dialect = postgresql.dialect()
        ddl = "\n".join(
            str(CreateTable(t).compile(dialect=dialect))
            for t in Base.metadata.sorted_tables
        )
        for token in ("UUID", "JSONB", "TIMESTAMP WITH TIME ZONE", "CREATE TABLE"):
            self.assertIn(token, ddl)
        for name in (
            "ix_match_events_match_time",
            "ix_matches_challenge_id",
            "ix_matches_status",
            "ix_matches_winner",
            "ix_match_events_match_id",
        ):
            ddl_indexes = "\n".join(
                str(CreateIndex(i).compile(dialect=dialect))
                for t in Base.metadata.sorted_tables
                for i in t.indexes
            )
            self.assertIn(name, ddl_indexes)


if __name__ == "__main__":
    unittest.main()
