"""One implementation of the fold, so every consumer does not write their own bugs.

Resolving `mart.t.v <- tmp_v.v <- ods.real.v` down to `mart.t.v <- ods.real.v` is mechanical,
but it is not obvious, and each of the ways to get it wrong was found the hard way while
writing the recipe that used to be published as documentation:

- a source with no table is not a relation to resolve -- a constant is `source_kind=generated`
  and folding it away deletes a real fact;
- an unbounded walk hangs or empties on a relation redefined in terms of itself;
- an empty result is not "this column has no lineage", and returning one silently says that;
- `end_to_end_lineage` is a final-state view, so a hop into a state no row describes cannot be
  folded at all, and substituting the surviving definition asserts the wrong origin
  (STATE-ID-002);
- a relation whose own columns were never resolved has no row for the column being read, only
  one keyed on `*` (TRACE-002).

The last two are why this returns what it could not fold rather than throwing it away. Core's
job is to state what is true; a fold that quietly drops what it cannot resolve turns a gap into
a false clean answer.
"""

from __future__ import annotations

from scope_lineage import fold_session_scoped
from scope_lineage.contract.task_lineage import to_task_lineage_dict
from scope_lineage.scope.task_lineage import parse_task_lineage

SCHEMA = {"ods.real": ["id", "amt"], "ods.a": ["id"], "ods.b": ["id"]}


def _document(sql, schema=SCHEMA):
    return to_task_lineage_dict(parse_task_lineage(sql, task_name="t", schema=schema))


def _folded(document, table, column):
    for item in fold_session_scoped(document)["end_to_end_lineage"]:
        if item.get("table") == table and item.get("column") == column:
            return item
    raise AssertionError(f"no row for {table}.{column}")


def test_a_hop_through_a_temp_view_resolves_to_the_physical_source():
    document = _document(
        "create or replace temp view tmp_v as select id, amt from ods.real;\n"
        "insert overwrite table mart.daily select id, amt from tmp_v"
    )
    row = _folded(document, "mart.daily", "amt")

    assert [(s["table"], s["column"]) for s in row["value_sources"]] == [("ods.real", "amt")]
    assert row["value_sources_folded"] is True


def test_the_original_document_is_not_mutated():
    document = _document(
        "create or replace temp view tmp_v as select id from ods.real;\n"
        "insert overwrite table mart.daily select id from tmp_v"
    )
    before = [
        s["table"]
        for item in document["end_to_end_lineage"]
        if item["table"] == "mart.daily"
        for s in item["value_sources"]
    ]
    fold_session_scoped(document)
    after = [
        s["table"]
        for item in document["end_to_end_lineage"]
        if item["table"] == "mart.daily"
        for s in item["value_sources"]
    ]

    assert before == after == ["tmp_v"]


def test_a_constant_survives_the_fold():
    """`source_kind=generated` has no table; folding it away deletes a real fact."""
    document = _document(
        "create or replace temp view tmp_v as select id, 'X' as tag from ods.real;\n"
        "insert overwrite table mart.daily select id, tag from tmp_v"
    )
    row = _folded(document, "mart.daily", "tag")

    assert [s["source_kind"] for s in row["value_sources"]] == ["generated"]


def test_a_hop_into_a_state_no_row_describes_is_kept_not_guessed():
    """The redefinition case. Substituting the surviving definition asserts a false origin."""
    document = _document(
        "create or replace temp view v as select id from ods.a;\n"
        "insert overwrite table mart.x select id from v;\n"
        "create or replace temp view v as select id from ods.b;\n"
        "insert overwrite table mart.y select id from v"
    )

    unfoldable = _folded(document, "mart.x", "id")
    assert [s["table"] for s in unfoldable["value_sources"]] == ["v"], "the edge is kept as-is"
    assert unfoldable["value_sources_folded"] is False
    assert "source_state_not_in_document" in unfoldable["fold_incomplete_reasons"]

    foldable = _folded(document, "mart.y", "id")
    assert [s["table"] for s in foldable["value_sources"]] == ["ods.b"]


def test_a_relation_whose_columns_are_unknown_is_kept_not_emptied():
    document = _document(
        "create or replace temp view tv as select * from ods.unknown_table;\n"
        "insert overwrite table mart.daily select id, amt from tv",
        schema={},
    )
    row = _folded(document, "mart.daily", "id")

    assert [s["table"] for s in row["value_sources"]] == ["tv"]
    assert row["value_sources_folded"] is False
    assert "source_column_not_in_document" in row["fold_incomplete_reasons"]


def test_a_cycle_terminates_and_keeps_the_edge():
    document = _document(
        "create or replace temp view a as select id from ods.a;\n"
        "create or replace temp view b as select id from a;\n"
        "create or replace temp view a as select id from b;\n"
        "insert overwrite table mart.daily select id from a"
    )
    row = _folded(document, "mart.daily", "id")

    assert row["value_sources"], "a cycle must not empty the row"
    assert row["value_sources_folded"] is False


def test_a_document_with_nothing_to_fold_is_returned_unchanged():
    document = _document("insert overwrite table mart.daily select id from ods.real")
    folded = fold_session_scoped(document)

    assert folded["end_to_end_lineage"] == document["end_to_end_lineage"]
    assert all(
        "value_sources_folded" not in item
        for item in folded["end_to_end_lineage"]
    )


def test_rows_for_the_session_scoped_relations_themselves_are_dropped():
    """They are not tables in the warehouse; a folded view should not list them."""
    document = _document(
        "create or replace temp view tmp_v as select id from ods.real;\n"
        "insert overwrite table mart.daily select id from tmp_v"
    )
    folded = fold_session_scoped(document)

    assert {item["table"] for item in folded["end_to_end_lineage"]} == {"mart.daily"}
    assert "tmp_v" not in folded["final_table_states"]
