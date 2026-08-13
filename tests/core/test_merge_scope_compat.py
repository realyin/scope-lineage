"""Regression coverage for SQLGlot's 30.17 MERGE scope-model change."""

from __future__ import annotations

import pytest

from lineage_parser import parse_scope_lineage
from lineage_parser.scope import scope_builder


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
    assert result.source_tables == ["dim.lookup", "ods.source"]
    assert result.scopes["ROOT"].raw_sql == (
        "(SELECT `source`.`id` AS `id`, `source`.`name` AS `name` "
        "FROM `ods`.`source` AS `source`) AS `source`"
    )
    assert result.scopes["ROOT"].raw_sql_available is True


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
