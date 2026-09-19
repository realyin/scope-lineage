"""End-to-end tests for ``scope-lineage glossary``.

The library is not done until the CLI that exposes it is wired and tested. ``glossary``
walks a corpus the way ``describe`` and ``tables`` do, so the same inputs are exercised
here -- one file, a tree, an unsupported document in the middle of a tree -- plus the
two things only this command has: ``--overrides`` and the counts its run summary prints.
"""

from __future__ import annotations

import json
from pathlib import Path

from scope_lineage.cli import main
from scope_lineage.scope.scope_builder import parse_scope_lineage

from .statement_document import write_statement_documents


PAID_SQL = (
    "INSERT INTO mart.orders SELECT o.order_id, o.pay_status FROM ods.app_order o "
    "WHERE o.pay_status = 'PAID'"
)
PAID_SCHEMA = {"ods.app_order": ["order_id", "pay_status"]}


def _write_artifacts(sql: str, out_dir: Path, schema=None) -> Path:
    write_statement_documents(parse_scope_lineage(sql, out_dir.name, schema=schema), out_dir)
    return out_dir


def _glossary(out_dir: Path) -> dict:
    return json.loads((out_dir / "glossary.json").read_text(encoding="utf-8"))


def test_glossary_writes_both_artifacts_into_out(tmp_path: Path, capsys) -> None:
    task = _write_artifacts(PAID_SQL, tmp_path / "task_a", schema=PAID_SCHEMA)
    out = tmp_path / "dict"

    assert main(["glossary", "--lineage", str(task / "lineage.json"), "--out", str(out)]) == 0

    glossary = _glossary(out)
    assert glossary["doc_format"] == "glossary-json/1"
    assert glossary["corpus"]["task_count"] == 1
    assert [item["value"] for item in glossary["values"]] == ["PAID"]
    assert [item["sql_literal"] for item in glossary["values"]] == ["'PAID'"]
    assert (out / "glossary.md").read_text(encoding="utf-8").startswith("# 术语与值域字典")
    assert "Collected" in capsys.readouterr().out


def test_glossary_json_is_indented_and_newline_terminated(tmp_path: Path) -> None:
    task = _write_artifacts(PAID_SQL, tmp_path / "task_a", schema=PAID_SCHEMA)
    out = tmp_path / "dict"
    assert main(["glossary", "--lineage", str(task / "lineage.json"), "--out", str(out)]) == 0

    raw = (out / "glossary.json").read_text(encoding="utf-8")
    assert raw.startswith('{\n  "doc_format"')
    assert raw.endswith("\n")
    assert "\\u" not in raw


def test_glossary_recurses_a_corpus_and_counts_what_it_skipped(
    tmp_path: Path, capsys
) -> None:
    corpus = tmp_path / "corpus"
    _write_artifacts(PAID_SQL, corpus / "nested" / "task_a", schema=PAID_SCHEMA)
    _write_artifacts(
        "INSERT INTO mart.web SELECT w.order_id, w.pay_status FROM ods.web_order w "
        "WHERE w.pay_status = 'PAID'",
        corpus / "task_b",
        schema={"ods.web_order": ["order_id", "pay_status"]},
    )
    unknown = corpus / "task_unknown"
    unknown.mkdir(parents=True)
    (unknown / "lineage.json").write_text(json.dumps({"schema_version": "9.9"}), encoding="utf-8")
    out = tmp_path / "dict"

    assert main(["glossary", "--lineage", str(corpus), "--out", str(out)]) == 0

    printed = capsys.readouterr().out
    assert "skipped_unknown_version=1" in printed
    glossary = _glossary(out)
    assert glossary["corpus"]["task_count"] == 2
    # Two tables, so two entries: the dictionary merges by column NAME in `terms`, and
    # keeps values per column reference -- `'PAID'` on web_order is its own observation.
    assert [item["column_ref"] for item in glossary["values"]] == [
        "ods.app_order.pay_status",
        "ods.web_order.pay_status",
    ]
    assert {item["column"] for item in glossary["values"]} == {"pay_status"}


