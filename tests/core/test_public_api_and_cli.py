"""Public import surface and minimal Core CLI behavior."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import lineage_parser
from lineage_parser.cli import main


REQUIRED_SYMBOLS = (
    Path(__file__).parent / "fixtures" / "public-api-required-symbols.json"
)


def test_public_exports_match_the_declared_core_api() -> None:
    assert set(lineage_parser.__all__) == lineage_parser.PUBLIC_CORE_API


def test_public_api_covers_the_approved_consumer_surface() -> None:
    required = set(json.loads(REQUIRED_SYMBOLS.read_text(encoding="utf-8")))
    missing = required - lineage_parser.PUBLIC_CORE_API

    assert not missing, f"Public Core API is missing approved symbols: {sorted(missing)}"
    assert all(hasattr(lineage_parser, name) for name in required)


def test_importing_core_does_not_load_upper_layers() -> None:
    script = (
        "import sys, lineage_parser; "
        "forbidden=('pipeline','pipeline.understanding.insight','pipeline.refactor',"
        "'pipeline.understanding.presets'); "
        "assert not any(n == p or n.startswith(p + '.') for n in sys.modules for p in forbidden)"
    )
    subprocess.run([sys.executable, "-c", script], check=True)


def test_core_cli_writes_only_lineage_and_diagnostics(tmp_path) -> None:
    sql_path = tmp_path / "demo.sql"
    sql_path.write_text(
        "INSERT INTO mart.t SELECT id FROM ods.source",
        encoding="utf-8",
    )
    output = tmp_path / "output"

    assert main([
        "parse",
        "--sql-file",
        str(sql_path),
        "--out",
        str(output),
    ]) == 0

    task_dir = output / "demo"
    assert {path.name for path in task_dir.iterdir()} == {
        "lineage.json",
        "diagnostics.json",
    }
    assert json.loads((task_dir / "lineage.json").read_text())["schema_version"] == "1.0"


def test_core_cli_accepts_exported_task_json_and_keeps_dependencies(tmp_path) -> None:
    task_path = tmp_path / "daily_customer.json"
    task_path.write_text(
        json.dumps(
            {
                "meta": {
                    "task_id": "task-002",
                    "task_name": "daily_customer",
                    "upstream_tasks": [
                        {"task_id": "task-001", "task_name": "clean_customer"}
                    ],
                    "downstream_tasks": [],
                    "sql": "INSERT INTO mart.customer SELECT id FROM ods.customer",
                },
                "query_time": "2026-08-01 10:00:00",
                "data_source": "scheduler_api",
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "output"

    assert main([
        "parse",
        "--task-file",
        str(task_path),
        "--out",
        str(output),
    ]) == 0

    lineage = json.loads(
        (output / "daily_customer" / "lineage.json").read_text(encoding="utf-8")
    )
    dependencies = lineage["task_dependencies"]
    assert dependencies["source_summary"] == {
        "source_format": "task_info_meta",
        "upstream_count": 1,
        "downstream_count": 0,
        "has_declared_task_dependencies": True,
    }
    assert dependencies["upstream_tasks"][0]["task_name"] == "clean_customer"


def test_core_cli_parses_task_directory_recursively(tmp_path) -> None:
    input_dir = tmp_path / "tasks"
    nested_dir = input_dir / "customer_domain"
    nested_dir.mkdir(parents=True)
    (input_dir / "orders.json").write_text(
        json.dumps(
            {
                "task_name": "orders",
                "sql": "INSERT INTO mart.orders SELECT id FROM ods.orders",
            }
        ),
        encoding="utf-8",
    )
    (nested_dir / "customers.json").write_text(
        json.dumps(
            {
                "meta": {
                    "task_name": "customers",
                    "sql": "INSERT INTO mart.customers SELECT id FROM ods.customers",
                }
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "output"

    assert main([
        "parse",
        "--input-dir",
        str(input_dir),
        "--out",
        str(output),
    ]) == 0

    assert (output / "orders" / "lineage.json").is_file()
    assert (output / "customer_domain" / "customers" / "lineage.json").is_file()


def test_core_cli_rejects_empty_task_sql(tmp_path) -> None:
    task_path = tmp_path / "empty.json"
    task_path.write_text(
        json.dumps({"meta": {"task_name": "empty", "sql": ""}}),
        encoding="utf-8",
    )

    assert main([
        "parse",
        "--task-file",
        str(task_path),
        "--out",
        str(tmp_path / "output"),
    ]) == 1


def test_core_cli_preserves_catalog_by_default_and_strips_configured_prefix(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("SCOPE_LINEAGE_CATALOG_PREFIXES", raising=False)
    sql_path = tmp_path / "catalog.sql"
    sql_path.write_text(
        "INSERT INTO mart.orders SELECT id FROM warehouse_catalog.ods.orders",
        encoding="utf-8",
    )

    default_output = tmp_path / "default"
    assert main([
        "parse",
        "--sql-file",
        str(sql_path),
        "--out",
        str(default_output),
    ]) == 0
    default_lineage = json.loads(
        (default_output / "catalog" / "lineage.json").read_text(encoding="utf-8")
    )
    assert default_lineage["source_tables"] == ["warehouse_catalog.ods.orders"]

    configured_output = tmp_path / "configured"
    assert main([
        "parse",
        "--sql-file",
        str(sql_path),
        "--catalog-prefixes",
        "warehouse_catalog",
        "--out",
        str(configured_output),
    ]) == 0
    configured_lineage = json.loads(
        (configured_output / "catalog" / "lineage.json").read_text(
            encoding="utf-8"
        )
    )
    assert configured_lineage["source_tables"] == ["ods.orders"]
    assert configured_lineage["end_to_end_lineage"][0]["physical_sources"] == [
        {"table": "ods.orders", "column": "id", "transform": "DIRECT"}
    ]
    assert "SCOPE_LINEAGE_CATALOG_PREFIXES" not in os.environ


def test_core_cli_catalog_prefixes_override_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SCOPE_LINEAGE_CATALOG_PREFIXES", "environment_catalog")
    sql_path = tmp_path / "catalog.sql"
    sql_path.write_text(
        "INSERT INTO mart.t SELECT id FROM cli_catalog.ods.source",
        encoding="utf-8",
    )
    output = tmp_path / "output"

    assert main([
        "parse",
        "--sql-file",
        str(sql_path),
        "--catalog-prefixes",
        "cli_catalog",
        "--out",
        str(output),
    ]) == 0

    lineage = json.loads(
        (output / "catalog" / "lineage.json").read_text(encoding="utf-8")
    )
    assert lineage["source_tables"] == ["ods.source"]
    assert os.environ["SCOPE_LINEAGE_CATALOG_PREFIXES"] == "environment_catalog"


def test_documented_example_corpus_is_executable(tmp_path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    output = tmp_path / "output"

    assert main([
        "parse",
        "--input-dir",
        str(project_root / "examples" / "tasks"),
        "--schema",
        str(project_root / "examples" / "metadata" / "schema_info.csv"),
        "--target-ddl-metadata",
        str(project_root / "examples" / "metadata" / "target_tables"),
        "--out",
        str(output),
    ]) == 0

    lineage_files = sorted(output.rglob("lineage.json"))
    assert len(lineage_files) == 5
    assert all(
        json.loads(path.read_text(encoding="utf-8"))["parse_status"] == "ok"
        for path in lineage_files
    )


def test_select_star_example_expands_and_uses_target_binding(tmp_path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    output = tmp_path / "output"

    assert main([
        "parse",
        "--sql-file",
        str(project_root / "examples" / "sql" / "select_star_with_schema.sql"),
        "--schema",
        str(project_root / "examples" / "metadata" / "schema_info.csv"),
        "--target-ddl-metadata",
        str(project_root / "examples" / "metadata" / "target_tables"),
        "--out",
        str(output),
    ]) == 0

    lineage = json.loads(
        (output / "select_star_with_schema" / "lineage.json").read_text(
            encoding="utf-8"
        )
    )
    assert lineage["target_field_binding"]["status"] == "applied"
    assert [item["column"] for item in lineage["end_to_end_lineage"]] == [
        "customer_id",
        "customer_name",
        "country_code",
        "registered_at",
        "dt",
    ]
    assert lineage["diagnostics"]["warning_count"] == 0


def test_core_cli_help_exposes_only_parse(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "parse" in help_text
    for upper_command in ("insight", "governance", "refactor-candidates"):
        assert upper_command not in help_text


def test_core_parse_help_explains_catalog_configuration(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["parse", "--help"])
    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "--catalog-prefixes" in help_text
    assert "SCOPE_LINEAGE_CATALOG_PREFIXES" in help_text
    assert "by default catalogs are preserved" in " ".join(help_text.split())


def test_public_qualified_field_extractor() -> None:
    assert lineage_parser.extract_qualified_field_refs(
        "a.id + `b`.`amount` + named_struct('x', c.value).x"
    ) == [("b", "amount"), ("a", "id"), ("c", "value")]
