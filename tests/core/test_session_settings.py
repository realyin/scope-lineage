"""A quoted regex column selection only expands when the session enables it.

`spark.sql.parser.quotedRegexColumnNames` defaults to `false` in Spark, and under
`false` a backtick-quoted regex is an ordinary (usually missing) column name -- the
statement fails analysis and never runs. Core expanded unconditionally, so a script
that disabled the feature, or never enabled it, still got lineage invented from a
pattern Spark would have rejected.

Declining to expand is all this does. The columns downstream of a pattern that cannot
expand already have an expression in the contract -- it is the same state a pattern
reaches today when no schema is available -- so nothing about it is redesigned here.
Only the leading warning changes, from "Core could not find this column" to the real
reason.
"""
from __future__ import annotations

from scope_lineage.scope.scope_builder import parse_all_scope_lineage

SCHEMA = {"db.src": ["dt", "a", "b", "c"]}
PROJECTION = "INSERT OVERWRITE TABLE db.tgt SELECT `(dt)?+.+` FROM db.src"


def _first(sql: str):
    return parse_all_scope_lineage(sql, task_name="t", schema=SCHEMA)[0]


def _outputs(result) -> list[str]:
    return [o.name for o in result.scopes["ROOT"].outputs or []]


def _warning_types(result) -> list[str]:
    return [w.type for w in result.diagnostics.warnings]


# --- drivers: must fail before the fix -------------------------------------------

def test_setting_disabled_declines_to_expand():
    result = _first(f"SET spark.sql.parser.quotedRegexColumnNames=false;\n{PROJECTION}")
    assert _outputs(result) == ["(dt)?+.+"]
    assert "regex_column_selection_disabled" in _warning_types(result)
    assert "column_not_found" not in _warning_types(result)


def test_no_setting_declines_to_expand():
    """Spark's own default is false; a script that never enables it never expanded."""
    result = _first(PROJECTION)
    assert _outputs(result) == ["(dt)?+.+"]
    assert "regex_column_selection_disabled" in _warning_types(result)


def test_setting_re_enabled_applies_to_later_statements():
    result = parse_all_scope_lineage(
        "SET spark.sql.parser.quotedRegexColumnNames=false;\n"
        "INSERT OVERWRITE TABLE db.a SELECT `(dt)?+.+` FROM db.src;\n"
        "SET spark.sql.parser.quotedRegexColumnNames=true;\n"
        "INSERT OVERWRITE TABLE db.b SELECT `(dt)?+.+` FROM db.src",
        task_name="t",
        schema=SCHEMA,
    )
    assert [o.name for o in result[0].scopes["ROOT"].outputs] == ["(dt)?+.+"]
    assert [o.name for o in result[1].scopes["ROOT"].outputs] == ["a", "b", "c"]


def test_value_with_a_trailing_comment_is_read():
    """The comment attaches to the boolean value node, so per-item rendering carries
    it too -- the matcher must strip comments explicitly."""
    result = _first(
        f"SET spark.sql.parser.quotedRegexColumnNames=true /* enabled */;\n{PROJECTION}"
    )
    assert _outputs(result) == ["a", "b", "c"]


# --- guards: must pass before AND after -------------------------------------------

def test_enabled_expands():
    result = _first(f"SET spark.sql.parser.quotedRegexColumnNames=true;\n{PROJECTION}")
    assert _outputs(result) == ["a", "b", "c"]


def test_an_unrelated_setting_does_not_disable_expansion():
    """The corpus is full of other SET keys; none may switch this off."""
    result = _first(
        "SET spark.sql.adaptive.enabled=true;\n"
        "SET spark.sql.parser.quotedRegexColumnNames=true;\n" + PROJECTION
    )
    assert _outputs(result) == ["a", "b", "c"]


def test_query_form_set_is_not_read_as_a_value():
    """`SET key` (no `=`) reads the setting; it parses as a Command and must not be
    mistaken for setting it false."""
    result = _first(
        "SET spark.sql.parser.quotedRegexColumnNames=true;\n"
        "SET spark.sql.parser.quotedRegexColumnNames;\n" + PROJECTION
    )
    assert _outputs(result) == ["a", "b", "c"]


def test_last_setting_wins():
    result = _first(
        "SET spark.sql.parser.quotedRegexColumnNames=false;\n"
        "SET spark.sql.parser.quotedRegexColumnNames=true;\n" + PROJECTION
    )
    assert _outputs(result) == ["a", "b", "c"]


def test_setting_after_the_write_does_not_affect_it():
    result = parse_all_scope_lineage(
        "SET spark.sql.parser.quotedRegexColumnNames=true;\n"
        + PROJECTION
        + ";\nSET spark.sql.parser.quotedRegexColumnNames=false",
        task_name="t",
        schema=SCHEMA,
    )
    assert [o.name for o in result[0].scopes["ROOT"].outputs] == ["a", "b", "c"]


def test_set_is_still_recorded_and_not_warned_about():
    """#88's behaviour is unchanged: a config statement is recorded, not called
    unsupported, and carries its SQL."""
    result = _first(f"SET spark.sql.parser.quotedRegexColumnNames=true;\n{PROJECTION}")
    control = [s for s in result.skipped_statements if s["category"] == "control_statement"]
    assert control and control[0].get("normalized_sql")
    assert "unsupported_statement" not in _warning_types(result)


def test_both_entry_points_agree():
    """The statement and task documents must not disagree about one setting.

    `parse_task_lineage` hands `parse_scope_lineage` a `tree=`, and the tree path used to
    fall back to "expand" -- so the same SQL expanded in the task document and declined in
    the statement document. The task path is precisely the caller that *does* hold the
    script, and it already folds the sibling partitionOverwriteMode setting, so it must
    pass this one down rather than let the callee guess.
    """
    from scope_lineage.scope.task_lineage import parse_task_lineage

    v1 = _first(PROJECTION)
    task = parse_task_lineage(PROJECTION, task_name="t", schema=SCHEMA)
    documents = list((task.statement_lineage or {}).values())
    assert documents, "expected the task document to carry the statement"
    v2_root = (documents[0].get("scopes") or {}).get("ROOT") or {}
    v2_columns = [c.get("name") for c in v2_root.get("columns") or []]

    assert _outputs(v1) == ["(dt)?+.+"]
    assert v2_columns == ["(dt)?+.+"], "the task document expanded what the statement declined"
