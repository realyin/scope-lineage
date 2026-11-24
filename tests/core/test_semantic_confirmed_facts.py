"""The owner's confirmations as the source of truth: read once, held by every check.

A run keeps its ``semantic-confirmations/1`` files in ``confirmations/``. Checks 3 and 4
read them: a code value the owner confirmed needs no comment or SQL behind it, and a
document that drops, downgrades or rewrites what was confirmed fails. ``semantic confirm``
replays them after every write, and ``semantic facts`` prints them for a writer. Without
any confirmations file every output is what it always was.

Every fixture is the example document (or its packet) with one thing changed, and one
confirmations file with the entry the test is about.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import shutil
from pathlib import Path

import pytest

from scope_lineage.semantics import apply_confirmations, validate_document
from scope_lineage.semantics.confirmed import ConfirmationsError, read_confirmations

from .table_semantics_demo import (
    CONFIRMATIONS,
    DEMO_TABLE,
    demo_packets,
    example,
    packet_of,
    read_json,
    run,
    write_json,
)

OTHER_TABLE = "demo_dwd.dwd_lending_borrower_df"


@pytest.fixture(scope="module")
def packets(tmp_path_factory) -> Path:
    return demo_packets(tmp_path_factory.mktemp("confirmed"))


@pytest.fixture(scope="module")
def packet(packets: Path) -> dict:
    return packet_of(packets)


@pytest.fixture
def document(packets: Path) -> dict:
    return example(packets)


def _entry(target: str, value, table: str = DEMO_TABLE, **extra) -> dict:
    return {"table": table, "target": target, "value": value, "by": "demo-reviewer",
            "date": "2026-09-26", **extra}


def _file(path: Path, *entries: dict) -> Path:
    return write_json(path, {"doc_format": "semantic-confirmations/1",
                             "confirmations": list(entries)})


def _confirmations(tmp_path: Path, *entries: dict):
    return read_confirmations(_file(tmp_path / "confirmations" / "c.json", *entries))


def _column(document: dict, name: str) -> dict:
    return next(column for column in document["columns"] if column["column"] == name)


def _index(document: dict, name: str) -> int:
    return next(i for i, column in enumerate(document["columns"]) if column["column"] == name)


def _problems(report: dict, check: str, status: str = "fail") -> list[dict]:
    return [f for f in report["failures"] if f["check"] == check and f["status"] == status]


X = {"value": "X", "meaning": "其他"}


def _with_x(document: dict, **extra) -> dict:
    """The motivating case: a code value no comment and no SQL mentions."""
    _column(document, "gender_cd")["code_values"].append({**X, "sources": ["confirmed"], **extra})
    return document


# ------------------------------------------------------------------- reading


def test_a_directory_is_read_in_file_name_order_and_later_entries_win(tmp_path: Path) -> None:
    directory = tmp_path / "confirmations"
    _file(directory / "b.json", _entry("column:gender_cd.code_values", {"value": "U", "meaning": "未填写"}),
          _entry("column:verify_status.meaning", "第二次"))
    _file(directory / "a.json", _entry("column:gender_cd.code_values",
                                       [{"value": "F", "meaning": "女"}, {"value": "U", "meaning": "未知"}]),
          _entry("column:verify_status.meaning", "第一次"))
    write_json(directory / "other.json", {"doc_format": "something-else/1"})
    (directory / "notes.txt").write_text("not json", encoding="utf-8")
    confirmations = read_confirmations(directory)
    assert [Path(f).name for f in confirmations.files] == ["a.json", "b.json"]
    state = confirmations.for_table(f"catalog.{DEMO_TABLE.upper()}")
    assert state.code_meanings("gender_cd") == {"F": "女", "U": "未填写"}
    assert state.meanings["verify_status"].value == "第二次"


def test_a_list_replaces_the_confirmed_values_and_an_object_merges(tmp_path: Path) -> None:
    state = _confirmations(
        tmp_path,
        _entry("column:gender_cd.code_values", {"value": "U", "meaning": "未知"}),
        _entry("column:gender_cd.code_values", [{"value": "F", "meaning": "女"}]),
        _entry("column:gender_cd.code_values", {"value": "M", "meaning": "男"}),
        _entry("summary.row", {"unique": "no"}),
        _entry("summary.row", "一行一个客户"),
        _entry("summary.row", {"unique": "sure"}),  # refused by confirm: adds nothing
    ).for_table(DEMO_TABLE)
    assert state.code_meanings("gender_cd") == {"F": "女", "M": "男"}
    assert state.row_fields() == {"unique": "no", "text": "一行一个客户"}


def test_a_directory_without_confirmations_reads_as_none(tmp_path: Path) -> None:
    (tmp_path / "confirmations").mkdir()
    assert read_confirmations(tmp_path / "confirmations") is None


def test_a_malformed_confirmations_file_is_an_error(tmp_path: Path) -> None:
    directory = tmp_path / "confirmations"
    _file(directory / "a.json", {"table": DEMO_TABLE})
    with pytest.raises(ConfirmationsError):
        read_confirmations(directory)
    (directory / "a.json").write_text("{", encoding="utf-8")
    with pytest.raises(ConfirmationsError):
        read_confirmations(directory)
    with pytest.raises(ConfirmationsError):
        read_confirmations(tmp_path / "none")


# ------------------------------------------------------------------- check 3


def test_a_confirmed_code_value_in_no_comment_and_no_sql_passes(
    tmp_path: Path, document: dict, packet: dict
) -> None:
    _with_x(document)
    assert len(_problems(validate_document(document, packet), "code_values")) == 1
    confirmations = _confirmations(tmp_path, _entry("column:gender_cd.code_values", X))
    report = validate_document(document, packet, confirmations=confirmations)
    assert report["failures"] == []


def test_an_unconfirmed_value_without_evidence_still_fails_as_before(
    tmp_path: Path, document: dict, packet: dict
) -> None:
    _column(document, "gender_cd")["code_values"].append(
        {"value": "Y", "meaning": "另一个", "sources": ["inferred"]})
    before = validate_document(document, packet)
    confirmations = _confirmations(tmp_path, _entry("column:gender_cd.code_values", X))
    _with_x(document)
    after = validate_document(document, packet, confirmations=confirmations)
    assert _problems(after, "code_values") == _problems(before, "code_values")
    (problem,) = _problems(after, "code_values")
    assert "unconfirmed: true" in problem["message"]


def test_a_confirmation_of_another_table_passes_nothing_here(
    tmp_path: Path, document: dict, packet: dict
) -> None:
    _with_x(document)
    confirmations = _confirmations(
        tmp_path, _entry("column:gender_cd.code_values", X, table=OTHER_TABLE))
    report = validate_document(document, packet, confirmations=confirmations)
    (problem,) = _problems(report, "code_values")
    assert "在注释和 SQL 里都找不到" in problem["message"]


def _owner_problem(report: dict) -> dict:
    (problem,) = _problems(report, "code_values")
    assert "owner" in problem["message"] and "确认文件" in problem["message"]
    assert "标 unconfirmed: true 并" not in problem["message"]
    return problem


def test_a_confirmed_value_marked_unconfirmed_fails(
    tmp_path: Path, document: dict, packet: dict
) -> None:
    _with_x(document, unconfirmed=True)
    confirmations = _confirmations(tmp_path, _entry("column:gender_cd.code_values", X))
    problem = _owner_problem(validate_document(document, packet, confirmations=confirmations))
    assert problem["at"] == f"columns[{_index(document, 'gender_cd')}].code_values[3]"


def test_a_confirmed_value_with_another_meaning_fails(
    tmp_path: Path, document: dict, packet: dict
) -> None:
    _column(document, "gender_cd")["code_values"][2]["meaning"] = "未填写"
    confirmations = _confirmations(
        tmp_path, _entry("column:gender_cd.code_values", {"value": "U", "meaning": "未知"}))
    problem = _owner_problem(validate_document(document, packet, confirmations=confirmations))
    assert "未知" in problem["message"] and "未填写" in problem["message"]


def test_a_meaning_spelt_otherwise_is_the_same_meaning(
    tmp_path: Path, document: dict, packet: dict
) -> None:
    _column(document, "gender_cd")["code_values"][2]["meaning"] = " 未知 "
    confirmations = _confirmations(
        tmp_path, _entry("column:gender_cd.code_values", {"value": "U", "meaning": "未知"}))
    assert validate_document(document, packet, confirmations=confirmations)["failures"] == []


def test_a_confirmed_value_the_document_left_out_fails(
    tmp_path: Path, document: dict, packet: dict
) -> None:
    confirmations = _confirmations(tmp_path, _entry("column:gender_cd.code_values", X))
    problem = _owner_problem(validate_document(document, packet, confirmations=confirmations))
    assert problem["at"] == f"columns[{_index(document, 'gender_cd')}].code_values"
    assert "'X'" in problem["message"]


def _constant(packet: dict, column: str, *literals: str) -> dict:
    packet = copy.deepcopy(packet)
    for entry in packet["lineage"]["columns"]:
        if entry["column"] == column:
            for producer in entry["producers"]:
                producer.update(constant_only=True, literal_outputs=list(literals))
    return packet


def test_a_confirmation_against_a_constant_column_does_not_pass(
    tmp_path: Path, document: dict, packet: dict
) -> None:
    constant = _constant(packet, "verify_status", "'1'")
    plain = _problems(validate_document(document, constant), "code_values")
    assert [p["at"] for p in plain] == [f"columns[{_index(document, 'verify_status')}].code_values[1]"]
    confirmations = _confirmations(
        tmp_path, _entry("column:verify_status.code_values", {"value": "0", "meaning": "未实名"}))
    report = validate_document(document, constant, confirmations=confirmations)
    (problem,) = _problems(report, "code_values")
    assert problem["at"] == plain[0]["at"]
    assert "矛盾" in problem["message"] and "owner" in problem["message"]
    del _column(document, "verify_status")["code_values"][1]
    (left_out,) = _problems(validate_document(document, constant, confirmations=confirmations),
                            "code_values")
    assert "矛盾" in left_out["message"]


def test_a_confirmed_empty_value_the_sql_never_writes_does_not_pass(
    tmp_path: Path, document: dict, packet: dict
) -> None:
    _column(document, "gender_cd")["code_values"].append(
        {"value": "", "meaning": "未填", "sources": ["confirmed"]})
    confirmations = _confirmations(
        tmp_path, _entry("column:gender_cd.code_values", {"value": "", "meaning": "未填"}))
    (problem,) = _problems(validate_document(document, packet, confirmations=confirmations),
                           "code_values")
    assert "矛盾" in problem["message"]


# ------------------------------------------------------------------- check 4


@pytest.mark.parametrize("confirmed, written, at", [
    ({"grain_columns": ["customer_id", "dt"]}, {}, "summary.row.grain_columns"),
    ({"unique": "no", "grain_source": "declared"}, {}, "summary.row.unique"),
    ({"unique": "yes"}, {"grain_source": "inferred"}, "summary.row.grain_source"),
])
def test_a_document_off_the_confirmed_row_fails_grain(
    tmp_path: Path, document: dict, packet: dict, confirmed: dict, written: dict, at: str
) -> None:
    document["summary"]["row"].update(written)
    confirmations = _confirmations(tmp_path, _entry("summary.row", confirmed))
    problems = _problems(validate_document(document, packet, confirmations=confirmations), "grain")
    assert at in [p["at"] for p in problems]
    assert all("owner" in p["message"] for p in problems if p["at"] == at)


def test_a_document_on_the_confirmed_row_passes(
    tmp_path: Path, document: dict, packet: dict
) -> None:
    confirmations = _confirmations(
        tmp_path, _entry("summary.row", {"grain_columns": ["customer_id"], "unique": "yes"}))
    report = validate_document(document, packet, confirmations=confirmations)
    assert report["failures"] == []
    assert report["checks"]["grain"]["pass"] > validate_document(document, packet)["checks"][
        "grain"]["pass"]


# ------------------------------------------------------------------- the commands


def _run(*argv) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = run(*argv)
    return code, out.getvalue(), err.getvalue()


def _stage(report: dict) -> str:
    return next(entry["stage"] for entry in report["tables"] if entry["table"] == DEMO_TABLE)


def _run_dir(tmp_path: Path, packets: Path, document: dict) -> Path:
    directory = tmp_path / "run"
    shutil.copytree(packets, directory / "packets")
    write_json(directory / "docs" / f"{DEMO_TABLE}.json", document)
    return directory


def _outputs(run_dir: Path) -> list:
    docs, packets = run_dir / "docs", run_dir / "packets"
    return [
        _run("semantic", "validate", docs, "--packets", packets),
        _run("semantic", "validate", docs, "--packets", packets, "--json"),
        _run("semantic", "status", run_dir, "--json"),
        _run("semantic", "status", run_dir),
        _run("semantic", "render", docs, "--out", run_dir / "pages"),
    ]


def test_without_confirmations_every_output_is_unchanged(
    tmp_path: Path, packets: Path, document: dict
) -> None:
    run_dir = _run_dir(tmp_path, packets, _with_x(document))
    absent = _outputs(run_dir)
    (run_dir / "confirmations").mkdir()
    write_json(run_dir / "confirmations" / "notes.json", {"doc_format": "something-else/1"})
    assert _outputs(run_dir) == absent
    validated, as_json, status, _, rendered = absent
    assert validated[0] == 1 and validated[2] == ""
    assert "confirmations" not in json.loads(as_json[1])
    assert "confirmations" not in json.loads(status[1])["directories"]
    assert "invalid" in rendered[2]


def test_the_run_confirmations_are_read_by_default_and_announced(
    tmp_path: Path, packets: Path, document: dict
) -> None:
    run_dir = _run_dir(tmp_path, packets, _with_x(document))
    _file(run_dir / "confirmations" / "c.json", _entry("column:gender_cd.code_values", X))
    validated, as_json, status, text, rendered = _outputs(run_dir)
    assert validated[0] == 0 and "confirmations: " in validated[2]
    report = json.loads(as_json[1])
    assert report["summary"]["clean"] == 1
    assert report["confirmations"]["entries"] == 1
    status_report = json.loads(status[1])
    assert _stage(status_report) == "valid"
    assert status_report["directories"]["confirmations"] == str(run_dir / "confirmations")
    assert "invalid" not in rendered[2]


def test_the_flag_names_the_confirmations_wherever_they_are(
    tmp_path: Path, packets: Path, document: dict
) -> None:
    run_dir = _run_dir(tmp_path, packets, _with_x(document))
    file = _file(tmp_path / "elsewhere.json", _entry("column:gender_cd.code_values", X))
    docs, packets_dir = run_dir / "docs", run_dir / "packets"
    assert _run("semantic", "validate", docs, "--packets", packets_dir,
                "--confirmations", file)[0] == 0
    code, out, _ = _run("semantic", "status", run_dir, "--json", "--confirmations", file)
    assert _stage(json.loads(out)) == "valid"
    assert "invalid" not in _run("catalog", "digest", docs, "--out", tmp_path / "digest",
                                 "--confirmations", file)[2]
    assert "invalid" in _run("catalog", "digest", docs, "--out", tmp_path / "digest")[2]


def test_a_malformed_confirmations_file_is_a_usage_error_everywhere(
    tmp_path: Path, packets: Path, document: dict
) -> None:
    run_dir = _run_dir(tmp_path, packets, document)
    _file(run_dir / "confirmations" / "c.json", {"table": DEMO_TABLE})
    docs = run_dir / "docs"
    for argv in (
        ("semantic", "validate", docs, "--packets", run_dir / "packets"),
        ("semantic", "status", run_dir),
        ("semantic", "fixed", run_dir, "--only", DEMO_TABLE),
        ("semantic", "render", docs, "--out", run_dir / "pages"),
        ("semantic", "confirm", docs, "--confirmations", run_dir / "confirmations"),
        ("semantic", "facts", "--confirmations", run_dir / "confirmations", "--table", DEMO_TABLE),
        ("catalog", "digest", docs, "--out", run_dir / "digest"),
    ):
        code, _, err = _run(*argv)
        assert code == 2, argv
        assert "--confirmations" in err


# ------------------------------------------------------------------- replay


def _replay_entries() -> list[dict]:
    asked = example()["summary"]["questions"][0]["text"]
    return [
        _entry("column:gender_cd.code_values",
               [{"value": "F", "meaning": "女"}, {"value": "M", "meaning": "男"},
                {"value": "U", "meaning": "未知"}]),
        _entry("column:gender_cd.code_values", X),
        _entry("column:verify_status.meaning", "实名认证状态"),
        _entry("summary.row", {"unique": "yes", "note": "同一个 dt 分区内按客户号唯一，业务方已确认。"}),
        _entry("question:q1", "不会。", asked=asked),
    ]


def test_replaying_the_confirmations_twice_changes_no_byte(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    write_json(docs / f"{DEMO_TABLE}.json", example())
    directory = tmp_path / "confirmations"
    entries = _replay_entries()
    _file(directory / "a.json", *entries[:3])
    _file(directory / "b.json", *entries[3:])
    code, first, _ = _run("semantic", "confirm", docs, "--confirmations", directory)
    assert code == 0 and first.startswith("Applied 5 confirmation(s) to 1 table(s) (unmatched=0)")
    once = (docs / f"{DEMO_TABLE}.json").read_bytes()
    code, second, _ = _run("semantic", "confirm", docs, "--confirmations", directory)
    assert code == 0
    assert second.splitlines()[0] == (
        "Applied 4 confirmation(s) to 0 table(s) (unmatched=0, skipped=1)")
    assert (docs / f"{DEMO_TABLE}.json").read_bytes() == once
    # The two code-value entries share target, person and date: one log line.
    assert len(json.loads(once)["confirmed"]) == 4


def test_a_merge_after_a_replace_is_replayed_without_a_change(tmp_path: Path) -> None:
    entries = [_replay_entries()[0],
               _entry("column:gender_cd.code_values", {"value": "U", "meaning": "未填写"})]
    once = apply_confirmations({DEMO_TABLE: example()}, entries)
    again = apply_confirmations(copy.deepcopy(once.documents), entries)
    assert again.documents == once.documents
    assert again.changed == set()


def test_replaying_onto_a_rewritten_document_restores_the_confirmed_slots(
    tmp_path: Path, packets: Path, document: dict
) -> None:
    run_dir = _run_dir(tmp_path, packets, document)
    _file(run_dir / "confirmations" / "c.json", *_replay_entries(),
          _entry("summary.row", {"grain_source": "declared"}))
    docs = run_dir / "docs"
    with pytest.raises(SystemExit):  # --confirmations is required
        _run("semantic", "confirm", docs)
    assert _run("semantic", "confirm", docs, "--confirmations", run_dir / "confirmations")[0] == 0
    confirmed = read_json(docs / f"{DEMO_TABLE}.json")
    rewritten = example(packets)  # a rewrite: none of the confirmed slots, no log
    gender = _column(rewritten, "gender_cd")["code_values"]
    gender[2].update(meaning="未填写", unconfirmed=True)
    _column(rewritten, "verify_status")["meaning"] = "实名标志"
    rewritten["summary"]["row"].update(unique="unknown", grain_source="inferred")
    write_json(docs / f"{DEMO_TABLE}.json", rewritten)
    assert _run("semantic", "validate", docs, "--packets", run_dir / "packets")[0] == 1
    assert _run("semantic", "confirm", docs, "--confirmations", run_dir / "confirmations")[0] == 0
    assert read_json(docs / f"{DEMO_TABLE}.json") == confirmed
    assert _run("semantic", "validate", docs, "--packets", run_dir / "packets")[0] == 0


# ------------------------------------------------------------------- facts


def test_facts_prints_one_confirmed_fact_per_line(tmp_path: Path) -> None:
    directory = tmp_path / "confirmations"
    directory.mkdir()
    shutil.copy(CONFIRMATIONS, directory / "a.json")
    _file(directory / "b.json",
          _entry("question:q10", "按\n环境唯一", asked="编号在哪个范围内唯一？"),
          _entry("summary.row", {"grain_columns": ["customer_id", "dt"],
                                 "grain_source": "declared"}),
          _entry("column:gender_cd.code_values", X))
    code, out, err = _run("semantic", "facts", "--confirmations", directory,
                          "--table", DEMO_TABLE, "--table", OTHER_TABLE)
    assert (code, err) == (0, "")
    by = "（demo-reviewer 于 2026-09-26 确认）"
    assert out == "\n".join([
        f"表 {DEMO_TABLE} 已确认的事实：",
        f"- 行粒度列：customer_id、dt{by}",
        f"- 行粒度来源：声明（grain_source: declared）{by}",
        f"- 按粒度列唯一：是（unique: yes）{by}",
        f"- 行的说明：同一个 dt 分区内按客户号唯一，业务方已确认。{by}",
        f"- 列 verify_status 的含义：实名认证状态{by}",
        f"- 列 gender_cd 的码值「F」：女{by}",
        f"- 列 gender_cd 的码值「M」：男{by}",
        f"- 列 gender_cd 的码值「U」：未知{by}",
        f"- 列 gender_cd 的码值「X」：其他{by}",
        f"- 问题 q1 的回答：不会。注册系统只允许 F、M、U 三个值。{by}",
        f"- 问题 q10（问：编号在哪个范围内唯一？）的回答：按 环境唯一{by}",
        f"表 {OTHER_TABLE} 已确认的事实：",
        "无",
    ]) + "\n"


def test_facts_needs_a_table_and_confirmations(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        _run("semantic", "facts", "--confirmations", CONFIRMATIONS)
    assert _run("semantic", "facts", "--table", DEMO_TABLE,
                "--confirmations", tmp_path / "none")[0] == 2
    (tmp_path / "empty").mkdir()
    assert _run("semantic", "facts", "--table", DEMO_TABLE, "--confirmations",
                tmp_path / "empty") == (0, f"表 {DEMO_TABLE} 已确认的事实：\n无\n", "")


@pytest.mark.parametrize("value, word", [
    ({"unique": "no"}, "否（unique: no）"), ({"unique": "unknown"}, "未知（unique: unknown）"),
    ({"grain_source": "inferred"}, "推断（grain_source: inferred）"),
    ({"grain_source": "proven"}, "血缘证明（grain_source: proven）"),
])
def test_facts_says_the_row_enums_in_words_with_the_field_value(
    tmp_path: Path, value: dict, word: str
) -> None:
    file = _file(tmp_path / "c.json", _entry("summary.row", value))
    out = _run("semantic", "facts", "--confirmations", file, "--table", DEMO_TABLE)[1]
    assert f"：{word}（demo-reviewer" in out


# ------------------------------------------------------------------- a row confirmed without its source


@pytest.mark.parametrize("confirmed", [{"unique": "yes"}, {"grain_columns": ["customer_id"]}])
def test_a_confirmed_row_replayed_onto_an_inferred_grain_makes_it_declared(
    tmp_path: Path, packets: Path, document: dict, confirmed: dict
) -> None:
    document["summary"]["row"]["grain_source"] = "inferred"
    run_dir = _run_dir(tmp_path, packets, document)
    _file(run_dir / "confirmations" / "c.json", _entry("summary.row", confirmed))
    docs = run_dir / "docs"
    assert _run("semantic", "validate", docs, "--packets", run_dir / "packets")[0] == 1
    assert _run("semantic", "confirm", docs, "--confirmations", run_dir / "confirmations")[0] == 0
    once = (docs / f"{DEMO_TABLE}.json").read_bytes()
    assert json.loads(once)["summary"]["row"]["grain_source"] == "declared"
    assert _run("semantic", "validate", docs, "--packets", run_dir / "packets")[0] == 0
    code, out, _ = _run("semantic", "confirm", docs, "--confirmations", run_dir / "confirmations")
    assert code == 0 and "to 0 table(s)" in out
    assert (docs / f"{DEMO_TABLE}.json").read_bytes() == once


def test_a_confirmed_row_leaves_a_proven_or_declared_grain_and_an_explicit_source_wins() -> None:
    for written in ("proven", "declared"):
        document = example()
        document["summary"]["row"]["grain_source"] = written
        result = apply_confirmations({DEMO_TABLE: document}, [_entry("summary.row", {"unique": "yes"})])
        assert result.documents[DEMO_TABLE]["summary"]["row"]["grain_source"] == written
    document = example()
    document["summary"]["row"]["grain_source"] = "inferred"
    explicit = _entry("summary.row", {"unique": "yes", "grain_source": "inferred"})
    result = apply_confirmations({DEMO_TABLE: document}, [explicit])
    assert result.documents[DEMO_TABLE]["summary"]["row"]["grain_source"] == "inferred"
    text_only = apply_confirmations({DEMO_TABLE: copy.deepcopy(document)},
                                    [_entry("summary.row", "一行一个客户")])
    assert text_only.documents[DEMO_TABLE]["summary"]["row"]["grain_source"] == "inferred"


# ------------------------------------------------------------------- semantic fixed


def test_fixed_judges_the_document_against_the_run_confirmations(
    tmp_path: Path, packets: Path, document: dict
) -> None:
    """A revision whose document holds a value only the owner confirmed: refused as invalid
    without the confirmations, recorded with them."""
    from scope_lineage.semantics.digests import document_digest

    run_dir = _run_dir(tmp_path, packets, document)
    review = run_dir / "reviews" / f"{DEMO_TABLE}.md"
    review.parent.mkdir(parents=True)
    review.write_text(
        f"---\nreviewed_doc_digest: {document_digest(document)}\n"
        f"reviewed_packet_digest: {document['packet_digest']}\nhigh: 1\nmedium: 0\nlow: 0\n---\n"
        "# 审读\n", encoding="utf-8")
    write_json(run_dir / "docs" / f"{DEMO_TABLE}.json", _with_x(copy.deepcopy(document)))
    code, _, err = _run("semantic", "fixed", run_dir, "--only", DEMO_TABLE)
    assert code == 1 and "invalid" in err
    assert "fixed_doc_digest" not in review.read_text(encoding="utf-8")
    _file(run_dir / "confirmations" / "c.json", _entry("column:gender_cd.code_values", X))
    code, out, err = _run("semantic", "fixed", run_dir, "--only", DEMO_TABLE)
    assert code == 0 and "fixed_doc_digest" in out
    assert "confirmations: " in err
    assert "fixed_doc_digest" in review.read_text(encoding="utf-8")
