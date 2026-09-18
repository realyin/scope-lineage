"""End-to-end tests for ``scope-lineage tables`` and ``describe --tables``.

The library is not done until the CLI that exposes it is wired and tested. ``tables`` is
the first subcommand whose unit of work is the corpus rather than the document, so what it
shares with ``render``/``describe`` (the input walk, the two skip counters, the format
switch) is pinned here beside what is new: the card directory it writes, and the
``describe --tables`` handshake that reads the file back.
"""

from __future__ import annotations

import json
from pathlib import Path

from scope_lineage.cli import main

from .statement_document import write_statement_documents
from scope_lineage.scope.scope_builder import parse_scope_lineage


SCHEMA = {
    "ods.customer_base": ["customer_id", "country_code", "dt"],
    "mart.customer_daily": ["customer_id", "country_code", "dt"],
}

PRODUCER_SQL = (
    "INSERT OVERWRITE TABLE mart.customer_daily PARTITION (dt = '20250101') "
    "SELECT customer_id, country_code FROM ods.customer_base "
    "GROUP BY customer_id, country_code"
)

CONSUMER_SQL = (
    "INSERT OVERWRITE TABLE mart.customer_rollup "
    "SELECT country_code, count(1) AS n FROM mart.customer_daily "
    "WHERE dt = '20250101' GROUP BY country_code"
)


def _corpus(root: Path) -> Path:
    for name, sql in (("producer_task", PRODUCER_SQL), ("consumer_task", CONSUMER_SQL)):
        task_dir = root / name
        write_statement_documents(parse_scope_lineage(sql, name, schema=SCHEMA), task_dir)
    return root


def test_tables_writes_the_index_the_json_and_one_card_per_table(
    tmp_path: Path, capsys
) -> None:
    corpus = _corpus(tmp_path / "corpus")
    out = tmp_path / "out"

    assert main(["tables", "--lineage", str(corpus), "--out", str(out)]) == 0

    cards = json.loads((out / "tables.json").read_text(encoding="utf-8"))
    assert cards["doc_format"] == "tables-json/1"
    assert cards["corpus"]["task_count"] == 2
    assert [item["table"] for item in cards["tables"]] == [
        "mart.customer_daily",
        "mart.customer_rollup",
        "ods.customer_base",
    ]
    assert (out / "tables.md").read_text(encoding="utf-8").startswith("---\n")
    written = sorted(path.name for path in (out / "tables").glob("*.md"))
    assert written == [
        "mart.customer_daily.md",
        "mart.customer_rollup.md",
        "ods.customer_base.md",
    ]
    assert "Carded 3 table(s) from 2 task(s)" in capsys.readouterr().out


def test_tables_json_is_indented_and_newline_terminated(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path / "corpus")
    out = tmp_path / "out"
    assert main(["tables", "--lineage", str(corpus), "--out", str(out)]) == 0

    raw = (out / "tables.json").read_text(encoding="utf-8")

    assert raw.startswith('{\n  "doc_format"')
    assert raw.endswith("\n")
    assert "\\u" not in raw


def test_running_tables_twice_writes_the_same_bytes(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path / "corpus")
    first, second = tmp_path / "first", tmp_path / "second"

    assert main(["tables", "--lineage", str(corpus), "--out", str(first)]) == 0
    assert main(["tables", "--lineage", str(corpus), "--out", str(second)]) == 0

    for name in ("tables.json", "tables.md"):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    assert (first / "tables" / "mart.customer_daily.md").read_bytes() == (
        second / "tables" / "mart.customer_daily.md"
    ).read_bytes()


def test_tables_format_json_writes_no_markdown(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path / "corpus")
    out = tmp_path / "out"

    assert main(
        ["tables", "--lineage", str(corpus), "--out", str(out), "--format", "json"]
    ) == 0

    assert (out / "tables.json").is_file()
    assert not (out / "tables.md").exists()
    assert not (out / "tables").exists()


def test_tables_rejects_an_unknown_format(tmp_path: Path, capsys) -> None:
    corpus = _corpus(tmp_path / "corpus")

    try:
        main(
            [
                "tables",
                "--lineage",
                str(corpus),
                "--out",
                str(tmp_path / "out"),
                "--format",
                "csv",
            ]
        )
    except SystemExit as exit_code:
        assert exit_code.code == 2
    assert "--format accepts json and md" in capsys.readouterr().err


def test_tables_reports_a_missing_lineage_root(tmp_path: Path, capsys) -> None:
    assert (
        main(["tables", "--lineage", str(tmp_path / "nope"), "--out", str(tmp_path / "o")])
        == 2
    )
    assert "--lineage path does not exist" in capsys.readouterr().err


