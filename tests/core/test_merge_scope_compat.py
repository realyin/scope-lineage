"""Regression coverage for SQLGlot's 30.17 MERGE scope-model change."""

from __future__ import annotations

import pytest
from sqlglot import exp

from scope_lineage import parse_scope_lineage
from scope_lineage.scope import scope_builder
from scope_lineage.scope.end_to_end import build_end_to_end_lineage


SCHEMA = {
    "mart.target": ["id", "name"],
    "ods.source": ["id", "name"],
    "ods.source_archive": ["id", "name"],
    "dim.lookup": ["id", "name"],
}


def test_merge_using_scope_is_not_inferred_from_the_last_sibling_subquery() -> None:
    result = parse_scope_lineage(
        """
        MERGE INTO mart.target target
        USING (SELECT id, name FROM ods.source) source
        ON target.id = source.id
        WHEN MATCHED THEN UPDATE SET target.name = (
          SELECT MAX(lookup.name)
          FROM dim.lookup lookup
          WHERE lookup.id = target.id
        )
        WHEN NOT MATCHED THEN INSERT (id, name) VALUES (source.id, source.name)
        """,
        "merge_with_sibling_subquery",
        schema=SCHEMA,
    )

    assert set(result.scopes) == {"ROOT", "subq:source", "subq:derived_0"}
    assert result.source_tables == ["dim.lookup", "mart.target", "ods.source"]
    assert result.scopes["ROOT"].raw_sql == (
        "(SELECT `source`.`id` AS `id`, `source`.`name` AS `name` "
        "FROM `ods`.`source` AS `source`) AS `source`"
    )
    assert result.scopes["ROOT"].raw_sql_available is True

    root_columns = result.scopes["ROOT"].columns
    assert [(column.name, column.merge_branch) for column in root_columns] == [
        ("name", "matched"),
        ("id", "not_matched"),
        ("name", "not_matched"),
    ]
    assert [
        (source.scope, source.column) for source in root_columns[0].sources
    ] == [("subq:derived_0", "name")]

    scalar_scope = result.scopes["subq:derived_0"]
    assert [
        (source.scope, source.column)
        for source in scalar_scope.columns[0].sources
    ] == [("dim.lookup", "name")]
    assert [
        (source.scope, source.column)
        for source in scalar_scope.filters[0].columns
    ] == [("dim.lookup", "id"), ("mart.target", "id")]

    # sqlglot rebinds this correlated reference to `lookup`.`target`.`id`, reading the
    # target alias as a struct field on the subquery's own table. Protecting the
    # reference across qualify is the only reason the target resolves at all here.
    assert scalar_scope.raw_sql == (
        "SELECT MAX(`lookup`.`name`) AS `_col_0` "
        "FROM `dim`.`lookup` AS `lookup` WHERE `lookup`.`id` = target.id"
    )
    assert "lookup`.`target" not in scalar_scope.raw_sql


@pytest.mark.parametrize(
    ("using_sql", "expected_scope_ids", "expected_sources"),
    [
        (
            "(SELECT id, name FROM ods.source) source",
            {"ROOT", "subq:source"},
            ["ods.source"],
        ),
        (
            """(
              WITH staged AS (SELECT id, name FROM ods.source)
              SELECT id, name FROM staged
            ) source""",
            {"ROOT", "cte:staged", "subq:source"},
            ["ods.source"],
        ),
        (
            """(
              SELECT id, name FROM ods.source
              UNION ALL
              SELECT id, name FROM ods.source_archive
            ) source""",
            {
                "ROOT",
                "subq:source",
                "union:source",
                "union:source:b01",
                "union:source:b02",
            },
            ["ods.source", "ods.source_archive"],
        ),
    ],
)
def test_merge_using_query_shapes_have_stable_scope_ids(
    using_sql: str,
    expected_scope_ids: set[str],
    expected_sources: list[str],
) -> None:
    result = parse_scope_lineage(
        f"""
        MERGE INTO mart.target target
        USING {using_sql}
        ON target.id = source.id
        WHEN MATCHED THEN UPDATE SET target.name = source.name
        """,
        "merge_using_shape",
        schema=SCHEMA,
    )

    assert set(result.scopes) == expected_scope_ids
    assert result.source_tables == expected_sources
    assert result.scopes["ROOT"].raw_sql_available is True
    assert result.scopes["ROOT"].raw_sql.endswith("AS `source`")


