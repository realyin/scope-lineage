"""A global temporary view is addressable as `global_temp.<name>`, and only as that.

Spark puts these views in the `global_temp` database; the bare name they were declared with
does not resolve. Core recorded the produced relation under the bare name, so the statement
that reads it -- necessarily written as `global_temp.gv` -- matched nothing. The relation was
marked session-scoped and the read still looked like an ordinary physical table, so a consumer
excluding session-scoped relations kept it, and `metadata_incomplete` fired for a table that
does not exist (TEMPVIEW-002).

This is the identity half of the same judgement PR #75 fixed the persistence half of. There,
"does it persist" had been keyed on which keyword produced the relation. Here, "which relation
is this" is still keyed on how it was spelled at the point of declaration rather than on how it
can be referred to.
"""

from __future__ import annotations

from scope_lineage.scope.task_lineage import parse_task_lineage

SCHEMA = {"ods.real": ["id"]}

SQL = (
    "create global temporary view gv as select id from ods.real;\n"
    "insert overwrite table mart.daily select id from global_temp.gv"
)


def _statement(result, kind):
    return [s for s in result.statements if s.get("stmt_kind") == kind]


def test_the_relation_is_recorded_under_the_name_it_can_be_read_by():
    result = parse_task_lineage(SQL, task_name="t", schema=SCHEMA)
    producing = _statement(result, "CTAS")[0]

    assert producing["target_table"] == "global_temp.gv"
    assert producing["is_session_scoped_relation"] is True


def test_the_read_resolves_to_the_relation_the_script_produced():
    result = parse_task_lineage(SQL, task_name="t", schema=SCHEMA)
    row = next(
        item for item in result.end_to_end_lineage
        if item.get("table") == "mart.daily"
    )
    source = row["value_sources"][0]

    assert source["table"] == "global_temp.gv"
    # It is a state this script produced, so it names which one -- the same guarantee any
    # other script-local relation gets.
    assert source["source_state"] == "state:global_temp.gv:001"


def test_a_consumer_excluding_session_scoped_relations_now_catches_it():
    result = parse_task_lineage(SQL, task_name="t", schema=SCHEMA)
    scoped = {
        s["target_table"] for s in result.statements
        if s.get("is_session_scoped_relation")
    }
    read_tables = {
        source["table"]
        for item in result.end_to_end_lineage
        if item.get("table") == "mart.daily"
        for source in item["value_sources"]
    }

    assert read_tables <= scoped, (read_tables, scoped)


def test_a_plain_temporary_view_keeps_its_bare_name():
    """Only GLOBAL moves into a database; an ordinary temp view is session-local by name."""
    result = parse_task_lineage(
        "create temporary view tv as select id from ods.real;\n"
        "insert overwrite table mart.daily select id from tv",
        task_name="t",
        schema=SCHEMA,
    )

    assert _statement(result, "CTAS")[0]["target_table"] == "tv"


def test_an_already_qualified_declaration_is_not_qualified_twice():
    result = parse_task_lineage(
        "create global temporary view global_temp.gv as select id from ods.real",
        task_name="t",
        schema=SCHEMA,
    )

    assert _statement(result, "CTAS")[0]["target_table"] == "global_temp.gv"
