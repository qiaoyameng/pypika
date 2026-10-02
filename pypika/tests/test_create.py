import unittest

from pypika import (
    Column,
    Columns,
    DialectNotSupported,
    ExcludeElement,
    Field,
    InitiallyOption,
    MySQLQuery,
    PostgreSQLQuery,
    Query,
    QueryException,
    Table,
    Tables,
)
from pypika.enums import ReferenceOption, SqlTypes
from pypika.terms import Function, Index, ValueWrapper


class CreateTableTests(unittest.TestCase):
    new_table, existing_table = Tables("abc", "efg")
    foo, bar = Columns(("a", "INT"), ("b", "VARCHAR(100)"))

    def test_create_table_with_columns(self):
        with self.subTest("with nullable"):
            a = Column("a", "INT", True)
            b = Column("b", "VARCHAR(100)", False)
            q = Query.create_table(self.new_table).columns(a, b)

            self.assertEqual('CREATE TABLE "abc" ("a" INT NULL,"b" VARCHAR(100) NOT NULL)', str(q))

        with self.subTest("with defaults"):
            a = Column("a", "INT", default=ValueWrapper(42))
            b = Column("b", "VARCHAR(100)", default=ValueWrapper("foo"))
            q = Query.create_table(self.new_table).columns(a, b)

            self.assertEqual('CREATE TABLE "abc" ("a" INT DEFAULT 42,"b" VARCHAR(100) DEFAULT \'foo\')', str(q))

        with self.subTest("with unwrapped defaults"):
            a = Column("a", "INT", default=42)
            b = Column("b", "VARCHAR(100)", default="foo")
            q = Query.create_table(self.new_table).columns(a, b)

            self.assertEqual('CREATE TABLE "abc" ("a" INT DEFAULT 42,"b" VARCHAR(100) DEFAULT \'foo\')', str(q))

        with self.subTest("with period for"):
            a = Column("id", "INT")
            b = Column("valid_from", "DATETIME")
            c = Column("valid_to", "DATETIME")
            q = Query.create_table(self.new_table).columns(a, b, c).period_for('valid_period', b, c)

            self.assertEqual(
                'CREATE TABLE "abc" ('
                '"id" INT,'
                '"valid_from" DATETIME,'
                '"valid_to" DATETIME,'
                'PERIOD FOR "valid_period" ("valid_from","valid_to"))',
                str(q),
            )

        with self.subTest("without temporary keyword"):
            q = Query.create_table(self.new_table).columns(self.foo, self.bar)

            self.assertEqual('CREATE TABLE "abc" ("a" INT,"b" VARCHAR(100))', str(q))

        with self.subTest("with temporary keyword"):
            q = Query.create_table(self.new_table).temporary().columns(self.foo, self.bar)

            self.assertEqual('CREATE TEMPORARY TABLE "abc" ("a" INT,"b" VARCHAR(100))', str(q))

        with self.subTest("with primary key"):
            q = Query.create_table(self.new_table).columns(self.foo, self.bar).primary_key(self.foo, self.bar)

            self.assertEqual('CREATE TABLE "abc" ("a" INT,"b" VARCHAR(100),PRIMARY KEY ("a","b"))', str(q))

        with self.subTest("with simple foreign key"):
            cref, dref = Columns(("c", "INT"), ("d", "VARCHAR(100)"))
            q = (
                Query.create_table(self.new_table)
                .columns(self.foo, self.bar)
                .foreign_key([self.foo, self.bar], self.existing_table, [cref, dref])
            )

            self.assertEqual(
                'CREATE TABLE "abc" ('
                '"a" INT,'
                '"b" VARCHAR(100),'
                'FOREIGN KEY ("a","b") REFERENCES "efg" ("c","d"))',
                str(q),
            )

        with self.subTest("with foreign key reference options"):
            cref, dref = Columns(("c", "INT"), ("d", "VARCHAR(100)"))
            q = (
                Query.create_table(self.new_table)
                .columns(self.foo, self.bar)
                .foreign_key(
                    [self.foo, self.bar],
                    self.existing_table,
                    [cref, dref],
                    on_delete=ReferenceOption.cascade,
                    on_update=ReferenceOption.restrict,
                )
            )

            self.assertEqual(
                'CREATE TABLE "abc" ('
                '"a" INT,'
                '"b" VARCHAR(100),'
                'FOREIGN KEY ("a","b") REFERENCES "efg" ("c","d") ON DELETE CASCADE ON UPDATE RESTRICT)',
                str(q),
            )

        with self.subTest("with unique keys"):
            q = (
                Query.create_table(self.new_table)
                .columns(self.foo, self.bar)
                .unique(self.foo, self.bar)
                .unique(self.foo)
            )

            self.assertEqual('CREATE TABLE "abc" ("a" INT,"b" VARCHAR(100),UNIQUE ("a","b"),UNIQUE ("a"))', str(q))

        with self.subTest("with system versioning"):
            q = Query.create_table(self.new_table).columns(self.foo, self.bar).with_system_versioning()

            self.assertEqual('CREATE TABLE "abc" ("a" INT,"b" VARCHAR(100)) WITH SYSTEM VERSIONING', str(q))

        with self.subTest("with unlogged keyword"):
            q = Query.create_table(self.new_table).unlogged().columns(self.foo, self.bar)

            self.assertEqual('CREATE UNLOGGED TABLE "abc" ("a" INT,"b" VARCHAR(100))', str(q))

        with self.subTest("with if not exists keyword"):
            q = Query.create_table(self.new_table).if_not_exists().columns(self.foo, self.bar)

            self.assertEqual('CREATE TABLE IF NOT EXISTS "abc" ("a" INT,"b" VARCHAR(100))', str(q))

        with self.subTest("with primary key & auto increment"):
            a = Column("a", SqlTypes.INTEGER_AUTO_INCREMENT, False)
            b = Column("b", "VARCHAR(100)", default="foo")
            q = Query.create_table(self.new_table).columns(a, b).primary_key(a)

            self.assertEqual(
                'CREATE TABLE "abc" ("a" INTEGER AUTO_INCREMENT NOT NULL,"b" VARCHAR(100) DEFAULT \'foo\',PRIMARY KEY ("a"))',
                str(q),
            )

    def test_create_table_with_select(self):
        select = Query.from_(self.existing_table).select(self.existing_table.foo, self.existing_table.bar)

        with self.subTest("without temporary keyword"):
            q = Query.create_table(self.new_table).as_select(select)

            self.assertEqual('CREATE TABLE "abc" AS (SELECT "foo","bar" FROM "efg")', str(q))

        with self.subTest("with temporary keyword"):
            q = Query.create_table(self.new_table).temporary().as_select(select)

            self.assertEqual(
                'CREATE TEMPORARY TABLE "abc" AS (SELECT "foo","bar" FROM "efg")',
                str(q),
            )

    def test_create_table_without_columns_or_select_empty(self):
        q = Query.create_table(self.new_table)

        self.assertEqual("", str(q))

    def test_create_table_with_select_and_columns_fails(self):
        select = Query.from_(self.existing_table).select(self.existing_table.foo, self.existing_table.bar)

        with self.subTest("for columns before as_select"):
            with self.assertRaises(AttributeError):
                Query.create_table(self.new_table).columns(self.foo, self.bar).as_select(select)

        with self.subTest("for as_select before columns"):
            with self.assertRaises(AttributeError):
                Query.create_table(self.new_table).as_select(select).columns(self.foo, self.bar)

        with self.subTest("repeated foreign key"):
            with self.assertRaises(AttributeError):
                Query.create_table(self.new_table).foreign_key([self.foo], self.existing_table, [self.bar]).foreign_key(
                    [self.foo], self.existing_table, [self.bar]
                )

    def test_create_table_as_select_not_query_raises_error(self):
        with self.assertRaises(TypeError):
            Query.create_table(self.new_table).as_select("abc")


