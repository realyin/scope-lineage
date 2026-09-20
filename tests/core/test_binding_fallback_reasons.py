"""Why a target-column binding fell back, and why a statement has none to make (Q4).

``binding_fallbacks=9`` named a number and nothing else: the reader could not tell a target
with no usable metadata from a column-count mismatch from a `SELECT *` nobody expanded, and
the statements that carry no ``target_field_binding`` at all were simply absent from the
summary -- the commonest of them (a CTAS, a MERGE, a write to a path) having no binding to
make in the first place.

Two closed vocabularies now say it:

* every ``status: "fallback"`` carries a ``fallback_reason`` derived from the ``issues[]``
  it already published -- ``issues[]`` itself is unchanged, and stays the place the
  particulars live (which column, which counts);
* a statement whose kind defines its own columns publishes
  ``{"status": "not_applicable", "reason": ...}`` instead of omitting the block, so
  "no binding" is a stated fact rather than a missing key.
"""

from __future__ import annotations

import json

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.metadata.target_table_metadata import (
    TargetColumnMetadata,
    TargetMetadataMap,
    TargetTableMetadata,
)
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.scope.scope_builder import parse_all_scope_lineage
from scope_lineage.scope.target_field_binding import (
    FALLBACK_REASONS,
    NOT_APPLICABLE_REASONS,
    apply_target_field_binding,
)

SCHEMA = {"ods.src": ["id", "amt", "dt"], "mart.dst": ["id", "amt"]}

INSERT = "INSERT INTO mart.dst SELECT id, amt FROM ods.src"
CTAS = "CREATE TABLE mart.built AS SELECT id, amt FROM ods.src"
MERGE = (
    "MERGE INTO mart.dst USING ods.src s ON mart.dst.id = s.id "
    "WHEN NOT MATCHED THEN INSERT *"
)
DIRECTORY = "INSERT OVERWRITE DIRECTORY '/warehouse/export/daily' SELECT id FROM ods.src"


def _metadata(
    columns=("id", "amt"),
    *,
    table="mart.dst",
    partition_columns=(),
    validation_issues=(),
) -> TargetMetadataMap:
    metadata = TargetMetadataMap()
    metadata[table] = TargetTableMetadata(
        table_name=table.split(".")[-1],
        full_table_name=table,
        columns=[
            TargetColumnMetadata(
                name=name,
                data_type="string",
                ordinal=index,
                is_partition=name in partition_columns,
                comment="",
            )
            for index, name in enumerate(columns)
        ],
        partition_columns=list(partition_columns),
        ddl="",
        source_file="dst.json",
        validation_issues=list(validation_issues),
        query_time=None,
        ddl_update_time=None,
        data_source="test",
        structure_source="ddl",
    )
    return metadata


def _result(sql: str, target_metadata=None, schema=SCHEMA):
    return parse_all_scope_lineage(
        sql, task_name="t", schema=schema, target_metadata=target_metadata
    )[0]


def _binding(sql: str, target_metadata=None, schema=SCHEMA) -> dict:
    return dict(_result(sql, target_metadata, schema).target_field_binding or {})


# --- drivers: one per fallback token -----------------------------------------------


def test_metadata_that_could_not_be_used_is_no_target_metadata() -> None:
    binding = _binding(
        INSERT, _metadata(validation_issues=["ddl_columns_not_parsed"])
    )
    assert binding["status"] == "fallback"
    assert binding["fallback_reason"] == "no_target_metadata"


def test_a_column_count_mismatch_says_so() -> None:
    binding = _binding(INSERT, _metadata(("id", "amt", "dt")))
    assert binding["fallback_reason"] == "projection_target_count_mismatch"
    # The particulars stay where they already were, unchanged.
    assert binding["issues"] == ["projection_target_count_mismatch:2!=3"]


def test_target_column_names_that_repeat_say_so() -> None:
    binding = _binding(INSERT, _metadata(("id", "id")))
    assert binding["fallback_reason"] == "target_column_names_not_unique"


