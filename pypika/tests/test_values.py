import sqlite3
import unittest

from pypika import (
    AliasedQuery,
    JoinException,
    PostgreSQLQuery,
    QmarkParameter,
    Query,
    SQLLiteQuery,
    Table,
    Values,
)
from pypika.utils import DialectNotSupported, QueryException
from pypika import functions as fn


class ValuesTests(unittest.TestCase):
    def test_from_values_postgresql_sample(self):
        weights = Values([(1, 1.5, None)], columns=["id", "weight", "note"], alias="w")

        query = PostgreSQLQuery.from_(weights).select(weights.id, weights.weight)

        self.assertEqual(
            'SELECT "w"."id","w"."weight" FROM (VALUES (1,1.5,null)) "w"("id","weight","note")',
            query.get_sql(),
        )

    def test_join_values(self):
        products = Table("products", alias="p")
        weights = Values([(1, 1.5), (2, 0.75)], columns=["id", "weight"], alias="w")

        query = (
            Query.from_(products)
            .join(weights)
            .on(products.id == weights.id)
            .select(products.name, weights.weight)
        )

        self.assertEqual(
            'SELECT "p"."name","w"."weight" FROM "products" "p" '
            "JOIN (VALUES (1,1.5),(2,0.75)) \"w\"(\"id\",\"weight\") "
            'ON "p"."id"="w"."id"',
            query.get_sql(),
        )

    def test_cte_uses_values_column_names(self):
        weights = Values([("a", 1)], columns=["code", "weight"])

        query = (
            Query.with_(weights, "weights")
            .from_(AliasedQuery("weights"))
            .select("code", "weight")
        )

        self.assertEqual(
            'WITH weights(code,weight) AS (VALUES (\'a\',1)) SELECT "weights"."code","weights"."weight" FROM weights',
            query.get_sql(),
        )

    def test_row_width_checked_at_construction(self):
        with self.assertRaisesRegex(QueryException, "VALUES row 1 has 1 values but 2 columns were expected"):
            Values([("a", 1), ("b",)], columns=["code", "weight"])

    def test_empty_values_requires_columns(self):
        with self.assertRaisesRegex(QueryException, "empty VALUES relation requires explicit columns"):
            Values([])

    def test_empty_values_requires_supported_dialect(self):
        empty_values = Values([], columns=["code", "weight"])

        with self.assertRaises(DialectNotSupported):
            Query.from_(empty_values.as_("w")).select("*").get_sql()

    def test_empty_values_postgresql(self):
        empty_values = Values([], columns=["code", "weight"], alias="w")

        query = PostgreSQLQuery.from_(empty_values).select(empty_values.code)

        self.assertEqual(
            'SELECT "w"."code" FROM (SELECT null,null WHERE 0) "w"("code","weight")',
            query.get_sql(),
        )

    def test_empty_values_sqlite_cte(self):
        empty_values = Values([], columns=["code"])

        query = (
            SQLLiteQuery.with_(empty_values, "weights")
            .from_(AliasedQuery("weights"))
            .select("code")
        )

        self.assertEqual(
            'WITH weights(code) AS (SELECT null WHERE 0) SELECT "weights"."code" FROM weights',
            query.get_sql(),
        )

    def test_empty_values_sqlite_from_aliases_columns_inside_subquery(self):
        empty_values = Values([], columns=["code"], alias="w")

        sql = SQLLiteQuery.from_(empty_values).select(empty_values.code).get_sql()

        self.assertEqual('SELECT "w"."code" FROM (SELECT null AS "code" WHERE 0) "w"', sql)

    def test_from_values_requires_alias(self):
        with self.assertRaisesRegex(QueryException, "VALUES relation used in FROM or JOIN requires an alias"):
            Query.from_(Values([("a", 1)], columns=["code", "weight"])).select("*").get_sql()

    def test_unknown_column_is_rejected(self):
        weights = Values([("a", 1)], columns=["code", "weight"], alias="w")

        with self.assertRaisesRegex(QueryException, "Column 'missing' is not defined"):
            weights.missing

    def test_expression_must_reference_joined_relation(self):
        products = Table("products", alias="p")
        weights = Values([(1, 1.5)], columns=["id", "weight"], alias="w")
        other_weights = Values([(1, 1.5)], columns=["id", "weight"], alias="other")

        with self.assertRaises(JoinException):
            Query.from_(products).join(weights).on(products.id == other_weights.id).select("*")

    def test_copy_does_not_share_alias(self):
        weights = Values([("a", 1)], columns=["code", "weight"])
        joined = weights.as_("w")
        nested = weights.as_("nested")

        self.assertIsNone(weights.alias)
        self.assertEqual("w", joined.alias)
        self.assertEqual("nested", nested.alias)

        nested_query = Query.from_(nested).select(nested.code)
        query = Query.with_(joined, "source").from_(AliasedQuery("source")).select("code")

        self.assertIn('"nested"', nested_query.get_sql())
        self.assertNotIn('"w"', nested_query.get_sql())
        self.assertIn("WITH source", query.get_sql())
        self.assertNotIn('"nested"', query.get_sql())

    def test_values_use_parameter_rules(self):
        parameter = QmarkParameter()
        weights = Values([("a", None)], columns=["code", "weight"], alias="w")

        sql = Query.from_(weights).select(weights.code).get_sql(parameter=parameter)

        self.assertEqual('SELECT "w"."code" FROM (VALUES (?,null)) "w"("code","weight")', sql)
        self.assertEqual(["a"], parameter.get_parameters())

    def test_sqlite_weighted_cte_query_is_executable(self):
        weights = Values([(1, 1.5, None)], columns=["id", "weight", "note"])
        quantities = Values([(1, 5)], columns=["id", "quantity"])

        query = (
            SQLLiteQuery.with_(weights, "weights")
            .with_(quantities, "quantities")
            .from_(AliasedQuery("weights"))
            .join(AliasedQuery("quantities"))
            .on_field("id")
            .select(
                AliasedQuery("weights").note,
                fn.Sum(AliasedQuery("weights").weight * AliasedQuery("quantities").quantity),
            )
        )

        sql = query.get_sql()
        self.assertIn("WITH weights(id,weight,note) AS (VALUES (1,1.5,null))", sql)
        self.assertIn("quantities(id,quantity) AS (VALUES (1,5))", sql)

        with sqlite3.connect(":memory:") as connection:
            ((note, weighted_total),) = connection.execute(sql).fetchall()
        self.assertIsNone(note)
        self.assertEqual(7.5, weighted_total)


class ValuesDialectTests(unittest.TestCase):
    def test_sqlite_builder_selects_empty_values_strategy(self):
        empty_values = Values([], columns=["code"], alias="w")

        sql = SQLLiteQuery.from_(empty_values).select(empty_values.code).get_sql()

        self.assertEqual('SELECT "w"."code" FROM (SELECT null AS "code" WHERE 0) "w"', sql)
