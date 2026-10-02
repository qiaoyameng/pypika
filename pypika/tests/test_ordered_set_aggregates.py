import unittest

from pypika import (
    NamedParameter,
    Order,
    PostgreSQLQuery,
    QmarkParameter,
    Query,
    Table,
)
from pypika.enums import Dialects, NullsOrder
from pypika import functions as fn
from pypika.percentiles import percentile_cont, percentile_disc
from pypika.utils import DialectNotSupported, FunctionException


class PercentileSqlTests(unittest.TestCase):
    table = Table("requests")

    def test_percentile_cont_basic(self):
        q = Query.from_(self.table).select(fn.PercentileCont(0.5).within_group(self.table.latency).as_("p50"))

        self.assertEqual(
            'SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY "latency") "p50" FROM "requests"',
            str(q),
        )

    def test_percentile_disc_basic(self):
        q = Query.from_(self.table).select(fn.PercentileDisc(0.9).within_group(self.table.latency))

        self.assertEqual(
            'SELECT PERCENTILE_DISC(0.9) WITHIN GROUP (ORDER BY "latency") FROM "requests"',
            str(q),
        )

    def test_percentile_cont_postgresql_dialect(self):
        q = PostgreSQLQuery.from_(self.table).select(fn.PercentileCont(0.5).within_group(self.table.latency))

        self.assertEqual(
            'SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY "latency") FROM "requests"',
            str(q),
        )

    def test_within_group_order_asc_desc(self):
        q = Query.from_(self.table).select(fn.PercentileCont(0.5).within_group(self.table.latency, order=Order.desc))

        self.assertEqual(
            'SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY "latency" DESC) FROM "requests"',
            str(q),
        )

    def test_within_group_nulls_first(self):
        q = Query.from_(self.table).select(
            fn.PercentileDisc(0.25).within_group(self.table.latency, nulls=NullsOrder.nulls_first)
        )

        self.assertEqual(
            'SELECT PERCENTILE_DISC(0.25) WITHIN GROUP (ORDER BY "latency" NULLS FIRST) FROM "requests"',
            str(q),
        )

    def test_within_group_order_and_nulls_tuple(self):
        q = Query.from_(self.table).select(
            fn.PercentileCont(0.75).within_group((self.table.latency, Order.desc, NullsOrder.nulls_last))
        )

        self.assertEqual(
            'SELECT PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY "latency" DESC NULLS LAST) FROM "requests"',
            str(q),
        )

    def test_within_group_tuple_partial(self):
        q = Query.from_(self.table).select(
            fn.PercentileCont(0.75).within_group((self.table.latency, Order.asc))
        )

        self.assertEqual(
            'SELECT PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY "latency" ASC) FROM "requests"',
            str(q),
        )

    def test_direct_args_kept_outside_within_group(self):
        q = Query.from_(self.table).select(fn.WithinGroupFunction("RANK", 100).within_group(self.table.score))

        self.assertEqual('SELECT RANK(100) WITHIN GROUP (ORDER BY "score") FROM "requests"', str(q))

    def test_generic_zero_arg_function(self):
        q = Query.from_(self.table).select(fn.WithinGroupFunction("MODE").within_group(self.table.size))

        self.assertEqual('SELECT MODE() WITHIN GROUP (ORDER BY "size") FROM "requests"', str(q))

    def test_generic_multiple_sort_items(self):
        q = Query.from_(self.table).select(
            fn.WithinGroupFunction("RANK", 1, 2).within_group(
                (self.table.a, Order.asc), (self.table.b, Order.desc, NullsOrder.nulls_first)
            )
        )

        self.assertEqual(
            'SELECT RANK(1,2) WITHIN GROUP (ORDER BY "a" ASC,"b" DESC NULLS FIRST) FROM "requests"',
            str(q),
        )

    def test_filter_clause(self):
        q = Query.from_(self.table).select(
            fn.PercentileCont(0.95).within_group(self.table.latency).filter(self.table.status == "ok").as_("p95")
        )

        self.assertEqual(
            'SELECT PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY "latency") '
            'FILTER(WHERE "status"=\'ok\') "p95" FROM "requests"',
            str(q),
        )

    def test_groupby_with_percentile(self):
        q = (
            Query.from_(self.table)
            .groupby(self.table.region)
            .select(self.table.region, fn.PercentileCont(0.5).within_group(self.table.latency).as_("p50"))
        )

        self.assertEqual(
            'SELECT "region",PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY "latency") "p50" '
            'FROM "requests" GROUP BY "region"',
            str(q),
        )

    def test_outer_orderby_distinct_from_within_group(self):
        q = (
            Query.from_(self.table)
            .groupby(self.table.region)
            .select(self.table.region, fn.PercentileCont(0.5).within_group(self.table.latency))
            .orderby(self.table.region, order=Order.desc)
        )

        self.assertEqual(
            'SELECT "region",PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY "latency") '
            'FROM "requests" GROUP BY "region" ORDER BY "region" DESC',
            str(q),
        )

    def test_param_fraction_named(self):
        q = Query.from_(self.table).select(fn.PercentileCont(NamedParameter("p")).within_group(self.table.latency))

        self.assertEqual(
            'SELECT PERCENTILE_CONT(:p) WITHIN GROUP (ORDER BY "latency") FROM "requests"',
            str(q),
        )

    def test_param_fraction_qmark_binding(self):
        parameter = QmarkParameter()
        q = Query.from_(self.table).select(fn.PercentileCont(0.5).within_group(self.table.latency))

        self.assertEqual(
            'SELECT PERCENTILE_CONT(?) WITHIN GROUP (ORDER BY "latency") FROM "requests"',
            q.get_sql(parameter=parameter),
        )
        self.assertEqual([0.5], parameter.get_parameters())

    def test_nested_subquery_field_reference(self):
        inner = Query.from_(self.table).select(self.table.region, self.table.latency)
        q = (
            Query.from_(inner)
            .groupby(inner.region)
            .select(inner.region, fn.PercentileCont(0.5).within_group(inner.latency).as_("p50"))
        )

        self.assertEqual(
            'SELECT "sq0"."region",PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY "sq0"."latency") "p50" '
            'FROM (SELECT "region","latency" FROM "requests") "sq0" GROUP BY "sq0"."region"',
            str(q),
        )

    def test_replace_table_rewrites_within_group_field(self):
        table_abc = Table("abc")
        table_xyz = Table("xyz")
        percentile = fn.PercentileCont(0.5).within_group(table_abc.latency)

        q = Query.from_(table_xyz).select(percentile.replace_table(table_abc, table_xyz))

        self.assertEqual(
            'SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY "latency") FROM "xyz"',
            str(q),
        )


