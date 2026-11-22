"""Audit 1.13-g / 1.13-a: two dead branches in the scope builder.

``_looks_schema_expanded_from_physical`` decides which scopes the dangling-ref sweep leaves
alone because their columns came from expanding ``SELECT *`` over a table's schema. It
guessed from the text of each column's expression (``expression in (None, "", name)``),
but a real star expansion writes ``a.x``, so the guess never held for one; it held instead
for bare columns no star produced. The expansion already records the fact it was guessing
(``star_schema_sources``), so the exemption reads that marker.

``_extract_case_branches`` also walked ``exp.When`` nodes, which a CASE never contains
(``exp.When`` is MERGE's clause and not a subclass of ``exp.If``); the walk is gone and the
sentinel pins that a nested CASE still yields only the outer branches.
"""

from __future__ import annotations

import sqlglot

from scope_lineage.scope.scope_builder import _looks_schema_expanded_from_physical, parse_scope_lineage
from scope_lineage.scope.scope_types import ScopeColumn, ScopeData, SourceRef
from scope_lineage.scope.select_scope import _extract_case_branches


def test_a_star_expanded_from_a_table_schema_is_exempt() -> None:
    result = parse_scope_lineage(
        "WITH c AS (SELECT * FROM s.a) INSERT OVERWRITE TABLE m.t SELECT c.x, c.q FROM c",
        "exempt",
        schema={"s.a": ["x", "y", "z"]},
    )

    assert _looks_schema_expanded_from_physical(result.scopes["cte:c"]) is True


def test_bare_physical_columns_without_a_star_are_not_exempt() -> None:
    # The shape a failed qualify leaves: bare column names read from a table, no star.
    scope = ScopeData(
        kind="cte",
        columns=[
            ScopeColumn(name=name, transform="DIRECT", expression=name,
                        sources=[SourceRef(scope="s.a", column=name)])
            for name in ("x", "y", "z")
        ],
    )

    assert _looks_schema_expanded_from_physical(scope) is False


def test_sentinel_an_explicit_column_list_is_not_exempt() -> None:
    result = parse_scope_lineage(
        "WITH c AS (SELECT x, y, z FROM s.a) INSERT OVERWRITE TABLE m.t SELECT c.x FROM c",
        "exempt",
        schema={"s.a": ["x", "y", "z"]},
    )

    assert _looks_schema_expanded_from_physical(result.scopes["cte:c"]) is False


def test_sentinel_a_nested_case_yields_only_the_outer_branches() -> None:
    case = sqlglot.parse_one(
        "CASE WHEN a = 1 THEN CASE WHEN b = 2 THEN 3 END ELSE 4 END", read="spark"
    )

    assert [branch["when_expr"] for branch in _extract_case_branches(case)] == ["a = 1", "ELSE"]
