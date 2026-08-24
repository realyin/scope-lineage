"""Pre-parse metadata coverage check and the batch metadata-gap manifest.

Twice in a row an incomplete schema quietly produced AMBIGUOUS artifacts and the
investigation started from the wrong end (a suspected parser defect, a suspected
SQL problem) instead of from the missing tables. The preflight makes the gap the
FIRST thing a run says: `parse --metadata-preflight` reports every referenced table
absent from the supplied schema, writes the machine-readable manifest, produces no
artifacts, and exits non-zero when gaps exist — so `preflight && parse` naturally
stops for a human decision. A normal batch parse writes the same manifest alongside
its artifacts whenever gaps exist. Both aggregate the per-task
`diagnostics.metadata_coverage` fact; nothing re-derives coverage a second way.
"""

from __future__ import annotations

import json

from scope_lineage.cli import main


def _write_inputs(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "task_a.json").write_text(
        json.dumps({
            "meta": {
                "task_name": "task_a",
                "sql": "INSERT INTO mart.a SELECT s.id, u.name FROM ods.known_src s JOIN ods.missing_dim u ON s.id = u.id",
            }
        }),
        encoding="utf-8",
    )
    (tasks / "task_b.json").write_text(
        json.dumps({
            "meta": {
                "task_name": "task_b",
                "sql": "INSERT INTO mart.b SELECT u.id FROM ods.missing_dim u",
            }
        }),
        encoding="utf-8",
    )
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(
        json.dumps({
            "ods.known_src": ["id"],
            "mart.a": ["id", "name"],
            "mart.b": ["id"],
        }),
        encoding="utf-8",
    )
    return tasks, schema_path


def test_preflight_reports_gaps_writes_manifest_and_no_artifacts(tmp_path, capsys) -> None:
    tasks, schema_path = _write_inputs(tmp_path)
    out = tmp_path / "out"

    code = main([
        "parse", "--input-dir", str(tasks), "--out", str(out),
        "--schema", str(schema_path), "--metadata-preflight",
    ])
    assert code == 1

    manifest = json.loads((out / "metadata_gaps.json").read_text(encoding="utf-8"))
    missing = {item["table"]: item for item in manifest["missing_tables"]}
    assert "ods.missing_dim" in missing
    assert missing["ods.missing_dim"]["referenced_by"] == ["task_a", "task_b"]
    assert manifest["missing_table_count"] == len(manifest["missing_tables"])

    # no lineage artifacts: the manifest is the only thing the preflight writes
    written = sorted(p.name for p in out.rglob("*") if p.is_file())
    assert written == ["metadata_gaps.json"]

    stdout = capsys.readouterr().out
    assert "ods.missing_dim" in stdout
    assert "Metadata preflight" in stdout


def test_preflight_clean_run_exits_zero(tmp_path, capsys) -> None:
    tasks, schema_path = _write_inputs(tmp_path)
    full_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    full_schema["ods.missing_dim"] = ["id", "name"]
    schema_path.write_text(json.dumps(full_schema), encoding="utf-8")
    out = tmp_path / "out"

    code = main([
        "parse", "--input-dir", str(tasks), "--out", str(out),
        "--schema", str(schema_path), "--metadata-preflight",
    ])
    assert code == 0
    manifest = json.loads((out / "metadata_gaps.json").read_text(encoding="utf-8"))
    assert manifest["missing_tables"] == []
    assert not any(p.name == "lineage.json" for p in out.rglob("*"))
    assert "0 missing" in capsys.readouterr().out


def test_batch_parse_with_gaps_writes_manifest_next_to_artifacts(tmp_path, capsys) -> None:
    tasks, schema_path = _write_inputs(tmp_path)
    out = tmp_path / "out"

    code = main([
        "parse", "--input-dir", str(tasks), "--out", str(out),
        "--schema", str(schema_path),
    ])
    assert code == 0

    assert any(p.name == "lineage.json" for p in out.rglob("*"))
    manifest = json.loads((out / "metadata_gaps.json").read_text(encoding="utf-8"))
    assert any(item["table"] == "ods.missing_dim" for item in manifest["missing_tables"])
    assert "metadata_gaps.json" in capsys.readouterr().out


def test_batch_parse_without_gaps_writes_no_manifest(tmp_path) -> None:
    tasks, schema_path = _write_inputs(tmp_path)
    full_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    full_schema["ods.missing_dim"] = ["id", "name"]
    schema_path.write_text(json.dumps(full_schema), encoding="utf-8")
    out = tmp_path / "out"

    code = main([
        "parse", "--input-dir", str(tasks), "--out", str(out),
        "--schema", str(schema_path),
    ])
    assert code == 0
    assert not (out / "metadata_gaps.json").exists()


def test_manifest_is_deterministic(tmp_path) -> None:
    tasks, schema_path = _write_inputs(tmp_path)
    contents = []
    for run in ("first", "second"):
        out = tmp_path / run
        main([
            "parse", "--input-dir", str(tasks), "--out", str(out),
            "--schema", str(schema_path), "--metadata-preflight",
        ])
        contents.append((out / "metadata_gaps.json").read_bytes())
    assert contents[0] == contents[1]