def test_merge_using_bare_table_with_only_not_matched_resolves_values() -> None:
    result = parse_scope_lineage(
        """
        MERGE INTO mart.target target
        USING ods.source source
        ON target.id = source.id
        WHEN NOT MATCHED THEN INSERT (id, name) VALUES (source.id, source.name)
        """,
        "merge_only_not_matched",
        schema=SCHEMA,
    )

    assert result.source_tables == ["ods.source"]
    assert [
        (
            column.name,
            [(source.scope, source.column) for source in column.sources],
            column.merge_branch,
            column.merge_when_index,
        )
        for column in result.scopes["ROOT"].columns
    ] == [
        ("id", [("ods.source", "id")], "not_matched", 0),
        ("name", [("ods.source", "name")], "not_matched", 0),
    ]


def test_merge_insert_star_materializes_using_scope_columns() -> None:
    result = parse_scope_lineage(
        """
        MERGE INTO mart.target target
        USING ods.source source
        ON target.id = source.id
        WHEN NOT MATCHED THEN INSERT *
        """,
        "merge_insert_star",
        schema=SCHEMA,
    )

    assert [
        (
            column.name,
            [(source.scope, source.column) for source in column.sources],
            column.merge_branch,
        )
        for column in result.scopes["ROOT"].columns
    ] == [
        ("id", [("subq:source", "id")], "not_matched"),
        ("name", [("subq:source", "name")], "not_matched"),
    ]


def test_uncorrelated_action_scalar_query_does_not_add_target_as_a_source() -> None:
    result = parse_scope_lineage(
        """
        MERGE INTO mart.target target
        USING ods.source source
        ON target.id = source.id
        WHEN MATCHED THEN UPDATE SET target.name = (
          SELECT MAX(lookup.name) FROM dim.lookup lookup
        )
        """,
        "merge_uncorrelated_scalar",
        schema=SCHEMA,
    )

    assert result.source_tables == ["dim.lookup", "ods.source"]
    assert [
        (source.scope, source.column)
        for source in result.scopes["ROOT"].columns[0].sources
    ] == [("subq:derived_0", "name")]


def test_missing_non_merge_root_scope_fails_with_a_specific_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scope_builder, "traverse_scope", lambda _expression: [])

    with pytest.raises(
        ValueError,
        match="sqlglot produced no root scope for a non-MERGE write query",
    ):
        parse_scope_lineage(
            "INSERT INTO mart.target SELECT id, name FROM ods.source",
            "missing_root_scope",
            schema=SCHEMA,
        )


def test_missing_merge_ast_fails_instead_of_emitting_empty_lineage() -> None:
    result = scope_builder.ScopeLineageResult(
        task_id="missing_merge_ast",
        target_table="mart.target",
        stmt_kind="MERGE",
    )
    result.scopes["ROOT"] = scope_builder.ScopeData(kind="root")

    with pytest.raises(
        ValueError,
        match="MERGE statement reached column resolution without a Merge AST node",
    ):
        scope_builder.resolve_all(result, [])


def test_cte_name_in_a_nested_scope_does_not_hide_a_physical_sibling_table() -> None:
    result = parse_scope_lineage(
        """
        INSERT INTO mart.target
        SELECT id FROM staging
        UNION ALL
        SELECT id FROM (
          WITH staging AS (SELECT id FROM ods.source)
          SELECT id FROM staging
        ) nested
        """,
        "lexical_cte_name",
        schema={"staging": ["id"], "ods.source": ["id"]},
    )

    assert result.source_tables == ["ods.source", "staging"]


CTE_MERGE_SCHEMA = {
    "ods.events": ["id", "event_type", "account_id"],
    "dim.accounts": ["account_id", "account_key"],
    "mart.event_target": ["id", "event_type", "account_key"],
}

CTE_MERGE_SQL = """
WITH staged AS (
  SELECT
    e.id,
    e.event_type,
    a.account_key
  FROM ods.events e
  LEFT JOIN dim.accounts a
    ON e.account_id = a.account_id
)
MERGE INTO mart.event_target target
USING (
  SELECT id, event_type, account_key
  FROM staged
) source
ON target.id = source.id
WHEN MATCHED THEN UPDATE SET
  target.id = source.id,
  target.event_type = source.event_type,
  target.account_key = source.account_key
WHEN NOT MATCHED THEN INSERT *
"""


