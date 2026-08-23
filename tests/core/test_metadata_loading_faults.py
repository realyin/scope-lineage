"""Which description of a table wins, and what one unusable file may cost.

A table's authoritative metadata carries two descriptions of its columns: the DDL and an
exported column array. They are not two claims to be checked against each other — the DDL
is the stronger one, and a partition column declared only in ``PARTITIONED BY`` is an
ordinary shape, not a contradiction. Treating the difference as a validation failure
rejected usable metadata, and one bad file aborted the whole load, which is what drives
operators to build their own metadata workarounds.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.metadata.schema_metadata import (
    MetadataFileError,
    load_schema_sources,
)


def _write(directory: Path, name: str, document: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}_metadata.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def _column(name: str, index: int, *, partition: int = 0) -> dict:
    return {
        "columnName": name,
        "columnType": "string",
        "columnComment": f"{name} 注释",
        "columnIndex": index,
        "isPartition": partition,
    }


def _healthy(name: str = "ods.healthy") -> dict:
    return {
        "table_name": name,
        "schema": [_column("id", 0), _column("v", 1)],
        "ddl": f"CREATE TABLE {name} (id string, v string) USING iceberg",
    }


def _partition_only_in_ddl(name: str = "ods.partitioned") -> dict:
    """The shape that used to abort the load: dt is in the DDL, not in the array."""
    return {
        "table_name": name,
        "schema": [_column("id", 0), _column("v", 1)],
        "ddl": f"CREATE TABLE {name} (id string, v string) USING iceberg PARTITIONED BY (dt)",
    }


def test_a_partition_column_declared_only_in_the_ddl_is_not_a_contradiction(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "ods.partitioned", _partition_only_in_ddl())

    schema = load_schema_sources([tmp_path])

    # The DDL is the stronger description, so its column set is the answer — dt included.
    assert schema["ods.partitioned"] == ["id", "v", "dt"]
    # Nothing was wrong here, so nothing is reported.
    assert schema.metadata_conflicts == []


def test_the_ddl_wins_over_the_column_array_rather_than_merging_with_it(
    tmp_path: Path,
) -> None:
    """A union would mean neither source is authoritative.

    The array names a column the DDL does not have. Keeping it would publish a column the
    table's own definition says is not there.
    """
    _write(
        tmp_path,
        "ods.stale_export",
        {
            "table_name": "ods.stale_export",
            "schema": [_column("id", 0), _column("dropped_col", 1)],
            "ddl": "CREATE TABLE ods.stale_export (id string) USING iceberg",
        },
    )

    schema = load_schema_sources([tmp_path])

    assert schema["ods.stale_export"] == ["id"]


def test_the_column_array_is_used_when_the_ddl_is_absent(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "ods.no_ddl",
        {"table_name": "ods.no_ddl", "schema": [_column("id", 0), _column("v", 1)]},
    )

    schema = load_schema_sources([tmp_path])

    assert schema["ods.no_ddl"] == ["id", "v"]


def test_an_unusable_file_costs_only_its_own_table(tmp_path: Path) -> None:
    """One table's metadata being unreadable must not blank out every other table.

    This is the failure that made a metadata directory unusable because one file in it
    was malformed.
    """
    _write(tmp_path, "ods.healthy", _healthy())
    _write(tmp_path, "ods.broken", {"table_name": "ods.broken", "schema": []})

    schema = load_schema_sources([tmp_path])

    assert schema["ods.healthy"] == ["id", "v"]
    assert "ods.broken" not in schema
    # The rejected table is reported rather than silently absent: "no metadata supplied"
    # and "metadata supplied but unusable" are different problems for an operator.
    assert [item.get("table") for item in schema.metadata_conflicts] == ["ods.broken"]


def test_a_load_that_produced_nothing_at_all_raises(tmp_path: Path) -> None:
    """Partial success is normal; producing no table at all is not.

    An empty schema returned quietly is indistinguishable from "these tables have no
    metadata", so the one case that must still raise is the one where nothing loaded.
    """
    path = _write(tmp_path, "ods.broken", {"table_name": "ods.broken", "schema": []})

    with pytest.raises(MetadataFileError):
        load_schema_sources([path])


def test_a_named_file_list_tolerates_one_unusable_member(tmp_path: Path) -> None:
    """On-demand loading passes a computed list of paths, not a directory.

    A rule that raised for explicitly named files would reinstate the original failure
    there: one unusable file among the fifty a task needs would leave the task with
    nothing.
    """
    healthy = _write(tmp_path / "a", "ods.healthy", _healthy())
    broken = _write(tmp_path / "b", "ods.broken", {"table_name": "ods.broken", "schema": []})

    schema = load_schema_sources([healthy, broken])

    assert schema["ods.healthy"] == ["id", "v"]
    assert [item.get("source_file") for item in schema.metadata_conflicts] == [
        "ods.broken_metadata.json"
    ]
