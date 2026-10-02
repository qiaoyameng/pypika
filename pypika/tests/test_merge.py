import unittest

from pypika import QmarkParameter, Query, QueryException, Table
from pypika.dialects import MSSQLQuery, MySQLQuery, PostgreSQLQuery
from pypika.enums import Boolean, Equality
from pypika.terms import BasicCriterion, ComplexCriterion, ParameterValueWrapper, ValueWrapper
from pypika.utils import DialectNotSupported


def _field_key(field):
    table_name = field.table.get_table_name() if field.table else None
    return table_name, field.name


def _criterion_value(criterion, row):
    if isinstance(criterion, ComplexCriterion):
        left = _criterion_value(criterion.left, row)
        right = _criterion_value(criterion.right, row)
        if criterion.comparator == Boolean.and_:
            return left and right
        if criterion.comparator == Boolean.or_:
            return left or right
        return left ^ right

    if not isinstance(criterion, BasicCriterion):
        raise AssertionError("The small test interpreter supports basic and AND/OR/XOR criteria")

    left = row.get(_field_key(criterion.left), criterion.left)
    if isinstance(criterion.right, ValueWrapper):
        right = criterion.right.value
    else:
        right = row.get(_field_key(criterion.right), criterion.right)

    if criterion.comparator == Equality.eq:
        return left == right
    if criterion.comparator == Equality.ne:
        return left != right
    if criterion.comparator == Equality.gt:
        return left > right
    if criterion.comparator == Equality.gte:
        return left >= right
    if criterion.comparator == Equality.lt:
        return left < right
    if criterion.comparator == Equality.lte:
        return left <= right
    raise AssertionError(f"Unsupported comparator: {criterion.comparator}")


def select_merge_action(merge, matched, row):
    scope = "matched" if matched else "not_matched"
    for branch in merge._branches:
        if branch.when != scope:
            continue
        if branch.criterion is None or _criterion_value(branch.criterion, row):
            return branch.action
    return None


