"""The edge that reads a session-scoped relation says so on itself.

`is_session_scoped_relation` sits on the statement that produces the relation, while the edges
a consumer has to act on are in `value_sources`. Acting on the marker therefore meant joining
two different objects: collect the relation names from `statement_sequence`, then intersect
that set against every `value_sources[].table`. Nothing was wrong with the facts, but the one
place a consumer looks -- the edge -- did not carry the answer (TEMPVIEW-003).

This was rejected once, on the grounds that it meant "adding a fourth `source_kind` value" and
would silently narrow every existing `source_kind == "physical_field"` filter. That objection
holds against changing `source_kind`, and this does not change it: `session_scoped` is a new
optional key beside it, so a filter that does not know the key keeps exactly the behaviour it
had.

Core resolves the relation, so the marker also survives spellings a consumer cannot match by
name -- a global temporary view is declared bare and read qualified, and the edge is marked
either way.
"""

from __future__ import annotations

from scope_lineage.scope.task_lineage import parse_task_lineage

SCHEMA = {"ods.real": ["id", "amt"]}


def _sources(result, table, column):
    for item in result.end_to_end_lineage:
        if item.get("table") == table and item.get("column") == column:
            return item.get("value_sources") or []
    raise AssertionError(f"no row for {table}.{column}")


def test_an_edge_reading_a_temp_view_is_marked():
    result = parse_task_lineage(
        "create or replace temp view tmp_v as select id, amt from ods.real;\n"
        "insert overwrite table mart.daily select id, amt from tmp_v",
        task_name="t",
        schema=SCHEMA,
    )
    source = _sources(result, "mart.daily", "amt")[0]

    assert source["table"] == "tmp_v"
    assert source["session_scoped"] is True


def test_an_edge_reading_a_real_table_is_not_marked():
    result = parse_task_lineage(
        "insert overwrite table mart.daily select id from ods.real",
        task_name="t",
        schema=SCHEMA,
    )
    source = _sources(result, "mart.daily", "id")[0]

    assert "session_scoped" not in source


def test_source_kind_is_untouched():
    """The objection that sank this idea the first time must stay answered."""
    result = parse_task_lineage(
        "create or replace temp view tmp_v as select id from ods.real;\n"
        "insert overwrite table mart.daily select id from tmp_v",
        task_name="t",
        schema=SCHEMA,
    )
    source = _sources(result, "mart.daily", "id")[0]

    assert source["source_kind"] == "physical_field"


def test_a_consumer_needs_only_the_edge():
    """The whole point: no join against statement_sequence."""
    result = parse_task_lineage(
        "create or replace temp view tmp_v as select id from ods.real;\n"
        "insert overwrite table mart.daily select id from tmp_v",
        task_name="t",
        schema=SCHEMA,
    )
    physical_only = [
        source
        for item in result.end_to_end_lineage
        for source in item.get("value_sources") or []
        if source.get("source_kind") == "physical_field"
        and not source.get("session_scoped")
    ]

    assert {s["table"] for s in physical_only} == {"ods.real"}


def test_a_global_temp_view_edge_is_marked_despite_the_spelling():
    """Declared bare, read qualified. Core resolves it; a name-matching consumer could not."""
    result = parse_task_lineage(
        "create global temporary view gv as select id from ods.real;\n"
        "insert overwrite table mart.daily select id from global_temp.gv",
        task_name="t",
        schema=SCHEMA,
    )
    source = _sources(result, "mart.daily", "id")[0]

    assert source["table"] == "global_temp.gv"
    assert source["session_scoped"] is True


def test_a_cached_relation_edge_is_marked_too():
    result = parse_task_lineage(
        "cache lazy table c as select id from ods.real;\n"
        "insert overwrite table mart.daily select id from c",
        task_name="t",
        schema=SCHEMA,
    )

    assert _sources(result, "mart.daily", "id")[0]["session_scoped"] is True
