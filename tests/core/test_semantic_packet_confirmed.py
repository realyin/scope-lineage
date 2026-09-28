"""``semantic packet --metadata-patch / --glossary``: what the owner confirmed reaches the writer.

A reviewed comment (``metadata-patch/1``) and a confirmed value meaning (the corpus
glossary's ``values[].meaning``) are answers, not readings: a writer who never sees them
guesses the meaning again and asks the owner the question the owner already answered.
So the packet carries them -- a patched comment wherever the packet reads a comment from
(the schema metadata or the lineage), marked ``comment_source: "patch"``, and each
column's ``confirmed_values`` -- and checks 3 and 12 take them as the facts they are.
Without the flags a packet is byte for byte what it was.

All data here is the synthetic demo corpus plus hand-written patch and glossary files.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from scope_lineage.semantics import validate_document
from scope_lineage.semantics.packet_confirmed import Confirmed

from .catalog_demo import CORPUS
from .table_semantics_demo import (
    DEMO_TABLE,
    demo_packets,
    example,
    pack,
    packet_of,
    read_json,
    run,
    write_json,
)

LOAN = "demo_dwd.dwd_lending_loan_df"
SOURCE = "demo_ods.ods_core_customer_df"

PATCH = {
    "doc_format": "metadata-patch/1",
    "tables": {SOURCE: {"table_name_cn": "Customer registrations, confirmed"}},
    "columns": {
        f"{DEMO_TABLE}.gender_cd": {"comment": "Gender: F female, M male, U unknown"},
        f"{SOURCE}.verify_flag": {"comment": "Verified flag: 0 no, 1 yes"},
        "demo_dwd.no_such_table.some_col": {"comment": "matches nothing"},
    },
}


def _value(ref: str, value: str, meaning=None, **extra) -> dict:
    column = extra.pop("column", ref.rsplit(".", 1)[-1])
    text = {"text": meaning, "source": "override", "confirmed_by": "owner",
            "date": "2026-09-28"} if meaning else None
    return {"column_ref": ref, "column": column, "value": value, "meaning": text, **extra}


GLOSSARY = {
    "doc_format": "glossary-json/1",
    "values": [
        # a catalog prefix and a column spelt in another case still name the loan column
        _value(f"spark_catalog.{LOAN}.loan_status", "2", "Overdue", column="Loan_Status"),
        _value(f"{LOAN}.loan_status", "2", "Second answer, never shown"),
        _value(f"{LOAN}.loan_status", "3", None),  # observed, not confirmed
        _value("subq:latest.loan_status", "9", "A scope column", logical=True),
        _value(f"{SOURCE}.gender", "U", "Unknown"),
        _value("demo_dwd.dwd_lending_borrower_df.gender_cd", "X", "Another table's value"),
    ],
}


@pytest.fixture(scope="module")
def work(tmp_path_factory) -> Path:
    work = tmp_path_factory.mktemp("confirmed")
    demo_packets(work)
    write_json(work / "patch.json", PATCH)
    write_json(work / "glossary.json", GLOSSARY)
    return work


def _pack(work: Path, out: str, *extra, schema: bool = True) -> int:
    if schema:
        return pack(CORPUS, work / "lineage", work / out, *extra)
    return run("semantic", "packet", "--lineage", work / "lineage", "--tasks", CORPUS / "tasks",
               "--out", work / out, *extra)


@pytest.fixture(scope="module")
def confirmed(work: Path) -> Path:
    flags = ("--metadata-patch", work / "patch.json", "--glossary", work / "glossary.json")
    assert _pack(work, "confirmed", *flags) == 0
    return work / "confirmed"


@pytest.fixture(scope="module")
def confirmed_bare(work: Path) -> Path:
    """The same flags without ``--schema``: every comment comes from the lineage."""
    flags = ("--metadata-patch", work / "patch.json", "--glossary", work / "glossary.json")
    assert _pack(work, "confirmed-bare", *flags, schema=False) == 0
    return work / "confirmed-bare"


def _column(entry: dict, name: str) -> dict:
    return next(column for column in entry["columns"] if column["name"] == name)


def _input(packet: dict, table: str) -> dict:
    return next(item for item in packet["inputs"] if item["table"] == table)


# ---------------------------------------------------------------- without the flags


def _keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_keys(item) for item in value))
    return set()


def test_without_the_flags_no_packet_carries_a_confirmed_key(work: Path) -> None:
    for path in (work / "packets").rglob("packet.json"):
        assert not _keys(read_json(path)) & {"comment_source", "confirmed_values"}, path
    text = (work / "packets" / DEMO_TABLE / "packet.md").read_text(encoding="utf-8")
    assert "已确认" not in text


def test_a_patch_and_a_glossary_that_confirm_nothing_change_no_byte(work: Path) -> None:
    write_json(work / "empty-patch.json", {"doc_format": "metadata-patch/1"})
    write_json(work / "silent-glossary.json", {
        "doc_format": "glossary-json/1",
        "values": [_value(f"{LOAN}.loan_status", "2", None)],
    })
    flags = ("--metadata-patch", work / "empty-patch.json",
             "--glossary", work / "silent-glossary.json")
    assert _pack(work, "silent", *flags) == 0
    for path in sorted((work / "packets").rglob("packet.*")):
        again = work / "silent" / path.relative_to(work / "packets")
        assert again.read_bytes() == path.read_bytes(), path


# ---------------------------------------------------------------- metadata patch


def test_the_patch_is_laid_over_the_schema_and_marked(confirmed: Path) -> None:
    packet = packet_of(confirmed)
    gender = _column(packet["target"], "gender_cd")
    assert gender["comment"] == "Gender: F female, M male, U unknown"
    assert gender["comment_source"] == "patch"
    assert "comment_source" not in _column(packet["target"], "customer_id")
    source = _input(packet, SOURCE)
    assert (source["comment"], source["comment_source"]) == (
        "Customer registrations, confirmed", "patch")
    flag = _column(source, "verify_flag")
    assert (flag["comment"], flag["comment_source"]) == ("Verified flag: 0 no, 1 yes", "patch")
    assert "comment_source" not in _column(source, "cust_no")
    # the target table was not patched, so it says nothing about its source
    assert "comment_source" not in packet["target"]


def test_the_comment_source_sits_right_behind_the_comment(confirmed: Path) -> None:
    gender = _column(packet_of(confirmed)["target"], "gender_cd")
    assert list(gender) == ["name", "type", "comment", "comment_source", "partition"]


def test_without_a_schema_the_patch_reaches_the_lineage_comments(confirmed_bare: Path) -> None:
    packet = packet_of(confirmed_bare)
    assert packet["target"]["metadata_source"] == "lineage"
    gender = _column(packet["target"], "gender_cd")
    assert (gender["comment"], gender["comment_source"]) == (
        "Gender: F female, M male, U unknown", "patch")
    source = _input(packet, SOURCE)
    assert source["comment_source"] == "patch"
    assert _column(source, "verify_flag")["comment_source"] == "patch"


def test_a_patched_description_under_the_schemas_name_marks_nothing(work: Path) -> None:
    """The packet shows the schema's name as the comment; the patch only gave the description."""
    schema = read_json(CORPUS / "schema_info.json")
    for table in schema["tables"]:
        if table["table_name"] == SOURCE:
            table["table_name_cn"] = "Customer registrations"
    write_json(work / "named-schema.json", schema)
    write_json(work / "desc-patch.json", {
        "doc_format": "metadata-patch/1",
        "tables": {SOURCE: {"table_desc": "One row per registration, confirmed"}},
    })
    code = run("semantic", "packet", "--lineage", work / "lineage", "--tasks", CORPUS / "tasks",
               "--schema", work / "named-schema.json", "--only", DEMO_TABLE,
               "--metadata-patch", work / "desc-patch.json", "--out", work / "desc")
    assert code == 0
    source = _input(packet_of(work / "desc"), SOURCE)
    assert source["comment"] == "Customer registrations"
    assert "comment_source" not in source