def test_glossary_reports_a_root_with_no_lineage_documents(tmp_path: Path, capsys) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["glossary", "--lineage", str(empty), "--out", str(tmp_path / "dict")]) == 1
    assert "no lineage.json found" in capsys.readouterr().err


def test_glossary_reports_a_missing_lineage_path(tmp_path: Path, capsys) -> None:
    assert main(
        ["glossary", "--lineage", str(tmp_path / "gone"), "--out", str(tmp_path / "dict")]
    ) == 2
    assert "--lineage path does not exist" in capsys.readouterr().err


def test_overrides_are_applied_and_unmatched_keys_reported(tmp_path: Path, capsys) -> None:
    task = _write_artifacts(PAID_SQL, tmp_path / "task_a", schema=PAID_SCHEMA)
    overrides = tmp_path / "glossary.overrides.json"
    overrides.write_text(
        json.dumps(
            {
                "terms": {"pay_status": {"meaning": "支付状态", "confirmed_by": "owner"}},
                "values": {
                    "pay_status='PAID'": {"meaning": "已支付", "date": "2026-09-18"},
                    "pay_status='NOPE'": {"meaning": "never seen"},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out = tmp_path / "dict"

    assert main(
        [
            "glossary",
            "--lineage",
            str(task / "lineage.json"),
            "--out",
            str(out),
            "--overrides",
            str(overrides),
        ]
    ) == 0

    glossary = _glossary(out)
    assert glossary["values"][0]["meaning"]["text"] == "已支付"
    assert glossary["overrides_applied"]["unmatched"] == ["pay_status='NOPE'"]
    assert "unmatched=1" in capsys.readouterr().out


def test_a_missing_overrides_file_is_an_error_not_a_silent_skip(
    tmp_path: Path, capsys
) -> None:
    task = _write_artifacts(PAID_SQL, tmp_path / "task_a", schema=PAID_SCHEMA)
    assert main(
        [
            "glossary",
            "--lineage",
            str(task / "lineage.json"),
            "--out",
            str(tmp_path / "dict"),
            "--overrides",
            str(tmp_path / "gone.json"),
        ]
    ) == 2
    assert "--overrides file does not exist" in capsys.readouterr().err


def test_a_malformed_overrides_file_names_the_file(tmp_path: Path, capsys) -> None:
    task = _write_artifacts(PAID_SQL, tmp_path / "task_a", schema=PAID_SCHEMA)
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert main(
        [
            "glossary",
            "--lineage",
            str(task / "lineage.json"),
            "--out",
            str(tmp_path / "dict"),
            "--overrides",
            str(broken),
        ]
    ) == 2
    assert "not valid JSON" in capsys.readouterr().err


def test_format_json_writes_no_markdown(tmp_path: Path) -> None:
    task = _write_artifacts(PAID_SQL, tmp_path / "task_a", schema=PAID_SCHEMA)
    out = tmp_path / "dict"
    assert main(
        [
            "glossary",
            "--lineage",
            str(task / "lineage.json"),
            "--out",
            str(out),
            "--format",
            "json",
        ]
    ) == 0
    assert (out / "glossary.json").is_file()
    assert not (out / "glossary.md").exists()


def test_an_unknown_format_is_a_usage_error(tmp_path: Path) -> None:
    task = _write_artifacts(PAID_SQL, tmp_path / "task_a", schema=PAID_SCHEMA)
    try:
        main(
            [
                "glossary",
                "--lineage",
                str(task / "lineage.json"),
                "--out",
                str(tmp_path / "dict"),
                "--format",
                "yaml",
            ]
        )
    except SystemExit as exit_code:
        assert exit_code.code == 2
    else:  # pragma: no cover - the parser must reject it
        raise AssertionError("--format yaml was accepted")
