"""A table name that holds an unbound run parameter is incomplete input, said as such.

``INSERT OVERWRITE TABLE cat.${db_name}.t`` names a table only once the scheduler binds
``db_name``. The parser read the parameter's bare name as the database
(``cat.db_name.t``), so the metadata preflight asked for the schema of a table that
does not exist, and the document called the task complete. The id now keeps the
parameter visible, the task is ``partial`` with ``input_incomplete`` as its first reason,
a ``table_name_parameter_unbound`` gap names the table and the parameter, and the
metadata report lists such tables apart from missing metadata. A parameter in a value
(``dt = '${dt}'``) is not a table name and changes nothing.
"""

from __future__ import annotations

import json

from scope_lineage.cli import main
from scope_lineage.scope.task_lineage import parse_task_lineage

SQL = "INSERT OVERWRITE TABLE cat.${db_name}.t PARTITION (dt = '${dt}') SELECT id FROM db.src"
SCHEMA = {"db.src": ["id"]}


def _gaps(result) -> list[dict]:
    return [
        gap for gap in result.diagnostics["lineage_fact_gaps"]
        if gap["gap_type"] == "table_name_parameter_unbound"
    ]


def test_the_table_id_keeps_the_parameter() -> None:
    result = parse_task_lineage(SQL, task_name="t", schema=SCHEMA)

    assert result.statement_lineage["stmt:001"]["target_table"] == "cat.${db_name}.t"


def test_an_unbound_table_parameter_is_incomplete_input() -> None:
    result = parse_task_lineage(SQL, task_name="t", schema=SCHEMA)

    [gap] = _gaps(result)
    assert gap["table"] == "cat.${db_name}.t"
    assert gap["parameters"] == ["db_name"]
    assert gap["statement_id"] == "stmt:001"
    assert gap["root_impact"] is True
    assert result.analysis_status["status"] == "partial"
    assert result.analysis_status["blocking_reasons"][0] == "input_incomplete"


def test_a_parameterised_table_is_not_missing_metadata() -> None:
    coverage = parse_task_lineage(SQL, task_name="t", schema=SCHEMA).diagnostics[
        "metadata_coverage"
    ]

    assert coverage["missing_tables"] == []
    assert coverage["unbound_parameter_tables"] == ["cat.${db_name}.t"]


def test_a_parameterised_source_table_is_reported_too() -> None:
    result = parse_task_lineage(
        "INSERT OVERWRITE TABLE db.out SELECT id FROM ${src_db}.src", task_name="t",
        schema={"db.out": ["id"]},
    )

    [gap] = _gaps(result)
    assert (gap["table"], gap["parameters"]) == ("${src_db}.src", ["src_db"])


def test_a_parameter_in_a_value_is_not_a_table_name() -> None:
    result = parse_task_lineage(
        "INSERT OVERWRITE TABLE db.out PARTITION (dt = '${dt}') SELECT id FROM db.src",
        task_name="t",
        schema={"db.src": ["id"], "db.out": ["id"]},
    )

    assert _gaps(result) == []


def test_the_parse_summary_names_the_unbound_parameter(tmp_path, capsys) -> None:
    sql_file = tmp_path / "t.sql"
    sql_file.write_text(SQL, encoding="utf-8")

    main(["parse", "--sql-file", str(sql_file), "--out", str(tmp_path / "out")])
    printed = capsys.readouterr().out

    assert "unbound parameter" in printed
    assert "cat.${db_name}.t" in printed
    assert "db_name.t" not in printed.replace("${db_name}.t", "")


def test_the_metadata_report_lists_parameterised_tables_apart(tmp_path) -> None:
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "t.json").write_text(
        json.dumps({"meta": {"task_name": "t", "sql": SQL}}), encoding="utf-8"
    )
    out = tmp_path / "out"

    main(["parse", "--input-dir", str(tasks), "--out", str(out), "--metadata-preflight"])
    report = json.loads((out / "metadata_gaps.json").read_text(encoding="utf-8"))

    assert "cat.${db_name}.t" not in {item["table"] for item in report["missing_tables"]}
    assert report["unbound_parameter_tables"] == [
        {"table": "cat.${db_name}.t", "referenced_by_task_count": 1, "referenced_by": ["t"]}
    ]


def _batch_parse(tmp_path, sql: str, schema: dict):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "t.json").write_text(
        json.dumps({"meta": {"task_name": "t", "sql": sql}}), encoding="utf-8"
    )
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps(schema), encoding="utf-8")
    out = tmp_path / "out"
    main(["parse", "--input-dir", str(tasks), "--out", str(out), "--schema", str(schema_file)])
    return out / "metadata_gaps.json"


def test_the_batch_metadata_report_lists_unbound_tables_too(tmp_path) -> None:
    """The batch branch wrote the manifest without the unbound tables preflight lists."""
    manifest = _batch_parse(
        tmp_path,
        "INSERT OVERWRITE TABLE db.tgt SELECT a.id, m.v "
        "FROM ${src_db}.src a JOIN db.missing m ON a.id = m.id",
        {"db.tgt": ["id", "v"]},
    )

    report = json.loads(manifest.read_text(encoding="utf-8"))
    assert [item["table"] for item in report["missing_tables"]] == ["db.missing"]
    assert [item["table"] for item in report["unbound_parameter_tables"]] == ["${src_db}.src"]


def test_a_batch_with_only_unbound_tables_still_writes_the_report(tmp_path) -> None:
    manifest = _batch_parse(
        tmp_path,
        "INSERT OVERWRITE TABLE db.tgt SELECT id FROM ${src_db}.src",
        {"db.tgt": ["id"]},
    )

    report = json.loads(manifest.read_text(encoding="utf-8"))
    assert report["missing_tables"] == []
    assert [item["table"] for item in report["unbound_parameter_tables"]] == ["${src_db}.src"]


def test_a_batch_with_no_gaps_writes_no_report(tmp_path) -> None:
    """Sentinel: complete metadata and no parameters leave no manifest behind."""
    manifest = _batch_parse(
        tmp_path,
        "INSERT OVERWRITE TABLE db.tgt SELECT id FROM db.src",
        {"db.tgt": ["id"], "db.src": ["id"]},
    )

    assert not manifest.exists()
