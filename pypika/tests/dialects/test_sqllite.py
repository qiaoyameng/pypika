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


class PartialIndexUpsertTests(unittest.TestCase):
    table_users = Table("users")

    def test_partial_index_insert_and_conflict_update_paths(self):
        import sqlite3

        from pypika.functions import Lower

        connection = sqlite3.connect(":memory:")
        connection.execute(
            "CREATE TABLE users ("
            "id INTEGER PRIMARY KEY, email TEXT NOT NULL, "
            "active INTEGER NOT NULL, updated INTEGER NOT NULL"
            ")"
        )
        connection.execute("CREATE UNIQUE INDEX active_email_index ON users (LOWER(email)) WHERE active = 1")
        connection.execute(
            "INSERT INTO users (id, email, active, updated) VALUES "
            "(1, 'a@example.com', 1, 0), (3, 'b@example.com', 0, 0)"
        )
        connection.commit()

        def upsert(user_id, email):
            query = (
                SQLLiteQuery.into(self.table_users)
                .columns("id", "email", "active", "updated")
                .insert(user_id, email, 1, 1)
                .on_conflict(Lower(self.table_users.email), where=self.table_users.active.eq(1))
                .do_update("email")
                .do_update("updated", 1)
                .do_update_where(self.table_users.updated.eq(0))
            )
            connection.execute(str(query))
            connection.commit()

        upsert(1, "A@example.com")
        upsert(2, "b@example.com")

        rows = connection.execute("SELECT id, email, active, updated FROM users ORDER BY id").fetchall()
        self.assertEqual(
            [
                (1, "A@example.com", 1, 1),
                (2, "b@example.com", 1, 1),
                (3, "b@example.com", 0, 0),
            ],
            rows,
        )
        connection.close()

    def test_constraint_conflict_target_is_unsupported(self):
        with self.assertRaises(QueryException):
            SQLLiteQuery.into(self.table_users).insert(1).on_conflict(constraint="users_pk").do_nothing()
