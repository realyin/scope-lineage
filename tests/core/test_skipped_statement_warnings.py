"""A statement ignored by design is recorded, not called unsupported.

`_statement_category` already separates a config statement (`control_statement`) and an
empty one (`empty_statement`) from the kinds this tool genuinely does not model. The task
document acts on that split -- it marks those two "ignored" and stays quiet. The statement
document imported the same function and never used it, warning `unsupported_statement` for
every skipped statement alike, which made SET and empty statements the largest source of
warnings in a run while saying nothing a consumer could act on.

Dropping the warning alone would trade a misleading signal for no signal: the statement
document's skip record carried no SQL, so which setting was executed was unrecoverable.
The record now carries `normalized_sql`, matching the task document's.
"""
from __future__ import annotations

from scope_lineage.scope.scope_builder import parse_all_scope_lineage
from scope_lineage.scope.task_lineage import parse_task_lineage

SCHEMA = {"db.s": ["a"], "db.t": ["a"], "db.u": ["a"]}


def _first(sql: str):
    return parse_all_scope_lineage(sql, task_name="t", schema=SCHEMA)[0]


def _warning_types(result) -> list[str]:
    return [w.type for w in result.diagnostics.warnings]


def _skipped(result, category: str) -> list[dict]:
    return [s for s in result.skipped_statements if s.get("category") == category]


def test_control_statement_is_recorded_but_not_warned():
    result = _first("SET spark.sql.ansi.enabled=false;\nINSERT INTO db.t SELECT a FROM db.s")
    assert _skipped(result, "control_statement"), result.skipped_statements
    assert "unsupported_statement" not in _warning_types(result)


def test_empty_statement_is_recorded_but_not_warned():
    # A bare `;` after a comment parses to exp.Semicolon; a plain `;;` yields None and is
    # never recorded at all, which is a separate v1/v2 divergence.
    result = _first("INSERT INTO db.t SELECT a FROM db.s;\n-- note\n;")
    assert _skipped(result, "empty_statement"), result.skipped_statements
    assert "unsupported_statement" not in _warning_types(result)


def test_skipped_control_statement_records_its_sql():
    """Without this the setting that was dropped is unrecoverable once the warning goes."""
    result = _first("SET spark.sql.ansi.enabled=false;\nINSERT INTO db.t SELECT a FROM db.s")
    record = _skipped(result, "control_statement")[0]
    assert "ansi" in (record.get("normalized_sql") or "").lower(), record


def test_row_mutation_still_warns():
    result = _first("DELETE FROM db.u WHERE a = 1;\nINSERT INTO db.t SELECT a FROM db.s")
    assert "unsupported_statement" in _warning_types(result)


def test_unsupported_kind_still_warns():
    result = _first("DROP TABLE db.u;\nINSERT INTO db.t SELECT a FROM db.s")
    assert "unsupported_statement" in _warning_types(result)


def test_statement_and_task_documents_agree_on_ignored_kinds():
    """Scoped to control/empty on purpose: the two documents still disagree about row
    mutations, which the task document models and the statement document does not."""
    sql = "SET spark.sql.ansi.enabled=false;\nINSERT INTO db.t SELECT a FROM db.s;\n-- x\n;"
    v1 = _warning_types(_first(sql))
    task = parse_task_lineage(sql, task_name="t", schema=SCHEMA)
    v2 = [w.get("type") for w in task.diagnostics["warnings"]]
    assert "unsupported_statement" not in v1
    assert "unsupported_statement" not in v2
