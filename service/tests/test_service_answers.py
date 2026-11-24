"""The page's answers: the record file, the ordered judgement, the overlay and its deletes.

Each test answers through ``CatalogState`` as ``POST /api/answers`` does (the request held
to its fields by the HTTP server's own ``_answer_request``), then changes the documents on
disk the way a rewrite or ``semantic confirm`` would, and looks at what the state judges,
overlays, exports and keeps in the file.
"""

from __future__ import annotations

import json
import os
import stat
import threading

import pytest
from answer_fixtures import (
    answer_on_disk,
    prepare,
    read_document,
    set_question,
    text_of,
    touch_later,
)
from service_paths import CUSTOMER, LOAN

from scope_lineage import cli_catalog_answers as core
from scope_lineage_service import answers as records_file
from scope_lineage_service.http_server import _answer_request
from scope_lineage_service.state import AnswerRefused, AnswersUnavailable, CatalogState


@pytest.fixture
def paths(inputs, tmp_path):
    prepare(inputs["semantics"])
    return {**inputs, "answers": tmp_path / "answers.json"}


def _state(paths, writer=True, **extra) -> CatalogState:
    return CatalogState(str(paths["ontology"]), semantics=str(paths["semantics"]),
                        answers=str(paths["answers"]), answers_writer=writer,
                        today=lambda: "2026-11-23", **extra)


def seen_of(state: CatalogState, table: str, question: str) -> dict:
    """What a page shows of one question: the disk's answer and the page record."""
    current = state.inputs()
    disk = records_file.disk_answer(
        records_file.find_question(current.disk_semantics, table, question))
    return {"disk": disk, "record": current.answers.record(table, question)}


def post(state, table, question, text="不会。", *, kind="answer", by="审核人甲", choice=None,
         to=None, asked=None, seen=None):
    payload = {"table": table, "question": question, "kind": kind, "by": by,
               "asked": asked if asked is not None else _asked(state, table, question),
               "seen": seen if seen is not None else seen_of(state, table, question)}
    payload["answer" if kind == "answer" else "reason"] = text
    if choice:
        payload["choice"] = choice
    if to:
        payload["to"] = to
    return state.save_answer(_answer_request(payload))


def _asked(state, table, question):
    found = records_file.find_question(state.inputs().disk_semantics, table, question)
    return found["text"] if found else "不存在的问题"


def file_records(paths) -> list[dict]:
    return json.loads(paths["answers"].read_text(encoding="utf-8"))["answers"]


def question_of(semantics, table, question):
    return next(q for q in semantics[table]["summary"]["questions"] if q["id"] == question)


def judged(state, table, question):
    view = state.inputs().answers
    for item in view.effective + view.unmatched:
        if (item.record["table"], item.record["question"]) == (table, question):
            return item
    return None


# ------------------------------------------------------------------ no answers file


def test_without_an_answers_file_nothing_changes(inputs) -> None:
    state = CatalogState(str(inputs["ontology"]), semantics=str(inputs["semantics"]))
    current = state.inputs()

    assert current.page_states is None and current.answers is None
    assert current.semantics is current.on_disk
    assert "answers" not in state.health()
    assert state.health()["writes"] == []


def test_health_lists_the_files_the_server_writes(paths) -> None:
    state = CatalogState(str(paths["ontology"]), pending=str(paths["pending"]),
                         answers=str(paths["answers"]), answers_writer=True)
    health = state.health()

    assert "read_only" not in health
    assert health["writes"] == ["pending.jsonl", "answers.json"]
    assert health["answers"] == {"path": "answers.json", "writer": True, "status": "ok",
                                 "records": 0, "effective": 0, "unmatched": 0}
    reader = CatalogState(str(paths["ontology"]), answers=str(paths["answers"]))
    assert reader.health()["writes"] == [] and reader.health()["answers"]["writer"] is False


# ------------------------------------------------------------------ the record file


def test_an_answer_is_one_record_in_the_file(paths) -> None:
    state = _state(paths)
    record = post(state, CUSTOMER, "q1", "不会。只有三个值。", choice="no")

    assert file_records(paths) == [record]
    assert record == {
        "table": CUSTOMER, "question": "q1", "asked": text_of(paths["semantics"], CUSTOMER, "q1"),
        "base": None, "kind": "answer", "answer": "不会。只有三个值。", "choice": "no",
        "source": {"kind": "person"}, "by": "审核人甲", "date": "2026-11-23",
    }
    document = json.loads(paths["answers"].read_text(encoding="utf-8"))
    assert document["doc_format"] == "question-answers/1"
    assert records_file.check_document(document) == [record]


