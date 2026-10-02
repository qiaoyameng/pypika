import sqlite3
import unittest

from pypika import (
    AliasedQuery,
    PostgreSQLQuery,
    QmarkParameter,
    Query,
    QueryException,
    SQLLiteQuery,
    Table,
    Values,
)


class ValuesTests(unittest.TestCase):
    def test_from_values_with_columns_and_alias(self):
        weights = Values(
            [(1, 0.5), (2, None)],
            columns=("id", "weight"),
            alias="weights",
        )

        query = Query.from_(weights).select(weights.id, weights.weight)

        self.assertEqual(
            'SELECT "weights"."id","weights"."weight" FROM (VALUES (1,0.5),(2,null)) '
            '"weights"("id","weight")',
            str(query),
        )

    def test_join_values(self):
        orders = Table("orders")
        weights = Values([("a", 0.25)], columns=("id", "weight"), alias="weights")

        query = (
            Query.from_(orders)
            .join(weights)
            .on(orders.id == weights.id)
            .select(orders.amount, weights.weight)
        )

        self.assertEqual(
            'SELECT "orders"."amount","weights"."weight" FROM "orders" JOIN (VALUES (\'a\',0.25)) '
            '"weights"("id","weight") ON "orders"."id"="weights"."id"',
            str(query),
        )

    def test_postgresql_from_values_sample(self):
        weights = Values([(1, None, "priority")], columns=("id", "weight", "note"), alias="weights")

        query = PostgreSQLQuery.from_(weights).select(weights.id, weights.weight, weights.note)

        self.assertEqual(
            "SELECT \"weights\".\"id\",\"weights\".\"weight\",\"weights\".\"note\" "
            "FROM (VALUES (1,null,'priority')) \"weights\"(\"id\",\"weight\",\"note\")",
            str(query),
        )

    def test_sqlite_weighted_cte_is_executable(self):
        weights = Values([("item-1", None)], columns=("id", "weight"))
        items = Table("items")
        weights_cte = AliasedQuery("weights")

        query = (
            SQLLiteQuery.with_(weights, "weights")
            .from_(items)
            .join(weights_cte)
            .on(items.id == weights_cte.id)
            .select(items.id, (items.quantity * weights_cte.weight).as_("weighted_score"))
        )

        self.assertEqual(
            'WITH weights("id","weight") AS (VALUES (\'item-1\',null)) '
            'SELECT "items"."id","items"."quantity"*"weights"."weight" "weighted_score" '
            'FROM "items" JOIN weights ON "items"."id"="weights"."id"',
            str(query),
        )

        connection = sqlite3.connect(":memory:")
        try:
            cursor = connection.cursor()
            cursor.execute("CREATE TABLE items (id TEXT PRIMARY KEY, quantity INTEGER)")
            cursor.executemany(
                "INSERT INTO items (id, quantity) VALUES (?, ?)",
                [("item-1", 3), ("item-2", 5)],
            )
            cursor.execute(str(query))
            self.assertEqual([("item-1", None)], cursor.fetchall())
        finally:
            connection.close()

    def test_sqlite_from_values_is_rejected(self):
        weights = Values([(1, 0.5)], columns=("id", "weight"), alias="weights")

        with self.assertRaises(QueryException):
            SQLLiteQuery.from_(weights).select(weights.id).get_sql()

    def test_parameters_use_query_parameter_rules(self):
        weights = Values([("a", 1.5)], columns=("id", "weight"), alias="weights")
        parameter = QmarkParameter()

        sql = Query.from_(weights).select(weights.id).get_sql(parameter=parameter)

        self.assertEqual('SELECT "weights"."id" FROM (VALUES (?,?)) "weights"("id","weight")', sql)
        self.assertEqual(["a", 1.5], parameter.get_parameters())

    def test_row_width_is_validated_against_columns(self):
        with self.assertRaises(QueryException):
            Values([(1, 2), (3,)], columns=("id", "weight"))

    def test_row_width_is_inferred_from_first_row(self):
        with self.assertRaises(QueryException):
            Values([(1, 2), (3,)])

    def test_empty_values_requires_columns(self):
        with self.assertRaises(QueryException):
            Values([])

    def test_empty_values_requires_dialect(self):
        weights = Values([], columns=("id", "weight"), alias="weights")

        with self.assertRaises(QueryException):
            Query.from_(weights).select(weights.star).get_sql()

    def test_empty_postgresql_values(self):
        weights = Values([], columns=("id", "weight"), alias="weights")

        query = PostgreSQLQuery.from_(weights).select(weights.star)

        self.assertEqual(
            'SELECT "weights".* FROM (SELECT null,null WHERE FALSE) "weights"("id","weight")',
            str(query),
        )

    def test_empty_sqlite_values_cte(self):
        weights = Values([], columns=("id", "weight"))

        query = SQLLiteQuery.with_(weights, "weights").from_(AliasedQuery("weights")).select("*")

        self.assertEqual(
            'WITH weights("id","weight") AS (SELECT null,null WHERE 0) SELECT * FROM weights',
            str(query),
        )

    def test_alias_isolation_after_copy_and_nesting(self):
        source = Values([(1,)], columns=("id"))

        first = source.as_("first")
        second = first.as_("second")

        self.assertIsNone(source.alias)
        self.assertEqual("first", first.alias)
        self.assertEqual("second", second.alias)

        inner_query = Query.from_(first).select(first.id)
        outer_query = Query.from_(inner_query).select(inner_query.id)

        self.assertEqual(
            'SELECT "sq0"."id" FROM (SELECT "first"."id" FROM (VALUES (1)) "first"("id")) "sq0"',
            str(outer_query),
        )


if __name__ == "__main__":
    unittest.main()