class OrderedSetValidationTests(unittest.TestCase):
    table = Table("requests")

    def test_unsupported_dialect_rejected(self):
        from pypika import MySQLQuery

        q = MySQLQuery.from_(self.table).select(fn.PercentileCont(0.5).within_group(self.table.latency))

        with self.assertRaises(DialectNotSupported):
            str(q)

    def test_unsupported_dialect_enum_rejected(self):
        percentile = fn.PercentileCont(0.5).within_group(self.table.latency)

        with self.assertRaises(DialectNotSupported):
            percentile.get_sql(dialect=Dialects.MYSQL)

    def test_over_rejected(self):
        percentile = fn.PercentileCont(0.5).within_group(self.table.latency)

        with self.assertRaises(AttributeError):
            percentile.over(self.table.region)

    def test_fraction_too_large_rejected(self):
        with self.assertRaises(FunctionException):
            fn.PercentileCont(1.01)

    def test_fraction_negative_rejected(self):
        with self.assertRaises(FunctionException):
            fn.PercentileDisc(-0.01)

    def test_fraction_non_numeric_rejected(self):
        with self.assertRaises(FunctionException):
            fn.PercentileCont("half")

    def test_fraction_bool_rejected(self):
        with self.assertRaises(FunctionException):
            fn.PercentileCont(True)

    def test_fraction_boundaries_accepted(self):
        fn.PercentileCont(0.0).within_group(self.table.latency).get_sql()
        fn.PercentileCont(1.0).within_group(self.table.latency).get_sql()

    def test_extra_direct_arg_rejected(self):
        with self.assertRaises(FunctionException):
            fn.PercentileCont(0.5, 0.6)

    def test_missing_direct_arg_rejected(self):
        with self.assertRaises(FunctionException):
            fn.PercentileCont()

    def test_generic_arity_check_can_be_added(self):
        class TwoArgPercentile(fn.WithinGroupFunction):
            num_args = 2

        with self.assertRaises(FunctionException):
            TwoArgPercentile("CUSTOM_PCTL", 0.5)

    def test_too_many_sort_items_rejected(self):
        with self.assertRaises(FunctionException):
            fn.PercentileCont(0.5).within_group(self.table.latency, self.table.latency2)

    def test_missing_within_group_rejected_at_render(self):
        q = Query.from_(self.table).select(fn.PercentileCont(0.5).as_("p50"))

        with self.assertRaises(FunctionException):
            str(q)

    def test_bad_tuple_arity_rejected(self):
        with self.assertRaises(FunctionException):
            fn.PercentileCont(0.5).within_group((self.table.latency, Order.asc, NullsOrder.nulls_first, "extra"))


