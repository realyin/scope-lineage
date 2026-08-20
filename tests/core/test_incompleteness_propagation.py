"""Reading a relation whose own columns are unknown does not produce complete lineage.

A temporary relation built from an unexpanded `SELECT *` has one row, keyed on `*`, with
`trace_complete: false`. A statement reading named columns out of it produced rows claiming
`trace_complete: true` -- a confident answer resting on a relation nobody could describe
(TRACE-002).

Two things follow from that, and the second is why it matters more than a flag being wrong.
A consumer folding the hop looks for the source column's row, finds only `*`, and gets an
empty result that reads as "this column has no lineage". Meanwhile the row itself says the
trace is complete, so nothing contradicts that reading.

Incompleteness already propagates from the *previous state of the table being written*. It did
not propagate from the *relations being read*, which is the same question asked of a different
edge.
"""

from __future__ import annotations

from scope_lineage.scope.task_lineage import parse_task_lineage

STAR_THROUGH_A_VIEW = (
    "create or replace temp view tv as select * from ods.unknown_table;\n"
    "insert overwrite table mart.daily select id, amt from tv"
)


def _row(result, table, column):
    for item in result.end_to_end_lineage:
        if item.get("table") == table and item.get("column") == column:
            return item
    raise AssertionError(f"no row for {table}.{column}")


def test_a_column_read_through_an_undescribed_relation_is_not_complete():
    result = parse_task_lineage(STAR_THROUGH_A_VIEW, task_name="t", schema={})

    row = _row(result, "mart.daily", "id")
    assert row["trace_complete"] is False
    assert "source_state_columns_unknown" in row["missing_reasons"], row["missing_reasons"]


def test_the_relation_that_caused_it_still_says_so_itself():
    result = parse_task_lineage(STAR_THROUGH_A_VIEW, task_name="t", schema={})

    assert _row(result, "tv", "*")["trace_complete"] is False


def test_a_described_relation_still_yields_complete_lineage():
    """The boundary: a temp view whose columns are known propagates nothing."""
    result = parse_task_lineage(
        "create or replace temp view tv as select id, amt from ods.real;\n"
        "insert overwrite table mart.daily select id, amt from tv",
        task_name="t",
        schema={"ods.real": ["id", "amt"]},
    )

    row = _row(result, "mart.daily", "id")
    assert row["trace_complete"] is True
    assert row["missing_reasons"] == []


def test_a_plain_physical_read_is_untouched():
    result = parse_task_lineage(
        "insert overwrite table mart.daily select id from ods.real",
        task_name="t",
        schema={"ods.real": ["id"]},
    )

    assert _row(result, "mart.daily", "id")["trace_complete"] is True


def test_the_statement_reports_it_as_a_gap_too():
    """A consumer reading diagnostics rather than walking rows must also see it."""
    result = parse_task_lineage(STAR_THROUGH_A_VIEW, task_name="t", schema={})
    gap_types = {gap.get("gap_type") for gap in result.diagnostics["lineage_fact_gaps"]}

    assert "source_state_columns_unknown" in gap_types, gap_types
