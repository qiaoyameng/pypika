import operator
import unittest

from pypika import (
    Field,
    NamedParameter,
    Query,
    QueryException,
    QmarkParameter,
    Table,
)
from pypika.dialects import PostgreSQLQuery
from pypika.enums import Boolean, Equality
from pypika.queries import MergeQueryBuilder
from pypika.terms import BasicCriterion, ComplexCriterion, NullCriterion, ValueWrapper
from pypika.utils import DialectNotSupported


COMPARATORS = {
    Equality.eq: operator.eq,
    Equality.ne: operator.ne,
    Equality.gt: operator.gt,
    Equality.gte: operator.ge,
    Equality.lt: operator.lt,
    Equality.lte: operator.le,
}


def term_value(term, values):
    if isinstance(term, Field):
        if term.table is not None:
            table_name = term.table.alias or term.table.get_table_name()
            return values[f"{table_name}.{term.name}"]
        return values[term.name]
    if isinstance(term, ValueWrapper):
        return term.value
    raise AssertionError(f"Unsupported term: {term!r}")


def evaluate(criterion, values):
    if criterion is None:
        return True
    if isinstance(criterion, NullCriterion):
        return term_value(criterion.term, values) is None
    if isinstance(criterion, ComplexCriterion) and criterion.comparator == Boolean.and_:
        return evaluate(criterion.left, values) and evaluate(criterion.right, values)
    if isinstance(criterion, ComplexCriterion) and criterion.comparator == Boolean.or_:
        return evaluate(criterion.left, values) or evaluate(criterion.right, values)
    if isinstance(criterion, BasicCriterion):
        return COMPARATORS[criterion.comparator](
            term_value(criterion.left, values),
            term_value(criterion.right, values),
        )
    raise AssertionError(f"Unsupported criterion: {criterion!r}")


def select_action(merge, matched, values):
    for branch in merge.branches:
        if branch.matched is matched and evaluate(branch.condition, values):
            return branch.action
    return None


