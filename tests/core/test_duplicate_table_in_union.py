"""A UNION branch's *sources* are its FROM/JOIN relations, not everything it reads.

`_detect_duplicate_table_in_union` warns when the same physical table feeds more than one
branch of a UNION -- the shape that usually means a branch was copy-pasted and its source
never changed. It read that fact off `branch.depends_on`.

`depends_on` is everything the scope reaches, and once a filter subquery's physical tables
were restored to it, a table referenced only inside a branch's `NOT EXISTS` started counting
as that branch's source. The anti-join pattern below -- one branch reading a table, the next
branch excluding rows that already exist in it -- is deliberate and extremely common, and it
now warns on every occurrence.

`ScopeInputEdge` already records exactly what this detector wants: "a direct input edge from
a FROM/JOIN source into a scope". Reading `input_edges` instead of `depends_on` separates the
two readings without losing a real duplicate, including one the branch pulls in by JOIN.

Not fixed here: a branch whose FROM is a derived table over the shared physical table is
still missed, because that edge points at a scope rather than at a table. That gap predates
this warning's regression and widening the detector's reach is a different change with a
different risk (DUP-UNION-001).
"""

from __future__ import annotations

from scope_lineage.scope.scope_builder import parse_all_scope_lineage

ANTI_JOIN = (
    "INSERT OVERWRITE TABLE tgt.t_out\n"
    "SELECT k, v FROM (\n"
    "    SELECT a.k, a.v FROM src.t_main a\n"
    "    UNION ALL\n"
    "    SELECT b.k, b.v FROM src.t_extra b\n"
    "    WHERE NOT EXISTS (SELECT 1 FROM src.t_main m WHERE m.k = b.k)\n"
    ") t"
)

REPEATED_FROM = (
    "INSERT OVERWRITE TABLE tgt.t_out\n"
    "SELECT k, v FROM (\n"
    "    SELECT a.k, a.v FROM src.t_main a WHERE a.flag = 1\n"
    "    UNION ALL\n"
    "    SELECT c.k, c.v FROM src.t_main c WHERE c.flag = 2\n"
    ") t"
)

SELF_JOIN_IN_ONE_BRANCH = (
    "INSERT OVERWRITE TABLE tgt.t_out\n"
    "SELECT k, v FROM (\n"
    "    SELECT x.k, y.v FROM src.t_main x JOIN src.t_main y ON y.k = x.k\n"
    "    UNION ALL\n"
    "    SELECT b.k, b.v FROM src.t_extra b\n"
    ") t"
)

JOINED_IN = (
    "INSERT OVERWRITE TABLE tgt.t_out\n"
    "SELECT k, v FROM (\n"
    "    SELECT a.k, a.v FROM src.t_main a\n"
    "    UNION ALL\n"
    "    SELECT b.k, b.v FROM src.t_extra b JOIN src.t_main j ON j.k = b.k\n"
    ") t"
)


def _warning_types(sql: str) -> list[str]:
    result = parse_all_scope_lineage(sql, "t")[0]
    return [warning.type for warning in result.diagnostics.warnings]


def test_a_table_read_only_by_a_branch_filter_subquery_is_not_a_branch_source():
    assert "duplicate_table_in_union" not in _warning_types(ANTI_JOIN)


def test_the_same_table_in_two_branch_from_clauses_is_still_reported():
    assert "duplicate_table_in_union" in _warning_types(REPEATED_FROM)


def test_a_table_joined_into_a_branch_is_still_a_branch_source():
    assert "duplicate_table_in_union" in _warning_types(JOINED_IN)


def test_a_table_read_twice_inside_one_branch_is_not_a_duplicate_across_branches():
    # One branch can hold several edges to the same table -- a self-join is the plain case.
    # Counting edges rather than branches makes a single branch look like three.
    assert "duplicate_table_in_union" not in _warning_types(SELF_JOIN_IN_ONE_BRANCH)
