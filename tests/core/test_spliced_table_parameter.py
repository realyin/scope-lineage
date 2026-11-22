"""A run parameter spliced into the middle of a name keeps the whole name.

``FROM db.src_${region}`` tokenizes as the word ``src_`` followed by a parameter, which
sqlglot's grammar cannot place: the strict parse failed, the lenient parse dropped the
parameter and everything after it up to the next clause, and the statement read a table
``db.src_`` -- reported as missing metadata -- while the JOINed table vanished. The
spliced name is now quoted as one identifier before parsing, so the table id keeps the
parameter (``db.src_${region}``), the table is reported as an unbound-parameter table and
the rest of the statement survives.
"""

from __future__ import annotations

import pytest

from scope_lineage.scope.spliced_parameters import quote_spliced_parameters
from scope_lineage.scope.task_lineage import parse_task_lineage

SQL = (
    "INSERT OVERWRITE TABLE db.tgt SELECT a.id, m.v "
    "FROM db.src_${region} a JOIN db.missing m ON a.id = m.id"
)
SCHEMA = {"db.tgt": ["id", "v"]}


def _parse(sql: str = SQL, schema=None):
    return parse_task_lineage(sql, task_name="t", schema=SCHEMA if schema is None else schema)


def test_the_spliced_table_keeps_its_whole_name_and_the_join_survives() -> None:
    lineage = _parse().statement_lineage["stmt:001"]

    assert sorted(lineage["source_tables"]) == ["db.missing", "db.src_${region}"]


def test_the_spliced_table_is_an_unbound_parameter_table_not_missing_metadata() -> None:
    coverage = _parse().diagnostics["metadata_coverage"]

    assert coverage["unbound_parameter_tables"] == ["db.src_${region}"]
    assert coverage["missing_tables"] == ["db.missing"]


def test_the_statement_is_not_syntax_recovered() -> None:
    result = _parse()

    assert "syntax_recovered" not in result.analysis_status["blocking_reasons"]
    assert result.analysis_status["blocking_reasons"][0] == "input_incomplete"


def test_the_quoting_is_disclosed() -> None:
    warnings = [
        w for w in _parse().diagnostics["warnings"]
        if w["type"] == "parameter_names_quoted_for_parse"
    ]

    assert len(warnings) == 1
    assert "src_${region}" in warnings[0]["msg"]


@pytest.mark.parametrize(
    "written, quoted",
    [
        ("db.src_${region}", "db.`src_${region}`"),
        ("db.${p}_src", "db.`${p}_src`"),
        ("db.a_${p}_b${q}", "db.`a_${p}_b${q}`"),
        ("${db}.t_${p}", "${db}.`t_${p}`"),
        ("src_${p}", "`src_${p}`"),
    ],
)
def test_spliced_names_are_quoted_whole(written: str, quoted: str) -> None:
    sql, names = quote_spliced_parameters(f"SELECT x FROM {written} a")

    assert sql == f"SELECT x FROM {quoted} a"
    assert names == (quoted.split(".")[-1].strip("`"),)


@pytest.mark.parametrize(
    "sql",
    [
        # A whole-part parameter already parses; leave it alone.
        "SELECT x FROM ${db}.t a",
        # A parameter inside a string is a value.
        "SELECT x FROM db.t WHERE dt = 'p_${dt}'",
        # A parameter standing alone in an expression is a value too.
        "SELECT x FROM db.t WHERE dt = ${dt}",
        # Inside a comment it is a remark.
        "SELECT x FROM db.t -- db.src_${region}\n",
        # Already quoted by the author.
        "SELECT x FROM db.`src_${region}` a",
        # Separated by whitespace: two tokens, not one name.
        "SELECT x FROM db.t WHERE a = b ${p}",
        # Outside a name position the same shape may be a value; left to the parser.
        "SELECT x FROM db.t WHERE dt = ${bizdate}01",
        "SELECT c_${x} FROM db.t",
    ],
)
def test_sentinel_what_is_not_a_spliced_name_is_untouched(sql: str) -> None:
    assert quote_spliced_parameters(sql) == (sql, ())


def test_sentinel_a_whole_part_parameter_is_reported_as_before() -> None:
    coverage = _parse(
        "INSERT OVERWRITE TABLE db.tgt SELECT a.id, m.v "
        "FROM ${src_db}.src a JOIN db.missing m ON a.id = m.id"
    ).diagnostics["metadata_coverage"]

    assert coverage["unbound_parameter_tables"] == ["${src_db}.src"]
    assert coverage["missing_tables"] == ["db.missing"]