def test_an_unexpanded_star_is_not_reported_as_a_count_mismatch() -> None:
    """One projection against two target columns, and the projection is `*`.

    Arithmetically a count mismatch, and that is what ``issues[]`` records; as a reason to
    act it is a different thing entirely -- the fix is the missing source schema, not the
    target DDL.
    """
    binding = _binding(
        "INSERT INTO mart.dst SELECT * FROM ods.undescribed",
        _metadata(),
        schema={"mart.dst": ["id", "amt"]},
    )
    assert binding["fallback_reason"] == "star_projection_unexpanded"
    assert binding["issues"] == ["projection_target_count_mismatch:1!=2"]


def test_an_insert_column_list_naming_a_column_the_metadata_lacks() -> None:
    binding = _binding(
        "INSERT INTO mart.dst (id, absent_col) SELECT id, amt FROM ods.src",
        _metadata(),
    )
    assert binding["status"] == "fallback"
    assert binding["fallback_reason"] == "insert_column_list_unknown_column"
    assert binding["issues"] == ["insert_column_list_unknown_column:absent_col"]


def test_a_statement_kind_without_positional_write_semantics() -> None:
    result = _result(INSERT, _metadata())
    result.stmt_kind = "UNKNOWN"
    result.target_field_binding = {}
    apply_target_field_binding(result, target_metadata=_metadata())
    assert result.target_field_binding["fallback_reason"] == "unsupported_statement_kind"


def test_a_reason_outside_the_set_is_other_and_keeps_its_issues() -> None:
    binding = _binding(
        "INSERT OVERWRITE TABLE mart.dst PARTITION (dt) "
        "SELECT id, amt, dt FROM ods.src",
        _metadata(),
    )
    assert binding["fallback_reason"] == "other"
    assert binding["issues"] == ["insert_partition_not_in_target_metadata:dt"]


def test_every_fallback_carries_a_documented_reason() -> None:
    cases = (
        _binding(INSERT, _metadata(validation_issues=["x"])),
        _binding(INSERT, _metadata(("id", "amt", "dt"))),
        _binding(INSERT, _metadata(("id", "id"))),
        _binding(
            "INSERT INTO mart.dst (id, absent_col) SELECT id, amt FROM ods.src",
            _metadata(),
        ),
    )
    for binding in cases:
        assert binding["status"] == "fallback"
        assert binding["fallback_reason"] in FALLBACK_REASONS


# --- drivers: one per not_applicable token ------------------------------------------


@pytest.mark.parametrize(
    "sql,reason",
    [
        (CTAS, "ctas_defines_columns"),
        (MERGE, "merge_target"),
        (DIRECTORY, "directory_target"),
    ],
)
def test_a_statement_with_no_binding_to_make_says_which_kind_it_is(
    sql: str, reason: str
) -> None:
    assert _binding(sql, _metadata()) == {"status": "not_applicable", "reason": reason}
    assert reason in NOT_APPLICABLE_REASONS


def test_the_block_is_published_even_when_no_metadata_was_supplied() -> None:
    """The reason is a fact about the statement, not about what the caller handed in."""
    assert _binding(CTAS) == {"status": "not_applicable", "reason": "ctas_defines_columns"}


def test_a_statement_that_writes_nowhere_says_so() -> None:
    result = _result(INSERT)
    result.target_table = ""
    result.target_field_binding = {}
    apply_target_field_binding(result, target_metadata=_metadata())
    assert result.target_field_binding == {
        "status": "not_applicable",
        "reason": "no_write_target",
    }


def test_not_applicable_is_not_a_fallback() -> None:
    result = _result(CTAS, _metadata())
    assert not [
        warning
        for warning in result.diagnostics.warnings
        if warning.type == "target_field_binding_fallback"
    ]


def test_the_document_states_the_reason_in_the_block_and_not_beside_it() -> None:
    document = to_lineage_dict(_result(CTAS, _metadata()))
    assert document["target_field_binding"] == {
        "status": "not_applicable",
        "reason": "ctas_defines_columns",
    }
    assert "target_binding_absent_reason" not in document


def test_a_target_missing_from_the_supplied_ddl_still_has_no_block() -> None:
    """The one absence that is a risk keeps its own key: the binding *should* have run."""
    document = to_lineage_dict(
        _result("INSERT INTO mart.absent SELECT id, amt FROM ods.src", _metadata())
    )
    assert "target_field_binding" not in document
    assert document["target_binding_absent_reason"] == "target_table_not_found"


# --- the run summary ------------------------------------------------------------------


