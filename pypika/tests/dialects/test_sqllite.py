import unittest

from pypika import Table
from pypika.dialects import SQLLiteQuery
from pypika.utils import QueryException


class SelectTests(unittest.TestCase):
    table_abc = Table("abc")

    def test_bool_true_as_one(self):
        q = SQLLiteQuery.from_("abc").select(True)

        self.assertEqual('SELECT 1 FROM "abc"', str(q))

    def test_bool_false_as_zero(self):
        q = SQLLiteQuery.from_("abc").select(False)

        self.assertEqual('SELECT 0 FROM "abc"', str(q))


class ReplaceTests(unittest.TestCase):
    def test_normal_replace(self):
        query = SQLLiteQuery.into("abc").replace("v1", "v2", "v3")
        expected_output = "REPLACE INTO \"abc\" VALUES ('v1','v2','v3')"
        self.assertEqual(expected_output, str(query))

    def test_replace_subquery(self):
        query = SQLLiteQuery.into("abc").replace(SQLLiteQuery.from_("def").select("f1", "f2"))
        expected_output = 'REPLACE INTO "abc" VALUES ((SELECT "f1","f2" FROM "def"))'
        self.assertEqual(expected_output, str(query))

    def test_insert_or_replace(self):
        query = SQLLiteQuery.into("abc").insert_or_replace("v1", "v2", "v3")
        expected_output = "INSERT OR REPLACE INTO \"abc\" VALUES ('v1','v2','v3')"
        self.assertEqual(expected_output, str(query))


class OnConflictTests(unittest.TestCase):
    table_users = Table("users")

    def test_on_conflict_do_nothing(self):
        query = SQLLiteQuery.into(self.table_users).insert(1).on_conflict(self.table_users.id).do_nothing()
        self.assertEqual('INSERT INTO "users" VALUES (1) ON CONFLICT (id) DO NOTHING', str(query))

    def test_on_conflict_partial_index_target_and_update_where(self):
        query = (
            SQLLiteQuery.into(self.table_users)
            .insert(1, "a@example.com", 1)
            .on_conflict(self.table_users.email)
            .where_target(self.table_users.active == 1)
            .do_update("name", "a")
            .where(self.table_users.version < 5)
        )
        self.assertEqual(
            'INSERT INTO "users" VALUES (1,\'a@example.com\',1) '
            'ON CONFLICT (email) WHERE "active"=1 '
            "DO UPDATE SET name='a' WHERE \"users\".\"version\"<5",
            str(query),
        )

    def test_on_conflict_chain_order_equivalent(self):
        expected = (
            'INSERT INTO "users" VALUES (1,\'a\',1) ON CONFLICT (email) WHERE "active"=1 '
            "DO UPDATE SET name='a' WHERE \"users\".\"version\"<5"
        )

        first = (
            SQLLiteQuery.into(self.table_users)
            .insert(1, "a", 1)
            .on_conflict("email")
            .where_target(self.table_users.active == 1)
            .do_update("name", "a")
            .where(self.table_users.version < 5)
        )
        second = (
            SQLLiteQuery.into(self.table_users)
            .insert(1, "a", 1)
            .on_conflict("email")
            .do_update("name", "a")
            .where(self.table_users.version < 5)
            .where_target(self.table_users.active == 1)
        )

        self.assertEqual(expected, str(first))
        self.assertEqual(expected, str(second))

    def test_sqlite_does_not_support_on_constraint(self):
        # SQLite conflict targets use indexed columns/expressions, never ON CONSTRAINT.
        with self.assertRaises(QueryException):
            SQLLiteQuery.into(self.table_users).insert(1).on_constraint("users_pkey")


class OnConflictPartialIndexIntegrationTests(unittest.TestCase):
    """Runs the generated SQL against a real SQLite database with a partial unique index."""

    table_users = Table("users")

    def setUp(self) -> None:
        import sqlite3

        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, name TEXT, active INTEGER NOT NULL)"
        )
        self.conn.execute(
            "CREATE UNIQUE INDEX uq_users_email_active ON users(email) WHERE active = 1"
        )

    def tearDown(self) -> None:
        self.conn.close()

    def _rows(self):
        return list(self.conn.execute("SELECT id, email, name, active FROM users ORDER BY id"))

    def test_insert_path_then_conflict_update_path(self):
        insert_legacy_row = "INSERT INTO users (id, email, name, active) VALUES (?, ?, ?, ?)"
        # 1) First row with the same email is inactive, so it is invisible to the partial index:
        #    inserting an active row takes the plain INSERT path.
        self.conn.execute(insert_legacy_row, (1, "a@example.com", "old", 0))

        insert_query = (
            SQLLiteQuery.into(self.table_users)
            .columns("id", "email", "name", "active")
            .insert(2, "a@example.com", "new", 1)
            .on_conflict("email")
            .where_target(self.table_users.active == 1)
            .do_nothing()
        )
        self.conn.execute(str(insert_query))
        self.assertEqual(
            [(1, "a@example.com", "old", 0), (2, "a@example.com", "new", 1)],
            self._rows(),
        )

        # 2) A second active row with the same email conflicts with the partial index and is
        #    routed to DO UPDATE; the update WHERE gates the assignment as well.
        update_query = (
            SQLLiteQuery.into(self.table_users)
            .columns("id", "email", "name", "active")
            .insert(3, "a@example.com", "updated", 1)
            .on_conflict("email")
            .where_target(self.table_users.active == 1)
            .do_update("name", "updated")
            .where(self.table_users.id < 3)
        )
        self.conn.execute(str(update_query))
        # The conflicting excluded row (id 3) is not inserted; the existing active row is updated.
        self.assertEqual(
            [(1, "a@example.com", "old", 0), (2, "a@example.com", "updated", 1)],
            self._rows(),
        )

        # 3) A conflict whose update WHERE is false performs no update (row 3 stays untouched).
        no_update_query = (
            SQLLiteQuery.into(self.table_users)
            .columns("id", "email", "name", "active")
            .insert(4, "a@example.com", "ignored", 1)
            .on_conflict("email")
            .where_target(self.table_users.active == 1)
            .do_update("name", "ignored")
            .where(self.table_users.id > 99)
        )
        self.conn.execute(str(no_update_query))
        self.assertEqual(
            [(1, "a@example.com", "old", 0), (2, "a@example.com", "updated", 1)],
            self._rows(),
        )

    def test_wrong_target_predicate_raises(self):
        # The conflict target WHERE must match the partial index predicate.
        import sqlite3

        self.conn.execute(
            "INSERT INTO users (id, email, name, active) VALUES (?, ?, ?, ?)",
            (1, "a@example.com", "x", 1),
        )
        query = (
            SQLLiteQuery.into(self.table_users)
            .columns("id", "email", "name", "active")
            .insert(2, "a@example.com", "y", 1)
            .on_conflict("email")
            .where_target(self.table_users.active == 0)
            .do_nothing()
        )
        with self.assertRaises(sqlite3.OperationalError):
            self.conn.execute(str(query))
