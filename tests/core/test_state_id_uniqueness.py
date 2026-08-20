"""A state id names one state of one table. Re-creating a relation must not reuse it.

`state_id` is what `table_state_graph.edges` and `statement_lineage` point at, so a duplicate
does not merely look untidy -- it makes the graph unreadable. A script that redefines a
temporary relation produced two nodes both called `state:v:001`, with different
`producer_statement_id`s, and nothing downstream could tell which one an edge meant
(STATE-ID-001).

The cause is that a CTAS is deliberately handed `previous=None`: it replaces the relation
entirely, so its value sources must not carry prior-state passthrough. But the ordinal was
derived from `previous`, so "no prior state to inherit from" was conflated with "this is the
first state of this table". Those are different questions, and only the first one is about
inheritance.

This matters beyond tidiness. A consumer folding a hop through a temporary relation resolves
it by name, and with one name mapping to two definitions the fold silently returns whichever
was recorded last -- turning an ambiguity in the artifact into a false assertion about where
a column came from.
"""

from __future__ import annotations

import pytest

from scope_lineage.scope.task_lineage import parse_task_lineage

SCHEMA = {"ods.a": ["id"], "ods.b": ["id"]}

REDEFINED = (
    "create or replace temp view v as select id from ods.a;\n"
    "insert overwrite table mart.x select id from v;\n"
    "create or replace temp view v as select id from ods.b;\n"
    "insert overwrite table mart.y select id from v"
)


def _nodes(result, table):
    return [n for n in result.table_state_graph["nodes"] if n.get("table") == table]


def test_every_state_id_in_the_graph_is_unique():
    result = parse_task_lineage(REDEFINED, task_name="t", schema=SCHEMA)
    ids = [n["state_id"] for n in result.table_state_graph["nodes"]]

    assert len(ids) == len(set(ids)), sorted(ids)


def test_a_redefined_relation_gets_a_second_state():
    result = parse_task_lineage(REDEFINED, task_name="t", schema=SCHEMA)
    states = _nodes(result, "v")

    assert len(states) == 2, states
    assert states[0]["state_id"] != states[1]["state_id"]
    # Each definition is attributable to the statement that wrote it.
    assert [s["producer_statement_id"] for s in states] == ["stmt:001", "stmt:003"]


def test_the_second_definition_does_not_inherit_from_the_first():
    """Ordinal numbering changes; CTAS replacement semantics must not.

    A CTAS replaces the relation, so the new state's value sources come only from its own
    SELECT -- no `prior_table_state` entry pointing at the previous definition.
    """
    result = parse_task_lineage(REDEFINED, task_name="t", schema=SCHEMA)
    second = _nodes(result, "v")[1]
    kinds = {
        source.get("source_kind")
        for sources in (second.get("value_sources") or {}).values()
        for source in sources
    }

    assert "prior_table_state" not in kinds, second.get("value_sources")


@pytest.mark.parametrize("sql,table,expected", [
    # A plain INSERT inherits, so its ordinal follows the state it appends to. `000` is the
    # state the table was in before the script ran, which has no producing statement.
    (
        "insert overwrite table mart.t select id from ods.a;\n"
        "insert into mart.t select id from ods.b",
        "mart.t",
        ["state:mart.t:000", "state:mart.t:001", "state:mart.t:002"],
    ),
    # A CTAS defines the relation, so there is no prior state to record.
    ("create table db.r as select id from ods.a", "db.r", ["state:db.r:001"]),
    (
        "create table db.r as select id from ods.a;\n"
        "create or replace table db.r as select id from ods.b",
        "db.r",
        ["state:db.r:001", "state:db.r:002"],
    ),
])
def test_states_are_still_numbered_in_order(sql, table, expected):
    result = parse_task_lineage(sql, task_name="t", schema=SCHEMA)

    assert [node["state_id"] for node in _nodes(result, table)] == expected


def test_the_contract_refuses_a_document_with_a_duplicate_state_id():
    """The graph is only readable if an id names one state, so validation must say so.

    Every `edges`, `final_table_states` and `input_states` reference is resolved by id. A
    duplicate makes those references ambiguous rather than invalid, which is why nothing
    caught it: each one still resolved, just not to a single thing.
    """
    from scope_lineage.contract.validation import _validate_task_cross_references

    document = {
        "table_state_graph": {
            "nodes": [
                {"table": "v", "state_id": "state:v:001", "producer_statement_id": "stmt:001"},
                {"table": "v", "state_id": "state:v:001", "producer_statement_id": "stmt:003"},
            ],
            "edges": [],
        },
        "statement_sequence": [
            {"statement_id": "stmt:001"},
            {"statement_id": "stmt:003"},
        ],
    }

    errors = _validate_task_cross_references(document)

    assert any("state:v:001" in error and "duplicate" in error.lower() for error in errors), errors
