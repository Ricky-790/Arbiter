"""DB model tests: metadata shape + PostgreSQL DDL validity (no live DB)."""

import unittest

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db.models import Base, Challenge, Match, MatchEvent


class DbModelTests(unittest.TestCase):
    def test_all_tables_registered(self) -> None:
        self.assertEqual(
            set(Base.metadata.tables), {"challenges", "matches", "match_events"}
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
                "sandbox_config",
                "files",
                "env_vars",
                "setup_script",
                "created_at",
                "updated_at",
            ],
        )
        self.assertFalse(cols["setup_script"].nullable is False)
        for name in ("sandbox_config", "files", "env_vars"):
            self.assertIsInstance(cols[name].type, postgresql.JSONB)

    def test_matches_columns_and_fks(self) -> None:
        cols = Match.__table__.columns
        self.assertTrue(cols["challenge_id"].nullable is False)
        fks = {fk.parent.name: fk.column.table.name for fk in Match.__table__.foreign_keys}
        self.assertEqual(fks, {"challenge_id": "challenges"})
        self.assertTrue(cols["winner"].nullable)
        self.assertTrue(cols["duration_seconds"].nullable)
        for indexed in ("challenge_id", "status", "winner", "created_at"):
            self.assertTrue(cols[indexed].index, indexed)
        # status/winner stay plain VARCHAR until asked to change.
        self.assertIsInstance(cols["status"].type, type(cols["winner"].type))

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
