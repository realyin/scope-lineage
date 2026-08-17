"""A qualifier does not make a column exist.

An unqualified column that no source can supply already produces ``column_not_found``.
The qualified path had no equivalent check, so ``ods.source.no_such_column`` was bound to
the named table and published as a proven physical field — a claim the schema in hand
disproves. These tests pin the symmetric diagnostic.
"""

from __future__ import annotations

from scope_lineage import parse_scope_lineage


SCHEMA = {
    "ods.source": ["id", "value"],
    "mart.target": ["id", "value"],
}


def _warning_types(result) -> list[str]:
    return [warning.type for warning in result.diagnostics.warnings]


def test_a_projection_qualified_by_a_table_that_lacks_the_column_is_reported() -> None:
    result = parse_scope_lineage(
        "INSERT INTO mart.target "
        "SELECT s.no_such_column AS id, s.value FROM ods.source s",
        "qualified_projection",
        schema=SCHEMA,
    )

    assert "column_not_in_table_schema" in _warning_types(result)
    # The author's qualifier is still honoured: the binding says what the SQL says, and
    # the warning says it cannot be true. Rewriting it to UNKNOWN would destroy the
    # evidence that the reference names ods.source.
    assert [
        (source.scope, source.column)
        for source in result.scopes["ROOT"].columns[0].sources
    ] == [("ods.source", "no_such_column")]


def test_a_filter_qualified_by_a_table_that_lacks_the_column_is_reported() -> None:
    result = parse_scope_lineage(
        "INSERT INTO mart.target "
        "SELECT s.id, s.value FROM ods.source s WHERE s.no_such_column = 1",
        "qualified_filter",
        schema=SCHEMA,
    )

    assert "column_not_in_table_schema" in _warning_types(result)


def test_a_join_predicate_qualified_by_a_table_that_lacks_the_column_is_reported() -> None:
    result = parse_scope_lineage(
        "INSERT INTO mart.target SELECT a.id, a.value FROM ods.source a "
        "JOIN ods.source b ON a.no_such_column = b.id",
        "qualified_join",
        schema=SCHEMA,
    )

    assert "column_not_in_table_schema" in _warning_types(result)


def test_an_unqualified_missing_column_keeps_its_existing_diagnostic() -> None:
    result = parse_scope_lineage(
        "INSERT INTO mart.target SELECT id, value FROM ods.source WHERE no_such_column = 1",
        "unqualified_control",
        schema=SCHEMA,
    )

    assert "column_not_found" in _warning_types(result)
    assert "column_not_in_table_schema" not in _warning_types(result)


def test_a_table_without_schema_metadata_is_not_accused_of_missing_columns() -> None:
    """Absence of metadata is not evidence of absence of a column.

    Missing coverage is already reported as a metadata gap; claiming the column does
    not exist would turn "we don't know" into a false statement about the warehouse.
    """
    result = parse_scope_lineage(
        "INSERT INTO mart.target SELECT s.anything AS id, s.other AS value "
        "FROM ods.undocumented s",
        "unknown_schema",
        schema=SCHEMA,
    )

    assert "column_not_in_table_schema" not in _warning_types(result)


def test_a_merge_target_ref_written_inside_using_is_reported() -> None:
    """The out-of-scope MERGE reference that #18 deliberately left unprotected.

    sqlglot rebinds it onto the USING relation's own table, which is how a column named
    ``target`` appears on ods.source. It stayed silent because the reference is qualified.
    """
    result = parse_scope_lineage(
        """
        MERGE INTO mart.target target
        USING (SELECT id, value FROM ods.source WHERE id = target.id) source
        ON target.id = source.id
        WHEN MATCHED THEN UPDATE SET target.value = source.value
        """,
        "merge_target_ref_in_using",
        schema=SCHEMA,
    )

    assert "column_not_in_table_schema" in _warning_types(result)