def test_a_new_record_replaces_the_old_one(paths) -> None:
    state = _state(paths)
    post(state, CUSTOMER, "q1", "暂时不知道", kind="deferred")
    post(state, CUSTOMER, "q1", "不会。")

    assert [(r["question"], r["kind"]) for r in file_records(paths)] == [("q1", "answer")]


@pytest.mark.parametrize("record, problem", [
    ({"answer": "a\nb"}, "line break"),
    ({"by": "x" * 61}, "at most 60"),
    ({"kind": "deferred"}, "has reason, not answer"),
    ({"choice": "maybe"}, "choice"),
    ({"base": {"answer": "x"}}, "base"),
    ({"table": "Demo.T"}, "lower case"),
    ({"extra": 1}, "unknown key"),
])
def test_an_illegal_record_makes_the_file_unreadable(paths, record, problem) -> None:
    good = {"table": CUSTOMER, "question": "q1", "asked": "?", "base": None, "kind": "answer",
            "answer": "x", "source": {"kind": "person"}, "by": "甲", "date": "2026-11-23"}
    paths["answers"].write_text(json.dumps(
        {"doc_format": "question-answers/1", "answers": [{**good, **record}]}), encoding="utf-8")
    state = _state(paths)

    view = state.inputs().answers
    assert view.status == "unreadable" and problem in view.reason


def test_two_records_for_one_question_make_the_file_unreadable(paths) -> None:
    record = {"table": CUSTOMER, "question": "q1", "asked": "?", "base": None, "kind": "answer",
              "answer": "x", "source": {"kind": "person"}, "by": "甲", "date": "2026-11-23"}
    paths["answers"].write_text(json.dumps(
        {"doc_format": "question-answers/1", "answers": [record, record]}), encoding="utf-8")

    assert "a second record" in _state(paths).inputs().answers.reason


# ------------------------------------------------------------------ judgement of answers


def test_row_1_a_table_or_question_that_is_gone_is_not_matched(paths) -> None:
    state = _state(paths)
    post(state, LOAN, "q2", "元。")
    post(state, CUSTOMER, "q3", "已认证与未认证。")
    (paths["semantics"] / f"{LOAN}.json").unlink()
    document = read_document(paths["semantics"], CUSTOMER)
    document["summary"]["questions"] = document["summary"]["questions"][:2]
    from answer_fixtures import write_document
    write_document(paths["semantics"], CUSTOMER, document)

    current = state.inputs()
    assert {(i.record["table"], i.reason) for i in current.answers.unmatched} == {
        (LOAN, "missing"), (CUSTOMER, "missing")}
    assert current.page_states == {} and len(file_records(paths)) == 2
    assert state.export_answers()["confirmations"] == []


def test_row_2_a_rewritten_question_is_not_matched_nor_overlaid_nor_exported(paths) -> None:
    """A3: the same id, another question."""
    state = _state(paths)
    post(state, CUSTOMER, "q1", "不会。")
    assert state.export_answers()["confirmations"]
    set_question(paths["semantics"], CUSTOMER, "q1", text="性别码值的含义从哪里来？")

    current = state.inputs()
    item = judged(state, CUSTOMER, "q1")
    assert (item.state, item.reason) == ("unmatched", "rewritten")
    assert item.now["text"] == "性别码值的含义从哪里来？"
    assert question_of(current.semantics, CUSTOMER, "q1")["status"] == "open"
    assert current.page_states == {}
    assert state.export_answers()["confirmations"] == []
    pack = state.context(tables=[CUSTOMER]).text()
    assert "不会。" not in pack


def test_question_text_is_compared_after_nfkc_and_folding_whitespace(paths) -> None:
    state = _state(paths)
    post(state, CUSTOMER, "q2", "唯一。")
    set_question(paths["semantics"], CUSTOMER, "q2", text="客户号在同一分区内是否唯一?  ")

    assert judged(state, CUSTOMER, "q2").state == "effective"


