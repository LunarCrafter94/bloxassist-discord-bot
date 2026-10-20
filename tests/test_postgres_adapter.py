"""Contract tests for the experimental PostgreSQL SQL compatibility adapter.

These verify SQL translation and connection ownership without requiring a live
PostgreSQL server. Provider-specific acceptance tests are still required.
"""
import sys
import unittest
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "source-files"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from bloxfruits_helper_credit_bot.database.guild_database import _PostgresDialectConnection


class _Cursor:
    rowcount = 1
    lastrowid = None

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class _FakeRawConnection:
    def __init__(self):
        self.queries = []
        self.closed = False
        self.commits = 0
        self.rollbacks = 0

    def execute(self, query, params=()):
        self.queries.append((query, params))
        return _Cursor()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True

    def __enter__(self):
        raise AssertionError("The adapter must not delegate context ownership to psycopg")

    def __exit__(self, *_args):
        self.closed = True


class PostgresAdapterTests(unittest.TestCase):
    def setUp(self):
        self.raw = _FakeRawConnection()
        self.connection = _PostgresDialectConnection(self.raw)

    def test_context_scope_commits_without_closing_long_lived_connection(self):
        with self.connection:
            self.connection.execute("UPDATE users SET credits = credits + ? WHERE user_id = ?", (5, 99))
        self.assertEqual(self.raw.commits, 1)
        self.assertFalse(self.raw.closed)
        self.assertEqual(self.raw.queries[0][0], "BEGIN")
        self.assertEqual(self.raw.queries[1][0], "UPDATE users SET credits = credits + %s WHERE user_id = %s")

    def test_context_scope_rolls_back_on_exception_and_keeps_connection_open(self):
        with self.assertRaisesRegex(RuntimeError, "test"):
            with self.connection:
                raise RuntimeError("test")
        self.assertEqual(self.raw.rollbacks, 1)
        self.assertFalse(self.raw.closed)

    def test_sqlite_autoincrement_and_integer_types_are_translated(self):
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS tickets (ticket_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL)"
        )
        query = self.raw.queries[-1][0]
        self.assertIn("ticket_id BIGSERIAL PRIMARY KEY", query)
        self.assertIn("user_id BIGINT NOT NULL", query)

    def test_insert_or_ignore_is_translated_to_postgres_conflict_handling(self):
        self.connection.execute("INSERT OR IGNORE INTO settings(setting_key, setting_value) VALUES (?, ?)", ("a", "b"))
        query, params = self.raw.queries[-1]
        self.assertTrue(query.startswith("INSERT INTO settings"))
        self.assertTrue(query.endswith("ON CONFLICT DO NOTHING"))
        self.assertEqual(params, ("a", "b"))

    def test_nullable_timestamp_expiry_expression_casts_both_parameters(self):
        self.connection.execute(
            "SELECT CASE WHEN ? IS NULL OR datetime(?) <= datetime('now', '-15 minutes') THEN 1 ELSE 0 END AS expired",
            (None, None),
        )
        query, params = self.raw.queries[-1]
        self.assertIn("CASE WHEN (%s)::timestamptz IS NULL OR (%s)::timestamptz <=", query)
        self.assertEqual(params, (None, None))

    def test_sqlite_datetime_expression_is_translated(self):
        self.connection.execute(
            "SELECT ticket_id FROM tickets WHERE datetime(resolution_requested_at) <= datetime('now', ?)",
            ("-15 minutes",),
        )
        query, params = self.raw.queries[-1]
        self.assertIn("resolution_requested_at::timestamptz", query)
        self.assertIn("now() + (%s)::interval", query)
        self.assertEqual(params, ("-15 minutes",))


if __name__ == "__main__":
    unittest.main()
