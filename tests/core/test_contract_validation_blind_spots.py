"""Two validation blind spots: dangling references and placeholder tables in complete rows.

``validate_cross_references`` checked only ``scope_graph.edges`` and
``columns[*].sources[*].scope`` in a statement document, and only the prior-state
``state_id`` in a task document. A dangling ``depends_on``, join side, scope input edge,
output logic block or ``source_state`` all validated as OK (C2.4-2).

``validate_contract_invariants`` checked a task document only through its embedded
statement documents. A top-level ``end_to_end_lineage`` row reading
``{"table": "UNKNOWN"}`` beside ``trace_complete: true`` passed (C2.4-1).

Every name here is synthetic.
"""

from __future__ import annotations

import copy

import pytest

from scope_lineage.contract import to_task_lineage_dict
from scope_lineage.contract.invariants import validate_contract_invariants
from scope_lineage.contract.validation import validate_cross_references
from scope_lineage.scope.task_lineage import parse_task_lineage

SQL = (
    "CREATE TEMPORARY VIEW tv AS SELECT id, v FROM ods.a; "
    "INSERT OVERWRITE TABLE mart.t SELECT tv.id, s.v FROM tv "
    "JOIN (SELECT id, v FROM ods.b WHERE v > 0) s ON tv.id = s.id;"
)
SCHEMA = {"mart.t": ["id", "v"], "ods.a": ["id", "v"], "ods.b": ["id", "v"]}


@pytest.fixture(scope="module")
def document() -> dict:
    return to_task_lineage_dict(parse_task_lineage(SQL, "t", schema=SCHEMA))


def _root(document: dict) -> dict:
    return document["statement_lineage"]["stmt:002"]["scopes"]["ROOT"]


def _subquery(document: dict) -> dict:
    return document["statement_lineage"]["stmt:002"]["scopes"]["subq:s"]


def _ghost_depends_on(document: dict) -> None:
    _root(document)["depends_on"].append("subq:ghost")


def _ghost_join_left(document: dict) -> None:
    _root(document)["joins"][0]["left_scope"] = "nope_l"


def _ghost_join_right(document: dict) -> None:
    _root(document)["joins"][0]["right_scope"] = "nope_r"


def _ghost_input_edge(document: dict) -> None:
    edge = next(
        item for item in _root(document)["input_edges"] if item["source_type"] == "scope"
    )
    edge["source_id"] = "subq:nope"


def _ghost_logic_block(document: dict) -> None:
    _root(document)["outputs"][0]["source_logic_blocks"] = ["lb:nope"]


def _ghost_value_source_state(document: dict) -> None:
    for row in document["end_to_end_lineage"]:
        for source in row["value_sources"]:
            if "source_state" in source:
                source["source_state"] = "state:ghost:009"


def _ghost_row_source_state(document: dict) -> None:
    row = next(row for row in document["end_to_end_lineage"] if row["table"] == "mart.t")
    row["row_membership_sources"] = [
        {"table": "tv", "column": "id", "source_state": "state:ghost:009"}
    ]


INJECTIONS = {
    "scopes.depends_on": (_ghost_depends_on, "depends_on='subq:ghost'"),
    "joins.left_scope": (_ghost_join_left, "left_scope='nope_l'"),
    "joins.right_scope": (_ghost_join_right, "right_scope='nope_r'"),
    "input_edges.source_id": (_ghost_input_edge, "source_id='subq:nope'"),
    "outputs.source_logic_blocks": (_ghost_logic_block, "'lb:nope'"),
    "value_sources.source_state": (_ghost_value_source_state, "'state:ghost:009'"),
    "row_membership_sources.source_state": (_ghost_row_source_state, "'state:ghost:009'"),
}


def test_the_unmodified_document_is_clean(document: dict) -> None:
    assert validate_cross_references(document) == []
    assert validate_contract_invariants(document) == []


@pytest.mark.parametrize("name", sorted(INJECTIONS))
def test_each_dangling_reference_is_reported(document: dict, name: str) -> None:
    inject, expected = INJECTIONS[name]
    mutated = copy.deepcopy(document)
    inject(mutated)

    errors = validate_cross_references(mutated)

    assert errors, name
    assert all(expected in error for error in errors), errors


def test_a_depends_on_naming_a_physical_table_is_valid(document: dict) -> None:
    assert "ods.b" in _subquery(document)["depends_on"]
    assert validate_cross_references(document) == []


def test_an_input_edge_from_a_physical_table_is_not_a_scope_reference(document: dict) -> None:
    mutated = copy.deepcopy(document)
    edge = next(
        item for item in _root(mutated)["input_edges"] if item["source_type"] == "physical_table"
    )
    edge["source_id"] = "ods.not_in_this_statement"

    assert validate_cross_references(mutated) == []


def _complete_row(document: dict) -> dict:
    return next(
        row for row in document["end_to_end_lineage"]
        if row["table"] == "mart.t" and row["trace_complete"]
    )


@pytest.mark.parametrize("sentinel", ["UNKNOWN", "AMBIGUOUS"])
@pytest.mark.parametrize(
    "field", ["value_sources", "row_membership_sources", "value_condition_sources"]
)
def test_a_placeholder_table_in_a_complete_row_is_a_violation(
    document: dict, field: str, sentinel: str
) -> None:
    mutated = copy.deepcopy(document)
    _complete_row(mutated)[field].append({"table": sentinel, "column": "status"})

    errors = validate_contract_invariants(mutated)

    assert len(errors) == 1, errors
    assert field in errors[0] and sentinel in errors[0] and "trace_complete" in errors[0]


def test_a_placeholder_table_in_an_incomplete_row_is_honest(document: dict) -> None:
    mutated = copy.deepcopy(document)
    row = _complete_row(mutated)
    row["row_membership_sources"].append({"table": "UNKNOWN", "column": "status"})
    row["trace_complete"] = False
    row["missing_reasons"] = ["row_condition_source_unresolved"]

    assert validate_contract_invariants(mutated) == []


def test_a_generated_source_without_a_table_is_not_a_placeholder(document: dict) -> None:
    mutated = copy.deepcopy(document)
    _complete_row(mutated)["value_sources"].append(
        {"source_kind": "generated", "source_type": "CONSTANT", "value": "1"}
    )

    assert validate_contract_invariants(mutated) == []


def test_a_merge_joining_its_target_is_a_valid_join_side() -> None:
    merged = to_task_lineage_dict(parse_task_lineage(
        "MERGE INTO mart.t t USING ods.a s ON t.id = s.id "
        "WHEN MATCHED THEN UPDATE SET t.v = s.v;",
        "t",
        schema=SCHEMA,
    ))
    root = merged["statement_lineage"]["stmt:001"]["scopes"]["ROOT"]
    assert any(join["left_scope"] == "mart.t" for join in root["joins"])

    assert validate_cross_references(merged) == []