class MergeTests(unittest.TestCase):
    def test_postgresql_merge_insert_update_delete(self):
        target = Table("accounts")
        source = Table("incoming_accounts")

        merge = (
            PostgreSQLQuery.merge(target, source, target.id == source.id)
            .when_matched(target.status == source.status)
            .then_delete()
            .when_matched()
            .then_update(target.balance, source.balance)
            .when_not_matched()
            .then_insert(target.id, target.balance, target.status)
            .values(source.id, source.balance, source.status)
        )

        self.assertEqual(
            'MERGE INTO "accounts" USING "incoming_accounts" ON "accounts"."id"="incoming_accounts"."id" '
            'WHEN MATCHED AND "accounts"."status"="incoming_accounts"."status" THEN DELETE '
            'WHEN MATCHED THEN UPDATE SET "balance"="incoming_accounts"."balance" '
            'WHEN NOT MATCHED THEN INSERT ("id","balance","status") '
            'VALUES ("incoming_accounts"."id","incoming_accounts"."balance","incoming_accounts"."status")',
            str(merge),
        )

    def test_source_can_be_subquery_with_alias(self):
        target = Table("accounts")
        source_table = Table("incoming_accounts")
        source = Query.from_(source_table).select(source_table.id, source_table.balance).as_("incoming")

        merge = (
            PostgreSQLQuery.merge(target, source, target.id == source.id)
            .when_matched()
            .then_update(target.balance, source.balance)
        )

        self.assertEqual(
            'MERGE INTO "accounts" USING (SELECT "id","balance" FROM "incoming_accounts") "incoming" '
            'ON "accounts"."id"="incoming"."id" '
            'WHEN MATCHED THEN UPDATE SET "balance"="incoming"."balance"',
            str(merge),
        )

    def test_source_can_be_subquery_without_explicit_alias(self):
        target = Table("accounts")
        source_table = Table("incoming_accounts")
        source = Query.from_(source_table).select(source_table.id, source_table.balance)

        merge = (
            PostgreSQLQuery.merge(target, source, target.id == source.id)
            .when_matched()
            .then_update(target.balance, source.balance)
        )

        self.assertEqual(
            'MERGE INTO "accounts" USING (SELECT "id","balance" FROM "incoming_accounts") "sq0" '
            'ON "accounts"."id"="sq0"."id" '
            'WHEN MATCHED THEN UPDATE SET "balance"="sq0"."balance"',
            str(merge),
        )

    def test_source_and_on_can_be_chained(self):
        target = Table("accounts")
        source = Table("incoming_accounts")

        merge = (
            PostgreSQLQuery.merge(target)
            .using(source)
            .on(target.id == source.id)
            .when_matched()
            .then_delete()
        )

        self.assertEqual(
            'MERGE INTO "accounts" USING "incoming_accounts" ON "accounts"."id"="incoming_accounts"."id" '
            'WHEN MATCHED THEN DELETE',
            str(merge),
        )

    def test_on_can_be_chained_after_source_argument(self):
        target = Table("accounts")
        source = Table("incoming_accounts")

        merge = (
            PostgreSQLQuery.merge(target, source)
            .on(target.id == source.id)
            .when_matched()
            .then_delete()
        )

        self.assertIn('USING "incoming_accounts"', str(merge))

    def test_source_can_be_table_name(self):
        target = Table("accounts")

        merge = (
            PostgreSQLQuery.merge(target, "incoming_accounts", target.id == Table("incoming_accounts").id)
            .when_matched()
            .then_delete()
        )

        self.assertIn('USING "incoming_accounts"', str(merge))

    def test_uses_terms_and_parameters(self):
        target = Table("accounts")
        source = Table("incoming_accounts")
        parameter = QmarkParameter()

        merge = (
            PostgreSQLQuery.merge(target, source, target.id == source.id)
            .when_matched(source.balance > 0)
            .then_update(target.balance, ParameterValueWrapper(parameter, 0))
        )

        self.assertEqual(
            'MERGE INTO "accounts" USING "incoming_accounts" ON "accounts"."id"="incoming_accounts"."id" '
            'WHEN MATCHED AND "incoming_accounts"."balance">? THEN UPDATE SET "balance"=?',
            merge.get_sql(parameter=parameter),
        )
        self.assertEqual([0, 0], parameter.get_parameters())

    def test_branch_order_interpreter(self):
        target = Table("accounts")
        source = Table("incoming_accounts")
        delete_condition = target.status == source.status
        update_condition = source.balance > 0
        insert_condition = source.status == "new"

        merge = (
            PostgreSQLQuery.merge(target, source, target.id == source.id)
            .when_matched(delete_condition)
            .then_delete()
            .when_matched(update_condition)
            .then_update(target.balance, source.balance)
            .when_not_matched(insert_condition)
            .then_insert(target.id).values(source.id)
        )

        delete_row = {
            ("accounts", "status"): "same",
            ("incoming_accounts", "status"): "same",
            ("incoming_accounts", "balance"): 1,
        }
        update_row = {
            ("accounts", "status"): "active",
            ("incoming_accounts", "status"): "new",
            ("incoming_accounts", "balance"): 1,
        }
        skipped_row = {
            ("accounts", "status"): "active",
            ("incoming_accounts", "status"): "new",
            ("incoming_accounts", "balance"): 0,
        }

        self.assertEqual("delete", select_merge_action(merge, True, delete_row))
        self.assertEqual("update", select_merge_action(merge, True, update_row))
        self.assertIsNone(select_merge_action(merge, True, skipped_row))
        self.assertEqual("insert", select_merge_action(merge, False, {("incoming_accounts", "status"): "new"}))
        self.assertIsNone(
            select_merge_action(merge, False, {("incoming_accounts", "status"): "active"})
        )

    def test_branches_derived_from_same_builder_do_not_modify_each_other(self):
        target = Table("accounts")
        source = Table("incoming_accounts")
        base = PostgreSQLQuery.merge(target, source, target.id == source.id)

        update_merge = (
            base.when_matched()
            .then_update(target.balance, source.balance)
        )
        delete_merge = (
            base.when_matched(source.archived == True)
            .then_delete()
        )

        self.assertEqual(
            'MERGE INTO "accounts" USING "incoming_accounts" ON "accounts"."id"="incoming_accounts"."id" '
            'WHEN MATCHED THEN UPDATE SET "balance"="incoming_accounts"."balance"',
            str(update_merge),
        )
        self.assertEqual(
            'MERGE INTO "accounts" USING "incoming_accounts" ON "accounts"."id"="incoming_accounts"."id" '
            'WHEN MATCHED AND "incoming_accounts"."archived"=true THEN DELETE',
            str(delete_merge),
        )
        self.assertEqual("", str(base))

    def test_insert_columns_and_values_count_must_match(self):
        target = Table("accounts")
        source = Table("incoming_accounts")

        with self.assertRaises(QueryException):
            (
                PostgreSQLQuery.merge(target, source, target.id == source.id)
                .when_not_matched()
                .then_insert(target.id, target.balance)
                .values(source.id)
            )

    def test_unconditional_followed_by_same_scope_is_unreachable(self):
        target = Table("accounts")
        source = Table("incoming_accounts")

        with self.assertRaises(QueryException):
            (
                PostgreSQLQuery.merge(target, source, target.id == source.id)
                .when_matched()
                .then_delete()
                .when_matched(source.balance > 0)
            )

    def test_not_matched_cannot_use_delete_action(self):
        target = Table("accounts")
        source = Table("incoming_accounts")

        with self.assertRaises(QueryException):
            (
                PostgreSQLQuery.merge(target, source, target.id == source.id)
                .when_not_matched()
                .then_delete()
            )

    def test_base_query_does_not_support_merge(self):
        target = Table("accounts")
        source = Table("incoming_accounts")

        with self.assertRaises(DialectNotSupported):
            Query.merge(target, source, target.id == source.id)

    def test_other_dialects_do_not_support_postgresql_merge_syntax(self):
        target = Table("accounts")
        source = Table("incoming_accounts")

        for dialect_query in (MySQLQuery, MSSQLQuery):
            with self.subTest(dialect_query=dialect_query):
                with self.assertRaises(DialectNotSupported):
                    dialect_query.merge(target, source, target.id == source.id)

    def test_update_is_not_valid_when_not_matched(self):
        target = Table("accounts")
        source = Table("incoming_accounts")

        with self.assertRaises(QueryException):
            PostgreSQLQuery.merge(target, source, target.id == source.id).when_not_matched().then_update().set(
                target.balance, source.balance
            )

    def test_set_chain_completes_branch(self):
        target = Table("accounts")
        source = Table("incoming_accounts")

        merge = (
            PostgreSQLQuery.merge(target, source, target.id == source.id)
            .when_matched()
            .then_update()
            .set(target.balance, source.balance)
            .set(target.status, source.status)
        )

        self.assertEqual(
            'MERGE INTO "accounts" USING "incoming_accounts" ON "accounts"."id"="incoming_accounts"."id" '
            'WHEN MATCHED THEN UPDATE SET "balance"="incoming_accounts"."balance",'
            '"status"="incoming_accounts"."status"',
            str(merge),
        )

    def test_pending_update_does_not_make_later_matched_branch_unreachable(self):
        target = Table("accounts")
        source = Table("incoming_accounts")

        merge = (
            PostgreSQLQuery.merge(target, source, target.id == source.id)
            .when_matched(source.archived == True)
            .then_update()
            .set(target.status, source.status)
            .when_matched()
            .then_delete()
        )

        self.assertIn('WHEN MATCHED AND "incoming_accounts"."archived"=true THEN UPDATE', str(merge))
        self.assertIn("WHEN MATCHED THEN DELETE", str(merge))

    def test_incomplete_branch_renders_empty_query(self):
        target = Table("accounts")
        source = Table("incoming_accounts")

        self.assertEqual("", str(PostgreSQLQuery.merge(target, source, target.id == source.id)))