def test_row_3_an_answer_written_back_is_deleted_by_the_writer(paths) -> None:
    state = _state(paths)
    post(state, CUSTOMER, "q1", "不会。", choice="no")
    answer_on_disk(paths["semantics"], CUSTOMER, "q1", "否：不会。", "审核人甲", "2026-11-23")

    current = state.inputs()
    assert current.answers.judgement.records == [] and file_records(paths) == []
    assert current.page_states == {} and current.answers.unmatched == []
    assert question_of(current.semantics, CUSTOMER, "q1")["answer"] == "否：不会。"


def test_row_3_a_reader_ignores_an_answer_written_back_and_leaves_the_file(paths) -> None:
    post(_state(paths), CUSTOMER, "q1", "不会。")
    before = paths["answers"].read_bytes()
    answer_on_disk(paths["semantics"], CUSTOMER, "q1", "不会。", "审核人甲", "2026-11-23")
    reader = _state(paths, writer=False)

    current = reader.inputs()
    assert current.answers.effective == [] and current.answers.unmatched == []
    assert current.page_states == {}
    assert paths["answers"].read_bytes() == before


def test_row_4_an_open_question_takes_the_answer(paths) -> None:
    state = _state(paths)
    post(state, CUSTOMER, "q1", "不会。")

    current = state.inputs()
    question = question_of(current.semantics, CUSTOMER, "q1")
    assert (question["status"], question["answer"], question["answered_by"]) == (
        "answered", "不会。", "审核人甲")
    assert question_of(current.disk_semantics, CUSTOMER, "q1")["status"] == "open"
    assert current.page_states == {(CUSTOMER, "q1"): {"written": False}}


def test_row_4_an_answer_changing_the_disk_answer_takes_effect(paths) -> None:
    answer_on_disk(paths["semantics"], CUSTOMER, "q2", "唯一。", "乙", "2026-01-01")
    state = _state(paths)
    record = post(state, CUSTOMER, "q2", "不唯一：分库后重复（历史数据）。")

    assert record["base"] == {"answer": "唯一。", "answered_by": "乙", "answered_on": "2026-01-01"}
    assert judged(state, CUSTOMER, "q2").state == "effective"
    assert question_of(state.inputs().semantics, CUSTOMER, "q2")["answer"] == "不唯一：分库后重复（历史数据）。"


def test_row_5_someone_else_answered_the_same_text_on_disk(paths) -> None:
    """``base`` null, the disk answered with the same words by another person: not ours."""
    state = _state(paths)
    post(state, CUSTOMER, "q1", "不会。")
    answer_on_disk(paths["semantics"], CUSTOMER, "q1", "不会。", "别人", "2026-11-23")

    item = judged(state, CUSTOMER, "q1")
    assert (item.state, item.reason) == ("unmatched", "changed")
    assert item.now["answered_by"] == "别人"
    assert question_of(state.inputs().semantics, CUSTOMER, "q1")["answered_by"] == "别人"
    assert state.export_answers()["confirmations"] == []


def test_row_5_the_disk_went_back_to_open_under_a_change(paths) -> None:
    answer_on_disk(paths["semantics"], CUSTOMER, "q2", "唯一。", "乙", "2026-01-01")
    state = _state(paths)
    post(state, CUSTOMER, "q2", "不唯一。")
    set_question(paths["semantics"], CUSTOMER, "q2", status="open", answer=None,
                 answered_by=None, answered_on=None)

    assert judged(state, CUSTOMER, "q2").reason == "changed"


def test_row_5_a_third_answer_on_disk(paths) -> None:
    answer_on_disk(paths["semantics"], CUSTOMER, "q2", "唯一。", "乙", "2026-01-01")
    state = _state(paths)
    post(state, CUSTOMER, "q2", "不唯一。")
    answer_on_disk(paths["semantics"], CUSTOMER, "q2", "看情况。", "丙", "2026-02-02")

    assert judged(state, CUSTOMER, "q2").reason == "changed"


def test_overlap_written_back_then_rewritten_is_judged_rewritten(paths) -> None:
    """The writer never read between the write-back and the rewrite: row 2 comes first."""
    post(_state(paths), CUSTOMER, "q1", "不会。")
    answer_on_disk(paths["semantics"], CUSTOMER, "q1", "不会。", "审核人甲", "2026-11-23")
    set_question(paths["semantics"], CUSTOMER, "q1", text="另一个问题？")

    item = judged(_state(paths), CUSTOMER, "q1")
    assert (item.state, item.reason) == ("unmatched", "rewritten")
    assert len(file_records(paths)) == 1


