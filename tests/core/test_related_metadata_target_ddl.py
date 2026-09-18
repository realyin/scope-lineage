"""Target DDL metadata reaches ``related_metadata.output_tables``.

The target table's own column comments are the first source of field semantics, and they
were the one metadata fact the contract dropped: ``_output_table_metadata`` consulted only
the ``--schema`` map, so a run given ``--target-ddl-metadata`` still published
``comment: null`` for every output column and ``metadata_complete: false`` -- a document
that reads like "nobody supplied metadata" for a run that did.

The fallback is a fallback, not a merge: ``--schema`` stays authoritative when it knows the
target, because two descriptions of one table must not be interleaved (the same argument
METADATA-001 settled for DDL versus schema array). ``metadata_source`` says which of the
two answered, so a consumer never has to guess where a comment came from.
"""

from __future__ import annotations

from scope_lineage.metadata.target_table_metadata import (
    TargetColumnMetadata,
    TargetMetadataMap,
    TargetTableMetadata,
)
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.scope.task_lineage import parse_task_lineage


SOURCE_SCHEMA = {"ods.customer": ["customer_id", "level"]}
SQL = (
    "INSERT OVERWRITE TABLE mart.profile PARTITION(dt='20260801') "
    "SELECT c.customer_id AS wrong_a, c.level AS wrong_b FROM ods.customer c"
)
MERGE_SQL = (
    "MERGE INTO mart.profile t USING ods.customer s ON t.customer_id = s.customer_id "
    "WHEN NOT MATCHED THEN INSERT *"
)


def _target_metadata(
    *,
    level_comment: str = "Derived customer level",
    level_type: str = "string",
) -> TargetMetadataMap:
    item = TargetTableMetadata(
        table_name="mart.profile",
        full_table_name="spark_catalog.mart.profile",
        columns=[
            TargetColumnMetadata("customer_id", "bigint", 0, False, "Customer identifier"),
            TargetColumnMetadata("customer_level", level_type, 1, False, level_comment),
            TargetColumnMetadata("dt", "string", 2, True, "Partition date"),
        ],
        partition_columns=["dt"],
        ddl="CREATE TABLE mart.profile(customer_id BIGINT, customer_level STRING, dt STRING)",
        source_file="profile_metadata.json",
        structure_source="ddl",
    )
    return TargetMetadataMap({item.table_name: item})


def _output_table(schema=None, target_metadata=None, sql: str = SQL) -> dict:
    result = parse_scope_lineage(
        sql,
        "related_metadata_target_ddl",
        schema=schema if schema is not None else dict(SOURCE_SCHEMA),
        target_metadata=target_metadata,
    )
    return result.related_metadata["output_tables"]["mart.profile"]


def test_target_ddl_supplies_output_column_types_and_comments() -> None:
    item = _output_table(target_metadata=_target_metadata())

    assert item["column_details"] == [
        {"name": "customer_id", "type": "bigint", "comment": "Customer identifier"},
        {"name": "customer_level", "type": "string", "comment": "Derived customer level"},
    ]
    assert item["metadata_complete"] is True
    assert item["metadata_source"] == "target_ddl"


def test_only_columns_the_statement_writes_are_kept() -> None:
    """The static partition column is in the DDL but not in the projection.

    The schema path already answers "which columns does this write produce" rather than
    "what does the table contain"; the fallback must not widen that answer.
    """
    item = _output_table(target_metadata=_target_metadata())

    assert [column["name"] for column in item["column_details"]] == [
        "customer_id",
        "customer_level",
    ]


def test_table_level_target_metadata_travels_with_the_output_table() -> None:
    item = _output_table(target_metadata=_target_metadata())

    assert item["table_metadata"] == {
        "full_table_name": "spark_catalog.mart.profile",
        "source_file": "profile_metadata.json",
        "structure_source": "ddl",
    }


def test_schema_wins_when_it_knows_the_target_table() -> None:
    schema = {**SOURCE_SCHEMA, "mart.profile": ["customer_id", "customer_level"]}

    item = _output_table(schema=schema, target_metadata=_target_metadata())

    # The schema map carries no comments here, and that is the point: the answer comes
    # from one source, not from whichever source happened to have a value.
    assert item["column_details"] == [
        {"name": "customer_id", "type": None, "comment": None},
        {"name": "customer_level", "type": None, "comment": None},
    ]
    assert item["metadata_complete"] is True
    assert item["metadata_source"] == "schema"
    assert "table_metadata" not in item


def test_no_metadata_at_all_is_unchanged_and_says_nothing_about_its_source() -> None:
    item = _output_table()

    assert item["column_details"] == [
        {"name": "wrong_a", "type": None, "comment": None},
        {"name": "wrong_b", "type": None, "comment": None},
    ]
    assert item["metadata_complete"] is False
    assert "metadata_source" not in item
    assert "table_metadata" not in item


def test_blank_ddl_comment_and_type_are_published_as_null_not_empty_string() -> None:
    item = _output_table(
        target_metadata=_target_metadata(level_comment="", level_type=""),
    )

    assert item["column_details"][1] == {
        "name": "customer_level",
        "type": None,
        "comment": None,
    }
    assert item["metadata_complete"] is True
    assert item["metadata_source"] == "target_ddl"


def test_merge_output_table_also_gets_the_target_ddl_fallback() -> None:
    """MERGE keeps its target metadata out of the binding pass, not out of the document."""
    item = _output_table(
        schema={"ods.customer": ["customer_id", "customer_level"]},
        target_metadata=_target_metadata(),
        sql=MERGE_SQL,
    )

    assert {column["name"]: column["comment"] for column in item["column_details"]} == {
        "customer_id": "Customer identifier",
        "customer_level": "Derived customer level",
        "dt": "Partition date",
    }
    assert item["metadata_source"] == "target_ddl"


def test_task_contract_statement_entry_carries_the_target_comments() -> None:
    task = parse_task_lineage(
        SQL,
        task_name="related_metadata_target_ddl_task",
        schema=dict(SOURCE_SCHEMA),
        target_metadata=_target_metadata(),
    )

    entries = list(task.statement_lineage.values())
    assert len(entries) == 1
    output_table = entries[0]["related_metadata"]["output_tables"]["mart.profile"]
    assert output_table["metadata_source"] == "target_ddl"
    assert [column["comment"] for column in output_table["column_details"]] == [
        "Customer identifier",
        "Derived customer level",
    ]