def test_the_summary_reports_the_patch_keys_nothing_answered(
    work: Path, capsys: pytest.CaptureFixture
) -> None:
    capsys.readouterr()
    assert _pack(work, "report", "--metadata-patch", work / "patch.json") == 0
    out = capsys.readouterr().out
    assert "patch_unmatched=1 (demo_dwd.no_such_table.some_col)" in out


def test_the_schema_overlay_counts_what_it_answered_as_matched(work: Path) -> None:
    """An answer the schema lookup carried to the packet is not reported unmatched."""
    from scope_lineage.cli_semantic import _metadata_lookup
    from scope_lineage.metadata.metadata_patch import load_metadata_patch

    write_json(work / "schema-only.json", {
        "doc_format": "metadata-patch/1",
        "columns": {f"{SOURCE}.update_ts": {"comment": "Last update, confirmed"}},
    })
    patch = load_metadata_patch([str(work / "schema-only.json")])
    args = type("Args", (), {"schema": str(CORPUS / "schema_info.json"), "schema_fallback": []})
    lookup = _metadata_lookup(args, None, patch)
    columns = {column["name"]: column for column in lookup(SOURCE)["columns"]}
    assert columns["update_ts"]["comment"] == "Last update, confirmed"
    assert columns["cust_no"]["comment"] == "Customer number"
    assert patch.unmatched() == []