def _confirm(paths, confirmations, capsys) -> str:
    from scope_lineage.cli import main

    file = paths["answers"].parent / "confirm.json"
    file.write_text(json.dumps(confirmations, ensure_ascii=False), encoding="utf-8")
    assert main(["semantic", "confirm", str(paths["semantics"]), "--confirmations", str(file),
                 "--reviews", str(paths["answers"].parent / "reviews")]) == 0
    for path in paths["semantics"].glob("*.json"):
        touch_later(path)
    return capsys.readouterr().out


def _correction(by="更正人"):
    return {"doc_format": "semantic-confirmations/1", "confirmations": [
        {"table": CUSTOMER, "target": "question:q1", "value": "会，历史数据有空值。", "by": by,
         "date": "2026-11-24"}]}


def test_a4_a_written_back_then_corrected_seen_in_between(paths, capsys) -> None:
    """(a) The writer read between the write-back and the correction: the record is gone,
    nothing is listed, and the correction is what the page and the pack show."""
    state = _state(paths)
    post(state, CUSTOMER, "q1", "不会。")
    assert "unmatched=0" in _confirm(paths, state.export_answers(), capsys)
    state.inputs()
    assert file_records(paths) == []
    _confirm(paths, _correction(), capsys)

    current = state.inputs()
    assert current.answers.unmatched == [] and current.page_states == {}
    assert question_of(current.semantics, CUSTOMER, "q1")["answer"] == "会，历史数据有空值。"
    assert "会，历史数据有空值。" in state.context(tables=[CUSTOMER]).text()


def test_a4_b_written_back_then_corrected_not_seen_in_between(paths, capsys) -> None:
    """(b) No read between them (the server was not running): the record falls to row 5,
    is neither overlaid nor exported, and the listing shows what the disk holds now."""
    state = _state(paths)
    post(state, CUSTOMER, "q1", "不会。")
    exported = state.export_answers()
    del state
    _confirm(paths, exported, capsys)
    _confirm(paths, _correction(), capsys)

    state = _state(paths)
    item = judged(state, CUSTOMER, "q1")
    assert (item.state, item.reason) == ("unmatched", "changed")
    assert item.listing()["now"]["answer"] == "会，历史数据有空值。"
    assert state.export_answers()["confirmations"] == []
    assert question_of(state.inputs().semantics, CUSTOMER, "q1")["answer"] == "会，历史数据有空值。"
    assert "回答：会，历史数据有空值。" in state.context(tables=[CUSTOMER]).text()


def test_export_then_confirm_matches_and_the_records_go(paths, capsys) -> None:
    """A6: the exported file is a legal confirmations file, confirm applies it all, and the
    next request deletes the records it wrote back; the overlay was what confirm writes."""
    state = _state(paths)
    post(state, CUSTOMER, "q1", "不会。", choice="no")
    post(state, LOAN, "q1", "不会。")
    post(state, CUSTOMER, "q2", "一半知道", kind="partial")
    overlaid = {table: read for table, read in state.inputs().semantics.items()}
    exported = state.export_answers()
    assert [c["value"] for c in exported["confirmations"]] == ["否：不会。", "不会。"]

    assert "unmatched=0" in _confirm(paths, exported, capsys)
    current = state.inputs()
    assert [r["kind"] for r in file_records(paths)] == ["partial"]
    for table in (CUSTOMER, LOAN):
        assert current.disk_semantics[table]["summary"]["questions"][0] == \
            overlaid[table]["summary"]["questions"][0]


def test_the_export_names_the_question_asked_and_replaces_only_a_changed_answer(paths) -> None:
    """Each entry carries ``asked``, so ``semantic confirm`` can refuse a rewritten question
    on its own; ``replace`` only where the person changed an answer already on disk."""
    answer_on_disk(paths["semantics"], CUSTOMER, "q2", "唯一。", "乙", "2026-01-01")
    state = _state(paths)
    post(state, CUSTOMER, "q1", "不会。")
    post(state, CUSTOMER, "q2", "不唯一。")

    entries = {c["target"]: c for c in state.export_answers()["confirmations"]}
    assert entries["question:q1"]["asked"] == text_of(paths["semantics"], CUSTOMER, "q1")
    assert "replace" not in entries["question:q1"]
    assert entries["question:q2"]["asked"] == text_of(paths["semantics"], CUSTOMER, "q2")
    assert entries["question:q2"]["replace"] is True


