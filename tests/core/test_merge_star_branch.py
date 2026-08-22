"""MERGE's `*` branches write the target's columns, not the source's.

Spark expands `INSERT *` and `UPDATE SET *` over `targetTable.output`: every target
column, in target order, each pulled from the source by name. Core walked the USING
side instead and published the *source's* names as though they were target columns, so
a source column the target does not have came out as a column of the target. The
`UPDATE SET *` form had no branch at all and silently produced nothing.

Both need the target's column list, which the MERGE path never received. It is handed
straight to column resolution rather than through `apply_target_field_binding`: that
pass runs before MERGE's ROOT columns exist, so routing it there would bind against an
empty projection and turn every MERGE into a count-mismatch fallback.
"""
from __future__ import annotations

from scope_lineage.metadata.target_table_metadata import (
    TargetColumnMetadata,
    TargetMetadataMap,
    TargetTableMetadata,
)
from scope_lineage.scope.scope_builder import parse_scope_lineage

# Source names `amt`; the target calls it `amount` and orders its columns differently.
SCHEMA = {"db.s": ["dt", "amt", "id"], "db.t": ["id", "amount", "dt"]}


def _target_metadata(columns=("id", "amount", "dt")) -> TargetMetadataMap:
    metadata = TargetMetadataMap()
    metadata["db.t"] = TargetTableMetadata(
        table_name="t",
        full_table_name="db.t",
        columns=[
            TargetColumnMetadata(name=name, data_type="string", ordinal=i,
                                 is_partition=False, comment="")
            for i, name in enumerate(columns)
        ],
        partition_columns=[], ddl="", source_file="x", validation_issues=[],
        query_time=None, ddl_update_time=None, data_source="test",
        structure_source="ddl",
    )
    return metadata


def _root(sql: str, *, schema=None, target_metadata=None):
    return parse_scope_lineage(
        sql, task_name="t",
        schema=SCHEMA if schema is None else schema,
        target_metadata=target_metadata,
    )


INSERT_STAR = (
    "MERGE INTO db.t USING db.s s ON db.t.id = s.id WHEN NOT MATCHED THEN INSERT *"
)
UPDATE_STAR = (
    "MERGE INTO db.t USING db.s s ON db.t.id = s.id WHEN MATCHED THEN UPDATE SET *"
)


# --- drivers: must fail before the fix -------------------------------------------

def test_insert_star_writes_the_target_columns_in_target_order():
    result = _root(INSERT_STAR, target_metadata=_target_metadata())
    assert [c.name for c in result.scopes["ROOT"].columns] == ["id", "amount", "dt"]


def test_a_target_column_the_source_lacks_is_reported_not_invented():
    """`amount` has no counterpart in the source, so Spark fails analysis. The column
    is still the target's, but its source is unresolved and the artifact says why."""
    result = _root(INSERT_STAR, target_metadata=_target_metadata())
    amount = next(c for c in result.scopes["ROOT"].columns if c.name == "amount")
    assert not amount.sources or all(s.scope == "UNKNOWN" for s in amount.sources)
    assert "merge_star_target_column_missing_in_source" in [
        w.type for w in result.diagnostics.warnings
    ]


def test_update_set_star_writes_the_target_columns():
    result = _root(UPDATE_STAR, target_metadata=_target_metadata())
    assert [c.name for c in result.scopes["ROOT"].columns] == ["id", "amount", "dt"]


# --- guards: must pass before AND after -------------------------------------------

def test_an_unknown_source_schema_is_left_alone():
    """The guard that bites: the fix's own condition is satisfied -- a `*` branch with
    target metadata -- but the source's columns are unknown, so we cannot say a target
    column is missing from it. Expanding here would invent columns and blame the user's
    SQL for our own missing metadata. Today's honest `star_not_expanded` must survive.
    """
    result = _root(
        "MERGE INTO db.t USING db.unknown s ON db.t.id = s.id "
        "WHEN NOT MATCHED THEN INSERT *",
        schema={"db.t": ["id", "amount", "dt"]},
        target_metadata=_target_metadata(),
    )
    assert [c.name for c in result.scopes["ROOT"].columns] == ["*"]
    assert "star_not_expanded" in [w.type for w in result.diagnostics.warnings]
    assert "merge_star_target_column_missing_in_source" not in [
        w.type for w in result.diagnostics.warnings
    ]


def test_an_explicit_column_list_is_untouched_and_never_binds():
    """Pins that the fix does not route through apply_target_field_binding: doing so
    would bind against an empty ROOT and make every MERGE a fallback."""
    result = _root(
        "MERGE INTO db.t USING db.s s ON db.t.id = s.id "
        "WHEN NOT MATCHED THEN INSERT (id, amount) VALUES (s.id, s.amt)",
        target_metadata=_target_metadata(),
    )
    assert [c.name for c in result.scopes["ROOT"].columns] == ["id", "amount"]
    assert not result.target_field_binding


def test_a_star_branch_without_target_metadata_is_unchanged():
    result = _root(INSERT_STAR)
    assert [c.name for c in result.scopes["ROOT"].columns] == ["dt", "amt", "id"]
    assert not result.target_field_binding


def test_a_named_update_assignment_is_unaffected():
    result = _root(
        "MERGE INTO db.t USING db.s s ON db.t.id = s.id "
        "WHEN MATCHED THEN UPDATE SET amount = s.amt",
        target_metadata=_target_metadata(),
    )
    assert [c.name for c in result.scopes["ROOT"].columns] == ["amount"]
