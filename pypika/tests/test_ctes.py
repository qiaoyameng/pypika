import sqlite3
import unittest

from pypika import CTE, AliasedQuery, Query, Table
from pypika import functions as fn
from pypika.terms import Function
from pypika.utils import QueryException, SetOperationException


class CTETests(unittest.TestCase):
    def setUp(self):
        self.directories = Table("directories")

    def _tree_cte(self):
        """
        Builds a recursive CTE walking a directory tree.  The anchor member selects the roots, the recursive
        member joins the CTE against the directories table, and the two are connected with UNION ALL.
        """
        tree = CTE(name="tree", columns=["id", "depth", "path"], recursive=True)
        anchor = (
            Query.from_(self.directories, wrap_set_operation_queries=False)
            .select(self.directories.id, 0, self.directories.name)
            .where(self.directories.parent_id.isnull())
        )
        recursive = (
            Query.from_(tree)
            .join(self.directories)
            .on(self.directories.parent_id == tree.id)
            .select(
                self.directories.id,
                tree.depth + 1,
                Function("printf", "%s/%s", tree.path, self.directories.name),
            )
        )
        return tree.define(anchor.union_all(recursive))

    RECURSIVE_TREE_SQL = (
        'WITH RECURSIVE tree(id,depth,path) AS ('
        'SELECT "id",0,"name" FROM "directories" WHERE "parent_id" IS NULL '
        'UNION ALL '
        'SELECT "directories"."id","tree"."depth"+1,'
        "printf('%s/%s',\"tree\".\"path\",\"directories\".\"name\") "
        'FROM tree JOIN "directories" ON "directories"."parent_id"="tree"."id"'
        ') '
    )

    def test_recursive_cte_with_columns_and_union_all(self):
        tree = self._tree_cte()
        query = Query.with_(tree).from_(tree).select("id", "depth", "path").orderby("path")

        self.assertEqual(
            self.RECURSIVE_TREE_SQL
            + 'SELECT "tree"."id","tree"."depth","tree"."path" FROM tree ORDER BY "tree"."path"',
            str(query),
        )

    def test_cte_with_explicit_columns_non_recursive(self):
        sub_query = Query.from_(self.directories).select("id", "name")
        cte = CTE(sub_query, "dirs", columns=["id", "name"])
        query = Query.with_(cte).from_(cte).select("*")

        self.assertEqual('WITH dirs(id,name) AS (SELECT "id","name" FROM "directories") SELECT * FROM dirs', str(query))

    def test_existing_with_behavior_unchanged(self):
        sub_query = Query.from_(self.directories).select("id")
        query = Query.with_(sub_query, "an_alias").from_(AliasedQuery("an_alias")).select("*")

        self.assertEqual('WITH an_alias AS (SELECT "id" FROM "directories") SELECT * FROM an_alias', str(query))

    def test_multiple_ctes_with_dependency_share_single_recursive_keyword(self):
        tree = self._tree_cte()
        summary = CTE(Query.from_(tree).select(fn.Max(tree.depth)), "max_depth")
        query = Query.with_(tree).with_(summary).from_(summary).select("*")

        self.assertEqual(
            self.RECURSIVE_TREE_SQL + ',max_depth AS (SELECT MAX("tree"."depth") FROM tree) SELECT * FROM max_depth',
            str(query),
        )

    def test_same_name_cte_in_inner_scope_shadows_outer(self):
        tree = self._tree_cte()
        inner = Query.with_(tree).from_(tree).select("*")
        outer = Query.with_(Query.from_(self.directories).select("id"), "tree").from_(inner).select("*")

        self.assertEqual(
            'WITH tree AS (SELECT "id" FROM "directories") '
            "SELECT * FROM (" + self.RECURSIVE_TREE_SQL + "SELECT * FROM tree) \"sq0\"",
            str(outer),
        )

    def test_duplicate_cte_name_raises(self):
        sub_query = Query.from_(self.directories).select("id")

        with self.assertRaises(QueryException):
            Query.with_(sub_query, "dup").with_(Query.from_(self.directories).select("name"), "dup")

        cte = CTE(sub_query, "dup")
        with self.assertRaises(QueryException):
            Query.with_(cte).with_(CTE(Query.from_(self.directories).select("name"), "dup"))

    def test_cte_requires_name(self):
        with self.assertRaises(QueryException):
            CTE(Query.from_(self.directories).select("id"))

    def test_unbound_cte_cannot_be_added_to_query(self):
        tree = CTE(name="tree", columns=["id"], recursive=True)
        with self.assertRaises(QueryException):
            Query.with_(tree)

    def test_column_count_mismatch_raises(self):
        tree = CTE(name="tree", columns=["id", "depth"], recursive=True)
        body = Query.from_(self.directories).select("id", "name", "parent_id")

        with self.assertRaises(QueryException):
            tree.define(body)

        with self.assertRaises(QueryException):
            CTE(body, "tree", columns=["id", "depth"])

    def test_column_count_mismatch_between_union_members_raises(self):
        tree = CTE(name="tree", columns=["id", "depth"], recursive=True)
        anchor = Query.from_(self.directories).select("id", "name")
        recursive = Query.from_(tree).join(self.directories).on(self.directories.parent_id == tree.id).select("id")

        with self.assertRaises(SetOperationException):
            tree.define(anchor.union_all(recursive))

    def test_star_select_skips_column_validation(self):
        # The column count of SELECT * cannot be determined statically, so the validation is skipped.
        cte = CTE(name="stars", columns=["id"]).define(Query.from_(self.directories).select("*"))
        query = Query.with_(cte).from_(cte).select("*")

        self.assertEqual('WITH stars(id) AS (SELECT * FROM "directories") SELECT * FROM stars', str(query))

    def test_define_returns_new_instance_and_leaves_original_unbound(self):
        ref = CTE(name="tree", columns=["id"], recursive=True)
        bound = ref.define(Query.from_(self.directories).select("id"))

        self.assertIsNone(ref.query)
        self.assertIsNotNone(bound.query)

        with self.assertRaises(AttributeError):
            bound.define(Query.from_(self.directories).select("id"))

    def test_derived_queries_do_not_rewrite_each_other(self):
        tree = self._tree_cte()
        base = Query.with_(tree).from_(tree).select("id", "depth", "path")
        base_sql = str(base)

        shallow = base.where(tree.depth <= 1).orderby("path")
        deep = base.where(tree.depth >= 2).orderby("path")

        self.assertEqual(base_sql, str(base))
        self.assertNotEqual(str(shallow), str(deep))
        self.assertEqual(
            self.RECURSIVE_TREE_SQL + 'SELECT "tree"."id","tree"."depth","tree"."path" FROM tree '
            'WHERE "tree"."depth"<=1 ORDER BY "tree"."path"',
            str(shallow),
        )
        self.assertEqual(
            self.RECURSIVE_TREE_SQL + 'SELECT "tree"."id","tree"."depth","tree"."path" FROM tree '
            'WHERE "tree"."depth">=2 ORDER BY "tree"."path"',
            str(deep),
        )