def test_export_then_confirm_changes_a_written_answer_and_refuses_a_rewrite(paths, capsys) -> None:
    """End to end on the documents: an answer that changes one already on disk is applied
    (it carries ``replace``); a question rewritten after the export is refused by the core
    itself, even though the file still names it."""
    answer_on_disk(paths["semantics"], CUSTOMER, "q2", "唯一。", "乙", "2026-01-01")
    state = _state(paths)
    post(state, CUSTOMER, "q2", "不唯一。")
    post(state, LOAN, "q1", "不会。")
    exported = state.export_answers()
    set_question(paths["semantics"], LOAN, "q1", text="放款日期从哪个系统来？")
    loan_before = (paths["semantics"] / f"{LOAN}.json").read_bytes()

    out = _confirm(paths, exported, capsys)
    assert out.splitlines()[0] == "Applied 1 confirmation(s) to 1 table(s) (unmatched=1)"
    assert f"unmatched: {LOAN} question:q1: question was rewritten" in out
    disk = read_document(paths["semantics"], CUSTOMER)["summary"]["questions"][1]
    assert (disk["answer"], disk["answered_by"]) == ("不唯一。", "审核人甲")
    assert (paths["semantics"] / f"{LOAN}.json").read_bytes() == loan_before

    again = _confirm(paths, exported, capsys)
    assert again.splitlines()[0] == (
        "Applied 0 confirmation(s) to 0 table(s) (unmatched=1, skipped=1)")


def _old_overlay(disk: dict, records: list[dict]) -> dict:
    """The overlay as it was before entries named the question asked."""
    entries = [{key: value for key, value in records_file.confirmation(record).items()
                if key not in ("asked", "replace")} for record in records]
    return core.overlay_answers(disk, entries)[0]


OVERLAY_CASES = {
    "open question answered": lambda s: post(s, CUSTOMER, "q1", "不会。"),
    "written answer changed": lambda s: post(s, CUSTOMER, "q2", "不唯一。"),
    "answer and note": lambda s: (post(s, LOAN, "q2", "元。"),
                                  post(s, CUSTOMER, "q3", "暂缓", kind="deferred")),
}
DISK_CHANGES = {
    "none": lambda p: None,
    "rewritten": lambda p: set_question(p["semantics"], CUSTOMER, "q1", text="另一个问题？"),
    "written back": lambda p: answer_on_disk(p["semantics"], CUSTOMER, "q1", "不会。", "审核人甲",
                                             "2026-11-23"),
    "changed under it": lambda p: answer_on_disk(p["semantics"], CUSTOMER, "q2", "看情况。", "丙",
                                                 "2026-02-02"),
}


@pytest.mark.parametrize("change", sorted(DISK_CHANGES))
@pytest.mark.parametrize("case", sorted(OVERLAY_CASES))
def test_the_overlay_is_what_it_was_for_every_state(paths, case, change) -> None:
    answer_on_disk(paths["semantics"], CUSTOMER, "q2", "唯一。", "乙", "2026-01-01")
    state = _state(paths, writer=False)
    OVERLAY_CASES[case](state)
    DISK_CHANGES[change](paths)

    current = state.inputs()
    effective = [item.record for item in current.answers.effective
                 if item.record["kind"] == records_file.ANSWER]
    assert current.semantics == _old_overlay(current.disk_semantics, effective)
    assert all(item.reason != records_file.NOT_APPLIED for item in current.answers.unmatched)


# ------------------------------------------------------------------ judgement of notes


@pytest.mark.parametrize("kind", ["partial", "deferred", "redirect", "invalid", "not_applicable"])
def test_note_rows_1_2_4(paths, kind) -> None:
    state = _state(paths)
    extra = {"to": "数据组某某"} if kind == "redirect" else {}
    post(state, CUSTOMER, "q1", "理由一", kind=kind, **extra)
    post(state, LOAN, "q1", "理由二", kind=kind, **extra)

    current = state.inputs()
    state_of = current.page_states[(CUSTOMER, "q1")]
    assert state_of["kind"] == kind and state_of["reason"] == "理由一"
    assert state_of.get("to") == extra.get("to")
    assert question_of(current.semantics, CUSTOMER, "q1")["status"] == "open"
    assert state.export_answers()["confirmations"] == []

    set_question(paths["semantics"], CUSTOMER, "q1", text="改写后的问题？")
    (paths["semantics"] / f"{LOAN}.json").unlink()
    reasons = {(i.record["table"], i.reason) for i in state.inputs().answers.unmatched}
    assert reasons == {(CUSTOMER, "rewritten"), (LOAN, "missing")}