def _metadata_file(path, table: str, columns: list[str]) -> None:
    path.write_text(
        json.dumps(
            {
                "table_name": table,
                "full_table_name": f"spark_catalog.{table}",
                "schema": [
                    {
                        "columnName": name,
                        "columnType": "string",
                        "columnComment": "",
                        "columnIndex": index,
                        "isPartition": 0,
                    }
                    for index, name in enumerate(columns)
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_the_run_summary_breaks_the_fallbacks_down_and_counts_the_rest(
    tmp_path, capsys
) -> None:
    from scope_lineage.cli import main

    sql_file = tmp_path / "t.sql"
    sql_file.write_text(
        "CREATE TABLE mart.built AS SELECT id, amt FROM ods.src;\n"
        "INSERT INTO mart.dst SELECT id, amt FROM ods.src;\n"
        "INSERT INTO mart.wide SELECT * FROM ods.src;\n",
        encoding="utf-8",
    )
    metadata_dir = tmp_path / "ddl"
    metadata_dir.mkdir()
    _metadata_file(metadata_dir / "dst.json", "mart.dst", ["id", "amt", "dt"])
    _metadata_file(metadata_dir / "wide.json", "mart.wide", ["id", "amt"])

    assert main([
        "parse",
        "--sql-file",
        str(sql_file),
        "--target-ddl-metadata",
        str(metadata_dir),
        "--out",
        str(tmp_path / "out"),
    ]) == 0

    summary = capsys.readouterr().out
    assert (
        "binding_fallbacks=2 "
        "(projection_target_count_mismatch:1,star_projection_unexpanded:1)"
    ) in summary
    assert "binding_not_applicable=1" in summary


def test_the_summary_omits_the_breakdown_and_the_count_when_there_is_nothing_to_say(
    tmp_path, capsys
) -> None:
    from scope_lineage.cli import main

    sql_file = tmp_path / "t.sql"
    sql_file.write_text(
        "INSERT INTO mart.dst SELECT id, amt FROM ods.src;\n", encoding="utf-8"
    )
    metadata_dir = tmp_path / "ddl"
    metadata_dir.mkdir()
    _metadata_file(metadata_dir / "dst.json", "mart.dst", ["id", "amt"])

    assert main([
        "parse",
        "--sql-file",
        str(sql_file),
        "--target-ddl-metadata",
        str(metadata_dir),
        "--out",
        str(tmp_path / "out"),
    ]) == 0

    summary = capsys.readouterr().out
    assert "binding_fallbacks=0," in summary
    assert "binding_not_applicable" not in summary


# --- what `describe` says -------------------------------------------------------------


def _target_binding_finding(sql: str, target_metadata=None) -> dict | None:
    profile = build_semantic_profile(to_lineage_dict(_result(sql, target_metadata)))
    findings = (profile.get("confidence") or {}).get("findings") or []
    return next(
        (item for item in findings if item.get("kind") == "target_binding"), None
    )


def test_the_finding_names_the_reason_a_fallback_fell_back() -> None:
    finding = _target_binding_finding(
        INSERT, _metadata(validation_issues=["ddl_columns_not_parsed"])
    )
    assert finding is not None
    assert "按 SQL 投影绑定：目标表无元数据" in finding["text"]


def test_a_statement_with_no_binding_to_make_is_not_a_governance_lead() -> None:
    assert _target_binding_finding(CTAS, _metadata()) is None


# --- guards: must pass before AND after -----------------------------------------------


def test_a_binding_that_was_applied_gains_nothing() -> None:
    binding = _binding(INSERT, _metadata())
    assert binding["status"] == "applied"
    assert "fallback_reason" not in binding
    assert "reason" not in binding


def test_the_schema_enumerates_exactly_the_reasons_core_can_publish() -> None:
    from importlib import resources

    schema = json.loads(
        resources.files("scope_lineage.schemas")
        .joinpath("lineage.schema.json")
        .read_text(encoding="utf-8")
    )
    binding = schema["properties"]["target_field_binding"]["properties"]
    assert tuple(binding["fallback_reason"]["enum"]) == FALLBACK_REASONS
    assert tuple(binding["reason"]["enum"]) == NOT_APPLICABLE_REASONS
    assert "not_applicable" in binding["status"]["enum"]
