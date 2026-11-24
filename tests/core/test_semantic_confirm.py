"""``semantic confirm``: a person's answers written back into table-semantics documents.

A confirmation names one table and one target -- a question, a column's meaning, a
column's code values, or the row statement -- and the answer. Applied, the entry gains
``confirmed`` in its sources (a question becomes ``answered``); a confirmation that
matches nothing is listed, never dropped.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from scope_lineage.semantics import DOC_FORMAT, apply_confirmations, schema_errors

from .table_semantics_demo import (
    CONFIRMATIONS,
    DEMO_TABLE,
    example,
    read_json,
    run,
    write_json,
)


def _confirmation(target: str, value, table: str = DEMO_TABLE) -> dict:
    return {"table": table, "target": target, "value": value, "by": "demo-reviewer",
            "date": "2026-09-26"}


def _apply(*entries: dict):
    documents = {DEMO_TABLE: example()}
    result = apply_confirmations(documents, list(entries))
    return result.documents[DEMO_TABLE], result


def _column(document: dict, name: str) -> dict:
    return next(column for column in document["columns"] if column["column"] == name)


def test_an_answered_question_is_closed_with_its_answer() -> None:
    document, result = _apply(_confirmation("question:q1", "只有 F、M、U。"))
    (question,) = [q for q in document["summary"]["questions"] if q["id"] == "q1"]
    assert question["status"] == "answered"
    assert (question["answer"], question["answered_by"], question["answered_on"]) == (
        "只有 F、M、U。", "demo-reviewer", "2026-09-26",
    )
    assert result.unmatched == []


def test_a_confirmed_meaning_replaces_the_draft_and_is_marked() -> None:
    document, _ = _apply(_confirmation("column:verify_status.meaning", "实名认证状态"))
    column = _column(document, "verify_status")
    assert column["meaning"] == "实名认证状态"
    assert column["sources"][-1] == "confirmed"


def test_confirmed_code_values_replace_the_list_and_each_is_marked() -> None:
    values = [{"value": "F", "meaning": "女"}, {"value": "M", "meaning": "男"}]
    document, _ = _apply(_confirmation("column:gender_cd.code_values", values))
    code_values = _column(document, "gender_cd")["code_values"]
    assert [(c["value"], c["meaning"]) for c in code_values] == [("F", "女"), ("M", "男")]
    assert all("confirmed" in c["sources"] and c["unconfirmed"] is False for c in code_values)


def test_one_confirmed_code_value_is_merged_into_the_list() -> None:
    document, _ = _apply(
        _confirmation("column:gender_cd.code_values", {"value": "U", "meaning": "未填写"})
    )
    code_values = {c["value"]: c for c in _column(document, "gender_cd")["code_values"]}
    assert code_values["U"]["meaning"] == "未填写"
    assert "confirmed" in code_values["U"]["sources"]
    assert "confirmed" not in code_values["F"]["sources"]


def test_a_confirmed_row_statement_is_merged_and_marked() -> None:
    document, _ = _apply(_confirmation("summary.row", {"unique": "yes", "note": "已确认唯一"}))
    row = document["summary"]["row"]
    assert (row["unique"], row["note"]) == ("yes", "已确认唯一")
    assert row["grain_columns"] == ["customer_id"]
    assert row["sources"][-1] == "confirmed"


def test_every_applied_confirmation_is_logged_and_the_document_stays_valid() -> None:
    document, result = _apply(
        _confirmation("question:q1", "只有 F、M、U。"),
        _confirmation("column:verify_status.meaning", "实名认证状态"),
    )
    assert [entry["target"] for entry in document["confirmed"]] == [
        "question:q1", "column:verify_status.meaning",
    ]
    assert len(result.applied) == 2
    assert schema_errors(document, DOC_FORMAT) == []


def test_applying_twice_changes_nothing_the_second_time() -> None:
    entry = _confirmation("column:verify_status.meaning", "实名认证状态")
    once, _ = _apply(entry)
    again = apply_confirmations({DEMO_TABLE: copy.deepcopy(once)}, [entry]).documents[DEMO_TABLE]
    assert again == once


UNMATCHED = {
    "unknown table": (_confirmation("question:q1", "x", table="demo_dwd.nope"), "table"),
    "unknown question": (_confirmation("question:q9", "x"), "question"),
    "unknown column": (_confirmation("column:ghost.meaning", "x"), "column"),
    "meaning not text": (_confirmation("column:verify_status.meaning", ["x"]), "value"),
    "code values not a list": (_confirmation("column:gender_cd.code_values", "F"), "value"),
    "row value off the schema": (_confirmation("summary.row", {"unique": "sure"}), "value"),
}


@pytest.mark.parametrize("name", sorted(UNMATCHED))
def test_a_confirmation_that_matches_nothing_is_listed_not_applied(name: str) -> None:
    entry, word = UNMATCHED[name]
    document, result = _apply(entry)
    assert document == example()
    (unmatched,) = result.unmatched
    assert unmatched["target"] == entry["target"]
    assert word in unmatched["reason"]


# ------------------------------------------------------------------- the command


def _directory(tmp_path: Path) -> Path:
    directory = tmp_path / "semantics"
    write_json(directory / f"{DEMO_TABLE}.json", example())
    return directory


def test_the_command_rewrites_in_place_and_reports(tmp_path: Path, capsys) -> None:
    directory = _directory(tmp_path)
    assert run("semantic", "confirm", directory, "--confirmations", CONFIRMATIONS) == 0
    document = read_json(directory / f"{DEMO_TABLE}.json")
    assert len(document["confirmed"]) == len(read_json(CONFIRMATIONS)["confirmations"])
    out = capsys.readouterr().out
    assert "unmatched=0" in out


def test_out_leaves_the_originals_alone(tmp_path: Path) -> None:
    directory = _directory(tmp_path)
    before = (directory / f"{DEMO_TABLE}.json").read_bytes()
    code = run("semantic", "confirm", directory, "--confirmations", CONFIRMATIONS,
               "--out", tmp_path / "confirmed")
    assert code == 0
    assert (directory / f"{DEMO_TABLE}.json").read_bytes() == before
    assert "confirmed" in read_json(tmp_path / "confirmed" / f"{DEMO_TABLE}.json")


def test_unmatched_confirmations_are_named_in_the_report(tmp_path: Path, capsys) -> None:
    directory = _directory(tmp_path)
    file = write_json(tmp_path / "c.json", {
        "doc_format": "semantic-confirmations/1",
        "confirmations": [_confirmation("column:ghost.meaning", "x")],
    })
    assert run("semantic", "confirm", directory, "--confirmations", file) == 0
    out = capsys.readouterr().out
    assert "unmatched=1" in out
    assert "column:ghost.meaning" in out


def test_a_malformed_confirmations_file_is_a_usage_error(tmp_path: Path) -> None:
    directory = _directory(tmp_path)
    file = write_json(tmp_path / "c.json", {"doc_format": "semantic-confirmations/1",
                                            "confirmations": [{"table": DEMO_TABLE}]})
    assert run("semantic", "confirm", directory, "--confirmations", file) == 2
    assert run("semantic", "confirm", directory, "--confirmations", tmp_path / "none.json") == 2


# ------------------------------------------------------------------- the question asked
#
# A question entry may carry ``asked``, the question's text as the person saw it. With it
# the answer lands only on the question that was asked, and an answer already on disk is
# changed only on ``replace: true``; without it an entry behaves as it always did.

ASKED = "性别码值除了 F、M、U 以外，还会不会出现其他值？"
ANSWER = "只有 F、M、U。"


def _asked(value: str = ANSWER, asked: str = ASKED, **extra) -> dict:
    return {**_confirmation("question:q1", value), "asked": asked, **extra}


def _answered(answer: str = ANSWER, by: str = "demo-reviewer", on: str = "2026-09-26") -> dict:
    document = example()
    document["summary"]["questions"][0].update(status="answered", answer=answer,
                                                answered_by=by, answered_on=on)
    return document


def _apply_to(document: dict, *entries: dict):
    result = apply_confirmations({DEMO_TABLE: document}, list(entries))
    return result.documents[DEMO_TABLE], result


def test_an_answer_to_the_question_asked_is_applied_as_before() -> None:
    with_asked, result = _apply(_asked())
    without, _ = _apply(_confirmation("question:q1", ANSWER))
    assert with_asked == without
    assert (len(result.applied), result.unmatched, result.skipped) == (1, [], [])


def test_an_answer_to_a_rewritten_question_is_not_applied() -> None:
    document, result = _apply(_asked(asked="性别码值从哪个系统来？"))
    assert document == example()
    (unmatched,) = result.unmatched
    assert "rewritten" in unmatched["reason"]
    assert result.applied == [] and result.changed == set()


@pytest.mark.parametrize("asked", [
    "  性别码值除了 F、M、U 以外，还会不会出现其他值？ ",
    "性别码值除了  F、M、U 以外，还会不会出现其他值?",
    "性别码值除了 Ｆ、Ｍ、Ｕ 以外,还会不会出现其他值?",
])
def test_the_question_asked_is_compared_after_nfkc_and_folding_whitespace(asked: str) -> None:
    document, result = _apply(_asked(asked=asked))
    assert result.unmatched == []
    assert document["summary"]["questions"][0]["status"] == "answered"


def test_letter_case_is_part_of_the_question() -> None:
    document, result = _apply(_asked(asked=ASKED.replace("F、M、U", "f、m、u")))
    assert document == example()
    assert "rewritten" in result.unmatched[0]["reason"]


def test_the_same_answer_already_on_disk_is_skipped_and_not_logged_again() -> None:
    on_disk = _answered()
    document, result = _apply_to(copy.deepcopy(on_disk), _asked())
    assert document == on_disk
    assert "confirmed" not in document
    assert (result.applied, result.unmatched, result.changed) == ([], [], set())
    (skipped,) = result.skipped
    assert (skipped["table"], skipped["target"]) == (DEMO_TABLE, "question:q1")


def test_a_different_answer_on_disk_is_not_replaced_without_replace() -> None:
    on_disk = _answered(answer="还会有空值。")
    document, result = _apply_to(copy.deepcopy(on_disk), _asked())
    assert document == on_disk
    (unmatched,) = result.unmatched
    assert "already answered" in unmatched["reason"] and "replace" in unmatched["reason"]


@pytest.mark.parametrize("different", [
    {"answer": "还会有空值。"}, {"by": "another-reviewer"}, {"on": "2026-01-01"},
])
def test_any_difference_on_disk_needs_replace(different: dict) -> None:
    on_disk = _answered(**different)
    _, refused = _apply_to(copy.deepcopy(on_disk), _asked())
    assert len(refused.unmatched) == 1 and refused.skipped == []
    document, replaced = _apply_to(copy.deepcopy(on_disk), _asked(replace=True))
    question = document["summary"]["questions"][0]
    assert (question["answer"], question["answered_by"], question["answered_on"]) == (
        ANSWER, "demo-reviewer", "2026-09-26")
    assert len(replaced.applied) == 1 and replaced.changed == {DEMO_TABLE}


def test_replace_does_not_override_a_rewritten_question() -> None:
    document, result = _apply_to(_answered(answer="x"), _asked(asked="另一个问题？", replace=True))
    assert document == _answered(answer="x")
    assert "rewritten" in result.unmatched[0]["reason"]


def test_without_asked_an_answered_question_is_still_overwritten() -> None:
    """The old behaviour, whatever ``replace`` says when ``asked`` is absent."""
    for extra in ({}, {"replace": False}, {"replace": True}):
        entry = {**_confirmation("question:q1", ANSWER), **extra}
        document, result = _apply_to(_answered(answer="还会有空值。"), entry)
        plain, _ = _apply_to(_answered(answer="还会有空值。"), _confirmation("question:q1", ANSWER))
        assert document == plain
        assert document["summary"]["questions"][0]["answer"] == ANSWER
        assert len(result.applied) == 1 and result.skipped == []


def test_asked_on_a_target_that_is_not_a_question_is_refused() -> None:
    entry = {**_confirmation("column:verify_status.meaning", "实名认证状态"), "asked": ASKED}
    document, result = _apply(entry)
    assert document == example()
    assert "question" in result.unmatched[0]["reason"]


def test_the_example_confirmations_give_the_same_documents_and_report(
    tmp_path: Path, capsys
) -> None:
    """The example carries no ``asked``: two runs in place, then ``--out``, report what they
    always did, and adding ``replace`` to every entry changes no byte."""
    plain = _directory(tmp_path / "plain")
    lines = []
    for extra in ([], [], ["--out", tmp_path / "out"]):
        assert run("semantic", "confirm", plain, "--confirmations", CONFIRMATIONS, *extra) == 0
        lines.append(capsys.readouterr().out)
    assert lines == [
        "Applied 4 confirmation(s) to 1 table(s) (unmatched=0)\n",
        "Applied 4 confirmation(s) to 0 table(s) (unmatched=0)\n",
        "Applied 4 confirmation(s) to 0 table(s) (unmatched=0)\n",
    ]
    for flag in (False, True):
        other = _directory(tmp_path / f"replace-{flag}")
        entries = read_json(CONFIRMATIONS)
        for entry in entries["confirmations"]:
            entry["replace"] = flag
        file = write_json(tmp_path / f"replace-{flag}.json", entries)
        assert run("semantic", "confirm", other, "--confirmations", file) == 0
        assert capsys.readouterr().out == lines[0]
        assert (other / f"{DEMO_TABLE}.json").read_bytes() == (
            plain / f"{DEMO_TABLE}.json").read_bytes()


def test_the_command_counts_and_names_the_skipped(tmp_path: Path, capsys) -> None:
    directory = tmp_path / "semantics"
    write_json(directory / f"{DEMO_TABLE}.json", _answered())
    before = (directory / f"{DEMO_TABLE}.json").read_bytes()
    file = write_json(tmp_path / "c.json", {"doc_format": "semantic-confirmations/1",
                                            "confirmations": [_asked()]})
    assert run("semantic", "confirm", directory, "--confirmations", file) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "Applied 0 confirmation(s) to 0 table(s) (unmatched=0, skipped=1)"
    assert f"  skipped: {DEMO_TABLE} question:q1: " in out
    assert (directory / f"{DEMO_TABLE}.json").read_bytes() == before


def test_the_schema_takes_asked_and_replace_and_nothing_else() -> None:
    def errors(**extra):
        return schema_errors({"doc_format": "semantic-confirmations/1",
                              "confirmations": [{**_confirmation("question:q1", "x"), **extra}]},
                             "semantic-confirmations/1")
    assert errors(asked=ASKED, replace=True) == []
    assert errors(asked="") and errors(replace="yes") and errors(seen="x")