def test_note_row_3_a_note_on_a_question_answered_on_disk_disappears(paths) -> None:
    state = _state(paths)
    post(state, CUSTOMER, "q1", "该问数据组", kind="redirect", to="数据组")
    answer_on_disk(paths["semantics"], CUSTOMER, "q1", "不会。", "乙", "2026-11-24")

    current = state.inputs()
    assert file_records(paths) == []
    assert current.answers.unmatched == [] and current.page_states == {}


def test_a_note_replaces_an_unwritten_answer(paths) -> None:
    state = _state(paths)
    post(state, CUSTOMER, "q1", "不会。")
    post(state, CUSTOMER, "q1", "其实不确定", kind="deferred")

    current = state.inputs()
    assert current.page_states == {(CUSTOMER, "q1"): {
        "kind": "deferred", "reason": "其实不确定", "by": "审核人甲", "date": "2026-11-23"}}
    assert question_of(current.semantics, CUSTOMER, "q1")["status"] == "open"


# ------------------------------------------------------------------ refusals


def test_the_page_must_have_seen_what_is_there(paths) -> None:
    state = _state(paths)
    with pytest.raises(AnswerRefused) as raised:
        post(state, CUSTOMER, "q1", asked="另一个问题？")
    assert raised.value.status == 409
    with pytest.raises(AnswerRefused) as raised:
        post(state, CUSTOMER, "q1", seen={"disk": {"answer": "x", "answered_by": None,
                                                   "answered_on": None}, "record": None})
    assert raised.value.status == 409


def test_two_people_changing_one_record_the_later_is_refused(paths) -> None:
    state = _state(paths)
    post(state, CUSTOMER, "q1", "不会。")
    both_saw = seen_of(state, CUSTOMER, "q1")
    post(state, CUSTOMER, "q1", "会。", by="甲", seen=both_saw)

    with pytest.raises(AnswerRefused) as raised:
        post(state, CUSTOMER, "q1", "可能。", by="乙", seen=both_saw)
    assert raised.value.status == 409
    with pytest.raises(AnswerRefused) as raised:
        state.withdraw_answer(CUSTOMER, "q1", both_saw["record"])
    assert raised.value.status == 409
    assert file_records(paths)[0]["answer"] == "会。"


def test_a_note_and_an_answer_at_once_the_later_is_refused(paths) -> None:
    state = _state(paths)
    both_saw = seen_of(state, CUSTOMER, "q1")
    post(state, CUSTOMER, "q1", "暂缓", kind="deferred", seen=both_saw)
    with pytest.raises(AnswerRefused) as raised:
        post(state, CUSTOMER, "q1", "不会。", seen=both_saw)
    assert raised.value.status == 409


def test_the_same_as_what_is_there_is_refused(paths) -> None:
    answer_on_disk(paths["semantics"], CUSTOMER, "q2", "唯一。", "乙", "2026-01-01")
    state = _state(paths)
    with pytest.raises(AnswerRefused) as raised:
        post(state, CUSTOMER, "q2", "唯一。", by="丙")
    assert (raised.value.status, raised.value.message) == (400, "the same as what is there now")
    post(state, CUSTOMER, "q1", "暂缓", kind="deferred")
    with pytest.raises(AnswerRefused) as raised:
        post(state, CUSTOMER, "q1", "暂缓", kind="deferred", by="丁")
    assert raised.value.status == 400


def test_the_same_words_to_a_rewritten_question_are_a_new_answer(paths) -> None:
    state = _state(paths)
    post(state, CUSTOMER, "q1", "不会。")
    set_question(paths["semantics"], CUSTOMER, "q1", text="性别码值有没有第四个值？")
    assert judged(state, CUSTOMER, "q1").reason == "rewritten"

    post(state, CUSTOMER, "q1", "不会。")
    assert judged(state, CUSTOMER, "q1").state == "effective"
    assert file_records(paths)[0]["asked"] == "性别码值有没有第四个值？"


