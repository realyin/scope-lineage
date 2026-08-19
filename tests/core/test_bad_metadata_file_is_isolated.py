"""One unreadable metadata file must cost that file, not every table beside it.

0.1.6 established the rule for source schema: a rejected file is recorded in
`metadata_conflicts` and only a load that produced no table at all raises. Three things kept it
from actually holding (META-ISOLATION-001):

- `load_schema_sources` guards with `except MetadataFileError`, but `load_schema_json` lets a raw
  `json.JSONDecodeError` out, so the guard never fires for the commonest kind of bad file;
- `load_target_table_metadata` raises on the first unreadable file and abandons the directory,
  the rule having never been applied to that path at all;
- a file-level rejection is recorded with `table: ""`, and the serializer keeps only conflicts
  whose table is among the referenced ones -- so the record existed and the artifact never showed
  it.

The third is the one that makes the other two dangerous rather than merely annoying: silence is
indistinguishable from "these tables have no metadata", which is the confusion this project
treats as a defect in its own right.
"""

from __future__ import annotations

import json

import pytest

from scope_lineage import MetadataFileError, load_schema_sources, load_target_table_metadata
from scope_lineage.metadata.schema_metadata import SchemaMap
from scope_lineage.scope.task_lineage import parse_task_lineage


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def _target_document(table):
    return {
        "table_name": table,
        "ddl": f"CREATE TABLE {table} (id BIGINT)",
        "schema": [{"columnName": "id", "columnType": "BIGINT", "columnIndex": 1, "isPartition": 0}],
    }


def test_a_broken_source_schema_file_does_not_cost_the_good_ones(tmp_path):
    good = _write(tmp_path / "good.json", json.dumps({"ods.src": ["id", "v"]}))
    bad = _write(tmp_path / "bad.json", '{"ods.other": ["id"')

    schema = load_schema_sources([str(good), str(bad)])

    assert schema.get("ods.src") == ["id", "v"], "the readable file's table must survive"


def test_the_broken_source_file_is_recorded_rather_than_swallowed(tmp_path):
    good = _write(tmp_path / "good.json", json.dumps({"ods.src": ["id"]}))
    bad = _write(tmp_path / "bad.json", '{"ods.other": ["id"')

    schema = load_schema_sources([str(good), str(bad)])

    assert [c.get("source_file") for c in schema.metadata_conflicts] == ["bad.json"]


def test_a_broken_target_metadata_file_does_not_cost_the_directory(tmp_path):
    _write(tmp_path / "ods.good_metadata.json", json.dumps(_target_document("ods.good")))
    _write(tmp_path / "ods.bad_metadata.json", json.dumps(_target_document("ods.bad"))[:-5])

    metadata = load_target_table_metadata(tmp_path)

    assert "ods.good" in metadata, "the readable file's table must survive"


def test_a_directory_of_only_broken_files_still_raises(tmp_path):
    """The 0.1.6 backstop: nothing loaded is the one case that must not pass quietly."""
    _write(tmp_path / "ods.bad_metadata.json", json.dumps(_target_document("ods.bad"))[:-5])

    with pytest.raises(MetadataFileError) as excinfo:
        load_target_table_metadata(tmp_path)

    assert "ods.bad_metadata.json" in str(excinfo.value), "say which file, not just that one failed"


def test_a_single_named_file_still_raises(tmp_path):
    """Skipping is for a directory. Naming one file and getting nothing back is a silent no-op."""
    bad = _write(tmp_path / "ods.bad_metadata.json", json.dumps(_target_document("ods.bad"))[:-5])

    with pytest.raises(MetadataFileError):
        load_target_table_metadata(bad)


def test_a_rejected_file_reaches_the_artifact(tmp_path):
    """Recorded but filtered out is the same as never recorded, from the reader's side."""
    schema = SchemaMap({"ods.src": ["id", "v"]})
    schema.metadata_conflicts.append({
        "table": "",
        "source_file": "bad.json",
        "reason": "metadata_rejected",
        "issues": ["not valid JSON"],
    })

    result = parse_task_lineage(
        "INSERT INTO mart.t SELECT id, v FROM ods.src", task_name="t", schema=schema
    )

    conflicts = (result.diagnostics.get("metadata_coverage") or {}).get("metadata_conflicts") or []
    assert [c.get("source_file") for c in conflicts] == ["bad.json"]


def test_a_table_scoped_conflict_for_an_unreferenced_table_is_still_filtered(tmp_path):
    """The filter exists for a reason: a conflict about a table this task never reads is noise."""
    schema = SchemaMap({"ods.src": ["id", "v"]})
    schema.metadata_conflicts.append({
        "table": "ods.unrelated",
        "source_file": "other.json",
        "reason": "metadata_rejected",
        "issues": ["column set mismatch"],
    })

    result = parse_task_lineage(
        "INSERT INTO mart.t SELECT id, v FROM ods.src", task_name="t", schema=schema
    )

    conflicts = (result.diagnostics.get("metadata_coverage") or {}).get("metadata_conflicts") or []
    assert conflicts == []
