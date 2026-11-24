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


def test_a_table_named_like_a_subdirectory_is_not_taken_for_the_directory(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """Run inside a directory holding one folder per table: the last table stays a table."""
    (tmp_path / "demo_dwd.a_df").mkdir()
    (tmp_path / "demo_dwd.b_df").mkdir()
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as raised:
        _digest("--out", tmp_path / "out", "--only", "demo_dwd.a_df", "demo_dwd.b_df")

    assert raised.value.code == 2
    assert "--only takes every word after it" in capsys.readouterr().err


def test_a_plain_directory_name_ending_only_is_still_taken_back(
    tmp_path: Path, monkeypatch
) -> None:
    """Sentinel: a directory word that is no ``db.table`` (``docs``, ``.``) is still one."""
    docs = _docs(tmp_path, _renamed(NEW_TABLE))
    monkeypatch.chdir(tmp_path)
    assert _digest("--out", tmp_path / "a", "--only", NEW_TABLE, "docs") == 0

    monkeypatch.chdir(docs)
    assert _digest("--out", tmp_path / "b", "--only", NEW_TABLE, ".") == 0


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


# --- the hand-over facts a drafter needs for constraints and derivations -------------


def test_each_table_carries_its_rules(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert _digest(_docs(tmp_path), "--out", out) == 0

    [table] = read_json(out / "digest.json")["tables"]
    assert table["rules"] == [
        {"id": "r1", "kind": "filter", "text": "只取注册表当天分区"},
        {"id": "r2", "kind": "dedup", "text": "每个客户号按更新时间倒序编号"},
        {"id": "r3", "kind": "filter", "text": "只保留编号为 1 的最新一条"},
    ]
    text = (out / "digest.md").read_text(encoding="utf-8")
    assert "- Rule r2 (dedup): 每个客户号按更新时间倒序编号" in text


def test_a_document_without_rules_gives_an_empty_list() -> None:
    document = copy.deepcopy(read_json(EXAMPLE))
    document.pop("rules", None)

    [table] = digest_tables([document])["tables"]

    assert table["rules"] == []


def test_columns_carry_derivation_null_meaning_and_watch_when_the_document_has_them() -> None:
    document = copy.deepcopy(read_json(EXAMPLE))
    document["columns"][2]["watch"] = "a watch note"

    [table] = digest_tables([document])["tables"]

    identifiers = {c["column"]: c for c in table["identifier_columns"]}
    assert identifiers["customer_id"]["derivation"] == "直接取注册表的客户号；每个客户号只留一行。"
    assert "null_meaning" not in identifiers["customer_id"]
    assert identifiers["verified_customer_no"]["null_meaning"] == "客户尚未实名"
    [gender] = table["descriptive_columns"]
    assert gender["watch"] == "a watch note"
    assert "watch" not in identifiers["customer_id"]
    assert "type" not in gender, "no table cards, no physical type"


def _tables_document(path: Path) -> Path:
    return write_json(path, {
        "doc_format": "tables-json/1",
        "corpus": {},
        "tables": [{
            "table": DEMO_TABLE,
            "columns": [
                {"name": "customer_id", "type": "string"},
                {"name": "GENDER_CD", "type": "char(1)"},
                {"name": "register_time", "type": None},
            ],
        }],
    })


def test_tables_adds_the_physical_type_of_each_column_the_cards_know(tmp_path: Path) -> None:
    out = tmp_path / "out"
    tables = _tables_document(tmp_path / "tables.json")

    assert _digest(_docs(tmp_path), "--tables", tables, "--out", out) == 0

    [table] = read_json(out / "digest.json")["tables"]
    identifiers = {c["column"]: c for c in table["identifier_columns"]}
    assert identifiers["customer_id"]["type"] == "string"
    assert "type" not in identifiers["verified_customer_no"]
    assert table["descriptive_columns"][0]["type"] == "char(1)"
    times = {c["column"]: c for c in table["time_columns"]}
    assert "type" not in times["register_time"], "an unknown type is left out"
    assert "gender_cd <char(1)>" in (out / "digest.md").read_text(encoding="utf-8")


def test_tables_of_another_format_or_missing_is_an_error(tmp_path: Path) -> None:
    wrong = write_json(tmp_path / "tables.json", {"doc_format": "lineage/1"})

    assert _digest(_docs(tmp_path), "--tables", wrong, "--out", tmp_path / "out") == 1
    assert _digest(_docs(tmp_path), "--tables", tmp_path / "nope.json", "--out", tmp_path / "o") == 2
    assert not (tmp_path / "out").exists()


# ------------------------------------------------------------------ answered questions
#
# A question answered by ``semantic confirm`` is no longer open; without these lines the
# drafter of a catalog saw less after the owner answered than before. The digest reads the
# documents only: an answer still waiting on a browsing page's record file is not in them.

ANSWER = "不会，只有 F、M、U 三个值。"
QUESTION = "性别码值除了 F、M、U 以外，还会不会出现其他值？"


def _answered_document(**entry) -> dict:
    """The example document with its ``q1`` answered by ``semantic confirm``."""
    from scope_lineage.semantics.confirm import apply_confirmations

    confirmation = {"table": DEMO_TABLE, "target": "question:q1", "value": ANSWER,
                    "by": "demo-reviewer", "date": "2026-01-01", **entry}
    result = apply_confirmations({DEMO_TABLE: read_json(EXAMPLE)}, [confirmation])
    assert result.unmatched == []
    return result.documents[DEMO_TABLE]


def _answered(tmp_path: Path) -> Path:
    docs = tmp_path / "docs"
    write_json(docs / EXAMPLE.name, _answered_document())
    return docs


def test_an_answered_question_reaches_the_digest_with_its_answer(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert _digest(_answered(tmp_path), "--out", out) == 0

    table = read_json(out / "digest.json")["tables"][0]
    assert table["open_questions"] == []
    assert table["answered_questions"] == [
        {"id": "q1", "text": QUESTION, "answer": ANSWER,
         "answered_by": "demo-reviewer", "answered_on": "2026-01-01"}
    ]


def test_the_markdown_prints_an_answered_question_with_its_answer(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert _digest(_answered(tmp_path), "--out", out) == 0

    text = (out / "digest.md").read_text(encoding="utf-8")
    assert f"- Answered q1: {QUESTION} -> {ANSWER} (demo-reviewer, 2026-01-01)" in text
    assert "- Open q1" not in text


def test_answering_changes_only_the_question_line_and_key(tmp_path: Path) -> None:
    """Byte for byte: the open question's line becomes the answered one, nothing else moves."""
    before, after = tmp_path / "before", tmp_path / "after"
    assert _digest(_docs(tmp_path / "a"), "--out", before) == 0
    assert _digest(_answered(tmp_path / "b"), "--out", after) == 0

    open_md = (before / "digest.md").read_text(encoding="utf-8")
    assert f"- Open q1: {QUESTION}\n" in open_md
    assert (after / "digest.md").read_text(encoding="utf-8") == open_md.replace(
        f"- Open q1: {QUESTION}\n",
        f"- Answered q1: {QUESTION} -> {ANSWER} (demo-reviewer, 2026-01-01)\n",
    )
    expected = read_json(before / "digest.json")
    expected["tables"][0]["open_questions"] = []
    expected["tables"][0]["answered_questions"] = read_json(after / "digest.json")["tables"][0][
        "answered_questions"]
    assert read_json(after / "digest.json") == expected


def test_a_document_with_no_answered_question_digests_byte_for_byte_as_before(
    tmp_path: Path,
) -> None:
    """No answered question: no key, no line -- the same bytes as a document whose question
    was never there to answer, apart from the open line itself."""
    out = tmp_path / "out"
    assert _digest(_docs(tmp_path), "--out", out) == 0
    assert "answered_questions" not in read_json(out / "digest.json")["tables"][0]
    assert "- Answered" not in (out / "digest.md").read_text(encoding="utf-8")

    bare = copy.deepcopy(read_json(EXAMPLE))
    bare["summary"]["questions"] = []
    unanswered = copy.deepcopy(read_json(EXAMPLE))
    unanswered["summary"]["questions"][0]["status"] = "answered"   # no answer text
    for name, document in (("bare", bare), ("unanswered", unanswered)):
        write_json(tmp_path / name / "docs" / EXAMPLE.name, document)
        assert _digest(tmp_path / name / "docs", "--out", tmp_path / name / "out") == 0
    for file in ("digest.md", "digest.json"):
        assert (tmp_path / "unanswered" / "out" / file).read_bytes() == (
            tmp_path / "bare" / "out" / file).read_bytes()


def test_a_question_marked_answered_without_an_answer_carries_nothing() -> None:
    """The schema allows it; there is no answer to hand the drafter, as before."""
    document = copy.deepcopy(read_json(EXAMPLE))
    document["summary"]["questions"][0]["status"] = "answered"

    table = digest_tables([document])["tables"][0]

    assert table["open_questions"] == []
    assert "answered_questions" not in table


def test_an_answer_without_who_or_when_prints_no_parentheses() -> None:
    document = copy.deepcopy(read_json(EXAMPLE))
    document["summary"]["questions"][0].update(status="answered", answer=ANSWER)

    from scope_lineage.catalog.digest import render_digest_markdown

    digest = digest_tables([document])
    assert digest["tables"][0]["answered_questions"] == [
        {"id": "q1", "text": QUESTION, "answer": ANSWER}]
    assert f"- Answered q1: {QUESTION} -> {ANSWER}\n" in render_digest_markdown(digest)


def test_an_answer_stays_with_the_table_it_belongs_to(tmp_path: Path) -> None:
    other = _renamed(NEW_TABLE)
    docs = _answered(tmp_path)
    write_json(docs / f"{NEW_TABLE}.json", other)
    out = tmp_path / "out"
    assert _digest(docs, "--out", out) == 0

    tables = {entry["table"]: entry for entry in read_json(out / "digest.json")["tables"]}
    assert "answered_questions" in tables[DEMO_TABLE]
    assert "answered_questions" not in tables[NEW_TABLE]
    assert tables[NEW_TABLE]["open_questions"] == [{"id": "q1", "text": QUESTION}]
