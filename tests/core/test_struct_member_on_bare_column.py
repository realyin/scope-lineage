"""`col.field` on a struct column is a member access, not a table qualifier.

`alias.col.field` has three parts and resolves as lineage from `alias.col`. Written without
the alias — `col.field` — it has two, and the struct resolver required three, so the first
part was looked up as a table alias, found nothing, and reported
`alias_not_bound_to_input_source` (STRUCT-001).

Whether the alias is there is not the author's choice alone: qualify adds it when it knows
the column set, and cannot when the input is a `SELECT *` over a table whose columns arrive
later. So the same SQL resolves or does not depending on how deep it sits, which is why a
shallow synthetic never reproduced this.
"""

from __future__ import annotations

from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {"ods.src": ["id", "flags"], "ods.other": ["id", "note"]}

# Two inputs, both `SELECT *`: qualify cannot add the alias to `flags.hide`, and with more
# than one input the resolver has no single source to fall back on. This is the real shape.
BARE_MEMBER_ACCESS = """INSERT INTO mart.t
SELECT SUM(flags.hide) AS hidden
FROM (SELECT * FROM ods.src) a
LEFT JOIN (SELECT * FROM ods.other) b ON a.id = b.id"""

QUALIFIED_MEMBER_ACCESS = """INSERT INTO mart.t
SELECT SUM(a.flags.hide) AS hidden
FROM (SELECT * FROM ods.src) a
LEFT JOIN (SELECT * FROM ods.other) b ON a.id = b.id"""


def _root(sql, schema=SCHEMA):
    result = parse_scope_lineage(sql, task_name="t", schema=schema)
    return result, {output.name: output for output in result.scopes["ROOT"].outputs}


def test_a_bare_struct_member_access_binds_to_the_struct_column():
    result, outputs = _root(BARE_MEMBER_ACCESS)

    resolution = outputs["hidden"].expression_resolution or {}
    assert resolution.get("status") == "resolved"
    assert resolution.get("physical_source_fields") == [
        {"table": "ods.src", "field": "flags"}
    ]
    assert result.diagnostics.lineage_fact_gaps == []


def test_the_qualified_form_is_unchanged():
    """The three-part form already worked; it must keep working identically."""
    result, outputs = _root(QUALIFIED_MEMBER_ACCESS)

    resolution = outputs["hidden"].expression_resolution or {}
    assert resolution.get("status") == "resolved"
    assert resolution.get("physical_source_fields") == [
        {"table": "ods.src", "field": "flags"}
    ]


def test_a_real_table_qualifier_is_still_a_qualifier():
    """`a.id` must not be read as member access on a column called `a`."""
    sql = """INSERT INTO mart.t
SELECT a.id AS the_id
FROM (SELECT * FROM ods.src) a
LEFT JOIN (SELECT * FROM ods.other) b ON a.id = b.id"""

    result, outputs = _root(sql)

    resolution = outputs["the_id"].expression_resolution or {}
    assert resolution.get("physical_source_fields") == [
        {"table": "ods.src", "field": "id"}
    ]


def test_a_name_that_is_neither_column_nor_alias_still_reports_a_gap():
    sql = """INSERT INTO mart.t
SELECT SUM(nothing_like_this.hide) AS hidden
FROM (SELECT * FROM ods.src) a
LEFT JOIN (SELECT * FROM ods.other) b ON a.id = b.id"""

    result, outputs = _root(sql)

    resolution = outputs["hidden"].expression_resolution or {}
    assert resolution.get("status") != "resolved"


def test_a_name_two_inputs_both_expose_is_not_guessed():
    """Ambiguity between inputs is a fact; picking one would be a guess."""
    sql = """INSERT INTO mart.t
SELECT SUM(flags.hide) AS hidden
FROM (SELECT * FROM ods.src) a
JOIN (SELECT * FROM ods.dup) b ON a.id = b.id"""

    result, outputs = _root(
        sql, {"ods.src": ["id", "flags"], "ods.dup": ["id", "flags"]}
    )

    resolution = outputs["hidden"].expression_resolution or {}
    fields = resolution.get("physical_source_fields") or []
    assert len(fields) != 1 or resolution.get("status") != "resolved"
