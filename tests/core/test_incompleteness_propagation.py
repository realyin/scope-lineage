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


NAMED_PROJECTION_INTO_AN_UNKNOWN_TABLE = (
    "insert overwrite table stage.t partition(dt='20260101') select id, amt from ods.real;\n"
    "insert overwrite table mart.t select id from stage.t"
)


def test_a_relation_whose_columns_are_named_is_described_whatever_else_is_missing():
    """`columns_known` answers a broader question than this gap asks.

    A valued-partition overwrite needs the table's prior state, and when the target is not in
    the supplied schema that state carries `schema_missing_for_state_passthrough`. `columns_known`
    is false for any missing reason at all, so keying this gap on it reported "the columns of
    this relation are unknown" about a relation whose columns are `['id', 'amt']` and sitting
    right there in the document.

    The question is narrower: does the relation have a row for the column being read. A
    wildcard projection has no such row and cannot get one; a named projection always does,
    whatever else about the state is imperfect (TRACE-002).
    """
    result = parse_task_lineage(
        NAMED_PROJECTION_INTO_AN_UNKNOWN_TABLE,
        task_name="t",
        schema={"ods.real": ["id", "amt"]},
    )

    staged = [item for item in result.end_to_end_lineage if item["table"] == "stage.t"]
    assert [item["column"] for item in staged] == ["id", "amt"], "the columns are known"

    row = _row(result, "mart.t", "id")
    assert row["trace_complete"] is True
    assert "source_state_columns_unknown" not in row["missing_reasons"]


def test_reading_a_column_the_relation_does_not_have_is_still_reported():
    """The narrower test must still catch what the broader one was there for."""
    result = parse_task_lineage(STAR_THROUGH_A_VIEW, task_name="t", schema={})
    row = _row(result, "mart.daily", "id")

    assert row["trace_complete"] is False
    assert "source_state_columns_unknown" in row["missing_reasons"]


def test_counting_rows_of_a_described_relation_is_not_a_gap():
    """`*` means two opposite things, and only one of them is a hole.

    A projection that stayed a wildcard names its target column `*` because the columns are
    genuinely unknown. `COUNT(*)` also records the source column as `*`, but that star is the
    row itself -- the lineage is resolved, and depending on every column is the fact rather
    than a gap in it. `_projection_state_missing_reasons` already carries this warning; keying
    this gap on "the relation has no row for the column read" walked into it from the other
    side, reporting relations with a dozen named columns as undescribed because nothing
    answered to `*`.
    """
    result = parse_task_lineage(
        "insert overwrite table stage.t select id, amt from ods.real;\n"
        "insert overwrite table mart.t select count(*) as n from stage.t",
        task_name="t",
        schema={"ods.real": ["id", "amt"]},
    )
    row = _row(result, "mart.t", "n")

    assert row["trace_complete"] is True
    assert "source_state_columns_unknown" not in row["missing_reasons"]
