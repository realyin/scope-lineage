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
