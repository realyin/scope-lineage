"""CLI `scope-lineage validate`: schema + referential + invariant checks in one pass.

The command exists so a corpus produced earlier (or by an older version) can be
audited from disk — the architecture sweep only guards documents this tree produces.
"""

from __future__ import annotations

import json

from scope_lineage.cli import main


def _write_corpus(tmp_path, sql: str = "INSERT INTO mart.t SELECT id FROM ods.source"):
    sql_path = tmp_path / "demo.sql"
    sql_path.write_text(sql, encoding="utf-8")
    output = tmp_path / "corpus"
    assert main(["parse", "--sql-file", str(sql_path), "--out", str(output)]) == 0
    return output


def test_validate_passes_a_clean_corpus(tmp_path, capsys) -> None:
    output = _write_corpus(tmp_path)
    assert main(["validate", "--lineage", str(output)]) == 0
    out = capsys.readouterr().out
    assert "Validated 1 document(s): OK" in out


def test_validate_accepts_a_single_file(tmp_path) -> None:
    output = _write_corpus(tmp_path)
    lineage_path = next(output.rglob("lineage.json"))
    assert main(["validate", "--lineage", str(lineage_path)]) == 0


def test_validate_reports_invariant_violations_and_fails(tmp_path, capsys) -> None:
    output = _write_corpus(tmp_path)
    lineage_path = next(output.rglob("lineage.json"))
    document = json.loads(lineage_path.read_text(encoding="utf-8"))
    nested = next(iter(document["statement_lineage"].values()))
    nested["field_mapping_chains"][0]["root_source_fields"] = ["AMBIGUOUS.id"]
    lineage_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    assert main(["validate", "--lineage", str(output)]) == 1
    captured = capsys.readouterr()
    assert "AMBIGUOUS root" in captured.out
    assert "violation(s)" in captured.out


def test_validate_reports_schema_violations_and_fails(tmp_path, capsys) -> None:
    output = _write_corpus(tmp_path)
    lineage_path = next(output.rglob("lineage.json"))
    document = json.loads(lineage_path.read_text(encoding="utf-8"))
    del document["statement_sequence"]
    lineage_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    assert main(["validate", "--lineage", str(output)]) == 1
    assert "schema:" in capsys.readouterr().out


def test_validate_errors_on_missing_path(tmp_path) -> None:
    assert main(["validate", "--lineage", str(tmp_path / "nope")]) == 2