class RecursiveCTESQLiteTests(unittest.TestCase):
    """
    Runs a recursive CTE built with PyPika against a three level directory tree in SQLite:

    root (id=1) -- docs (id=2) -- work (id=4), and pics (id=3) below root.
    """

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE directories (id INTEGER PRIMARY KEY, parent_id INTEGER, name TEXT)")
        self.conn.executemany(
            "INSERT INTO directories (id, parent_id, name) VALUES (?, ?, ?)",
            [(1, None, "root"), (2, 1, "docs"), (3, 1, "pics"), (4, 2, "work")],
        )

        directories = Table("directories")
        tree = CTE(name="tree", columns=["id", "depth", "path"], recursive=True)
        anchor = (
            Query.from_(directories, wrap_set_operation_queries=False)
            .select(directories.id, 0, directories.name)
            .where(directories.parent_id.isnull())
        )
        recursive = (
            Query.from_(tree)
            .join(directories)
            .on(directories.parent_id == tree.id)
            .select(
                directories.id,
                tree.depth + 1,
                Function("printf", "%s/%s", tree.path, directories.name),
            )
        )
        self.tree = tree.define(anchor.union_all(recursive))

    def tearDown(self):
        self.conn.close()

    def test_directory_tree_depth_and_path(self):
        query = Query.with_(self.tree).from_(self.tree).select("id", "depth", "path").orderby("path")

        rows = self.conn.execute(str(query)).fetchall()

        self.assertEqual(
            [(1, 0, "root"), (2, 1, "root/docs"), (4, 2, "root/docs/work"), (3, 1, "root/pics")],
            rows,
        )
        self.assertEqual(2, max(row[1] for row in rows))
        self.assertEqual(
            ["root", "root/docs", "root/docs/work", "root/pics"],
            [row[2] for row in rows],
        )

    def test_derived_queries_against_sqlite(self):
        base = Query.with_(self.tree).from_(self.tree).select("id", "depth", "path")
        shallow = base.where(self.tree.depth <= 1).orderby("path")
        deep = base.where(self.tree.depth >= 2)

        self.assertNotEqual(str(shallow), str(deep))

        shallow_rows = self.conn.execute(str(shallow)).fetchall()
        deep_rows = self.conn.execute(str(deep)).fetchall()

        self.assertEqual([(1, 0, "root"), (2, 1, "root/docs"), (3, 1, "root/pics")], shallow_rows)
        self.assertEqual([(4, 2, "root/docs/work")], deep_rows)