def test_a_note_on_a_question_answered_on_disk_is_refused(paths) -> None:
    answer_on_disk(paths["semantics"], CUSTOMER, "q2", "唯一。", "乙", "2026-01-01")
    state = _state(paths)
    with pytest.raises(AnswerRefused) as raised:
        post(state, CUSTOMER, "q2", "问题有误", kind="invalid")
    assert raised.value.status == 400


def test_an_unknown_question_is_404(paths) -> None:
    state = _state(paths)
    with pytest.raises(AnswerRefused) as raised:
        post(state, CUSTOMER, "q9", seen={"disk": None, "record": None})
    assert raised.value.status == 404
    with pytest.raises(AnswerRefused) as raised:
        state.withdraw_answer(CUSTOMER, "q1", {})
    assert raised.value.status == 404


def test_withdrawing_brings_back_the_disk(paths) -> None:
    answer_on_disk(paths["semantics"], CUSTOMER, "q2", "唯一。", "乙", "2026-01-01")
    state = _state(paths)
    post(state, CUSTOMER, "q1", "不会。")
    post(state, CUSTOMER, "q2", "不唯一。")
    for question in ("q1", "q2"):
        state.withdraw_answer(CUSTOMER, question, seen_of(state, CUSTOMER, question)["record"])

    current = state.inputs()
    assert file_records(paths) == [] and current.page_states == {}
    assert question_of(current.semantics, CUSTOMER, "q1")["status"] == "open"
    assert question_of(current.semantics, CUSTOMER, "q2")["answer"] == "唯一。"


# ------------------------------------------------------------------ the file going wrong


def test_a_damaged_file_answers_from_disk_and_says_so(paths) -> None:
    state = _state(paths)
    post(state, CUSTOMER, "q1", "不会。")
    paths["answers"].write_text("{half", encoding="utf-8")
    touch_later(paths["answers"])

    current = state.inputs()
    assert current.answers.status == "unreadable" and current.page_states == {}
    assert question_of(current.semantics, CUSTOMER, "q1")["status"] == "open"
    health = state.health()["answers"]
    assert health["status"] == "unreadable" and "not a JSON document" in health["reason"]
    with pytest.raises(AnswersUnavailable):
        post(state, CUSTOMER, "q2", seen={"disk": None, "record": None})
    assert paths["answers"].read_text(encoding="utf-8") == "{half"


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="needs file permissions")
def test_an_unwritable_file_fails_the_post_but_not_the_reads(paths) -> None:
    state = _state(paths)
    post(state, CUSTOMER, "q1", "不会。")
    directory = paths["answers"].parent
    mode = directory.stat().st_mode
    directory.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        with pytest.raises(AnswersUnavailable) as raised:
            post(state, CUSTOMER, "q2", "唯一。")
        assert "cannot be written" in raised.value.message
        assert question_of(state.inputs().semantics, CUSTOMER, "q1")["status"] == "answered"
    finally:
        directory.chmod(mode)


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="needs file permissions")
def test_a_failed_delete_does_not_fail_the_request_and_is_reported(paths) -> None:
    state = _state(paths)
    post(state, CUSTOMER, "q1", "不会。")
    answer_on_disk(paths["semantics"], CUSTOMER, "q1", "不会。", "审核人甲", "2026-11-23")
    directory = paths["answers"].parent
    mode = directory.stat().st_mode
    directory.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        current = state.inputs()
        assert current.page_states == {} and current.answers.unmatched == []
        assert "could not be deleted" in state.health()["answers"]["problem"]
        assert state.questions(status="all").exit_code == 0
    finally:
        directory.chmod(mode)
    assert len(file_records(paths)) == 1


def test_the_delete_reads_the_file_again_and_keeps_a_changed_record(paths) -> None:
    """A record replaced between the judgement and the delete is not deleted."""
    state = _state(paths)
    post(state, CUSTOMER, "q1", "不会。")
    judged_record = file_records(paths)[0]
    replaced = {**judged_record, "answer": "会。", "date": "2026-11-24"}
    records_file.write_records(paths["answers"], [replaced])

    with state._lock:
        kept = state._delete([judged_record])
    assert kept == [replaced] and file_records(paths) == [replaced]