class OrderedSetCloneTests(unittest.TestCase):
    table = Table("requests")

    def test_within_group_does_not_mutate_original(self):
        percentile = fn.PercentileCont(0.5)
        ordered = percentile.within_group(self.table.latency)

        self.assertIsNot(percentile, ordered)
        self.assertEqual([], percentile._within_group)
        self.assertEqual(1, len(ordered._within_group))

    def test_filter_does_not_mutate_original(self):
        ordered = fn.PercentileCont(0.5).within_group(self.table.latency)
        filtered = ordered.filter(self.table.status == "ok")

        self.assertIsNot(ordered, filtered)
        self.assertFalse(ordered._include_filter)
        self.assertEqual([], ordered._filters)
        self.assertTrue(filtered._include_filter)
        self.assertEqual(1, len(filtered._filters))

    def test_chained_within_group_calls_accumulate(self):
        generic = fn.WithinGroupFunction("RANK", 1, 2)
        generic = generic.within_group((self.table.a, Order.asc))
        generic = generic.within_group((self.table.b, Order.desc))

        self.assertEqual(2, len(generic._within_group))

    def test_order_keyword_does_not_apply_to_direct_args(self):
        percentile = fn.PercentileCont(0.5).within_group(self.table.latency, order=Order.desc)

        self.assertEqual(Order.desc, percentile._within_group[0][1])
        self.assertEqual(0.5, percentile.args[0].value)


class PercentileReferenceEvaluatorTests(unittest.TestCase):
    sample = [3, 1, 4, 2]

    def test_median_differs_for_even_sample(self):
        # Sorted: [1, 2, 3, 4], position 1.5 -> interpolated (2 + 3) / 2 = 2.5
        # discrete: first rank/N >= 0.5 -> rank 2 -> 2
        self.assertEqual(2.5, percentile_cont(0.5, self.sample))
        self.assertEqual(2.0, percentile_disc(0.5, self.sample))

    def test_continuous_interpolation_fraction(self):
        # position (N - 1) * 0.25 = 0.75 -> 1 + (2 - 1) * 0.75
        self.assertEqual(1.75, percentile_cont(0.25, self.sample))

    def test_discrete_returns_stored_value(self):
        self.assertEqual(1.0, percentile_disc(0.25, self.sample))
        self.assertEqual(3.0, percentile_disc(0.75, self.sample))

    def test_endpoints(self):
        self.assertEqual(1.0, percentile_cont(0.0, self.sample))
        self.assertEqual(4.0, percentile_cont(1.0, self.sample))
        self.assertEqual(1.0, percentile_disc(0.0, self.sample))
        self.assertEqual(4.0, percentile_disc(1.0, self.sample))

    def test_nulls_ignored(self):
        self.assertEqual(2.5, percentile_cont(0.5, [None, 1, 2, None, 3, 4]))
        self.assertEqual(2.0, percentile_disc(0.5, [None, 1, 2, None, 3, 4]))

    def test_odd_sample_coincides(self):
        odd = [10, 20, 30]
        self.assertEqual(20.0, percentile_cont(0.5, odd))
        self.assertEqual(20.0, percentile_disc(0.5, odd))

    def test_fraction_out_of_range(self):
        with self.assertRaises(ValueError):
            percentile_cont(1.1, self.sample)
        with self.assertRaises(ValueError):
            percentile_disc(-0.1, self.sample)

    def test_empty_sample(self):
        with self.assertRaises(ValueError):
            percentile_cont(0.5, [])
        with self.assertRaises(ValueError):
            percentile_disc(0.5, [None])


if __name__ == "__main__":
    unittest.main()
