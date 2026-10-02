import sqlite3
import unittest

from pypika import AliasedQuery, CustomFunction, QueryException, RecursiveCTE, SQLLiteQuery, Table
from pypika import functions as fn


class RecursiveCTETests(unittest.TestCase):
    categories = Table("categories")
    tree_name = "category_tree"
    tree_ref = AliasedQuery(tree_name)
    tree_columns = ["id", "parent_id", "name", "depth", "path"]
    printf = CustomFunction("printf", ["format", "path", "name"])

    def anchor_query(self):
        return (
            SQLLiteQuery.from_(self.categories)
            .select(
                self.categories.id,
                self.categories.parent_id,
                self.categories.name,
                0,
                fn.Cast(self.categories.name, "TEXT"),
            )
            .where(self.categories.parent_id.isnull())
        )

    def recursive_query(self):
        return (
            SQLLiteQuery.from_(self.categories)
            .join(self.tree_ref)
            .on(self.categories.parent_id == self.tree_ref.id)
            .select(
                self.categories.id,
                self.categories.parent_id,
                self.categories.name,
                self.tree_ref.depth + 1,
                self.printf("%s/%s", self.tree_ref.path, self.categories.name),
            )
        )

    def recursive_cte(self):
        return RecursiveCTE(self.tree_name, self.tree_columns).anchor(self.anchor_query()).union_all(
            self.recursive_query()
        )

    def tree_query(self):
        recursive_cte = self.recursive_cte()
        recursive_ref = recursive_cte.reference()
        return (
            SQLLiteQuery.with_recursive(recursive_cte)
            .from_(recursive_ref)
            .select(
                recursive_ref.id,
                recursive_ref.depth,
                recursive_ref.path,
            )
            .orderby(recursive_ref.id)
        )

    def test_sqlite_directory_tree(self):
        query = self.tree_query()
        sql = str(query)

        self.assertIn(
            'WITH RECURSIVE category_tree ("id","parent_id","name","depth","path") AS (',
            sql,
        )
        self.assertIn(" UNION ALL ", sql)
        self.assertIn('SELECT "category_tree"."id","category_tree"."depth","category_tree"."path"', sql)
        self.assertIn("FROM category_tree", sql)

        connection = sqlite3.connect(":memory:")
        connection.execute(
            "CREATE TABLE categories (id INTEGER PRIMARY KEY, parent_id INTEGER, name TEXT)"
        )
        connection.executemany(
            "INSERT INTO categories VALUES (?, ?, ?)",
            [
                (1, None, "root"),
                (2, 1, "child"),
                (3, 2, "grandchild"),
            ],
        )

        self.assertEqual(
            connection.execute(sql).fetchall(),
            [
                (1, 0, "root"),
                (2, 1, "root/child"),
                (3, 2, "root/child/grandchild"),
            ],
        )

    def test_accepts_union_all_anchor_and_recursive_query(self):
        union_query = self.anchor_query().union_all(self.recursive_query())
        cte = RecursiveCTE(self.tree_name, self.tree_columns, union_query)

        query = SQLLiteQuery.with_recursive(cte).from_(self.tree_ref).select(self.tree_ref.id)

        self.assertIn("WITH RECURSIVE", str(query))
        self.assertIn("UNION ALL", str(query))

    def test_cte_object_can_be_used_as_self_reference(self):
        cte = RecursiveCTE(self.tree_name, self.tree_columns).anchor(self.anchor_query())
        recursive = (
            SQLLiteQuery.from_(self.categories)
            .join(cte)
            .on(self.categories.parent_id == cte.id)
            .select(
                self.categories.id,
                self.categories.parent_id,
                self.categories.name,
                cte.depth + 1,
                self.printf("%s/%s", cte.path, self.categories.name),
            )
        )
        cte = cte.union_all(recursive)

        query = SQLLiteQuery.with_recursive(cte).from_(cte).select(cte.id)

        self.assertIn("JOIN category_tree ON", str(query))
        self.assertIn("FROM category_tree", str(query))

    def test_multiple_ctes_preserve_dependencies(self):
        selected_categories = SQLLiteQuery.from_(self.tree_ref).select(self.tree_ref.id)

        query = (
            SQLLiteQuery.with_recursive(self.recursive_cte())
            .with_(selected_categories, "category_ids")
            .from_(AliasedQuery("category_ids"))
            .select("id")
        )

        sql = str(query)
        self.assertLess(sql.index("category_tree ("), sql.index("category_ids AS"))
        self.assertIn("FROM category_ids", sql)

    def test_anchor_uses_same_named_local_cte_scope(self):
        local_tree = (
            SQLLiteQuery.with_(self.anchor_query(), "category_tree")
            .from_(AliasedQuery("category_tree"))
            .select("id")
        )
        anchor = self.anchor_query().where(self.categories.id.isin(local_tree))

        cte = RecursiveCTE(self.tree_name, self.tree_columns, anchor, self.recursive_query())

        self.assertIn("WITH category_tree AS", str(SQLLiteQuery.with_recursive(cte).from_(self.tree_ref).select("id")))

    def test_duplicate_cte_names_are_rejected(self):
        query = SQLLiteQuery.with_recursive(self.recursive_cte()).from_(self.tree_ref).select("id")

        with self.assertRaises(QueryException):
            query.with_(self.anchor_query(), self.tree_name)

        self.assertNotIn("category_ids", str(query))

    def test_anchor_self_reference_is_rejected(self):
        anchor = SQLLiteQuery.from_(self.tree_ref).select(
            self.tree_ref.id,
            self.tree_ref.parent_id,
            self.tree_ref.name,
            self.tree_ref.depth,
            self.tree_ref.path,
        )

        with self.assertRaises(QueryException):
            RecursiveCTE(self.tree_name, self.tree_columns, anchor, self.recursive_query())

    def test_recursive_query_must_reference_cte(self):
        recursive = SQLLiteQuery.from_(self.categories).select(
            self.categories.id,
            self.categories.parent_id,
            self.categories.name,
            1,
            self.categories.name,
        )

        with self.assertRaises(QueryException):
            RecursiveCTE(self.tree_name, self.tree_columns, self.anchor_query(), recursive)

    def test_declared_column_references_are_validated(self):
        recursive = (
            SQLLiteQuery.from_(self.categories)
            .join(self.tree_ref)
            .on(self.categories.parent_id == self.tree_ref.id)
            .select(
                self.categories.id,
                self.categories.parent_id,
                self.categories.name,
                self.tree_ref.level + 1,
                self.categories.name,
            )
        )

        with self.assertRaisesRegex(QueryException, "level"):
            RecursiveCTE(self.tree_name, self.tree_columns, self.anchor_query(), recursive)

    def test_column_count_is_validated_early(self):
        recursive = (
            SQLLiteQuery.from_(self.categories)
            .join(self.tree_ref)
            .on(self.categories.parent_id == self.tree_ref.id)
            .select(
                self.categories.id,
                self.categories.parent_id,
                self.categories.name,
                self.tree_ref.depth + 1,
            )
        )

        with self.assertRaisesRegex(QueryException, "same number of columns"):
            RecursiveCTE(self.tree_name, self.tree_columns, self.anchor_query(), recursive)

    def test_unknown_column_count_reports_static_limit(self):
        anchor = SQLLiteQuery.from_(self.categories).select("*")
        recursive = SQLLiteQuery.from_(self.tree_ref).select("*")

        with self.assertRaisesRegex(QueryException, "Cannot statically determine"):
            RecursiveCTE(self.tree_name, self.tree_columns, anchor, recursive)

    def test_derived_queries_remain_independent(self):
        base = SQLLiteQuery.with_recursive(self.recursive_cte()).from_(self.tree_ref).select(self.tree_ref.id)
        with_depth = base.select(self.tree_ref.depth)
        with_path = with_depth.select(self.tree_ref.path)

        self.assertEqual(
            str(base),
            'WITH RECURSIVE category_tree ("id","parent_id","name","depth","path") AS ('
            'SELECT "id","parent_id","name",0,CAST("name" AS TEXT) FROM "categories" '
            'WHERE "parent_id" IS NULL UNION ALL '
            'SELECT "categories"."id","categories"."parent_id","categories"."name",'
            '"category_tree"."depth"+1,printf(\'%s/%s\',"category_tree"."path","categories"."name") '
            'FROM "categories" JOIN category_tree ON "categories"."parent_id"="category_tree"."id") '
            'SELECT "category_tree"."id" FROM category_tree',
        )
        self.assertIn('SELECT "category_tree"."id","category_tree"."depth" FROM category_tree', str(with_depth))
        self.assertIn(
            'SELECT "category_tree"."id","category_tree"."depth","category_tree"."path" FROM category_tree',
            str(with_path),
        )

    def test_derived_recursive_ctes_remain_independent(self):
        first_anchor = self.anchor_query().where(self.categories.id == 1)
        second_anchor = self.anchor_query().where(self.categories.id == 2)
        base_cte = RecursiveCTE(self.tree_name, self.tree_columns)

        first_cte = base_cte.anchor(first_anchor).union_all(self.recursive_query())
        second_cte = base_cte.anchor(second_anchor).union_all(self.recursive_query())

        self.assertIn('"id"=1', first_cte.get_with_sql(quote_char='"'))
        self.assertNotIn('"id"=1', second_cte.get_with_sql(quote_char='"'))
        self.assertEqual(base_cte.anchor_query, None)


if __name__ == "__main__":
    unittest.main()