def test_merge_action_target_refs_do_not_leak_into_a_cte_projection() -> None:
    """A MERGE action's ``target.*`` must never be pasted onto an unrelated projection.

    Qualify reorders ``find_all(exp.Column)`` — a leading WITH block moves behind the
    MERGE body — while keeping the column count identical. Pairing the two traversals by
    position therefore passes its own count check and writes the action's ``target.*``
    into the CTE and into neighbouring UPDATE assignments (MERGE-CTE-001).
    """
    result = parse_scope_lineage(
        CTE_MERGE_SQL,
        "merge_with_cte_source",
        schema=CTE_MERGE_SCHEMA,
    )

    staged = result.scopes["cte:staged"]
    assert [column.name for column in staged.columns] == [
        "id",
        "event_type",
        "account_key",
    ]
    assert [column.expression for column in staged.columns] == [
        "`e`.`id`",
        "`e`.`event_type`",
        "`a`.`account_key`",
    ]

    # Both branches are asserted field by field: a count-only check cannot tell a
    # correct mapping apart from one that cycled the target columns by position.
    assert [
        (column.merge_branch, column.name, tuple(
            (source.scope, source.column) for source in column.sources
        ))
        for column in result.scopes["ROOT"].columns
    ] == [
        ("matched", "id", (("subq:source", "id"),)),
        ("matched", "event_type", (("subq:source", "event_type"),)),
        ("matched", "account_key", (("subq:source", "account_key"),)),
        ("not_matched", "id", (("subq:source", "id"),)),
        ("not_matched", "event_type", (("subq:source", "event_type"),)),
        ("not_matched", "account_key", (("subq:source", "account_key"),)),
    ]

    assert result.source_tables == ["dim.accounts", "ods.events"]
    assert result.diagnostics.warnings == []
    assert result.diagnostics.lineage_fact_gaps == []


def test_cte_projection_and_correlated_target_ref_do_not_contaminate_each_other() -> None:
    """The two mechanisms have to coexist: one CTE field, one correlated target field."""
    result = parse_scope_lineage(
        """
        WITH staged AS (SELECT e.id, e.event_type FROM ods.events e)
        MERGE INTO mart.event_target target
        USING (SELECT id, event_type FROM staged) source
        ON target.id = source.id
        WHEN MATCHED THEN UPDATE SET
          target.event_type = source.event_type,
          target.account_key = (
            SELECT MAX(lookup.name) FROM dim.lookup lookup WHERE lookup.id = target.id
          )
        """,
        "merge_cte_and_correlated_scalar",
        schema={
            "ods.events": ["id", "event_type"],
            "dim.lookup": ["id", "name"],
            "mart.event_target": ["id", "event_type", "account_key"],
        },
    )

    assert [
        (column.name, column.expression) for column in result.scopes["cte:staged"].columns
    ] == [("id", "`e`.`id`"), ("event_type", "`e`.`event_type`")]

    root_columns = result.scopes["ROOT"].columns
    assert [column.name for column in root_columns] == ["event_type", "account_key"]
    assert [
        (source.scope, source.column) for source in root_columns[0].sources
    ] == [("subq:source", "event_type")]
    assert [
        (source.scope, source.column) for source in root_columns[1].sources
    ] == [("subq:derived_0", "name")]

    assert result.scopes["subq:derived_0"].raw_sql.endswith("`lookup`.`id` = target.id")
    assert result.source_tables == ["dim.lookup", "mart.event_target", "ods.events"]
    assert result.diagnostics.warnings == []
    assert result.diagnostics.lineage_fact_gaps == []


def test_repeated_target_refs_are_all_restored_without_touching_sql_literals() -> None:
    result = parse_scope_lineage(
        """
        MERGE INTO mart.event_target target
        USING (SELECT id, event_type FROM ods.events) source
        ON target.id = source.id
        WHEN MATCHED THEN UPDATE SET
          target.account_key = (
            SELECT MAX(lookup.name) FROM dim.lookup lookup
            WHERE (lookup.id = target.id OR lookup.parent_id = target.id)
              AND lookup.kind = 'literal_value'
          )
        """,
        "merge_repeated_target_refs",
        schema={
            "ods.events": ["id", "event_type"],
            "dim.lookup": ["id", "parent_id", "name", "kind"],
            "mart.event_target": ["id", "event_type", "account_key"],
        },
    )

    scalar_scope = result.scopes["subq:derived_0"]
    assert scalar_scope.raw_sql == (
        "SELECT MAX(`lookup`.`name`) AS `_col_0` FROM `dim`.`lookup` AS `lookup` "
        "WHERE (`lookup`.`id` = target.id OR `lookup`.`parent_id` = target.id) "
        "AND `lookup`.`kind` = 'literal_value'"
    )
    assert "__scope_lineage" not in scalar_scope.raw_sql
    assert [
        (source.scope, source.column) for source in scalar_scope.filters[0].columns
    ] == [
        ("dim.lookup", "kind"),
        ("dim.lookup", "id"),
        ("mart.event_target", "id"),
        ("dim.lookup", "parent_id"),
    ]


