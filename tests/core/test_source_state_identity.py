"""A source that reads a script-local relation says which state of it it read.

`state_id` became unique per re-creation (STATE-ID-001), but a value source names only the
table. So a script that redefines a temporary relation gives two different reads the identical
source `{table: "v", column: "id"}`, and a consumer resolving that hop by name folds both to
whichever definition was recorded last -- a false statement about where the column came from
(STATE-ID-002).

`end_to_end_lineage` is a final-state view by definition: it walks the state each table is in
when the script ends. So the row for the earlier definition is not in the document and cannot
be, without changing what the field means. Naming the state on the source is what makes that
survivable: a consumer looking for `state:v:001` finds no row, and knows the hop cannot be
folded from this document instead of silently folding it wrong.

That is the whole claim being made here -- detectable rather than complete. Core states which
state was read; it does not promise every state is reachable.

Only states produced by a statement in this script are named. A table nobody wrote is in the
state it had before the script began, and there is no second candidate to be confused with.
"""

from __future__ import annotations

from scope_lineage.scope.task_lineage import parse_task_lineage

SCHEMA = {"ods.a": ["id"], "ods.b": ["id"], "ods.plain": ["id"]}

REDEFINED = (
    "create or replace temp view v as select id from ods.a;\n"
    "insert overwrite table mart.x select id from v;\n"
    "create or replace temp view v as select id from ods.b;\n"
    "insert overwrite table mart.y select id from v"
)


def _sources(result, table, column="id"):
    for item in result.end_to_end_lineage:
        if item.get("table") == table and item.get("column") == column:
            return item.get("value_sources") or []
    raise AssertionError(f"no end_to_end row for {table}.{column}")


def test_two_reads_of_a_redefined_relation_are_distinguishable():
    result = parse_task_lineage(REDEFINED, task_name="t", schema=SCHEMA)

    assert _sources(result, "mart.x")[0]["source_state"] == "state:v:001"
    assert _sources(result, "mart.y")[0]["source_state"] == "state:v:002"


def test_an_unfoldable_hop_is_detectable_rather_than_wrong():
    """The point of the field: a consumer can tell the fold is unavailable."""
    result = parse_task_lineage(REDEFINED, task_name="t", schema=SCHEMA)
    rows_by_state = {
        item.get("target_state") for item in result.end_to_end_lineage
    }

    read_by_x = _sources(result, "mart.x")[0]["source_state"]
    read_by_y = _sources(result, "mart.y")[0]["source_state"]

    assert read_by_x not in rows_by_state, "the earlier definition is not in a final-state view"
    assert read_by_y in rows_by_state, "the surviving definition is, and folds normally"


def test_a_table_nobody_wrote_carries_no_source_state():
    """No second candidate exists, so naming a state would be noise."""
    result = parse_task_lineage(
        "insert overwrite table mart.t select id from ods.plain",
        task_name="t",
        schema=SCHEMA,
    )
    source = _sources(result, "mart.t")[0]

    assert source["table"] == "ods.plain"
    assert "source_state" not in source


def test_a_table_written_earlier_in_the_script_is_named():
    result = parse_task_lineage(
        "insert overwrite table stage.t select id from ods.plain;\n"
        "insert overwrite table mart.t select id from stage.t",
        task_name="t",
        schema=SCHEMA,
    )
    source = _sources(result, "mart.t")[0]

    assert source["table"] == "stage.t"
    assert source["source_state"] == "state:stage.t:001"


def test_generated_sources_are_untouched():
    result = parse_task_lineage(
        "insert overwrite table mart.t select 'X' as tag from ods.plain",
        task_name="t",
        schema=SCHEMA,
    )
    source = _sources(result, "mart.t", "tag")[0]

    assert source["source_kind"] == "generated"
    assert "source_state" not in source
