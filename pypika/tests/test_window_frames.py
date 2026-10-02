import sqlite3
import unittest

from pypika import FrameExclusion, Query, Tables
from pypika import analytics as an
from pypika.dialects import SQLLiteQuery
from pypika.enums import Dialects
from pypika.utils import DialectNotSupported, QueryException


class GroupsFrameTests(unittest.TestCase):
    table_abc = Tables("abc")[0]

    def test_groups_unbounded_preceding(self):
        expr = an.Sum(self.table_abc.fizz).over(self.table_abc.foo).orderby(self.table_abc.date).groups(an.Preceding())

        q = Query.from_(self.table_abc).select(expr)

        self.assertEqual(
            "SELECT "
            'SUM("fizz") '
            "OVER("
            'PARTITION BY "foo" ORDER BY "date" '
            "GROUPS UNBOUNDED PRECEDING"
            ") "
            'FROM "abc"',
            str(q),
        )

    def test_groups_between_offset_preceding_and_offset_following(self):
        expr = (
            an.Sum(self.table_abc.fizz)
            .over(self.table_abc.foo)
            .orderby(self.table_abc.date)
            .groups(an.Preceding(1), an.Following(1))
        )

        q = Query.from_(self.table_abc).select(expr)

        self.assertEqual(
            "SELECT "
            'SUM("fizz") '
            "OVER("
            'PARTITION BY "foo" ORDER BY "date" '
            "GROUPS BETWEEN 1 PRECEDING AND 1 FOLLOWING"
            ") "
            'FROM "abc"',
            str(q),
        )

    def test_groups_between_current_row_and_unbounded_following(self):
        expr = an.Avg(self.table_abc.fizz).orderby(self.table_abc.date).groups(an.CURRENT_ROW, an.Following())

        q = Query.from_(self.table_abc).select(expr)

        self.assertEqual(
            "SELECT "
            'AVG("fizz") '
            "OVER("
            'ORDER BY "date" '
            "GROUPS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING"
            ") "
            'FROM "abc"',
            str(q),
        )

    def test_groups_called_twice_raises_attribute_error(self):
        with self.assertRaises(AttributeError):
            an.Sum(self.table_abc.fizz).orderby(self.table_abc.date).groups(an.Preceding()).groups(an.Preceding())

    def test_groups_then_rows_raises_attribute_error(self):
        with self.assertRaises(AttributeError):
            an.Sum(self.table_abc.fizz).orderby(self.table_abc.date).groups(an.Preceding()).rows(an.Preceding())


class FrameExclusionTests(unittest.TestCase):
    table_abc = Tables("abc")[0]

    def test_exclude_current_row(self):
        expr = (
            an.Sum(self.table_abc.fizz)
            .orderby(self.table_abc.date)
            .rows(an.Preceding(), an.Following())
            .exclude(FrameExclusion.CURRENT_ROW)
        )

        q = Query.from_(self.table_abc).select(expr)

        self.assertEqual(
            "SELECT "
            'SUM("fizz") '
            "OVER("
            'ORDER BY "date" '
            "ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING EXCLUDE CURRENT ROW"
            ") "
            'FROM "abc"',
            str(q),
        )

    def test_exclude_group(self):
        expr = (
            an.Sum(self.table_abc.fizz)
            .orderby(self.table_abc.date)
            .groups(an.Preceding(1), an.Following(1))
            .exclude(FrameExclusion.GROUP)
        )

        q = Query.from_(self.table_abc).select(expr)

        self.assertEqual(
            "SELECT "
            'SUM("fizz") '
            "OVER("
            'ORDER BY "date" '
            "GROUPS BETWEEN 1 PRECEDING AND 1 FOLLOWING EXCLUDE GROUP"
            ") "
            'FROM "abc"',
            str(q),
        )

    def test_exclude_ties(self):
        expr = (
            an.Sum(self.table_abc.fizz)
            .orderby(self.table_abc.date)
            .range(an.Preceding(), an.CURRENT_ROW)
            .exclude(FrameExclusion.TIES)
        )

        q = Query.from_(self.table_abc).select(expr)

        self.assertEqual(
            "SELECT "
            'SUM("fizz") '
            "OVER("
            'ORDER BY "date" '
            "RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW EXCLUDE TIES"
            ") "
            'FROM "abc"',
            str(q),
        )

    def test_exclude_no_others(self):
        expr = (
            an.Sum(self.table_abc.fizz)
            .orderby(self.table_abc.date)
            .rows(an.Preceding())
            .exclude(FrameExclusion.NO_OTHERS)
        )

        q = Query.from_(self.table_abc).select(expr)

        self.assertEqual(
            "SELECT "
            'SUM("fizz") '
            "OVER("
            'ORDER BY "date" '
            "ROWS UNBOUNDED PRECEDING EXCLUDE NO OTHERS"
            ") "
            'FROM "abc"',
            str(q),
        )

    def test_exclude_accepts_value_and_name_strings(self):
        expr = an.Sum(self.table_abc.fizz).orderby(self.table_abc.date).rows(an.Preceding()).exclude("TIES")
        self.assertIn("EXCLUDE TIES", str(Query.from_(self.table_abc).select(expr)))

        expr = an.Sum(self.table_abc.fizz).orderby(self.table_abc.date).rows(an.Preceding()).exclude("CURRENT_ROW")
        self.assertIn("EXCLUDE CURRENT ROW", str(Query.from_(self.table_abc).select(expr)))

    def test_exclude_unknown_value_raises_value_error(self):
        with self.assertRaises(ValueError):
            an.Sum(self.table_abc.fizz).orderby(self.table_abc.date).rows(an.Preceding()).exclude("EVERYTHING")

    def test_exclude_called_twice_raises_attribute_error(self):
        with self.assertRaises(AttributeError):
            an.Sum(self.table_abc.fizz).orderby(self.table_abc.date).rows(an.Preceding()).exclude("TIES").exclude(
                "GROUP"
            )

    def test_exclude_without_frame_raises_query_exception(self):
        expr = an.Sum(self.table_abc.fizz).orderby(self.table_abc.date).exclude("TIES")

        with self.assertRaises(QueryException):
            str(Query.from_(self.table_abc).select(expr))


