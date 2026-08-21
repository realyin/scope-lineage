"""A LATERAL VIEW generator over a literal must record its constant source.

``_resolve_lateral_scope`` resolved the generator argument's column references and
minted the output columns with whatever came back. For a generator over a literal
-- ``EXPLODE(ARRAY(...))``, ``INLINE(ARRAY(STRUCT(...)))`` -- that is the empty
list, so the column became a dead end: no source to report, and no reason why.
``end_to_end_lineage`` then rendered it ``source_kind: "unresolved"`` while
``trace_complete`` stayed true, which is exactly the pair a consumer cannot tell
apart from a proven source (LINEAGE-002).

The VALUES / table-valued-function path in the same module already routes a
source-free leaf through ``_source_free_leaf_sources``; this is that path's
missing twin.
"""
from __future__ import annotations

from scope_lineage.scope.end_to_end import build_end_to_end_lineage
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {"db.src": ["id", "a", "b", "col"]}


def _parse(sql: str):
    return parse_scope_lineage(sql, task_name="t", schema=SCHEMA)


def _row(result, column: str) -> dict:
    for row in build_end_to_end_lineage(result):
        if row.get("column") == column:
            return row
    raise AssertionError(f"no end_to_end row for {column}")


def _zero_source_columns(result) -> list[tuple[str, str]]:
    return [
        (scope_id, column.name)
        for scope_id, scope_data in result.scopes.items()
        for column in scope_data.columns or []
        if not column.sources
    ]


def test_generator_over_literal_array_records_its_constant_source():
    result = _parse(
        "INSERT INTO db.tgt SELECT s.id, w.dw FROM db.src s "
        "LATERAL VIEW EXPLODE(ARRAY('day','week')) w AS dw"
    )
    row = _row(result, "dw")
    assert row["source_kind"] == "generated", row
    assert row["generated_sources"], row
    assert row["trace_complete"] is True, row


def test_generator_over_literal_struct_records_its_constant_source():
    result = _parse(
        "INSERT INTO db.tgt SELECT s.id, ao.c1, ao.c2 FROM db.src s "
        "LATERAL VIEW INLINE(ARRAY(STRUCT('a' AS c1, 'x' AS c2))) ao AS c1, c2"
    )
    for column in ("c1", "c2"):
        row = _row(result, column)
        assert row["source_kind"] == "generated", row
        assert row["generated_sources"], row


def test_scope_column_from_literal_generator_has_sources():
    """Pins the fix to the resolver, not to the end-to-end tracer.

    Recovering the source only while building end_to_end_lineage would leave this
    assertion failing -- and would leave the same dead end in the scope document,
    where field_mapping_chains and any scope-graph consumer still read it.
    """
    result = _parse(
        "INSERT INTO db.tgt SELECT s.id, w.dw FROM db.src s "
        "LATERAL VIEW EXPLODE(ARRAY('day','week')) w AS dw"
    )
    assert _zero_source_columns(result) == []


def test_downstream_case_over_generator_column_becomes_mixed():
    """An intended downstream consequence, pinned so it cannot regress silently.

    A column that branches on the generator's value genuinely depends on both the
    physical inputs and the literal array, so `mixed` is the correct answer -- not
    the `physical` the tracer reported while the constant was invisible.
    """
    result = _parse(
        "INSERT INTO db.tgt WITH m AS ("
        " SELECT s.a, s.b, w.dw FROM db.src s LATERAL VIEW EXPLODE(ARRAY('day','week')) w AS dw"
        ") SELECT CASE WHEN m.dw = 'day' THEN m.a ELSE m.b END AS dt FROM m"
    )
    row = _row(result, "dt")
    assert row["source_kind"] == "mixed", row


def test_generator_over_column_is_unchanged():
    """Negative control: the common form was never affected and must stay put."""
    result = _parse(
        "INSERT INTO db.tgt SELECT s.id, w.dw FROM db.src s "
        "LATERAL VIEW EXPLODE(SPLIT(s.col, ',')) w AS dw"
    )
    assert _zero_source_columns(result) == []
    assert _row(result, "dw")["source_kind"] == "physical"


def test_no_end_to_end_row_claims_complete_with_zero_sources():
    """The invariant the defect broke: nothing is 'fully traced' to nowhere."""
    result = _parse(
        "INSERT INTO db.tgt SELECT s.id, w.dw FROM db.src s "
        "LATERAL VIEW EXPLODE(ARRAY('day','week')) w AS dw"
    )
    for row in build_end_to_end_lineage(result):
        empty = not (
            row.get("physical_sources")
            or row.get("generated_sources")
            or row.get("rowset_sources")
        )
        assert not (empty and row.get("trace_complete")), row
