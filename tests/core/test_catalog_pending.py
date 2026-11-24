"""``catalog pending``: the definitions an agent found missing, kept for the catalog's owner.

An agent that meets a business word the catalog does not define writes its SQL with a
``/* 待确认：… */`` placeholder instead of guessing. ``pending add`` appends each missing
definition to a JSON Lines file (``catalog-pending/1``), from options or from a SQL file's
placeholders, and never touches a line already there. ``pending list`` groups the lines
that name the same thing (normalised text, nothing fuzzier), counts the questions that hit
it, and -- given the ontology and the table semantics -- marks the open question a table
already records about the same column and the catalog object that now carries the name.

Every case runs on the recorded demo ontology and the demo table-semantics document.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.cli import main
from scope_lineage.render.catalog_pending import (
    PENDING_FORMAT,
    pending_line,
    pending_report,
    read_pending,
)

ROOT = Path(__file__).resolve().parents[2]
ONTOLOGY = Path(__file__).parent / "fixtures" / "catalog" / "ontology.json"
SEMANTICS = ROOT / "examples" / "table-semantics"
LOAN = "demo_dwd.dwd_lending_loan_df"
CUSTOMER = "demo_dwd.dwd_party_customer_info_df"
DATE = "2026-01-02"


def _add(pending: Path, *argv: str) -> int:
    return main(["catalog", "pending", "add", str(pending), "--date", DATE, *argv])


def _lines(pending: Path) -> list[dict]:
    return [json.loads(line) for line in pending.read_text(encoding="utf-8").splitlines()]


def _list(pending: Path, capsys, *argv: str) -> tuple[int, dict]:
    capsys.readouterr()  # what an earlier command printed
    code = main(["catalog", "pending", "list", str(pending), "--json", *argv])
    return code, json.loads(capsys.readouterr().out)


# --------------------------------------------------------------------- add


def test_add_appends_one_line_with_what_is_missing_and_where(tmp_path: Path) -> None:
    pending = tmp_path / "pending.jsonl"
    assert _add(
        pending,
        "--missing", "哪些借据状态算结清",
        "--question", "上月结清了多少笔借据",
        "--column", f"{LOAN}.loan_status",
        "--term", "结清",
        "--proposed", "loan_status = '3'",
    ) == 0
    (line,) = _lines(pending)
    assert line == {
        "doc_format": PENDING_FORMAT,
        "date": DATE,
        "missing": "哪些借据状态算结清",
        "question": "上月结清了多少笔借据",
        "term": "结清",
        "tables": [LOAN],
        "columns": [f"{LOAN}.loan_status"],
        "proposed": "loan_status = '3'",
    }
    assert PENDING_FORMAT == "catalog-pending/1"


def test_add_never_rewrites_the_lines_already_there(tmp_path: Path) -> None:
    pending = tmp_path / "pending.jsonl"
    pending.write_text('{"keep": "this line as it is"}', encoding="utf-8")  # no newline
    assert _add(pending, "--missing", "甲", "--question", "问一") == 0
    assert _add(pending, "--missing", "乙", "--question", "问二") == 0
    lines = pending.read_text(encoding="utf-8").splitlines()
    assert lines[0] == '{"keep": "this line as it is"}'
    assert [json.loads(line).get("missing") for line in lines[1:]] == ["甲", "乙"]


def test_add_from_sql_appends_one_line_a_placeholder(tmp_path: Path, capsys) -> None:
    sql = tmp_path / "q.sql"
    sql.write_text(
        f"SELECT l.loan_no FROM {LOAN} l JOIN {CUSTOMER} c ON l.customer_id = c.customer_id\n"
        f"WHERE l.loan_status = /* 待确认：哪些借据状态算结清 */ '3'\n"
        f"  AND /* 待确认：注销客户算不算 */ 1 = 1",
        encoding="utf-8",
    )
    pending = tmp_path / "pending.jsonl"
    assert _add(pending, "--from-sql", str(sql), "--question", "上月结清了多少笔借据") == 0
    tied, loose = _lines(pending)
    assert tied["missing"] == "哪些借据状态算结清"
    assert tied["question"] == "上月结清了多少笔借据"
    assert tied["columns"] == [f"{LOAN}.loan_status"]
    assert tied["tables"] == [LOAN]
    assert tied["source"] == {"sql": str(sql), "statement": 1, "written": "l.loan_status"}
    # tied to no column: the tables the statement reads, and no column
    assert loose["missing"] == "注销客户算不算"
    assert "columns" not in loose
    assert loose["tables"] == [LOAN, CUSTOMER]
    assert loose["source"] == {"sql": str(sql), "statement": 1}
    assert "2" in capsys.readouterr().out


def test_add_from_sql_without_placeholders_writes_nothing_and_exits_1(tmp_path: Path) -> None:
    sql = tmp_path / "q.sql"
    sql.write_text(f"SELECT l.loan_no FROM {LOAN} l", encoding="utf-8")
    pending = tmp_path / "pending.jsonl"
    assert _add(pending, "--from-sql", str(sql), "--question", "问") == 1
    assert not pending.exists()


def test_add_from_sql_that_does_not_parse_exits_2(tmp_path: Path) -> None:
    sql = tmp_path / "q.sql"
    sql.write_text("SELECT FROM WHERE ( /* 待确认：哪些码 */", encoding="utf-8")
    assert _add(tmp_path / "p.jsonl", "--from-sql", str(sql), "--question", "问") == 2


def test_add_refuses_a_placeholder_that_says_nothing(tmp_path: Path, capsys) -> None:
    sql = tmp_path / "q.sql"
    sql.write_text(f"SELECT l.loan_no FROM {LOAN} l WHERE /* 待确认： */ 1 = 1", encoding="utf-8")
    pending = tmp_path / "pending.jsonl"
    assert _add(pending, "--from-sql", str(sql), "--question", "问") == 1
    assert not pending.exists()
    assert "第 1 条语句" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [
    ["--question", "问"],
    ["--missing", "甲", "--from-sql", "q.sql", "--question", "问"],
    ["--from-sql", "q.sql", "--term", "甲", "--question", "问"],
    ["--missing", "甲", "--question", "问", "--column", "no_table_here"],
])
def test_add_refuses_options_that_do_not_fit_together(tmp_path: Path, argv: list) -> None:
    pending = tmp_path / "pending.jsonl"
    assert _add(pending, *argv) == 2
    assert not pending.exists()


def test_add_refuses_a_date_that_is_not_a_date(tmp_path: Path) -> None:
    pending = tmp_path / "pending.jsonl"
    code = main(["catalog", "pending", "add", str(pending), "--missing", "甲",
                 "--question", "问", "--date", "yesterday"])
    assert code == 2


def test_the_date_defaults_to_today_taken_in_one_place(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("scope_lineage.cli_catalog_pending.today", lambda: "2030-05-06")
    pending = tmp_path / "pending.jsonl"
    assert main(["catalog", "pending", "add", str(pending), "--missing", "甲",
                 "--question", "问"]) == 0
    assert _lines(pending)[0]["date"] == "2030-05-06"


def test_the_render_layer_takes_the_date_it_is_given() -> None:
    line = pending_line(missing=" 甲 ", question="问", date="2001-02-03")
    assert line == {"doc_format": PENDING_FORMAT, "date": "2001-02-03", "missing": "甲",
                    "question": "问"}
    with pytest.raises(TypeError):
        pending_line(missing="甲", question="问")  # type: ignore[call-arg]


# -------------------------------------------------------------------- list


def _write(pending: Path, *entries: dict) -> Path:
    pending.write_text(
        "".join(
            json.dumps({"doc_format": PENDING_FORMAT, "date": DATE, **entry}, ensure_ascii=False)
            + "\n"
            for entry in entries
        ),
        encoding="utf-8",
    )
    return pending


def test_list_groups_the_same_missing_thing_by_normalised_text(tmp_path: Path, capsys) -> None:
    pending = _write(
        tmp_path / "pending.jsonl",
        {"missing": "哪些码算 未接通", "question": "问一", "tables": [LOAN]},
        {"missing": "哪些码算　未接通 ", "question": "问二", "date": "2026-01-05"},
        {"missing": "哪些码算未接通", "question": "问三"},  # no space: another thing
        {"missing": "ABC 口径", "question": "问一"},
        {"missing": "abc  口径", "question": "问一"},
    )
    code, report = _list(pending, capsys)
    assert code == 0
    assert report["doc_format"] == "catalog-pending-list/1"
    assert report["lines"] == 5
    by_text = {item["missing"]: item for item in report["items"]}
    first = by_text["哪些码算 未接通"]
    assert first["hits"] == 2
    assert first["questions"] == ["问一", "问二"]
    assert first["dates"] == {"first": DATE, "last": "2026-01-05"}
    assert first["lines"] == [1, 2]
    assert first["tables"] == [LOAN]
    assert by_text["哪些码算未接通"]["hits"] == 1
    assert by_text["ABC 口径"]["hits"] == 2
    assert by_text["ABC 口径"]["questions"] == ["问一"]
    assert [item["hits"] for item in report["items"]] == [2, 2, 1]
    # nothing was checked against a catalog or table semantics
    assert first["recorded_questions"] is None and first["in_catalog"] is None


def test_list_marks_the_open_question_a_table_already_records_for_the_column(
    tmp_path: Path, capsys,
) -> None:
    pending = _write(
        tmp_path / "pending.jsonl",
        {"missing": "性别码还有哪些值", "question": "问一", "columns": [f"{CUSTOMER}.GENDER_CD"]},
        {"missing": "认证状态的口径", "question": "问二", "columns": [f"{CUSTOMER}.verify_status"]},
    )
    code, report = _list(pending, capsys, "--semantics", str(SEMANTICS))
    assert code == 0
    by_text = {item["missing"]: item for item in report["items"]}
    (recorded,) = by_text["性别码还有哪些值"]["recorded_questions"]
    assert recorded["table"] == CUSTOMER
    assert recorded["id"] == "q1"
    assert recorded["status"] == "open"
    assert by_text["认证状态的口径"]["recorded_questions"] == []


def test_list_marks_entries_whose_name_the_catalog_now_carries(tmp_path: Path, capsys) -> None:
    pending = _write(
        tmp_path / "pending.jsonl",
        {"missing": "豁免", "question": "问一"},
        {"missing": "豁免的范围", "question": "问二", "term": "用户"},
        {"missing": "豁免的金额", "question": "问三"},  # the attribute is 豁免金额
    )
    code, report = _list(pending, capsys, "--ontology", str(ONTOLOGY))
    assert code == 0
    by_text = {item["missing"]: item for item in report["items"]}
    assert {(o["kind"], o["id"]) for o in by_text["豁免"]["in_catalog"]} >= {
        ("concept", "concept:fee_waiver"),
    }
    assert [o["id"] for o in by_text["豁免的范围"]["in_catalog"]] == ["concept:customer"]
    assert by_text["豁免的金额"]["in_catalog"] == []


def test_list_reports_lines_it_cannot_read_and_exits_1(tmp_path: Path, capsys) -> None:
    pending = tmp_path / "pending.jsonl"
    pending.write_text(
        "not json\n"
        + json.dumps({"doc_format": "other/1", "missing": "甲", "question": "问", "date": DATE})
        + "\n\n"
        + json.dumps({"doc_format": PENDING_FORMAT, "missing": "", "question": "问", "date": DATE})
        + "\n"
        + json.dumps({"doc_format": PENDING_FORMAT, "missing": "乙", "question": "问", "date": DATE},
                     ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    code, report = _list(pending, capsys)
    assert code == 1
    assert [p["line"] for p in report["problems"]] == [1, 2, 4]
    assert [item["missing"] for item in report["items"]] == ["乙"]


def test_list_of_a_file_that_is_not_there_exits_2(tmp_path: Path, capsys) -> None:
    assert main(["catalog", "pending", "list", str(tmp_path / "none.jsonl")]) == 2
    assert "none.jsonl" in capsys.readouterr().err


def test_list_text_names_each_item_its_hits_and_marks(tmp_path: Path, capsys) -> None:
    pending = _write(
        tmp_path / "pending.jsonl",
        {"missing": "性别码还有哪些值", "question": "问一", "columns": [f"{CUSTOMER}.gender_cd"]},
        {"missing": "性别码还有哪些值", "question": "问二", "columns": [f"{CUSTOMER}.gender_cd"]},
    )
    code = main(["catalog", "pending", "list", str(pending), "--semantics", str(SEMANTICS),
                 "--ontology", str(ONTOLOGY)])
    text = capsys.readouterr().out
    assert code == 0
    assert "性别码还有哪些值" in text and "2 次" in text
    assert "问一" in text and "问二" in text
    assert "q1" in text


def test_the_report_is_built_from_plain_data() -> None:
    entries, problems = read_pending([
        json.dumps({"doc_format": PENDING_FORMAT, "missing": "甲", "question": "问", "date": DATE},
                   ensure_ascii=False),
    ])
    assert problems == []
    report = pending_report(entries, problems)
    assert [item["missing"] for item in report["items"]] == ["甲"]


def test_the_report_reads_the_catalogs_names_once_for_every_item(monkeypatch) -> None:
    """A pending file of many items is checked against a catalog of many tables without
    reading the catalog again for each item (the board and ``pending list`` both wait on it)."""
    from scope_lineage.render import catalog_search

    document = json.loads(ONTOLOGY.read_text(encoding="utf-8"))
    calls = []
    original = catalog_search._items
    monkeypatch.setattr(
        catalog_search, "_items", lambda *args: calls.append(1) or original(*args)
    )
    entries = [
        {**pending_line(missing=f"缺口 {n}", question="q", date="2026-01-01"), "line": n}
        for n in range(1, 6)
    ]
    entries.append({**pending_line(missing="客户", question="q", date="2026-01-01"), "line": 6})

    report = pending_report(entries, document=document)

    assert len(calls) == 1
    named = next(item for item in report["items"] if item["missing"] == "客户")
    assert [o["id"] for o in named["in_catalog"]] == ["concept:customer"]


# ------------------------------------------------------------------ replies
#
# The owner answers a group with ``pending reply``: one more line in the same file
# (``kind: reply``), never a rewrite. A reply is not a hit: it adds no question and moves
# no date. ``list`` shows each group's latest reply and its status, and by default leaves
# out the groups a reply closed (``resolved``, ``rejected``); ``--status`` picks others.


def _reply(pending: Path, missing: str, *argv: str) -> int:
    return main(["catalog", "pending", "reply", str(pending), "--missing", missing,
                 "--date", "2026-01-09", *argv])


def _two_groups(tmp_path: Path) -> Path:
    return _write(
        tmp_path / "pending.jsonl",
        {"missing": "哪些码算 未接通", "question": "问一", "tables": [LOAN]},
        {"missing": "哪些码算 未接通", "question": "问二", "date": "2026-01-05"},
        {"missing": "豁免的范围", "question": "问三"},
    )


def test_reply_appends_one_reply_line_keyed_by_the_missing_text(tmp_path: Path, capsys) -> None:
    pending = _two_groups(tmp_path)
    before = pending.read_text(encoding="utf-8")
    assert _reply(pending, "哪些码算　未接通 ", "--reply", "码 3、4 算未接通",
                  "--status", "answered", "--by", "owner") == 0
    after = pending.read_text(encoding="utf-8")
    assert after.startswith(before)
    reply = _lines(pending)[-1]
    assert reply == {
        "doc_format": PENDING_FORMAT, "kind": "reply", "date": "2026-01-09",
        "missing": "哪些码算　未接通", "reply": "码 3、4 算未接通", "status": "answered",
        "by": "owner",
    }
    assert "reply" in capsys.readouterr().out.lower()


def test_a_reply_is_not_a_hit_and_moves_no_date(tmp_path: Path, capsys) -> None:
    pending = _two_groups(tmp_path)
    assert _reply(pending, "哪些码算 未接通", "--reply", "码 3、4", "--status", "answered") == 0
    code, report = _list(pending, capsys)
    assert code == 0
    item = next(i for i in report["items"] if i["missing"] == "哪些码算 未接通")
    assert item["hits"] == 2
    assert item["questions"] == ["问一", "问二"]
    assert item["dates"] == {"first": DATE, "last": "2026-01-05"}
    assert item["lines"] == [1, 2]
    assert report["lines"] == 3
    assert report["replies"] == 1


def test_list_shows_each_groups_latest_reply_and_status(tmp_path: Path, capsys) -> None:
    pending = _two_groups(tmp_path)
    assert _reply(pending, "哪些码算 未接通", "--reply", "先按码 3", "--status", "answered") == 0
    assert _reply(pending, "哪些码算 未接通", "--reply", "码 3、4 都算",
                  "--status", "answered", "--by", "owner") == 0
    code, report = _list(pending, capsys)
    assert code == 0
    by_text = {item["missing"]: item for item in report["items"]}
    replied = by_text["哪些码算 未接通"]
    assert replied["status"] == "answered"
    assert replied["reply"] == {
        "reply": "码 3、4 都算", "status": "answered", "by": "owner", "date": "2026-01-09",
        "line": 5,
    }
    assert by_text["豁免的范围"]["status"] == "open"
    assert by_text["豁免的范围"]["reply"] is None
    main(["catalog", "pending", "list", str(pending)])
    text = capsys.readouterr().out
    assert "码 3、4 都算" in text and "先按码 3" not in text
    assert "已答复" in text


def test_list_leaves_out_closed_groups_unless_status_asks(tmp_path: Path, capsys) -> None:
    pending = _two_groups(tmp_path)
    assert _reply(pending, "豁免的范围", "--reply", "目录已有", "--status", "resolved") == 0
    code, report = _list(pending, capsys)
    assert code == 0
    assert [item["missing"] for item in report["items"]] == ["哪些码算 未接通"]
    assert report["status"] == "active" and report["closed"] == 1
    _, report = _list(pending, capsys, "--status", "resolved")
    assert [item["missing"] for item in report["items"]] == ["豁免的范围"]
    _, report = _list(pending, capsys, "--status", "open")
    assert [item["missing"] for item in report["items"]] == ["哪些码算 未接通"]
    _, report = _list(pending, capsys, "--status", "all")
    assert len(report["items"]) == 2
    main(["catalog", "pending", "list", str(pending)])
    assert "1 项已关闭" in capsys.readouterr().out
    # a later reply reopens it: the latest reply decides
    assert _reply(pending, "豁免的范围", "--reply", "还要按产品分", "--status", "answered") == 0
    _, report = _list(pending, capsys)
    assert len(report["items"]) == 2


def test_list_without_replies_prints_what_it_printed_before(tmp_path: Path, capsys) -> None:
    pending = _two_groups(tmp_path)
    code, report = _list(pending, capsys)
    assert code == 0
    assert set(report) == {"doc_format", "lines", "checked", "items", "problems"}
    assert set(report["items"][0]) == {
        "missing", "hits", "questions", "terms", "tables", "columns", "proposed", "dates",
        "lines", "recorded_questions", "in_catalog",
    }
    main(["catalog", "pending", "list", str(pending)])
    assert capsys.readouterr().out == (
        "# 待确认的定义：3 条记录，2 项\n"
        "\n"
        "## 1. 哪些码算 未接通（2 次）\n"
        "- 问到它的问题：问一；问二\n"
        f"- 涉及：{LOAN}\n"
        f"- 记录日期：{DATE} 至 2026-01-05（第 1、2 行）\n"
        "\n"
        "## 2. 豁免的范围（1 次）\n"
        "- 问到它的问题：问三\n"
        f"- 记录日期：{DATE}（第 3 行）\n"
    )


def test_reply_refuses_a_missing_text_no_entry_has(tmp_path: Path, capsys) -> None:
    pending = _two_groups(tmp_path)
    before = pending.read_text(encoding="utf-8")
    assert _reply(pending, "没有记过的东西", "--reply", "x", "--status", "answered") == 1
    assert "没有记过的东西" in capsys.readouterr().err
    assert pending.read_text(encoding="utf-8") == before
    assert _reply(tmp_path / "none.jsonl", "甲", "--reply", "x", "--status", "answered") == 2
    assert not (tmp_path / "none.jsonl").exists()


@pytest.mark.parametrize("argv", [
    ["--reply", "两行\n文字", "--status", "answered"],
    ["--reply", "带控制符\x07", "--status", "answered"],
    ["--reply", "长" * 2001, "--status", "answered"],
    ["--reply", "  ", "--status", "answered"],
    ["--reply", "x", "--status", "answered", "--by", "a\tb"],
    ["--reply", "x", "--status", "answered", "--date", "2026-13-01"],
])
def test_reply_refuses_text_that_does_not_fit_on_one_line(tmp_path: Path, argv: list) -> None:
    pending = _two_groups(tmp_path)
    before = pending.read_text(encoding="utf-8")
    assert _reply(pending, "豁免的范围", *argv) == 2
    assert pending.read_text(encoding="utf-8") == before


def test_reply_takes_only_the_known_statuses(tmp_path: Path) -> None:
    pending = _two_groups(tmp_path)
    with pytest.raises(SystemExit) as raised:
        _reply(pending, "豁免的范围", "--reply", "x", "--status", "done")
    assert raised.value.code == 2


def test_a_malformed_reply_line_is_reported_like_a_malformed_entry(tmp_path: Path, capsys) -> None:
    pending = _two_groups(tmp_path)
    with pending.open("a", encoding="utf-8") as handle:
        for line in (
            {"doc_format": PENDING_FORMAT, "kind": "reply", "date": DATE, "missing": "豁免的范围",
             "reply": "x", "status": "done"},
            {"doc_format": PENDING_FORMAT, "kind": "reply", "date": DATE, "missing": "豁免的范围",
             "status": "resolved"},
            {"doc_format": PENDING_FORMAT, "kind": "reply", "date": DATE, "missing": "谁也没问",
             "reply": "x", "status": "resolved"},
        ):
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
    code, report = _list(pending, capsys)
    assert code == 1
    assert [p["line"] for p in report["problems"]] == [4, 5, 6]
    assert {item["missing"]: item["status"] for item in report["items"]} == {
        "哪些码算 未接通": "open", "豁免的范围": "open",
    }


def test_the_board_shows_a_replied_pending_item_as_answered(tmp_path: Path) -> None:
    from scope_lineage.cli_catalog_answers import questions

    pending = _two_groups(tmp_path)
    assert _reply(pending, "豁免的范围", "--reply", "目录已有", "--status", "resolved") == 0
    document = json.loads(ONTOLOGY.read_text(encoding="utf-8"))
    text = pending.read_text(encoding="utf-8")
    board = questions(document, None, text, status="all", source="pending").result
    status = {item["missing"]: item["status"] for item in board["items"]}
    assert status == {"哪些码算 未接通": "open", "豁免的范围": "answered"}
    replied = next(item for item in board["items"] if item["missing"] == "豁免的范围")
    assert replied["reply"]["reply"] == "目录已有"
    board = questions(document, None, text, source="pending").result
    assert [item["missing"] for item in board["items"]] == ["哪些码算 未接通"]