class FrameBoundValidationTests(unittest.TestCase):
    table_abc = Tables("abc")[0]

    def test_negative_offset_raises_value_error(self):
        with self.assertRaises(ValueError):
            an.Preceding(-1)
        with self.assertRaises(ValueError):
            an.Following(-3)
        with self.assertRaises(ValueError):
            an.Preceding("-2")

    def test_non_scalar_offset_raises_type_error(self):
        with self.assertRaises(TypeError):
            an.Preceding([1])

    def test_raw_sql_string_bound_raises_type_error(self):
        with self.assertRaises(TypeError):
            an.Sum(self.table_abc.fizz).orderby(self.table_abc.date).rows("UNBOUNDED PRECEDING")

    def test_current_row_constant_still_accepted(self):
        expr = an.Sum(self.table_abc.fizz).orderby(self.table_abc.date).rows(an.CURRENT_ROW)

        self.assertIn("ROWS CURRENT ROW", str(Query.from_(self.table_abc).select(expr)))

    def test_frame_start_after_frame_end_raises_value_error(self):
        with self.assertRaises(ValueError):
            an.Sum(self.table_abc.fizz).orderby(self.table_abc.date).rows(an.Following(2), an.Preceding(2))

        with self.assertRaises(ValueError):
            an.Sum(self.table_abc.fizz).orderby(self.table_abc.date).rows(an.CURRENT_ROW, an.Preceding())

        with self.assertRaises(ValueError):
            an.Sum(self.table_abc.fizz).orderby(self.table_abc.date).rows(an.Following(), an.Following(1))

    def test_unbounded_following_frame_start_raises_value_error(self):
        with self.assertRaises(ValueError):
            an.Sum(self.table_abc.fizz).orderby(self.table_abc.date).rows(an.Following(), an.Following())

    def test_unbounded_preceding_frame_end_raises_value_error(self):
        with self.assertRaises(ValueError):
            an.Sum(self.table_abc.fizz).orderby(self.table_abc.date).rows(an.Preceding(), an.Preceding())

    def test_valid_bound_orders_are_accepted(self):
        expr = an.Sum(self.table_abc.fizz).orderby(self.table_abc.date).rows(an.Preceding(5), an.Preceding(2))
        self.assertIn("ROWS BETWEEN 5 PRECEDING AND 2 PRECEDING", str(Query.from_(self.table_abc).select(expr)))

        expr = an.Sum(self.table_abc.fizz).orderby(self.table_abc.date).rows(an.Preceding(), an.Following())
        self.assertIn(
            "ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING", str(Query.from_(self.table_abc).select(expr))
        )