class CreateTableExcludeTests(unittest.TestCase):
    def test_exclude_room_equality_and_range_overlap(self):
        q = (
            PostgreSQLQuery.create_table("bookings")
            .columns(
                Column("id", "INT"),
                Column("room_id", "INT"),
                Column("starts_at", "TIMESTAMP"),
                Column("ends_at", "TIMESTAMP"),
            )
            .primary_key("id")
            .unique("room_id", "starts_at")
            .foreign_key(["room_id"], Table("rooms"), ["id"])
            .exclude(
                "no_double_booking",
                ExcludeElement("room_id", "="),
                ExcludeElement(Function("tsrange", Field("starts_at"), Field("ends_at")), "&&"),
            )
        )

        self.assertEqual(
            'CREATE TABLE "bookings" ('
            '"id" INT,'
            '"room_id" INT,'
            '"starts_at" TIMESTAMP,'
            '"ends_at" TIMESTAMP,'
            'UNIQUE ("room_id","starts_at"),'
            'CONSTRAINT "no_double_booking" EXCLUDE USING gist '
            '("room_id" WITH =,tsrange("starts_at","ends_at") WITH &&),'
            'PRIMARY KEY ("id"),'
            'FOREIGN KEY ("room_id") REFERENCES "rooms" ("id"))',
            str(q),
        )

    def test_exclude_unnamed_constraint(self):
        q = (
            PostgreSQLQuery.create_table("bookings")
            .columns(Column("room_id", "INT"))
            .exclude(None, ExcludeElement("room_id", "="))
        )

        self.assertEqual(
            'CREATE TABLE "bookings" ("room_id" INT,EXCLUDE USING gist ("room_id" WITH =))',
            str(q),
        )

    def test_exclude_multiple_constraints(self):
        q = (
            PostgreSQLQuery.create_table("bookings")
            .columns(Column("room_id", "INT"), Column("desk_id", "INT"))
            .exclude("room_uniq", ExcludeElement("room_id", "="))
            .exclude("desk_uniq", ExcludeElement("desk_id", "="), using="spgist")
        )

        self.assertEqual(
            'CREATE TABLE "bookings" ('
            '"room_id" INT,'
            '"desk_id" INT,'
            'CONSTRAINT "room_uniq" EXCLUDE USING gist ("room_id" WITH =),'
            'CONSTRAINT "desk_uniq" EXCLUDE USING spgist ("desk_id" WITH =))',
            str(q),
        )

    def test_exclude_with_quoted_names(self):
        q = (
            PostgreSQLQuery.create_table("bookings")
            .columns(Column("booking room", "INT"))
            .exclude("room uniq", ExcludeElement("booking room", "="))
        )

        self.assertEqual(
            'CREATE TABLE "bookings" ("booking room" INT,'
            'CONSTRAINT "room uniq" EXCLUDE USING gist ("booking room" WITH =))',
            str(q),
        )

    def test_exclude_with_predicate(self):
        with self.subTest("boolean flag predicate"):
            q = (
                PostgreSQLQuery.create_table("bookings")
                .columns(Column("room_id", "INT"), Column("active", "BOOLEAN"))
                .exclude("active_booking", ExcludeElement("room_id", "="), where=Field("active"))
            )

            self.assertEqual(
                'CREATE TABLE "bookings" ('
                '"room_id" INT,'
                '"active" BOOLEAN,'
                'CONSTRAINT "active_booking" EXCLUDE USING gist ("room_id" WITH =) WHERE ("active"))',
                str(q),
            )

        with self.subTest("comparison predicate"):
            q = (
                PostgreSQLQuery.create_table("bookings")
                .columns(Column("room_id", "INT"), Column("floor", "INT"))
                .exclude("room_uniq", ExcludeElement("room_id", "="), where=Field("floor") > 0)
            )

            self.assertEqual(
                'CREATE TABLE "bookings" ('
                '"room_id" INT,'
                '"floor" INT,'
                'CONSTRAINT "room_uniq" EXCLUDE USING gist ("room_id" WITH =) WHERE ("floor">0))',
                str(q),
            )

    def test_exclude_deferrable_options(self):
        with self.subTest("deferrable initially deferred"):
            q = (
                PostgreSQLQuery.create_table("bookings")
                .columns(Column("room_id", "INT"))
                .exclude(
                    "room_uniq",
                    ExcludeElement("room_id", "="),
                    deferrable=True,
                    initially=InitiallyOption.deferred,
                )
            )

            self.assertEqual(
                'CREATE TABLE "bookings" ('
                '"room_id" INT,'
                'CONSTRAINT "room_uniq" EXCLUDE USING gist ("room_id" WITH =) DEFERRABLE INITIALLY DEFERRED)',
                str(q),
            )

        with self.subTest("not deferrable initially immediate"):
            q = (
                PostgreSQLQuery.create_table("bookings")
                .columns(Column("room_id", "INT"))
                .exclude(
                    "room_uniq",
                    ExcludeElement("room_id", "="),
                    deferrable=False,
                    initially=InitiallyOption.immediate,
                )
            )

            self.assertEqual(
                'CREATE TABLE "bookings" ('
                '"room_id" INT,'
                'CONSTRAINT "room_uniq" EXCLUDE USING gist ("room_id" WITH =) NOT DEFERRABLE INITIALLY IMMEDIATE)',
                str(q),
            )

    def test_exclude_initially_deferred_requires_deferrable(self):
        with self.subTest("not deferrable"):
            with self.assertRaises(QueryException):
                PostgreSQLQuery.create_table("bookings").columns(Column("room_id", "INT")).exclude(
                    "room_uniq",
                    ExcludeElement("room_id", "="),
                    deferrable=False,
                    initially=InitiallyOption.deferred,
                )

        with self.subTest("deferrable unspecified"):
            with self.assertRaises(QueryException):
                PostgreSQLQuery.create_table("bookings").columns(Column("room_id", "INT")).exclude(
                    "room_uniq",
                    ExcludeElement("room_id", "="),
                    initially=InitiallyOption.deferred,
                )

    def test_exclude_duplicate_name_raises_error(self):
        with self.assertRaises(QueryException):
            (
                PostgreSQLQuery.create_table("bookings")
                .columns(Column("room_id", "INT"), Column("desk_id", "INT"))
                .exclude("room_uniq", ExcludeElement("room_id", "="))
                .exclude("room_uniq", ExcludeElement("desk_id", "="))
            )

    def test_exclude_unknown_column_raises_error(self):
        with self.subTest("in element"):
            with self.assertRaises(QueryException):
                PostgreSQLQuery.create_table("bookings").columns(Column("room_id", "INT")).exclude(
                    "room_uniq", ExcludeElement("missing", "=")
                )

        with self.subTest("in function expression"):
            with self.assertRaises(QueryException):
                PostgreSQLQuery.create_table("bookings").columns(Column("room_id", "INT")).exclude(
                    "room_uniq", ExcludeElement(Function("tsrange", Field("starts_at"), Field("ends_at")), "&&")
                )

        with self.subTest("in predicate"):
            with self.assertRaises(QueryException):
                PostgreSQLQuery.create_table("bookings").columns(Column("room_id", "INT")).exclude(
                    "room_uniq", ExcludeElement("room_id", "="), where=Field("active")
                )

    def test_exclude_requires_elements(self):
        with self.assertRaises(QueryException):
            PostgreSQLQuery.create_table("bookings").columns(Column("room_id", "INT")).exclude("room_uniq")

    def test_exclude_invalid_arguments_raise_error(self):
        with self.subTest("non-term expression"):
            with self.assertRaises(TypeError):
                ExcludeElement(42, "=")

        with self.subTest("empty operator"):
            with self.assertRaises(ValueError):
                ExcludeElement("room_id", " ")

        with self.subTest("empty using"):
            with self.assertRaises(ValueError):
                PostgreSQLQuery.create_table("bookings").columns(Column("room_id", "INT")).exclude(
                    "room_uniq", ExcludeElement("room_id", "="), using=""
                )

        with self.subTest("non-criterion predicate"):
            with self.assertRaises(TypeError):
                PostgreSQLQuery.create_table("bookings").columns(Column("room_id", "INT")).exclude(
                    "room_uniq", ExcludeElement("room_id", "="), where="active"
                )

        with self.subTest("non-enum initially"):
            with self.assertRaises(TypeError):
                PostgreSQLQuery.create_table("bookings").columns(Column("room_id", "INT")).exclude(
                    "room_uniq", ExcludeElement("room_id", "="), deferrable=True, initially="INITIALLY DEFERRED"
                )

    def test_exclude_unsupported_dialects_raise_error(self):
        with self.subTest("ansi"):
            q = Query.create_table("bookings").columns(Column("room_id", "INT")).exclude(
                "room_uniq", ExcludeElement("room_id", "=")
            )
            with self.assertRaises(DialectNotSupported):
                q.get_sql()

        with self.subTest("mysql"):
            q = MySQLQuery.create_table("bookings").columns(Column("room_id", "INT")).exclude(
                "room_uniq", ExcludeElement("room_id", "=")
            )
            with self.assertRaises(DialectNotSupported):
                q.get_sql()

    def test_derived_builders_do_not_share_mutable_lists(self):
        base = PostgreSQLQuery.create_table("bookings").columns(Column("room_id", "INT"), Column("desk_id", "INT"))
        q1 = base.exclude("room_uniq", ExcludeElement("room_id", "="))
        q2 = base.exclude("desk_uniq", ExcludeElement("desk_id", "="))

        self.assertEqual('CREATE TABLE "bookings" ("room_id" INT,"desk_id" INT)', str(base))
        self.assertEqual(
            'CREATE TABLE "bookings" ("room_id" INT,"desk_id" INT,'
            'CONSTRAINT "room_uniq" EXCLUDE USING gist ("room_id" WITH =))',
            str(q1),
        )
        self.assertEqual(
            'CREATE TABLE "bookings" ("room_id" INT,"desk_id" INT,'
            'CONSTRAINT "desk_uniq" EXCLUDE USING gist ("desk_id" WITH =))',
            str(q2),
        )

    def test_derived_builders_do_not_share_column_lists(self):
        base = PostgreSQLQuery.create_table("bookings").columns(Column("room_id", "INT"))
        derived = base.columns(Column("desk_id", "INT"))

        self.assertEqual('CREATE TABLE "bookings" ("room_id" INT)', str(base))
        self.assertEqual('CREATE TABLE "bookings" ("room_id" INT,"desk_id" INT)', str(derived))