@pytest.mark.parametrize(
    "content",
    [
        None,  # no such file
        {"doc_format": "glossary-json/1"},  # not a metadata patch
        {"doc_format": "metadata-patch/1", "columns": ["a.b.c"]},  # not a mapping
    ],
)
def test_a_patch_that_cannot_be_read_exits_2(
    work: Path, content, capsys: pytest.CaptureFixture
) -> None:
    path = work / "bad-patch.json"
    path.unlink(missing_ok=True)
    if content is not None:
        write_json(path, content)
    capsys.readouterr()
    assert _pack(work, "bad", "--metadata-patch", path) == 2
    assert "bad-patch.json" in capsys.readouterr().err
    assert not (work / "bad").exists()


# ---------------------------------------------------------------- glossary


def test_confirmed_values_reach_the_target_column(confirmed: Path) -> None:
    status = _column(packet_of(confirmed, LOAN)["target"], "loan_status")
    assert status["confirmed_values"] == [
        {"value": "2", "meaning": "Overdue"}
    ]
    assert "confirmed_values" not in _column(packet_of(confirmed, LOAN)["target"], "loan_no")


def test_confirmed_values_reach_the_input_columns(confirmed: Path) -> None:
    packet = packet_of(confirmed)
    gender = _column(_input(packet, SOURCE), "gender")
    assert [item["value"] for item in gender["confirmed_values"]] == ["U"]
    # another table's gender_cd answer is not this table's
    assert "confirmed_values" not in _column(packet["target"], "gender_cd")
    borrower = packet_of(confirmed, "demo_dwd.dwd_lending_borrower_df")
    loans = _column(_input(borrower, LOAN), "loan_status")
    assert loans["confirmed_values"][0]["meaning"] == "Overdue"


def test_confirmed_values_skip_logical_and_unanswered_entries_and_keep_the_first() -> None:
    confirmed = Confirmed(GLOSSARY)
    assert confirmed.values(LOAN, "LOAN_STATUS") == {"confirmed_values": [
        {"value": "2", "meaning": "Overdue"}
    ]}
    assert confirmed.values("demo_dwd.other_table", "loan_status") == {}
    assert Confirmed(None).values(LOAN, "loan_status") == {}


def test_a_logical_entry_never_answers_a_column() -> None:
    glossary = {"values": [_value("subq:latest.loan_status", "9", "Scope", logical=True)]}
    assert Confirmed(glossary).values("subq:latest", "loan_status") == {}


def test_a_glossary_of_another_format_is_refused(work: Path) -> None:
    assert _pack(work, "wrong", "--glossary", work / "patch.json") == 1
    assert _pack(work, "missing", "--glossary", work / "no-such-glossary.json") == 2


# ---------------------------------------------------------------- packet.md