class FrameDialectSupportTests(unittest.TestCase):
    table_abc = Tables("abc")[0]

    def test_groups_frame_unsupported_dialect_raises(self):
        expr = an.Sum(self.table_abc.fizz).orderby(self.table_abc.date).groups(an.Preceding())

        for dialect in (Dialects.MYSQL, Dialects.ORACLE, Dialects.MSSQL, Dialects.SNOWFLAKE):
            with self.subTest(dialect=dialect), self.assertRaises(DialectNotSupported) as ctx:
                expr.get_sql(dialect=dialect)
            self.assertIn("GROUPS", str(ctx.exception))

    def test_exclude_unsupported_dialect_raises(self):
        expr = an.Sum(self.table_abc.fizz).orderby(self.table_abc.date).rows(an.Preceding()).exclude("TIES")

        for dialect in (Dialects.MYSQL, Dialects.ORACLE, Dialects.REDSHIFT):
            with self.subTest(dialect=dialect), self.assertRaises(DialectNotSupported) as ctx:
                expr.get_sql(dialect=dialect)
            self.assertIn("EXCLUDE", str(ctx.exception))

    def test_supported_dialects_render(self):
        expr = (
            an.Sum(self.table_abc.fizz)
            .orderby(self.table_abc.date)
            .groups(an.Preceding(1), an.Following(1))
            .exclude("GROUP")
        )

        for dialect in (Dialects.POSTGRESQL, Dialects.SQLLITE, None):
            with self.subTest(dialect=dialect):
                sql = expr.get_sql(dialect=dialect) if dialect else expr.get_sql()
                self.assertIn("GROUPS BETWEEN 1 PRECEDING AND 1 FOLLOWING EXCLUDE GROUP", sql)

    def test_rows_and_range_frames_unaffected_by_dialect(self):
        expr = an.Sum(self.table_abc.fizz).orderby(self.table_abc.date).rows(an.Preceding(2))

        self.assertIn("ROWS 2 PRECEDING", expr.get_sql(dialect=Dialects.MYSQL))


class SQLiteWindowFrameExecutionTests(unittest.TestCase):
    """
    Runs the generated SQL against a real SQLite database containing three rows
    with the same ORDER BY value and compares the window sums against
    hand-computed expectations, proving EXCLUDE GROUP and EXCLUDE TIES differ.
    """

    # (x, v) rows; the three x=1 rows form one peer group
    ROWS = [(1, 10), (1, 20), (1, 30), (2, 40), (3, 50)]

    # Hand-computed SUM(v) OVER (ORDER BY x GROUPS BETWEEN 1 PRECEDING AND 1 FOLLOWING EXCLUDE ...)
    # groups: g1 = {10, 20, 30}, g2 = {40}, g3 = {50}
    EXPECTED = {
        FrameExclusion.NO_OTHERS: [100, 100, 100, 150, 90],
        FrameExclusion.CURRENT_ROW: [90, 80, 70, 110, 40],
        FrameExclusion.GROUP: [40, 40, 40, 110, 40],
        # EXCLUDE TIES drops only the current row's peers, keeping the current row itself
        FrameExclusion.TIES: [50, 60, 70, 150, 90],
    }

    @classmethod
    def setUpClass(cls):
        cls.connection = sqlite3.connect(":memory:")
        cls.connection.execute("CREATE TABLE t (x INT, v INT)")
        cls.connection.executemany("INSERT INTO t VALUES (?, ?)", cls.ROWS)

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()

    def _window_sums(self, exclusion):
        t = Tables("t")[0]
        expr = (
            an.Sum(t.v)
            .orderby(t.x)
            .groups(an.Preceding(1), an.Following(1))
            .exclude(exclusion)
        )
        q = SQLLiteQuery.from_(t).select(t.x, expr.as_("s")).orderby(t.x)

        return [row[1] for row in self.connection.execute(str(q)).fetchall()]

    def test_exclude_group_matches_hand_computed(self):
        self.assertEqual(self.EXPECTED[FrameExclusion.GROUP], self._window_sums(FrameExclusion.GROUP))

    def test_exclude_ties_matches_hand_computed(self):
        self.assertEqual(self.EXPECTED[FrameExclusion.TIES], self._window_sums(FrameExclusion.TIES))

    def test_exclude_current_row_matches_hand_computed(self):
        self.assertEqual(self.EXPECTED[FrameExclusion.CURRENT_ROW], self._window_sums(FrameExclusion.CURRENT_ROW))

    def test_exclude_no_others_matches_hand_computed(self):
        self.assertEqual(self.EXPECTED[FrameExclusion.NO_OTHERS], self._window_sums(FrameExclusion.NO_OTHERS))

    def test_exclude_group_and_ties_differ(self):
        self.assertNotEqual(self._window_sums(FrameExclusion.GROUP), self._window_sums(FrameExclusion.TIES))