class MergeCriterionOrderTests(unittest.TestCase):
    def test_basic_criterion_equality(self):
        target = Table("accounts")
        source = Table("incoming_accounts")
        first = target.id == source.id
        second = target.balance < 0

        merge = (
            PostgreSQLQuery.merge(target, source, first)
            .when_matched(first)
            .then_delete()
            .when_matched(second)
            .then_update(target.balance, source.balance)
        )

        delete_row = {("accounts", "id"): 1, ("incoming_accounts", "id"): 1, ("accounts", "balance"): 0}
        update_row = {("accounts", "id"): 1, ("incoming_accounts", "id"): 2, ("accounts", "balance"): -1}
        skipped_row = {("accounts", "id"): 1, ("incoming_accounts", "id"): 2, ("accounts", "balance"): 0}

        self.assertEqual("delete", select_merge_action(merge, True, delete_row))
        self.assertEqual("update", select_merge_action(merge, True, update_row))
        self.assertIsNone(select_merge_action(merge, True, skipped_row))

    def test_complex_criterion_order(self):
        target = Table("accounts")
        source = Table("incoming_accounts")
        left = source.archived == True
        right = source.balance < 0
        condition = left & right

        merge = (
            PostgreSQLQuery.merge(target, source, target.id == source.id)
            .when_matched(condition)
            .then_delete()
            .when_matched()
            .then_update(target.balance, source.balance)
        )

        self.assertEqual(
            "delete",
            select_merge_action(
                merge,
                True,
                {("incoming_accounts", "archived"): True, ("incoming_accounts", "balance"): -1},
            ),
        )
        self.assertEqual(
            "update",
            select_merge_action(
                merge,
                True,
                {("incoming_accounts", "archived"): True, ("incoming_accounts", "balance"): 1},
            ),
        )
        self.assertIs(Boolean.and_, condition.comparator)
        self.assertIs(Equality.eq, left.comparator)


if __name__ == "__main__":
    unittest.main()
