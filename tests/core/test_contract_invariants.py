"""Semantic consistency invariants across a lineage document's derivation layers.

`validate_cross_references` answers "does every referenced id exist"; this checker
answers the question that let the AMBIGUOUS defect ship: "do independently computed
views of the same fact agree with each other". Each invariant here guards a fact the
contract derives in more than one place (see the dual-derivation inventory); a chain
that says complete while end_to_end says ambiguous is exactly what it exists to catch.
"""

from __future__ import annotations

import copy

import pytest

from scope_lineage.contract import to_lineage_dict, to_task_lineage_dict
from scope_lineage.contract.invariants import validate_contract_invariants
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.scope.task_lineage import parse_task_lineage


CLEAN_SQL = """
INSERT OVERWRITE TABLE mart.session_summary
SELECT o.session_id AS session_id,
       CONCAT(o.begin_date, ' ', o.begin_time) AS session_start_time,
       'fixed' AS label
FROM (
  SELECT a.session_id, a.begin_date, a.begin_time
  FROM ods.session_events a
) o
"""

AMBIGUOUS_SQL = """
INSERT OVERWRITE TABLE mart.session_summary
SELECT o.session_id AS session_id,
       CONCAT(begin_date, ' ', begin_time) AS session_start_time
FROM (
  SELECT a.session_id, a.begin_date, a.begin_time
  FROM ods.session_events a
) o
LEFT JOIN ods.session_dim g ON o.session_id = g.session_id
"""


@pytest.fixture(scope="module")
def clean_document() -> dict:
    return to_lineage_dict(parse_scope_lineage(CLEAN_SQL, "case_task"))


def _mutated(document: dict) -> dict:
    return copy.deepcopy(document)


def _chain(document: dict, field: str) -> dict:
    return next(
        chain
        for chain in document["field_mapping_chains"]
        if chain["target_field"] == field
    )


def _e2e(document: dict, column: str) -> dict:
    return next(
        entry
        for entry in document["end_to_end_lineage"]
        if entry["column"] == column
    )


def test_clean_document_has_no_violations(clean_document: dict) -> None:
    assert validate_contract_invariants(clean_document) == []


def test_current_parser_output_with_ambiguity_has_no_violations() -> None:
    document = to_lineage_dict(parse_scope_lineage(AMBIGUOUS_SQL, "case_task"))
    assert validate_contract_invariants(document) == []


def test_ambiguous_root_with_complete_chain_is_reported(clean_document: dict) -> None:
    document = _mutated(clean_document)
    chain = _chain(document, "session_start_time")
    chain["root_source_fields"] = ["AMBIGUOUS.begin_date"]
    errors = validate_contract_invariants(document)
    assert any("AMBIGUOUS root" in error and "session_start_time" in error for error in errors)


def test_unknown_root_with_complete_chain_is_reported(clean_document: dict) -> None:
    document = _mutated(clean_document)
    chain = _chain(document, "session_start_time")
    chain["root_source_fields"] = ["UNKNOWN.begin_date"]
    errors = validate_contract_invariants(document)
    assert any("UNKNOWN root" in error for error in errors)


def test_chain_complete_but_e2e_incomplete_is_reported(clean_document: dict) -> None:
    document = _mutated(clean_document)
    entry = _e2e(document, "session_start_time")
    entry["trace_complete"] = False
    errors = validate_contract_invariants(document)
    assert any(
        "trace_status=complete" in error and "trace_complete=false" in error
        for error in errors
    )


def test_chain_incomplete_but_e2e_complete_is_reported(clean_document: dict) -> None:
    document = _mutated(clean_document)
    chain = _chain(document, "session_start_time")
    chain["trace_status"] = "incomplete"
    chain["chain_status"] = "partially_resolved"
    chain["missing_reasons"] = ["ambiguous_unqualified:begin_date"]
    errors = validate_contract_invariants(document)
    assert any(
        "trace_status=incomplete" in error and "trace_complete=true" in error
        for error in errors
    )


def test_chain_without_e2e_entry_is_reported(clean_document: dict) -> None:
    document = _mutated(clean_document)
    document["end_to_end_lineage"] = [
        entry
        for entry in document["end_to_end_lineage"]
        if entry["column"] != "session_start_time"
    ]
    errors = validate_contract_invariants(document)
    assert any("no end_to_end_lineage entry" in error for error in errors)