class PostgreSQLMergeTests(unittest.TestCase):
    def test_insert_update_delete_from_subquery(self):
        target = Table("customers")
        source_table = Table("customer_updates")
        source = (
            Query.from_(source_table)
            .select(
                source_table.id,
                source_table.name,
                source_table.updated_at,
                source_table.is_deleted,
            )
            .as_("updates")
        )

        merge = (
            PostgreSQLQuery.merge(target)
            .using(source)
            .on(target.id == Field("id", table=source))
            .when_matched(Field("is_deleted", table=source).isnull())
            .then_delete()
            .when_matched(Field("updated_at", table=source) > target.updated_at)
            .then_update()
            .set(target.name, Field("name", table=source))
            .set(target.updated_at, QmarkParameter())
            .when_not_matched()
            .then_insert(target.id, target.name, target.updated_at)
            .values(
                Field("id", table=source),
                Field("name", table=source),
                NamedParameter("now"),
            )
        )

        self.assertEqual(
            'MERGE INTO "customers" '
            'USING (SELECT "id","name","updated_at","is_deleted" FROM "customer_updates") "updates" '
            'ON "customers"."id"="updates"."id" '
            'WHEN MATCHED AND "updates"."is_deleted" IS NULL THEN DELETE '
            'WHEN MATCHED AND "updates"."updated_at">"customers"."updated_at" '
            'THEN UPDATE SET "name"="updates"."name","updated_at"=? '
            'WHEN NOT MATCHED THEN INSERT ("id","name","updated_at") '
            'VALUES ("updates"."id","updates"."name",:now)',
            str(merge),
        )

    def test_table_source_and_terms_remain_terms(self):
        target = Table("target")
        source = Table("source")

        merge = (
            PostgreSQLQuery.merge(target)
            .using(source)
            .on(target.id == source.id)
            .when_matched(source.amount > target.amount)
            .then_update()
            .set(target.amount, source.amount)
            .when_not_matched()
            .then_insert(target.id, target.amount)
            .values(source.id, source.amount)
        )

        self.assertEqual(
            'MERGE INTO "target" USING "source" ON "target"."id"="source"."id" '
            'WHEN MATCHED AND "source"."amount">"target"."amount" '
            'THEN UPDATE SET "amount"="source"."amount" '
            'WHEN NOT MATCHED THEN INSERT ("id","amount") '
            'VALUES ("source"."id","source"."amount")',
            str(merge),
        )

    def test_branch_order_interpreter(self):
        target = Table("target")
        source = Table("source")
        merge = (
            PostgreSQLQuery.merge(target)
            .using(source)
            .on(target.id == source.id)
            .when_matched(source.deleted.isnull())
            .then_delete()
            .when_matched(source.updated_at > target.updated_at)
            .then_update()
            .set(target.updated_at, source.updated_at)
            .when_not_matched()
            .then_insert(target.id)
            .values(source.id)
        )

        delete_row = {"source.deleted": None, "source.updated_at": 10, "target.updated_at": 0}
        update_row = {"source.deleted": False, "source.updated_at": 10, "target.updated_at": 0}
        insert_values = {"id": 1}

        self.assertEqual("delete", select_action(merge, True, delete_row))
        self.assertEqual("update", select_action(merge, True, update_row))
        self.assertEqual("insert", select_action(merge, False, insert_values))

    def test_branches_derived_from_same_builder_do_not_mutate_each_other(self):
        target = Table("target")
        source = Table("source")
        base = PostgreSQLQuery.merge(target).using(source).on(target.id == source.id)

        deleted = base.when_matched(source.deleted.isnull()).then_delete()
        updated = (
            base.when_matched(source.updated_at > target.updated_at)
            .then_update()
            .set(target.updated_at, source.updated_at)
        )
        inserted = base.when_not_matched().then_insert(target.id).values(source.id)

        self.assertEqual([], list(base.branches))
        self.assertEqual(["delete"], [branch.action for branch in deleted.branches])
        self.assertEqual(["update"], [branch.action for branch in updated.branches])
        self.assertEqual(["insert"], [branch.action for branch in inserted.branches])

        extended_deleted = deleted.when_not_matched().then_insert(target.id).values(source.id)

        self.assertEqual(["delete"], [branch.action for branch in deleted.branches])
        self.assertEqual(["delete", "insert"], [branch.action for branch in extended_deleted.branches])

    def test_insert_columns_and_values_must_match(self):
        target = Table("target")
        source = Table("source")

        with self.assertRaises(QueryException):
            (
                PostgreSQLQuery.merge(target)
                .using(source)
                .on(target.id == source.id)
                .when_not_matched()
                .then_insert(target.id, target.name)
                .values(source.id)
            )

    def test_unconditional_branch_followed_by_same_scope_is_unreachable(self):
        target = Table("target")
        source = Table("source")
        merge = (
            PostgreSQLQuery.merge(target)
            .using(source)
            .on(target.id == source.id)
            .when_not_matched()
            .then_insert(target.id)
            .values(source.id)
        )

        with self.assertRaises(QueryException):
            merge.when_not_matched(source.id > 0)

    def test_conditional_branch_after_unconditional_same_scope_is_unreachable(self):
        target = Table("target")
        source = Table("source")

        with self.assertRaises(QueryException):
            (
                PostgreSQLQuery.merge(target)
                .using(source)
                .on(target.id == source.id)
                .when_matched()
                .then_delete()
                .when_matched(source.deleted.isnull())
            )

    def test_action_scope_is_enforced(self):
        target = Table("target")
        source = Table("source")
        merge = PostgreSQLQuery.merge(target).using(source).on(target.id == source.id)

        with self.assertRaises(QueryException):
            merge.when_not_matched().then_delete()
        with self.assertRaises(QueryException):
            merge.when_matched().then_insert(target.id)
        with self.assertRaises(QueryException):
            merge.when_not_matched().then_update()

    def test_required_merge_parts_are_validated(self):
        target = Table("target")
        source = Table("source")

        with self.assertRaises(QueryException):
            str(PostgreSQLQuery.merge(target).using(source))
        with self.assertRaises(QueryException):
            str(PostgreSQLQuery.merge(target).on(target.id == source.id))
        with self.assertRaises(QueryException):
            str(
                PostgreSQLQuery.merge(target)
                .using(source)
                .on(target.id == source.id)
                .when_matched()
                .then_update()
            )

    def test_base_dialect_does_not_expose_postgresql_merge(self):
        with self.assertRaises(DialectNotSupported):
            Query.merge(Table("target"))

    def test_generic_builder_does_not_render_dialect_sql(self):
        target = Table("target")
        source = Table("source")
        with self.assertRaises(DialectNotSupported):
            str(
                MergeQueryBuilder(target=target)
                .using(source)
                .on(target.id == source.id)
            )
