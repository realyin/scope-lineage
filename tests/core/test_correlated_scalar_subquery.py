"""A correlated scalar subquery's outer reference is a source of the projection, not a gap.

``(SELECT MAX(d.name) FROM db.dim d WHERE d.id = t.k) AS nm`` reads ``t.k`` from the
outer ``FROM db.src t``. The physical fields already held ``db.src.k``, but reference
extraction skipped every column inside the nested SELECT -- the outer ``t.k`` with them --
so ``t`` was never expanded, and the text check for unexpanded aliases then marked the
column ``partially_resolved`` (``expanded_expression_contains_unexpanded_alias:t``),
which made the task partial. A table named like its alias (``db.t t``) hid it.
"""

from __future__ import annotations

from scope_lineage.scope.task_lineage import parse_task_lineage

SCHEMA = {"db.src": ["id", "k"], "db.dim": ["id", "name"], "db.out": ["id", "nm"]}


def _parse(sql: str):
    result = parse_task_lineage(sql, task_name="t", schema=SCHEMA)
    gaps = [gap for gap in result.diagnostics["lineage_fact_gaps"]]
    return result, gaps


def test_an_outer_reference_in_a_scalar_subquery_is_expanded() -> None:
    result, gaps = _parse(
        "INSERT OVERWRITE TABLE db.out SELECT t.id, "
        "(SELECT MAX(d.name) FROM db.dim d WHERE d.id = t.k) AS nm FROM db.src t"
    )

    assert gaps == []
    assert result.analysis_status["status"] == "complete"
    output = next(
        item for item in result.statement_lineage["stmt:001"]["scopes"]["ROOT"]["outputs"]
        if item["name"] == "nm"
    )
    assert "`db.src`.`k`" in output["expression_resolution"]["expanded_expression"]


def test_an_alias_the_subquery_redefines_is_not_taken_for_the_outer_one() -> None:
    result, _gaps = _parse(
        "INSERT OVERWRITE TABLE db.out SELECT t.id, "
        "(SELECT MAX(t.name) FROM db.dim t WHERE t.id = 1) AS nm FROM db.src t"
    )
    output = next(
        item for item in result.statement_lineage["stmt:001"]["scopes"]["ROOT"]["outputs"]
        if item["name"] == "nm"
    )

    assert "`db.src`.`name`" not in output["expression_resolution"]["expanded_expression"]


DEEP = (
    "INSERT OVERWRITE TABLE db.out SELECT t.id, "
    "(SELECT SUM(x.amt) FROM (SELECT SUM(d.name) AS amt FROM db.dim d "
    "WHERE d.id = t.k GROUP BY d.id) x) AS nm FROM db.src t"
)


def _sources(result, column: str) -> set[tuple[str, str]]:
    row = next(item for item in result.end_to_end_lineage if item["column"] == column)
    return {(source["table"], source["column"]) for source in row["value_sources"]}


def test_an_outer_reference_two_levels_down_stays_an_outer_reference() -> None:
    """sqlglot read ``t.k`` there as the struct field ``k`` of a column ``t`` of ``db.dim``."""
    result, gaps = _parse(DEEP)

    assert ("db.src", "k") in _sources(result, "nm")
    assert ("db.dim", "t") not in _sources(result, "nm")
    assert gaps == []


def test_a_struct_column_of_the_inner_source_stays_a_struct_access() -> None:
    schema = {**SCHEMA, "db.dim": ["id", "name", "t"]}
    result = parse_task_lineage(DEEP, task_name="t", schema=schema)

    assert ("db.dim", "t") in _sources(result, "nm")