def test_tables_reports_an_empty_lineage_root(tmp_path: Path, capsys) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    assert main(["tables", "--lineage", str(empty), "--out", str(tmp_path / "o")]) == 1
    assert "no lineage.json found" in capsys.readouterr().err


def test_tables_skips_documents_of_an_unknown_version(tmp_path: Path, capsys) -> None:
    corpus = _corpus(tmp_path / "corpus")
    stranger = corpus / "stranger"
    stranger.mkdir()
    (stranger / "lineage.json").write_text(
        json.dumps({"schema_version": "0.9"}), encoding="utf-8"
    )

    assert main(["tables", "--lineage", str(corpus), "--out", str(tmp_path / "out")]) == 0

    assert "skipped_unknown_version=1" in capsys.readouterr().out


# ----------------------------------------------------------------- describe --tables


def _cards(tmp_path: Path) -> tuple[Path, Path]:
    corpus = _corpus(tmp_path / "corpus")
    out = tmp_path / "cards"
    assert main(["tables", "--lineage", str(corpus), "--out", str(out)]) == 0
    return corpus, out / "tables.json"


def test_describe_with_tables_carries_the_upstream_card_into_the_profile(
    tmp_path: Path,
) -> None:
    corpus, cards = _cards(tmp_path)

    assert (
        main(
            [
                "describe",
                "--lineage",
                str(corpus / "consumer_task" / "lineage.json"),
                "--tables",
                str(cards),
            ]
        )
        == 0
    )

    profile = json.loads(
        (corpus / "consumer_task" / "semantic.json").read_text(encoding="utf-8")
    )
    card = profile["inputs"][0]["card"]
    assert card["produced_by_task"] == "producer_task"
    assert profile["confidence"]["metadata_coverage"]["table_cards"] == {
        "inputs_with_card": 1,
        "inputs_total": 1,
        "consumers": 0,
    }
    markdown = (corpus / "consumer_task" / "semantic.md").read_text(encoding="utf-8")
    header = next(
        line for line in markdown.splitlines() if line.startswith("| 输入表 |")
    )
    rows = [line for line in markdown.splitlines() if line.startswith("| `mart.")]
    # the widened table must stay a well-formed GFM table: header, rule and every row
    # carry the same cell count, which a bare substring assertion would not notice
    assert header.count("|") == 8
    assert "| 一行是什么（来自生产任务） |" in header
    assert rows and all(row.count("|") == 8 for row in rows)


def test_describe_with_tables_lists_downstream_consumers_on_the_target(
    tmp_path: Path,
) -> None:
    corpus, cards = _cards(tmp_path)

    assert (
        main(
            [
                "describe",
                "--lineage",
                str(corpus / "producer_task" / "lineage.json"),
                "--tables",
                str(cards),
            ]
        )
        == 0
    )

    markdown = (corpus / "producer_task" / "semantic.md").read_text(encoding="utf-8")
    assert "- 下游消费：`consumer_task`" in markdown


def test_describe_without_tables_writes_the_document_it_always_wrote(
    tmp_path: Path,
) -> None:
    corpus, cards = _cards(tmp_path)
    task = corpus / "consumer_task"

    assert main(["describe", "--lineage", str(task / "lineage.json")]) == 0
    plain = (task / "semantic.json").read_text(encoding="utf-8")
    plain_md = (task / "semantic.md").read_text(encoding="utf-8")

    profile = json.loads(plain)
    assert "card" not in profile["inputs"][0]
    assert "downstream_consumers" not in profile["task"]
    assert "table_cards" not in profile["confidence"]["metadata_coverage"]
    assert "一行是什么" not in plain_md
    assert "下游消费" not in plain_md


def test_describe_rejects_a_tables_path_that_is_not_there(tmp_path: Path, capsys) -> None:
    corpus = _corpus(tmp_path / "corpus")

    assert (
        main(
            [
                "describe",
                "--lineage",
                str(corpus / "consumer_task" / "lineage.json"),
                "--tables",
                str(tmp_path / "missing.json"),
            ]
        )
        == 2
    )
    assert "--tables path does not exist" in capsys.readouterr().err


def test_describe_rejects_a_tables_file_of_the_wrong_document_format(
    tmp_path: Path, capsys
) -> None:
    corpus = _corpus(tmp_path / "corpus")
    stranger = tmp_path / "stranger.json"
    stranger.write_text(json.dumps({"doc_format": "semantic-json/1"}), encoding="utf-8")

    assert (
        main(
            [
                "describe",
                "--lineage",
                str(corpus / "consumer_task" / "lineage.json"),
                "--tables",
                str(stranger),
            ]
        )
        == 1
    )
    assert "--tables expects a tables-json/1 document" in capsys.readouterr().err