class CreateIndexTests(unittest.TestCase):
    new_index = Index("abc")
    new_table = Table("my_table")
    columns = (new_table.a, new_table.b)
    where = new_table.a > 1

    def test_create_index_simple(self) -> None:
        q = Query.create_index(self.new_index).on(self.new_table).columns(*self.columns)
        self.assertEqual(
            f'CREATE INDEX "{self.new_index.name}" ON "{self.new_table.get_table_name()}"({", ".join([c.name for c in self.columns])})',
            q.get_sql(),
        )

    def test_create_index_where(self) -> None:
        q = Query.create_index(self.new_index).on(self.new_table).columns(*self.columns).where(self.where)
        self.assertEqual(
            f'CREATE INDEX "{self.new_index.name}" ON "{self.new_table.get_table_name()}"({", ".join([c.name for c in self.columns])}) WHERE {self.where.get_sql()}',
            q.get_sql(),
        )

    def test_create_index_unique(self) -> None:
        q = Query.create_index(self.new_index).on(self.new_table).columns(*self.columns).unique()
        self.assertEqual(
            f'CREATE UNIQUE INDEX "{self.new_index.name}" ON "{self.new_table.get_table_name()}"({", ".join([c.name for c in self.columns])})',
            q.get_sql(),
        )

    def test_create_index_if_not_exists(self) -> None:
        q = Query.create_index(self.new_index).on(self.new_table).columns(*self.columns).if_not_exists()
        self.assertEqual(
            f'CREATE INDEX IF NOT EXISTS "{self.new_index.name}" ON "{self.new_table.get_table_name()}"({", ".join([c.name for c in self.columns])})',
            q.get_sql(),
        )

    def test_create_index_without_columns_raises_error(self) -> None:
        with self.assertRaises(AttributeError):
            Query.create_index(self.new_index).on(self.new_table).get_sql()

    def test_create_index_without_table_raises_error(self) -> None:
        with self.assertRaises(AttributeError):
            Query.create_index(self.new_index).columns(*self.columns).get_sql()
