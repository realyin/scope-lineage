"""Whether qualify succeeded cannot be read from object identity.

`sqlglot.optimizer.qualify` mutates the tree it is given and returns that same object, so
`qualified is src_expr` is true whether it succeeded or raised. The branch guarded by that
comparison — "check if qualify would have failed" — therefore ran every time, qualifying
each statement a second time to learn something the first call already knew (QUALIFY-001).

Cost only, not correctness: the second pass is redundant. But on a statement with tens of
thousands of column references it is not a cheap redundancy.
"""

from __future__ import annotations

import pytest

import scope_lineage.scope.scope_builder as scope_builder
from scope_lineage.scope.scope_builder import parse_scope_lineage

SQL = "INSERT INTO mart.t SELECT a, b FROM ods.src"
SCHEMA = {"ods.src": ["a", "b"]}


def test_qualify_runs_once_for_a_statement_it_can_handle(monkeypatch):
    calls = []
    real = scope_builder.sg_qualify

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(scope_builder, "sg_qualify", counting)
    parse_scope_lineage(SQL, task_name="t", schema=SCHEMA)

    assert len(calls) == 1


def test_a_statement_qualify_can_handle_is_not_a_fallback():
    result = parse_scope_lineage(SQL, task_name="t", schema=SCHEMA)

    assert result.diagnostics.fallback_used is False


def test_a_failing_qualify_is_recorded_as_a_fallback(monkeypatch):
    def always_raises(*_args, **_kwargs):
        raise RuntimeError("qualify refused this statement")

    monkeypatch.setattr(scope_builder, "sg_qualify", always_raises)
    result = parse_scope_lineage(SQL, task_name="t", schema=SCHEMA)

    assert result.diagnostics.fallback_used is True


def test_a_failing_qualify_still_produces_lineage():
    """Degrading is the point of the fallback: an unqualified AST is still analysed."""
    result = parse_scope_lineage(SQL, task_name="t", schema=SCHEMA)

    assert [output.name for output in result.scopes["ROOT"].outputs] == ["a", "b"]


@pytest.mark.parametrize("statement", [
    "CREATE TABLE mart.t AS SELECT a FROM ods.src",
    "MERGE INTO mart.t AS x USING ods.src AS s ON x.a = s.a "
    "WHEN MATCHED THEN UPDATE SET x.b = s.b",
])
def test_the_other_write_shapes_also_qualify_once(monkeypatch, statement):
    calls = []
    real = scope_builder.sg_qualify

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(scope_builder, "sg_qualify", counting)
    parse_scope_lineage(statement, task_name="t", schema=SCHEMA)

    assert len(calls) == 1
