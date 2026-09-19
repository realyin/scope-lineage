"""End-to-end tests for ``scope-lineage ontology``.

A library capability is not done until the CLI that exposes it is wired and tested. What
``ontology`` shares with ``tables`` / ``glossary`` (the corpus walk, the two skip
counters, the format switch) is pinned here beside what is new: it is the first command
that *consumes* two other corpus documents, so both the "built in memory" and the
"supplied on the command line" routes have to produce the same bytes.
"""

from __future__ import annotations

import json
from pathlib import Path

from scope_lineage.cli import main
from scope_lineage.scope.scope_builder import parse_scope_lineage

from .statement_document import write_statement_documents


SCHEMA = {
    "ods.customer_base": ["customer_id", "country_code", "state", "dt"],
    "mart.customer_daily": ["customer_id", "country_code", "dt"],
}

PRODUCER_SQL = (
    "INSERT OVERWRITE TABLE mart.customer_daily PARTITION (dt = '20250101') "
    "SELECT customer_id, max(country_code) AS country_code FROM ods.customer_base "
    "WHERE state IN ('NEW', 'PAID') GROUP BY customer_id"
)

CONSUMER_SQL = (
    "INSERT OVERWRITE TABLE mart.customer_rollup "
    "SELECT b.country_code, count(1) AS n FROM ods.customer_base b "
    "LEFT JOIN mart.customer_daily d ON b.customer_id = d.customer_id "
    "WHERE d.dt = '20250101' GROUP BY b.country_code"
)


def _corpus(root: Path) -> Path:
    for name, sql in (("producer_task", PRODUCER_SQL), ("consumer_task", CONSUMER_SQL)):
        write_statement_documents(parse_scope_lineage(sql, name, schema=SCHEMA), root / name)
    return root


def _run(*args: str) -> int:
    return main(["ontology", *args])


def test_ontology_writes_the_json_and_the_index(tmp_path: Path, capsys) -> None:
    corpus = _corpus(tmp_path / "corpus")
    out = tmp_path / "out"

    assert _run("--lineage", str(corpus), "--out", str(out)) == 0

    ontology = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    assert ontology["doc_format"] == "ontology-json/1"
    assert ontology["corpus"]["task_count"] == 2
    assert [item["id"] for item in ontology["entities"]] == [
        "mart.customer_daily",
        "mart.customer_rollup",
        "ods.customer_base",
    ]
    assert [item["id"] for item in ontology["relations"]] == ["rel:001"]
    assert (out / "ontology.md").read_text(encoding="utf-8").startswith("---\n")
    assert "Modelled 3 entity(ies), 1 relation(s)" in capsys.readouterr().out


def test_the_corpus_proof_reaches_the_relation(tmp_path: Path) -> None:
    """The producing task proved ``customer_id`` unique, so the JOIN is not a guess."""
    out = tmp_path / "out"
    assert _run("--lineage", str(_corpus(tmp_path / "corpus")), "--out", str(out)) == 0

    relation = json.loads((out / "ontology.json").read_text(encoding="utf-8"))["relations"][0]

    assert relation["from"]["entity"] == "ods.customer_base"
    assert relation["to"]["entity"] == "mart.customer_daily"
    assert relation["cardinality"]["claim"] == "many_to_one"
    assert relation["cardinality"]["tier"] == "proven"


def test_ontology_json_is_indented_and_newline_terminated(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert _run("--lineage", str(_corpus(tmp_path / "corpus")), "--out", str(out)) == 0

    raw = (out / "ontology.json").read_text(encoding="utf-8")

    assert raw.startswith('{\n  "doc_format"')
    assert raw.endswith("\n")
    assert "\\u" not in raw


def test_running_ontology_twice_writes_the_same_bytes(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path / "corpus")
    first, second = tmp_path / "first", tmp_path / "second"

    assert _run("--lineage", str(corpus), "--out", str(first)) == 0
    assert _run("--lineage", str(corpus), "--out", str(second)) == 0

    for name in ("ontology.json", "ontology.md"):
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_supplied_tables_and_glossary_give_the_same_document(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path / "corpus")
    built, supplied = tmp_path / "built", tmp_path / "supplied"
    cards, terms = tmp_path / "cards", tmp_path / "terms"

    assert main(["tables", "--lineage", str(corpus), "--out", str(cards)]) == 0
    assert main(["glossary", "--lineage", str(corpus), "--out", str(terms)]) == 0
    assert _run("--lineage", str(corpus), "--out", str(built)) == 0
    assert (
        _run(
            "--lineage",
            str(corpus),
            "--out",
            str(supplied),
            "--tables",
            str(cards / "tables.json"),
            "--glossary",
            str(terms / "glossary.json"),
        )
        == 0
    )

    assert (built / "ontology.json").read_bytes() == (supplied / "ontology.json").read_bytes()


def test_ontology_format_json_writes_no_markdown(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert (
        _run(
            "--lineage", str(_corpus(tmp_path / "corpus")), "--out", str(out),
            "--format", "json",
        )
        == 0
    )

    assert (out / "ontology.json").is_file()
    assert not (out / "ontology.md").exists()


def test_ontology_rejects_an_unknown_format(tmp_path: Path, capsys) -> None:
    corpus = _corpus(tmp_path / "corpus")

    try:
        _run("--lineage", str(corpus), "--out", str(tmp_path / "out"), "--format", "csv")
    except SystemExit as exit_code:
        assert exit_code.code == 2
    assert "--format accepts json and md" in capsys.readouterr().err


def test_ontology_reports_a_missing_lineage_root(tmp_path: Path, capsys) -> None:
    assert _run("--lineage", str(tmp_path / "nope"), "--out", str(tmp_path / "o")) == 2
    assert "--lineage path does not exist" in capsys.readouterr().err


def test_ontology_reports_an_empty_lineage_root(tmp_path: Path, capsys) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    assert _run("--lineage", str(empty), "--out", str(tmp_path / "o")) == 1
    assert "no lineage.json found" in capsys.readouterr().err


def test_ontology_skips_documents_of_an_unknown_version(tmp_path: Path, capsys) -> None:
    corpus = _corpus(tmp_path / "corpus")
    stranger = corpus / "stranger"
    stranger.mkdir()
    (stranger / "lineage.json").write_text(
        json.dumps({"schema_version": "0.9"}), encoding="utf-8"
    )

    assert _run("--lineage", str(corpus), "--out", str(tmp_path / "out")) == 0

    assert "skipped_unknown_version=1" in capsys.readouterr().out


def test_ontology_rejects_a_tables_path_that_is_not_there(tmp_path: Path, capsys) -> None:
    corpus = _corpus(tmp_path / "corpus")

    assert (
        _run(
            "--lineage", str(corpus), "--out", str(tmp_path / "out"),
            "--tables", str(tmp_path / "missing.json"),
        )
        == 2
    )
    assert "--tables path does not exist" in capsys.readouterr().err


def test_ontology_rejects_a_glossary_of_the_wrong_document_format(
    tmp_path: Path, capsys
) -> None:
    corpus = _corpus(tmp_path / "corpus")
    stranger = tmp_path / "stranger.json"
    stranger.write_text(json.dumps({"doc_format": "tables-json/1"}), encoding="utf-8")

    assert (
        _run(
            "--lineage", str(corpus), "--out", str(tmp_path / "out"),
            "--glossary", str(stranger),
        )
        == 1
    )
    assert "--glossary expects a glossary-json/1 document" in capsys.readouterr().err
