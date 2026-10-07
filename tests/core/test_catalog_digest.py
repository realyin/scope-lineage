"""``scope-lineage catalog digest``: table semantics condensed into catalog-drafting material."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scope_lineage.catalog import digest_tables, load_catalog
from scope_lineage.cli import main

from .catalog_demo import DEMO
from .table_semantics_demo import CONFIRMATIONS, DEMO_TABLE, EXAMPLE, read_json, write_json

NEW_TABLE = "demo_dwd.dwd_party_customer_new_df"


def _docs(tmp_path: Path, *extra: dict) -> Path:
    """The example document, the confirmations beside it, and ``extra`` documents."""
    docs = tmp_path / "docs"
    write_json(docs / EXAMPLE.name, read_json(EXAMPLE))
    write_json(docs / CONFIRMATIONS.name, read_json(CONFIRMATIONS))
    for document in extra:
        write_json(docs / f"{document['table']}.json", document)
    return docs


def _renamed(table: str) -> dict:
    document = copy.deepcopy(read_json(EXAMPLE))
    document["table"] = table
    return document


def _digest(*argv) -> int:
    return main(["catalog", "digest", *[str(arg) for arg in argv]])


def test_digest_condenses_one_document(tmp_path: Path, capsys) -> None:
    out = tmp_path / "out"

    assert _digest(_docs(tmp_path), "--out", out) == 0

    digest = read_json(out / "digest.json")
    assert digest["doc_format"] == "catalog-digest/1"
    assert "catalog" not in digest
    [table] = digest["tables"]
    assert table["table"] == DEMO_TABLE
    assert table["concept"] == "concept:customer"
    assert table["representation_kind"] == "core"
    assert table["row"].startswith("一个客户")
    assert table["grain"] == {"columns": ["customer_id"], "source": "proven", "unique": "yes"}
    assert table["time"]["kind"] == "snapshot"
    assert table["time"]["cycle"] == "daily"
    assert [c["column"] for c in table["identifier_columns"]] == ["customer_id", "verified_customer_no"]
    assert [c["column"] for c in table["state_columns"]] == ["verify_status"]
    assert table["state_columns"][0]["code_values"] == [
        {"value": "1", "meaning": "已实名"},
        {"value": "0", "meaning": "未实名"},
    ]
    assert [c["column"] for c in table["time_columns"]] == ["register_time", "dt"]
    assert table["measure_columns"] == []
    assert [c["column"] for c in table["descriptive_columns"]] == ["gender_cd"]
    assert table["technical_columns"] == ["etl_time"]
    assert table["columns"] == 7
    assert table["related"]["upstream"] == [{"table": "demo_ods.ods_core_customer_df", "role": "main"}]
    assert table["open_questions"] == [
        {"id": "q1", "text": "性别码值除了 F、M、U 以外，还会不会出现其他值？"}
    ]
    assert "Digested 1 table(s)" in capsys.readouterr().out


def test_the_markdown_carries_the_same_facts(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert _digest(_docs(tmp_path), "--out", out) == 0

    text = (out / "digest.md").read_text(encoding="utf-8")
    assert f"## {DEMO_TABLE}" in text
    assert "concept:customer" in text
    assert "customer_id" in text
    assert "verify_status" in text
    assert "1=已实名" in text
    assert "性别码值除了" in text
    assert "demo_ods.ods_core_customer_df" in text


def test_the_catalog_names_what_it_does_not_cover(tmp_path: Path) -> None:
    extended = copy.deepcopy(read_json(EXAMPLE))
    extended["columns"].append(
        {
            "column": "nickname",
            "meaning": "昵称",
            "category": "descriptive",
            "derivation": "直接取注册表的昵称。",
            "sources": ["sql"],
            "confidence": "high",
        }
    )
    docs = _docs(tmp_path, _renamed(NEW_TABLE))
    write_json(docs / EXAMPLE.name, extended)
    out = tmp_path / "out"

    assert _digest(docs, "--catalog", DEMO, "--out", out) == 0

    digest = read_json(out / "digest.json")
    assert digest["catalog"]["name"] == "demo-lending"
    assert digest["catalog"]["tables_without_representation"] == [NEW_TABLE]
    assert digest["catalog"]["columns_without_binding"] == {DEMO_TABLE: ["nickname"]}
    by_table = {entry["table"]: entry for entry in digest["tables"]}
    assert by_table[DEMO_TABLE]["catalog"] == {
        "represented": True,
        "concept": "concept:customer",
        "kind": "core",
        "unbound_columns": ["nickname"],
    }
    assert by_table[NEW_TABLE]["catalog"] == {"represented": False}
    text = (out / "digest.md").read_text(encoding="utf-8")
    assert NEW_TABLE in text.split("## ")[1]  # the coverage section comes first
    assert "nickname" in text


def test_digest_catalog_matching_ignores_case_and_catalog_prefix() -> None:
    document = _renamed("spark_catalog.DEMO_DWD.dwd_party_customer_info_df")

    digest = digest_tables([document], load_catalog(DEMO))

    assert digest["catalog"]["tables_without_representation"] == []


def test_only_narrows_the_tables(tmp_path: Path) -> None:
    out = tmp_path / "out"
    docs = _docs(tmp_path, _renamed(NEW_TABLE))

    assert _digest(docs, "--only", f"spark_catalog.{NEW_TABLE}", "--out", out) == 0

    assert [entry["table"] for entry in read_json(out / "digest.json")["tables"]] == [NEW_TABLE]


def test_only_an_unknown_table_exits_one(tmp_path: Path, capsys) -> None:
    out = tmp_path / "out"

    assert _digest(_docs(tmp_path), "--only", "demo_dwd.nothing", "--out", out) == 1

    assert "demo_dwd.nothing" in capsys.readouterr().err
    assert not out.exists()


def test_only_before_the_directory_reads_as_the_directory_first(tmp_path: Path) -> None:
    docs = _docs(tmp_path, _renamed(NEW_TABLE))
    first, last = tmp_path / "first", tmp_path / "last"

    assert _digest(docs, "--only", NEW_TABLE, "--out", first) == 0
    assert _digest("--out", last, "--only", NEW_TABLE, docs) == 0

    for name in ("digest.json", "digest.md"):
        assert (last / name).read_bytes() == (first / name).read_bytes()


def test_only_swallowing_a_word_that_is_no_directory_is_an_error(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit) as raised:
        _digest("--out", tmp_path / "out", "--only", NEW_TABLE, "docs_typo")

    assert raised.value.code == 2
    assert "--only takes every word after it" in capsys.readouterr().err


def test_tables_are_ordered_and_the_output_is_deterministic(tmp_path: Path) -> None:
    docs = _docs(tmp_path, _renamed("demo_dwd.a_first_df"), _renamed(NEW_TABLE))

    assert _digest(docs, "--catalog", DEMO, "--out", tmp_path / "a") == 0
    assert _digest(docs, "--catalog", DEMO, "--out", tmp_path / "b") == 0

    tables = [entry["table"] for entry in read_json(tmp_path / "a" / "digest.json")["tables"]]
    assert tables == sorted(tables)
    for name in ("digest.json", "digest.md"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_an_illegal_document_is_skipped_and_exits_one(tmp_path: Path, capsys) -> None:
    docs = _docs(tmp_path)
    broken = _renamed(NEW_TABLE)
    del broken["summary"]
    write_json(docs / "broken.json", broken)
    out = tmp_path / "out"

    assert _digest(docs, "--out", out) == 1

    assert "broken.json" in capsys.readouterr().err
    assert [entry["table"] for entry in read_json(out / "digest.json")["tables"]] == [DEMO_TABLE]


def test_no_documents_or_no_directory(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()

    assert _digest(tmp_path / "empty", "--out", tmp_path / "out") == 1
    assert _digest(tmp_path / "nowhere", "--out", tmp_path / "out") == 2


def test_an_unreadable_catalog_exits_two(tmp_path: Path) -> None:
    out = tmp_path / "out"

    assert _digest(_docs(tmp_path), "--catalog", tmp_path / "nowhere", "--out", out) == 2
    assert not out.exists()


def test_digest_json_is_plain_json(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert _digest(_docs(tmp_path), "--out", out) == 0

    assert json.loads((out / "digest.json").read_text(encoding="utf-8"))["tables"]
