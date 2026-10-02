import math
import unittest

from pypika import (
    MySQLQuery,
    NullsOrdering,
    NumericParameter,
    Order,
    Parameter,
    PostgreSQLQuery,
    Table,
    functions as fn,
)
from pypika.terms import OrderedSetAggregateFunction
from pypika.utils import DialectNotSupported, FunctionException


def percentile_cont(values, fraction):
    """
    Reference evaluator for the continuous percentile: interpolates between the two closest
    values of the sorted input (PostgreSQL ``percentile_cont`` semantics).
    """
    ordered = sorted(values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    rank = fraction * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def percentile_disc(values, fraction):
    """
    Reference evaluator for the discrete percentile: returns the first value of the sorted
    input whose cumulative distribution is greater than or equal to the fraction
    (PostgreSQL ``percentile_disc`` semantics).
    """
    ordered = sorted(values)
    if not ordered:
        return None
    index = max(math.ceil(fraction * len(ordered)) - 1, 0)
    return ordered[index]


class PercentileSqlTests(unittest.TestCase):
    table = Table("requests")

    def test_percentile_cont_postgresql(self):
        expr = fn.PercentileCont(0.5).within_group(self.table.latency)
        q = PostgreSQLQuery.from_(self.table).select(expr)

        self.assertEqual(
            'SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY "latency") FROM "requests"',
            str(q),
        )

    def test_percentile_disc_postgresql(self):
        expr = fn.PercentileDisc(0.9).within_group(self.table.latency)
        q = PostgreSQLQuery.from_(self.table).select(expr)

        self.assertEqual(
            'SELECT PERCENTILE_DISC(0.9) WITHIN GROUP (ORDER BY "latency") FROM "requests"',
            str(q),
        )

    def test_sort_key_direction_and_nulls_ordering(self):
        expr = fn.PercentileCont(0.5).within_group(
            self.table.latency, order=Order.desc, nulls=NullsOrdering.last
        )
        q = PostgreSQLQuery.from_(self.table).select(expr)

        self.assertEqual(
            'SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY "latency" DESC NULLS LAST) FROM "requests"',
            str(q),
        )

    def test_sort_key_nulls_first(self):
        expr = fn.PercentileDisc(0.5).within_group(self.table.latency, nulls=NullsOrdering.first)
        q = PostgreSQLQuery.from_(self.table).select(expr)

        self.assertEqual(
            'SELECT PERCENTILE_DISC(0.5) WITHIN GROUP (ORDER BY "latency" NULLS FIRST) FROM "requests"',
            str(q),
        )

    def test_alias(self):
        expr = fn.PercentileCont(0.5).within_group(self.table.latency).as_("median")
        q = PostgreSQLQuery.from_(self.table).select(expr)

        self.assertEqual(
            'SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY "latency") "median" FROM "requests"',
            str(q),
        )

    def test_filter(self):
        expr = fn.PercentileCont(0.5).within_group(self.table.latency).filter(self.table.status == "ok")
        q = PostgreSQLQuery.from_(self.table).select(expr)

        self.assertEqual(
            "SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY \"latency\") "
            "FILTER(WHERE \"status\"='ok') FROM \"requests\"",
            str(q),
        )

    def test_within_group_is_distinct_from_outer_orderby(self):
        expr = fn.PercentileCont(0.5).within_group(self.table.latency, order=Order.desc).as_("median")
        q = PostgreSQLQuery.from_(self.table).select(expr).orderby(self.table.region)

        self.assertEqual(
            'SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY "latency" DESC) "median" '
            'FROM "requests" ORDER BY "region"',
            str(q),
        )

    def test_fraction_uses_parameter_binding(self):
        expr = fn.PercentileCont(NumericParameter("1")).within_group(self.table.latency)
        q = PostgreSQLQuery.from_(self.table).select(expr)

        self.assertEqual(
            'SELECT PERCENTILE_CONT(:1) WITHIN GROUP (ORDER BY "latency") FROM "requests"',
            str(q),
        )

    def test_fraction_qmark_parameter(self):
        expr = fn.PercentileDisc(Parameter("?")).within_group(self.table.latency)
        q = PostgreSQLQuery.from_(self.table).select(expr)

        self.assertEqual(
            'SELECT PERCENTILE_DISC(?) WITHIN GROUP (ORDER BY "latency") FROM "requests"',
            str(q),
        )

    def test_nested_subquery_field_reference(self):
        subquery = PostgreSQLQuery.from_(self.table).select(self.table.latency).as_("sq")
        expr = fn.PercentileDisc(0.5).within_group(subquery.latency)
        q = PostgreSQLQuery.from_(subquery).select(expr)

        self.assertEqual(
            'SELECT PERCENTILE_DISC(0.5) WITHIN GROUP (ORDER BY "sq"."latency") '
            'FROM (SELECT "latency" FROM "requests") "sq"',
            str(q),
        )

    def test_nested_subquery_selects_percentile(self):
        inner = PostgreSQLQuery.from_(self.table).select(
            fn.PercentileCont(0.5).within_group(self.table.latency).as_("median")
        ).as_("sq")
        outer = PostgreSQLQuery.from_(inner).select(inner.median)

        self.assertEqual(
            'SELECT "sq"."median" FROM ('
            'SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY "latency") "median" FROM "requests"'
            ') "sq"',
            str(outer),
        )


class GenericOrderedSetAggregateTests(unittest.TestCase):
    table = Table("requests")

    def test_generic_ordered_set_aggregate(self):
        expr = OrderedSetAggregateFunction("MODE").within_group(self.table.status)
        q = PostgreSQLQuery.from_(self.table).select(expr)

        self.assertEqual(
            'SELECT MODE() WITHIN GROUP (ORDER BY "status") FROM "requests"',
            str(q),
        )

    def test_generic_multiple_sort_keys(self):
        expr = OrderedSetAggregateFunction("RANK", 0.5).within_group(self.table.region, self.table.latency)
        q = PostgreSQLQuery.from_(self.table).select(expr)

        self.assertEqual(
            'SELECT RANK(0.5) WITHIN GROUP (ORDER BY "region","latency") FROM "requests"',
            str(q),
        )

    def test_extensible_via_subclass(self):
        class Rank(OrderedSetAggregateFunction):
            NUM_SORT_KEYS = 1
            REQUIRES_WITHIN_GROUP = True

            def __init__(self, value, alias=None):
                super().__init__("RANK", value, alias=alias)

        expr = Rank(42).within_group(self.table.latency)
        q = PostgreSQLQuery.from_(self.table).select(expr)

        self.assertEqual(
            'SELECT RANK(42) WITHIN GROUP (ORDER BY "latency") FROM "requests"',
            str(q),
        )

    def test_unsupported_dialect_rejected(self):
        expr = fn.PercentileCont(0.5).within_group(self.table.latency)
        q = MySQLQuery.from_(self.table).select(expr)

        with self.assertRaises(DialectNotSupported):
            str(q)


class ValidationTests(unittest.TestCase):
    table = Table("requests")

    def test_fraction_above_range_rejected(self):
        with self.assertRaises(FunctionException):
            fn.PercentileCont(1.5)

    def test_fraction_below_range_rejected(self):
        with self.assertRaises(FunctionException):
            fn.PercentileDisc(-0.1)

    def test_fraction_bounds_allowed(self):
        fn.PercentileCont(0)
        fn.PercentileCont(1)

    def test_missing_within_group_rejected(self):
        with self.assertRaises(FunctionException):
            fn.PercentileCont(0.5).get_sql()

    def test_wrong_number_of_sort_keys_rejected(self):
        expr = fn.PercentileCont(0.5).within_group(self.table.region, self.table.latency)

        with self.assertRaises(FunctionException):
            expr.get_sql()

    def test_over_is_rejected(self):
        with self.assertRaises(FunctionException):
            fn.PercentileCont(0.5).within_group(self.table.latency).over(self.table.region)


class CloneBranchTests(unittest.TestCase):
    table = Table("requests")

    def test_within_group_clone_branches(self):
        base = fn.PercentileCont(0.5)
        branch_asc = base.within_group(self.table.latency)
        branch_desc = base.within_group(self.table.latency, order=Order.desc)

        self.assertEqual([], base._within_group)
        self.assertEqual(
            'PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY "latency")',
            branch_asc.get_sql(quote_char='"'),
        )
        self.assertEqual(
            'PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY "latency" DESC)',
            branch_desc.get_sql(quote_char='"'),
        )

    def test_filter_clone_branches(self):
        base = fn.PercentileCont(0.5).within_group(self.table.latency)
        branch_ok = base.filter(self.table.status == "ok")
        branch_err = base.filter(self.table.status == "err")

        self.assertEqual(
            'PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY "latency")',
            base.get_sql(quote_char='"'),
        )
        self.assertEqual(
            "PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY \"latency\") FILTER(WHERE \"status\"='ok')",
            branch_ok.get_sql(quote_char='"'),
        )
        self.assertEqual(
            "PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY \"latency\") FILTER(WHERE \"status\"='err')",
            branch_err.get_sql(quote_char='"'),
        )

    def test_alias_clone_branches(self):
        base = fn.PercentileCont(0.5).within_group(self.table.latency)
        aliased = base.as_("median")

        self.assertIsNone(base.alias)
        self.assertEqual("median", aliased.alias)


class ReferenceEvaluatorTests(unittest.TestCase):
    data = [40, 10, 30, 20]

    def test_continuous_percentile_interpolates(self):
        self.assertEqual(25.0, percentile_cont(self.data, 0.5))
        self.assertEqual(17.5, percentile_cont(self.data, 0.25))

    def test_discrete_percentile_picks_actual_value(self):
        self.assertEqual(20, percentile_disc(self.data, 0.5))
        self.assertEqual(10, percentile_disc(self.data, 0.25))

    def test_percentiles_differ_on_same_data(self):
        self.assertNotEqual(
            percentile_cont(self.data, 0.5),
            percentile_disc(self.data, 0.5),
        )

    def test_percentiles_agree_on_bounds(self):
        self.assertEqual(percentile_cont(self.data, 0), percentile_disc(self.data, 0))
        self.assertEqual(percentile_cont(self.data, 1), percentile_disc(self.data, 1))

    def test_empty_input(self):
        self.assertIsNone(percentile_cont([], 0.5))
        self.assertIsNone(percentile_disc([], 0.5))