def test_the_markdown_marks_patched_comments_and_lists_confirmed_values(confirmed: Path) -> None:
    text = (confirmed / DEMO_TABLE / "packet.md").read_text(encoding="utf-8")
    assert "- 已确认事实：" in text
    assert "Gender: F female, M male, U unknown（已确认，元数据补丁）" in text
    assert "（Customer registrations, confirmed（已确认，元数据补丁））" in text
    assert "| 列 | 类型 | 注释 | 本表用到 | 已确认码值 |" in text
    assert "U=Unknown |" in text
    loan = (confirmed / LOAN / "packet.md").read_text(encoding="utf-8")
    assert "| # | 列 | 类型 | 注释 | 分区列 | 已确认码值 |" in loan
    assert "| `loan_status` | string | Loan status code |  | 2=Overdue |" in loan


# ---------------------------------------------------------------- checks 3, 7 and 12


@pytest.fixture
def packet(work: Path) -> dict:
    return copy.deepcopy(packet_of(work / "packets"))


@pytest.fixture
def document(work: Path) -> dict:
    return example(work / "packets")


def _problems(report: dict, check: str) -> list[dict]:
    return [f for f in report["failures"] if f["check"] == check and f["status"] == "fail"]


def _doc_column(document: dict, name: str) -> dict:
    return next(column for column in document["columns"] if column["column"] == name)


def _confirm(packet: dict, where: str, name: str, value: str, meaning: str) -> None:
    entry = packet["target"] if where == "target" else _input(packet, where)
    _column(entry, name).setdefault("confirmed_values", []).append(
        {"value": value, "meaning": meaning})


def test_a_code_value_the_glossary_confirms_needs_no_text(document: dict, packet: dict) -> None:
    _doc_column(document, "gender_cd")["code_values"].append(
        {"value": "X", "meaning": "Other", "sources": ["confirmed"]})
    assert len(_problems(validate_document(document, packet), "code_values")) == 1
    _confirm(packet, "target", "gender_cd", "X", "Other")
    assert _problems(validate_document(document, packet), "code_values") == []


def test_a_code_value_confirmed_on_a_source_column_needs_no_text(
    document: dict, packet: dict
) -> None:
    _doc_column(document, "gender_cd")["code_values"].append(
        {"value": "X", "meaning": "Other", "sources": ["confirmed"]})
    _confirm(packet, SOURCE, "gender", "X", "Other")
    assert _problems(validate_document(document, packet), "code_values") == []
    # a column the target column does not read answers nothing
    packet = copy.deepcopy(packet)
    del _column(_input(packet, SOURCE), "gender")["confirmed_values"]
    _confirm(packet, SOURCE, "cust_no", "X", "Other")
    assert len(_problems(validate_document(document, packet), "code_values")) == 1


def test_a_confirmed_value_left_unconfirmed_fails_documented_meaning(
    document: dict, packet: dict
) -> None:
    _confirm(packet, SOURCE, "verify_flag", "0", "Not verified")
    _doc_column(document, "verify_status")["code_values"][1].update(
        meaning="待确认", unconfirmed=True)
    (problem,) = _problems(validate_document(document, packet), "documented_meaning")
    assert problem["at"] == "columns[4].code_values[1]"
    assert "字典已确认它的含义（0 = Not verified）" in problem["message"]
    assert "sources 写 confirmed" in problem["message"]
    assert "去掉 unconfirmed" in problem["message"]


def test_a_confirmed_state_named_pending_may_be_written_as_it_stands(
    document: dict, packet: dict
) -> None:
    _confirm(packet, "target", "verify_status", "0", "待确认")
    _doc_column(document, "verify_status")["code_values"][1]["meaning"] = "待确认"
    assert _problems(validate_document(document, packet), "documented_meaning") == []


def test_a_confirmed_source_is_an_accepted_source(document: dict, packet: dict) -> None:
    _confirm(packet, "target", "verify_status", "0", "Not verified")
    code = _doc_column(document, "verify_status")["code_values"][1]
    code.update(meaning="Not verified", sources=["confirmed"])
    _doc_column(document, "gender_cd")["sources"] = ["confirmed"]
    assert validate_document(document, packet)["failures"] == []