def test_a_target_ref_outside_a_merge_action_is_left_unresolved() -> None:
    """``target.x`` in USING is out of scope, not correlated, so it is not protected.

    Protecting it would turn an author error into lineage that looks proven: the target
    table would appear as a real input of the source query. It stays as sqlglot left it
    and never binds to the target.

    (What it leaves behind — a filter reference to a column the schema does not list —
    is reported by neither a warning nor a fact gap today. That silence predates this
    fix and needs a schema audit over filter columns, not a change here.)
    """
    result = parse_scope_lineage(
        """
        MERGE INTO mart.event_target target
        USING (SELECT id, event_type FROM ods.events WHERE id = target.id) source
        ON target.id = source.id
        WHEN MATCHED THEN UPDATE SET target.event_type = source.event_type
        """,
        "merge_target_ref_in_using",
        schema={
            "ods.events": ["id", "event_type"],
            "mart.event_target": ["id", "event_type"],
        },
    )

    assert result.source_tables == ["ods.events"]
    assert [
        (source.scope, source.column)
        for source in result.scopes["subq:source"].filters[0].columns
    ] == [("ods.events", "id"), ("ods.events", "target")]


@pytest.mark.parametrize(
    ("sabotage", "expected_hits"),
    [("drop", 0), ("duplicate", 2)],
)
def test_an_unrestorable_target_ref_fails_instead_of_publishing_a_guess(
    monkeypatch: pytest.MonkeyPatch,
    sabotage: str,
    expected_hits: int,
) -> None:
    original = scope_builder._qualify_ast

    def broken_qualify(ast):
        qualified = original(ast)
        for literal in list(qualified.find_all(exp.Literal)):
            if not literal.is_string or "__scope_lineage_merge_target_ref" not in str(
                literal.this
            ):
                continue
            if sabotage == "drop":
                literal.replace(exp.Literal.string("dropped"))
            else:
                literal.replace(
                    exp.Or(this=literal.copy(), expression=literal.copy())
                )
        return qualified

    monkeypatch.setattr(scope_builder, "_qualify_ast", broken_qualify)

    with pytest.raises(
        ValueError,
        match=(
            "MERGE target reference could not be restored after qualify: "
            f"sentinel found {expected_hits} times, expected exactly 1"
        ),
    ):
        parse_scope_lineage(
            """
            MERGE INTO mart.target target
            USING (SELECT id, name FROM ods.source) source
            ON target.id = source.id
            WHEN MATCHED THEN UPDATE SET target.name = (
              SELECT MAX(lookup.name) FROM dim.lookup lookup WHERE lookup.id = target.id
            )
            """,
            "merge_unrestorable_target_ref",
            schema=SCHEMA,
        )


def test_a_failed_merge_restore_is_reported_as_a_failed_statement_not_empty_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Script-level callers must see ``failed``, never a statement with no lineage."""
    original = scope_builder._qualify_ast

    def broken_qualify(ast):
        qualified = original(ast)
        for literal in list(qualified.find_all(exp.Literal)):
            if literal.is_string and "__scope_lineage_merge_target_ref" in str(literal.this):
                literal.replace(exp.Literal.string("dropped"))
        return qualified

    monkeypatch.setattr(scope_builder, "_qualify_ast", broken_qualify)

    results = scope_builder.parse_all_scope_lineage(
        """
        MERGE INTO mart.target target
        USING (SELECT id, name FROM ods.source) source
        ON target.id = source.id
        WHEN MATCHED THEN UPDATE SET target.name = (
          SELECT MAX(lookup.name) FROM dim.lookup lookup WHERE lookup.id = target.id
        )
        """,
        "merge_unrestorable_target_ref_script",
        schema=SCHEMA,
    )

    assert [result.parse_status for result in results] == ["failed"]


def test_merge_with_a_cte_source_traces_every_branch_to_physical_roots() -> None:
    result = parse_scope_lineage(
        CTE_MERGE_SQL,
        "merge_with_cte_source",
        schema=CTE_MERGE_SCHEMA,
    )

    assert [
        (
            item["merge_branch"],
            item["column"],
            item["trace_complete"],
            tuple((source["table"], source["column"]) for source in item["physical_sources"]),
        )
        for item in build_end_to_end_lineage(result)
    ] == [
        ("matched", "id", True, (("ods.events", "id"),)),
        ("matched", "event_type", True, (("ods.events", "event_type"),)),
        ("matched", "account_key", True, (("dim.accounts", "account_key"),)),
        ("not_matched", "id", True, (("ods.events", "id"),)),
        ("not_matched", "event_type", True, (("ods.events", "event_type"),)),
        ("not_matched", "account_key", True, (("dim.accounts", "account_key"),)),
    ]
