"""Task-level statement inventory and opt-in CLI quality gates."""

from __future__ import annotations

import json
from pathlib import Path

from scope_lineage.cli import main
from scope_lineage.scope.scope_builder import _collect_insert_trees


def _mixed_script(path: Path) -> None:
    path.write_text(
        """
        SET spark.sql.shuffle.partitions = 8;
        DELETE FROM mart.target WHERE expired = true;
        INSERT INTO mart.target SELECT id FROM ods.first_source;
        INSERT INTO mart.audit SELECT id FROM ods.second_source;
        """,
        encoding="utf-8",
    )


def test_skipped_statements_have_stable_task_level_identity_and_category() -> None:
    writes, skipped = _collect_insert_trees(
        """
        SET spark.sql.shuffle.partitions = 8;
        DELETE FROM mart.target WHERE expired = true;
        INSERT INTO mart.target SELECT id FROM ods.source;
        """
    )

    assert len(writes) == 1
    assert [
        {
            key: item[key]
            for key in (
                "statement_id",
                "statement_index",
                "statement_kind",
                "category",
                "model_status",
            )
        }
        for item in skipped
    ] == [
        {
            "statement_id": "stmt:001",
            "statement_index": 0,
            "statement_kind": "SET",
            "category": "control_statement",
            "model_status": "ignored",
        },
        {
            "statement_id": "stmt:002",
            "statement_index": 1,
            "statement_kind": "DELETE",
            "category": "row_mutation",
            "model_status": "unsupported",
        },
    ]


def test_cli_counts_unsupported_mutation_once_per_task_and_balanced_rejects_it(
    tmp_path: Path,
    capsys,
) -> None:
    sql_path = tmp_path / "mixed.sql"
    _mixed_script(sql_path)

    assert main([
        "parse",
        "--sql-file",
        str(sql_path),
        "--out",
        str(tmp_path / "permissive"),
    ]) == 0
    assert "unsupported_mutations=1" in capsys.readouterr().out

    assert main([
        "parse",
        "--sql-file",
        str(sql_path),
        "--quality-policy",
        "balanced",
        "--allow-partial",
        "--out",
        str(tmp_path / "balanced"),
    ]) == 1
    assert "unsupported_mutations=1" in capsys.readouterr().out


def test_explicit_unsupported_mutation_gate_does_not_require_balanced_policy(
    tmp_path: Path,
) -> None:
    sql_path = tmp_path / "mixed.sql"
    _mixed_script(sql_path)

    assert main([
        "parse",
        "--sql-file",
        str(sql_path),
        "--fail-on-unsupported-mutation",
        "--out",
        str(tmp_path / "output"),
    ]) == 1


def test_strict_policy_rejects_root_fact_gaps_and_recovered_syntax(
    tmp_path: Path,
) -> None:
    ambiguous = tmp_path / "ambiguous.sql"
    ambiguous.write_text(
        "INSERT INTO mart.target SELECT id FROM ods.first_source a "
        "JOIN ods.second_source b ON a.id = b.id",
        encoding="utf-8",
    )
    schema = tmp_path / "schema.csv"
    schema.write_text(
        "table_name,column_name\n"
        "ods.first_source,id\n"
        "ods.second_source,id\n",
        encoding="utf-8",
    )
    recovered = tmp_path / "recovered.sql"
    recovered.write_text(
        "INSERT INTO mart.target SELECT id FROM ods.source WHERE WHERE id > 0",
        encoding="utf-8",
    )

    assert main([
        "parse",
        "--sql-file",
        str(ambiguous),
        "--schema",
        str(schema),
        "--quality-policy",
        "strict",
        "--out",
        str(tmp_path / "ambiguous-output"),
    ]) == 1
    assert main([
        "parse",
        "--sql-file",
        str(ambiguous),
        "--schema",
        str(schema),
        "--contract-version",
        "2.0",
        "--quality-policy",
        "strict",
        "--out",
        str(tmp_path / "ambiguous-v2-output"),
    ]) == 1
    assert main([
        "parse",
        "--sql-file",
        str(recovered),
        "--quality-policy",
        "strict",
        "--out",
        str(tmp_path / "recovered-output"),
    ]) == 1


def test_binding_fallback_gate_has_an_independent_exit_policy(tmp_path: Path) -> None:
    sql_path = tmp_path / "binding.sql"
    sql_path.write_text(
        "INSERT INTO mart.target SELECT id FROM ods.source",
        encoding="utf-8",
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    (metadata_dir / "target.json").write_text(
        json.dumps({
            "table_name": "mart.target",
            "schema": [
                {"columnName": "id", "columnIndex": 0, "isPartition": 0},
                {"columnName": "amount", "columnIndex": 1, "isPartition": 0},
            ],
        }),
        encoding="utf-8",
    )

    assert main([
        "parse",
        "--sql-file",
        str(sql_path),
        "--target-ddl-metadata",
        str(metadata_dir),
        "--fail-on-binding-fallback",
        "--out",
        str(tmp_path / "output"),
    ]) == 1
