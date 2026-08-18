"""A column named like a keyword must not be able to hang the loader.

sqlglot's Spark dialect does not terminate when it parses a ``CREATE TABLE`` whose column
name is an unquoted ``not`` — a 51-character statement runs forever, on 30.0.0, 30.6.0 and
30.17.0 alike. Backquoting the name makes it parse in milliseconds. Since the metadata DDL
is a platform export and such a column is both legal and real, and since a pure-Python
caller cannot put a timeout around sqlglot (``signal.alarm`` is swallowed by sqlglot's own
``except Exception``), the trigger has to be removed before the text is handed over
(METADATA-002).

The string-level tests come first on purpose: if the normalization regresses, they fail in
milliseconds and name the cause, rather than leaving the parse-level tests to hang.
"""

from __future__ import annotations

import json
from pathlib import Path

from scope_lineage.metadata.schema_metadata import load_schema_sources
from scope_lineage.metadata.target_table_metadata import (
    _facts_from_ddl,
    _quoted_keyword_column_names,
)


def test_unquoted_keyword_column_name_is_quoted():
    ddl = "CREATE TABLE db.t (a DOUBLE, not DOUBLE COMMENT 'n')"

    normalized = _quoted_keyword_column_names(ddl)

    assert "`not` DOUBLE" in normalized
    assert "(a DOUBLE" in normalized


def test_keyword_match_ignores_case():
    for spelling in ("NOT", "Not", "nOt"):
        ddl = f"CREATE TABLE db.t (a DOUBLE, {spelling} DOUBLE)"

        normalized = _quoted_keyword_column_names(ddl)

        assert f"`{spelling}` DOUBLE" in normalized


def test_commas_inside_types_do_not_split_columns():
    ddl = (
        "CREATE TABLE db.t (\n"
        "  a STRUCT<x: INT, y: STRING>,\n"
        "  b DECIMAL(10, 2),\n"
        "  not DOUBLE\n"
        ")"
    )

    normalized = _quoted_keyword_column_names(ddl)

    assert "STRUCT<x: INT, y: STRING>" in normalized
    assert "DECIMAL(10, 2)" in normalized
    assert "`not` DOUBLE" in normalized


def test_commas_and_parens_inside_comments_are_ignored():
    ddl = (
        "CREATE TABLE db.t (\n"
        "  a DOUBLE COMMENT '递归统计:子文件数(不计副本), 含子目录',\n"
        "  not DOUBLE COMMENT 'n'\n"
        ")"
    )

    normalized = _quoted_keyword_column_names(ddl)

    assert "'递归统计:子文件数(不计副本), 含子目录'" in normalized
    assert "`not` DOUBLE" in normalized


def test_ddl_without_keyword_columns_is_returned_unchanged():
    ddl = (
        "CREATE TABLE db.t (\n"
        "  msg_id STRING COMMENT 'msg_id',\n"
        "  score DOUBLE\n"
        ")\n"
        "COMMENT '一张普通表'"
    )

    assert _quoted_keyword_column_names(ddl) == ddl


def test_already_quoted_column_is_left_alone():
    ddl = "CREATE TABLE db.t (a DOUBLE, `not` DOUBLE)"

    assert _quoted_keyword_column_names(ddl) == ddl


def test_table_level_constraint_is_not_treated_as_a_column():
    ddl = "CREATE TABLE db.t (a INT, not DOUBLE, PRIMARY KEY (a))"

    normalized = _quoted_keyword_column_names(ddl)

    assert "`not` DOUBLE" in normalized
    assert "PRIMARY KEY (a)" in normalized


def test_unbalanced_ddl_is_returned_unchanged():
    ddl = "CREATE TABLE db.t (a DOUBLE, not DOUBLE"

    assert _quoted_keyword_column_names(ddl) == ddl


def test_ddl_without_a_column_list_is_returned_unchanged():
    ddl = "CREATE TABLE db.t USING iceberg"

    assert _quoted_keyword_column_names(ddl) == ddl


def test_keyword_column_survives_ddl_fact_extraction():
    ddl = "CREATE TABLE db.t (a DOUBLE, not DOUBLE COMMENT 'n')"
    # Guard the guard: without the rewrite the parse below never returns, so assert the
    # trigger is gone before handing the text to sqlglot.
    assert "`not`" in _quoted_keyword_column_names(ddl)

    issues: list[str] = []
    table, columns, partitions = _facts_from_ddl(ddl, issues)

    assert columns == ["a", "not"]
    assert partitions == []
    assert issues == []
    assert table == "db.t"


def test_keyword_column_that_only_failed_to_parse_is_also_recovered():
    """Not every keyword column hangs — some merely fail, and cost the whole table.

    ``like`` is the shape found in the real corpus: three tables were rejected outright
    with ``ddl_parse_failed:ParseError`` and lost all 3005+ of their columns. Quoting
    recovers them by the same rule that stops ``not`` from hanging.
    """
    ddl = "CREATE TABLE db.t (a DOUBLE, like DOUBLE COMMENT 'x')"

    issues: list[str] = []
    _table, columns, _partitions = _facts_from_ddl(ddl, issues)

    assert columns == ["a", "like"]
    assert issues == []


def test_keyword_partition_column_is_reported_not_hung():
    """``PARTITIONED BY (not STRING)`` raises rather than hanging — pin that shape."""
    issues: list[str] = []

    table, columns, partitions = _facts_from_ddl(
        "CREATE TABLE db.t (a DOUBLE) PARTITIONED BY (not STRING)",
        issues,
    )

    assert (table, columns, partitions) == ("", [], [])
    assert any(issue.startswith("ddl_parse_failed:") for issue in issues)


def _document(table: str, ddl: str, column_names: list[str]) -> dict:
    return {
        "table_name": table,
        "full_table_name": f"catalog.{table}",
        "ddl": ddl,
        "schema": [
            {
                "columnName": name,
                "columnType": "double",
                "columnComment": f"{name} 注释",
                "columnIndex": index,
                "isPartition": 0,
            }
            for index, name in enumerate(column_names)
        ],
    }


def test_table_with_keyword_column_loads_with_every_column(tmp_path: Path):
    document = _document("db.t", "CREATE TABLE db.t (a DOUBLE, not DOUBLE)", ["a", "not"])
    path = tmp_path / "db.t_metadata.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    schema = load_schema_sources([str(path)])

    assert schema["db.t"] == ["a", "not"]
    assert schema.metadata_conflicts == []


def test_neighbouring_tables_are_unaffected(tmp_path: Path):
    keyword = _document("db.t", "CREATE TABLE db.t (a DOUBLE, not DOUBLE)", ["a", "not"])
    plain = _document("db.u", "CREATE TABLE db.u (b DOUBLE)", ["b"])
    for name, document in (("db.t", keyword), ("db.u", plain)):
        (tmp_path / f"{name}_metadata.json").write_text(
            json.dumps(document, ensure_ascii=False), encoding="utf-8"
        )

    schema = load_schema_sources([
        str(tmp_path / "db.t_metadata.json"),
        str(tmp_path / "db.u_metadata.json"),
    ])

    assert schema["db.t"] == ["a", "not"]
    assert schema["db.u"] == ["b"]
