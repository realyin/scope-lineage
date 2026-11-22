"""Two more paths that published a placeholder table beside ``trace_complete: true``.

WP3q closed the DELETE / UPDATE / MERGE predicate path. Two others remained, and the
new top-level invariant (no ``UNKNOWN`` / ``AMBIGUOUS`` table in a complete row) would
fail on both:

- an INSERT whose WHERE reads a bare column two joined tables both have published
  ``{"table": "AMBIGUOUS"}`` as a row-membership source, with no gap;
- a predicate qualifier that names no table of the query it sits in published the
  qualifier itself as the table: a correlated ``t.id`` for ``DELETE FROM mart.t t``
  became table ``t``, and a qualifier naming nothing became a table of that name.

Every name here is synthetic.
"""

from __future__ import annotations

from scope_lineage.contract import to_task_lineage_dict
from scope_lineage.contract.invariants import validate_contract_invariants
from scope_lineage.scope.task_lineage import parse_task_lineage

SCHEMA = {"mart.t": ["id", "v"], "ods.a": ["id", "v", "status"], "ods.b": ["id", "status"]}
REASON = "row_condition_source_unresolved"


def _run(sql: str):
    return parse_task_lineage(sql, "t", schema=SCHEMA)


def _rows(result, table: str = "mart.t") -> list[dict]:
    return [row for row in result.end_to_end_lineage if row["table"] == table]


def _gaps(result) -> list[dict]:
    return [
        gap for gap in result.diagnostics["lineage_fact_gaps"]
        if gap["gap_type"] == REASON
    ]


def _membership_tables(row: dict) -> set[str]:
    return {source["table"] for source in row["row_membership_sources"]}


def _invariants(result) -> list[str]:
    return validate_contract_invariants(to_task_lineage_dict(result))


INSERT_JOIN = (
    "INSERT OVERWRITE TABLE mart.t SELECT a.id, a.v FROM ods.a a "
    "JOIN ods.b b ON a.id = b.id WHERE {column} = 1;"
)


def test_an_insert_condition_two_tables_could_own_is_a_gap_not_a_name() -> None:
    """Like any INSERT condition field that reaches no physical column: no name, a gap.

    ``trace_complete`` keeps answering only whether the values were traced; the gap is
    what ``conditions_closed`` reads (docs: when a row may be used as a complete fact).
    """
    result = _run(INSERT_JOIN.format(column="status"))

    rows = _rows(result)
    assert rows
    for row in rows:
        assert _membership_tables(row) == {"ods.a", "ods.b"}
        assert row["trace_complete"] is True
    [gap] = _gaps(result)
    assert gap["column"] == "status"
    assert gap["scope_id"] == "AMBIGUOUS"
    assert gap["logic_type"] == "filter"
    assert gap["root_impact"] is True
    assert _invariants(result) == []


def test_an_insert_condition_with_a_qualifier_is_unchanged() -> None:
    result = _run(INSERT_JOIN.format(column="b.status"))

    for row in _rows(result):
        assert row["trace_complete"] is True
        assert {"table": "ods.b", "column": "status"} in row["row_membership_sources"]
    assert _gaps(result) == []


def test_a_correlated_reference_to_the_delete_alias_is_the_target() -> None:
    result = _run(
        "DELETE FROM mart.t t WHERE EXISTS (SELECT 1 FROM ods.a a WHERE a.id = t.id);"
    )

    for row in _rows(result):
        assert _membership_tables(row) == {"ods.a", "mart.t"}
        assert row["trace_complete"] is True
    assert _gaps(result) == []


def test_a_correlated_reference_to_the_unaliased_target_name_is_the_target() -> None:
    result = _run(
        "UPDATE mart.t SET v = 0 WHERE EXISTS (SELECT 1 FROM ods.a a WHERE a.id = t.id);"
    )

    by_column = {row["column"]: row for row in _rows(result)}
    assert {source["table"] for source in by_column["v"]["value_condition_sources"]} == {
        "ods.a", "mart.t",
    }
    assert by_column["v"]["trace_complete"] is True


def test_a_reference_to_an_enclosing_query_alias_resolves_there() -> None:
    result = _run(
        "DELETE FROM mart.t WHERE id IN (SELECT a.id FROM ods.a a "
        "WHERE EXISTS (SELECT 1 FROM ods.b b WHERE b.id = a.id));"
    )

    for row in _rows(result):
        assert _membership_tables(row) == {"mart.t", "ods.a", "ods.b"}
        assert row["trace_complete"] is True


def test_a_qualifier_naming_no_table_is_a_gap_not_a_table() -> None:
    result = _run(
        "DELETE FROM mart.t WHERE EXISTS (SELECT 1 FROM ods.a a WHERE a.id = zz.id);"
    )

    for row in _rows(result):
        assert "zz" not in _membership_tables(row)
        assert "UNKNOWN" not in _membership_tables(row)
        assert {"table": "ods.a", "column": "id"} in row["row_membership_sources"]
        assert row["trace_complete"] is True
        assert REASON not in row["missing_reasons"]
    [gap] = _gaps(result)
    assert gap["column"] == "id"
    assert _invariants(result) == []


def test_a_top_level_target_qualifier_is_the_target() -> None:
    result = _run("DELETE FROM mart.t x WHERE x.v = 1;")

    for row in _rows(result):
        assert row["row_membership_sources"] == [{"table": "mart.t", "column": "v"}]
        assert row["trace_complete"] is True
