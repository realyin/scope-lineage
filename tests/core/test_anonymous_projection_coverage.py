"""Chain coverage and the name_is_generated marker for unbound anonymous projections.

The end-to-end layer emits an entry for every ROOT output; the chain layer used to
skip outputs whose name is not a reliable target column (generated `_col_N`, purely
numeric aliases), so mapping.md showed a section-4 row with no section-5 explanation.
Chains now cover exactly the population end_to_end covers, and the contract says which
published names are generated placeholders — a fact that previously died inside the
parser (`ScopeColumn.name_is_generated` was never serialized).
"""

from __future__ import annotations

from scope_lineage import (
    TargetColumnMetadata,
    TargetMetadataMap,
    TargetTableMetadata,
    render_mapping_markdown,
    validate_contract_invariants,
)
from scope_lineage.contract import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage


# the anonymous projection must reference MORE than one field: a sole-field anonymous
# projection recovers that field's name and is not a generated-name case at all
ANONYMOUS_SQL = """
INSERT OVERWRITE TABLE mart.notify_payload
SELECT o.contract_no AS contract_no,
       CONCAT('{"code":"', o.contract_no, '","cust":"', o.customer_no, '"}')
FROM (SELECT a.contract_no, a.customer_no FROM ods.enqueue_list a) o
"""

NUMERIC_ALIAS_SQL = """
INSERT OVERWRITE TABLE mart.notify_payload
SELECT a.contract_no AS contract_no, a.flag AS `123`
FROM ods.enqueue_list a
"""


def _document(sql: str, target_metadata=None) -> dict:
    return to_lineage_dict(
        parse_scope_lineage(sql, "case_task", target_metadata=target_metadata)
    )


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


def _payload_metadata() -> TargetMetadataMap:
    item = TargetTableMetadata(
        table_name="notify_payload",
        full_table_name="mart.notify_payload",
        columns=[
            TargetColumnMetadata(name="contract_no", ordinal=0),
            TargetColumnMetadata(name="payload_json", ordinal=1),
        ],
        partition_columns=[],
        ddl="",
        source_file="synthetic",
        structure_source="schema",
    )
    return TargetMetadataMap({item.table_name: item})


def test_anonymous_projection_gets_a_marked_chain() -> None:
    document = _document(ANONYMOUS_SQL)
    entry = _e2e(document, "_col_1")
    assert entry["name_is_generated"] is True
    chain = _chain(document, "_col_1")
    assert chain["name_is_generated"] is True
    assert chain["final_output_fields"] == []
    assert chain["target_position"] == 1
    assert chain["ordered_steps"]
    assert validate_contract_invariants(document) == []


def test_named_projection_keeps_its_shape() -> None:
    document = _document(ANONYMOUS_SQL)
    assert "name_is_generated" not in _e2e(document, "contract_no")
    chain = _chain(document, "contract_no")
    assert "name_is_generated" not in chain
    assert chain["final_output_fields"] == ["mart.notify_payload.contract_no"]


def test_anonymous_projection_renders_a_section_five_chunk() -> None:
    rendered = render_mapping_markdown(_document(ANONYMOUS_SQL))
    steps_section = rendered[rendered.index("## 5."): rendered.index("## 6.")]
    assert "### 字段 _col_1（匿名投影，未绑定目标列）" in steps_section
    assert "mart.notify_payload._col_1" not in rendered


def test_bound_generated_name_is_not_marked() -> None:
    # positional target binding renames _col_1 to the real column; the published
    # name is no longer a placeholder, so the marker must not fire
    document = _document(ANONYMOUS_SQL, target_metadata=_payload_metadata())
    entry = _e2e(document, "payload_json")
    assert "name_is_generated" not in entry
    chain = _chain(document, "payload_json")
    assert "name_is_generated" not in chain
    assert chain["final_output_fields"] == ["mart.notify_payload.payload_json"]
    assert validate_contract_invariants(document) == []


def test_numeric_alias_gets_an_unmarked_chain_and_honest_title() -> None:
    document = _document(NUMERIC_ALIAS_SQL)
    chain = _chain(document, "123")
    assert "name_is_generated" not in chain
    assert chain["final_output_fields"] == []
    rendered = render_mapping_markdown(document)
    assert "### 字段 123（未绑定目标列）" in rendered
    assert "mart.notify_payload.123" not in rendered
    assert validate_contract_invariants(document) == []


def test_directory_write_title_takes_precedence() -> None:
    document = _document(ANONYMOUS_SQL)
    document["target_table"] = "directory:/tmp/out"
    rendered = render_mapping_markdown(document)
    assert "（写入目录 /tmp/out）" in rendered
    assert "（匿名投影，未绑定目标列）" not in rendered


def test_marked_chain_with_bound_output_is_an_invariant_violation() -> None:
    document = _document(ANONYMOUS_SQL)
    chain = _chain(document, "_col_1")
    chain["final_output_fields"] = ["mart.notify_payload.payload_json"]
    errors = validate_contract_invariants(document)
    assert any("name_is_generated" in error for error in errors)