def test_a_post_racing_the_delete_keeps_the_new_record(paths) -> None:
    """The delete and the post hold one lock: whichever goes first, the new answer stays."""
    state = _state(paths)
    post(state, CUSTOMER, "q1", "不会。")
    answer_on_disk(paths["semantics"], CUSTOMER, "q1", "不会。", "审核人甲", "2026-11-23")
    errors = []

    def answer_q2():
        try:
            post(state, CUSTOMER, "q2", "唯一。")
        except AnswerRefused as error:  # pragma: no cover - a failure is reported below
            errors.append(error)

    threads = [threading.Thread(target=answer_q2), threading.Thread(target=state.inputs)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert [(r["question"], r["answer"]) for r in file_records(paths)] == [("q2", "唯一。")]


def test_concurrent_answers_to_two_questions_are_both_kept(paths) -> None:
    state = _state(paths)
    seen = {q: seen_of(state, CUSTOMER, q) for q in ("q1", "q2", "q3")}
    threads = [threading.Thread(target=post, args=(state, CUSTOMER, q, f"回答{q}"),
                                kwargs={"seen": seen[q]}) for q in seen]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(r["question"] for r in file_records(paths)) == ["q1", "q2", "q3"]


def test_a_document_half_written_comes_back_on_the_next_request(paths) -> None:
    state = _state(paths)
    post(state, LOAN, "q1", "不会。")
    path = paths["semantics"] / f"{LOAN}.json"
    good = path.read_bytes()
    path.write_text("{half", encoding="utf-8")
    touch_later(path)
    assert judged(state, LOAN, "q1").reason == "missing"

    path.write_bytes(good)
    touch_later(path, 20)
    assert judged(state, LOAN, "q1").state == "effective"
    assert len(file_records(paths)) == 1


# ------------------------------------------------------------------ signatures and overlay


def test_a_change_to_the_answers_file_reads_no_document_again(paths, monkeypatch) -> None:
    state = _state(paths)
    calls = []
    monkeypatch.setattr(core, "load_ontology", lambda *a: calls.append("ontology"))
    monkeypatch.setattr(core, "load_semantics", lambda *a: calls.append("semantics"))
    record = post(state, CUSTOMER, "q1", "不会。")
    records_file.write_records(paths["answers"], [{**record, "answer": "会。"}])
    touch_later(paths["answers"])

    assert question_of(state.inputs().semantics, CUSTOMER, "q1")["answer"] == "会。"
    assert calls == []


def test_the_servers_own_write_does_not_read_the_file_again(paths, monkeypatch) -> None:
    state = _state(paths)
    reads = []
    real = records_file.read_records
    monkeypatch.setattr(records_file, "read_records", lambda path: reads.append(path) or real(path))
    post(state, CUSTOMER, "q1", "不会。")
    reads.clear()
    state.inputs()
    state.inputs()

    assert reads == []


def test_the_overlay_touches_only_the_answered_tables(paths, monkeypatch) -> None:
    state = _state(paths)
    disk = state.inputs().disk_semantics
    calls = []
    real = core.overlay_answers
    monkeypatch.setattr(core, "overlay_answers",
                        lambda semantics, entries: calls.append(list(entries)) or real(semantics, entries))
    post(state, CUSTOMER, "q1", "不会。")
    post(state, CUSTOMER, "q2", "暂缓", kind="deferred")

    current = state.inputs()
    assert current.semantics[LOAN] is disk[LOAN]
    assert current.semantics[CUSTOMER] is not disk[CUSTOMER]
    assert current.disk_semantics is disk
    assert [{e["table"] for e in entries} for entries in calls] == [{CUSTOMER}, {CUSTOMER}]
    assert all(e["target"] == "question:q1" for entries in calls for e in entries)


def test_without_a_semantics_directory_the_answers_are_all_not_matched(inputs, tmp_path) -> None:
    file = tmp_path / "answers.json"
    record = {"table": CUSTOMER, "question": "q1", "asked": "?", "base": None, "kind": "answer",
              "answer": "x", "source": {"kind": "person"}, "by": "甲", "date": "2026-11-23"}
    records_file.write_records(file, [record])
    state = CatalogState(str(inputs["ontology"]), answers=str(file), answers_writer=True)

    current = state.inputs()
    assert current.semantics is None and [i.reason for i in current.answers.unmatched] == ["missing"]
