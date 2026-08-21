"""CREATE TABLE/VIEW may omit AS before its query; sqlglot only accepts that for SELECT.

`CREATE TABLE t AS SELECT ...` may be written without the `AS` in Spark. sqlglot
handles that when the query starts with SELECT, but not when it starts with WITH --
there it falls back to a Command, and the whole statement's lineage is lost.

The repair inserts the `AS` and re-parses. It runs on the token stream, per statement,
because the tokenizer strips comments and string literals: on real scripts, a
commented-out `create table` line sitting directly above a live `WITH ... AS (` is a
far more common text match than the defect itself, and a text-level rewrite there
would silently swallow the following statement's CTE.
"""
from __future__ import annotations

import pytest

from scope_lineage.scope.scope_builder import (
    NoSupportedWriteStatementError,
    parse_all_scope_lineage,
    parse_scope_lineage,
)

SCHEMA = {"db.s": ["a", "b"], "db.u": ["a"]}


def _kinds(sql: str) -> list[tuple[str, str]]:
    return [
        (r.stmt_kind, r.target_table)
        for r in parse_all_scope_lineage(sql, task_name="t", schema=SCHEMA)
    ]


# --- drivers: must fail before the fix -------------------------------------------

def test_ctas_with_leading_cte_and_no_as_is_parsed():
    result = parse_scope_lineage(
        "create table db.t WITH tmp AS (SELECT a FROM db.s) SELECT a FROM tmp",
        task_name="t",
        schema=SCHEMA,
    )
    assert result.stmt_kind == "CTAS"
    assert result.target_table == "db.t"
    assert result.source_tables == ["db.s"]


def test_ctas_with_table_options_and_leading_cte_is_parsed():
    for options in ("USING iceberg", "PARTITIONED BY (dt)", "TBLPROPERTIES('k'='v')"):
        result = parse_scope_lineage(
            f"create table db.t {options} WITH tmp AS (SELECT a FROM db.s) SELECT a FROM tmp",
            task_name="t",
            schema=SCHEMA,
        )
        assert result.stmt_kind == "CTAS", options
        assert result.source_tables == ["db.s"], options


def test_create_view_with_leading_cte_is_parsed():
    result = parse_scope_lineage(
        "CREATE OR REPLACE TEMPORARY VIEW db.v "
        "WITH tmp AS (SELECT a FROM db.s) SELECT a FROM tmp",
        task_name="t",
        schema=SCHEMA,
    )
    assert result.source_tables == ["db.s"]


def test_repaired_lineage_equals_explicit_as_spelling():
    """Mechanical equivalence: the repair's only legitimate effect is to make the
    text mean what the explicit-AS spelling already means. Comparing the rendered
    contract checks every column, not just that something was produced."""
    from scope_lineage.contract.lineage import to_lineage_dict

    without = parse_scope_lineage(
        "create table db.t WITH tmp AS (SELECT a, b FROM db.s) SELECT a, b FROM tmp",
        task_name="t", schema=SCHEMA,
    )
    with_as = parse_scope_lineage(
        "create table db.t AS WITH tmp AS (SELECT a, b FROM db.s) SELECT a, b FROM tmp",
        task_name="t", schema=SCHEMA,
    )
    assert to_lineage_dict(without) == to_lineage_dict(with_as)


# --- guards: must pass before AND after -------------------------------------------

def test_commented_out_create_above_live_with_is_untouched():
    """The highest-value guard: this text shape is the common one in real scripts,
    and a text-level rewrite here eats the INSERT's CTE and projection."""
    sql = (
        "--create table db.c\n"
        "insert overwrite table db.u\n"
        "with c as (SELECT a FROM db.s)\n"
        "select a from c"
    )
    assert _kinds(sql) == [("INSERT_OVERWRITE", "db.u")]
    result = parse_scope_lineage(sql, task_name="t", schema=SCHEMA)
    assert result.source_tables == ["db.s"]


def test_comment_string_literal_containing_with_is_untouched():
    result = parse_scope_lineage(
        "create table db.t COMMENT 'a WITH x AS (' AS SELECT a FROM db.s",
        task_name="t", schema=SCHEMA,
    )
    assert result.source_tables == ["db.s"]


def test_column_definition_ddl_is_not_treated_as_ctas():
    """A column-definition DDL writes no rows; it must stay unmodelled, not become
    a CTAS whose query is whatever followed it."""
    with pytest.raises(NoSupportedWriteStatementError):
        _kinds("create table db.t (a int, b string)")


def test_create_like_database_function_untouched():
    for sql in ("create table db.t LIKE db.s", "CREATE DATABASE db2"):
        with pytest.raises(NoSupportedWriteStatementError):
            _kinds(sql)


def test_explicit_as_and_plain_ctas_unchanged():
    for sql in (
        "create table db.t AS WITH tmp AS (SELECT a FROM db.s) SELECT a FROM tmp",
        "create table db.t SELECT a FROM db.s",
    ):
        result = parse_scope_lineage(sql, task_name="t", schema=SCHEMA)
        assert result.stmt_kind == "CTAS", sql
        assert result.source_tables == ["db.s"], sql