def test_e2e_entry_without_chain_is_reported(clean_document: dict) -> None:
    document = _mutated(clean_document)
    document["field_mapping_chains"] = [
        chain
        for chain in document["field_mapping_chains"]
        if chain["target_field"] != "session_start_time"
    ]
    errors = validate_contract_invariants(document)
    assert any("no field_mapping_chain" in error for error in errors)


def test_e2e_physical_table_outside_source_tables_is_reported(clean_document: dict) -> None:
    document = _mutated(clean_document)
    entry = _e2e(document, "session_start_time")
    entry["physical_sources"] = [
        {"table": "ods.not_a_source", "column": "begin_date", "transform": "EXPRESSION"}
    ]
    errors = validate_contract_invariants(document)
    assert any("ods.not_a_source" in error and "source_tables" in error for error in errors)


def test_root_source_physical_table_outside_source_tables_is_reported(
    clean_document: dict,
) -> None:
    document = _mutated(clean_document)
    chain = _chain(document, "session_start_time")
    chain["root_source_fields"] = ["ods.not_a_source.begin_date"]
    errors = validate_contract_invariants(document)
    assert any("ods.not_a_source" in error for error in errors)


def test_step_physical_table_outside_source_tables_is_reported(clean_document: dict) -> None:
    document = _mutated(clean_document)
    chain = _chain(document, "session_start_time")
    resolution = chain["ordered_steps"][0].setdefault("expression_resolution", {})
    resolution["physical_source_fields"] = [
        {"table": "ods.not_a_source", "field": "begin_date"}
    ]
    errors = validate_contract_invariants(document)
    assert any("ods.not_a_source" in error for error in errors)


def test_sentinel_listed_as_source_table_is_reported(clean_document: dict) -> None:
    document = _mutated(clean_document)
    document["source_tables"] = [*document["source_tables"], "AMBIGUOUS"]
    errors = validate_contract_invariants(document)
    assert any("sentinel" in error and "source_tables" in error for error in errors)


def test_sentinel_as_physical_source_is_reported(clean_document: dict) -> None:
    document = _mutated(clean_document)
    entry = _e2e(document, "session_start_time")
    entry["physical_sources"] = [
        {"table": "AMBIGUOUS", "column": "begin_date", "transform": "EXPRESSION"}
    ]
    errors = validate_contract_invariants(document)
    assert any("sentinel" in error for error in errors)


def test_ambiguities_with_trace_complete_is_reported(clean_document: dict) -> None:
    document = _mutated(clean_document)
    entry = _e2e(document, "session_start_time")
    entry["ambiguities"] = [
        {"scope": "ROOT", "column": "begin_date", "candidate_count": 2, "candidates": []}
    ]
    # trace_complete stays true -> the combination is the violation
    errors = validate_contract_invariants(document)
    assert any("ambiguities" in error and "trace_complete" in error for error in errors)


def test_complete_chain_with_missing_reasons_is_reported(clean_document: dict) -> None:
    document = _mutated(clean_document)
    chain = _chain(document, "session_start_time")
    chain["missing_reasons"] = ["stray_reason"]
    errors = validate_contract_invariants(document)
    assert any("missing_reasons" in error and "complete" in error for error in errors)


def test_complete_chain_with_unresolved_status_is_reported(clean_document: dict) -> None:
    document = _mutated(clean_document)
    chain = _chain(document, "session_start_time")
    chain["chain_status"] = "unresolved"
    errors = validate_contract_invariants(document)
    assert any("chain_status" in error for error in errors)


def test_constant_roots_are_not_flagged(clean_document: dict) -> None:
    # 'label' is a constant field; its CONSTANT.* root must not read as a physical table
    errors = validate_contract_invariants(clean_document)
    assert not any("label" in error for error in errors)


def test_task_document_recurses_into_nested_statements() -> None:
    task_document = to_task_lineage_dict(parse_task_lineage(CLEAN_SQL, task_name="case_task"))
    assert validate_contract_invariants(task_document) == []

    broken = copy.deepcopy(task_document)
    nested = next(iter(broken["statement_lineage"].values()))
    chain = next(
        chain
        for chain in nested["field_mapping_chains"]
        if chain["target_field"] == "session_start_time"
    )
    chain["root_source_fields"] = ["AMBIGUOUS.begin_date"]
    errors = validate_contract_invariants(broken)
    assert any(error.startswith("statement_lineage[") and "AMBIGUOUS root" in error for error in errors)
