"""Structured page answers (S-H): a record that answers a question with the row's grain, a
column's meaning or code values, besides a sentence.

Each test answers through ``CatalogState`` as ``POST /api/answers`` does (the request held
by the HTTP server's own ``_answer_request``), changes the documents on disk the way a
rewrite or ``semantic confirm`` would, and looks at what the state judges, overlays,
exports and keeps. The review conditions each have tests here: a record's two entries stand
or fall together on the page (and not in a replay), refusals are mapped back to records by
entry, two records on one slot, a changed code value's export note, and a code value the
SQL never writes failing at validation after a replay.
"""

from __future__ import annotations

import copy
import io
import json
from contextlib import redirect_stderr

import pytest
from answer_fixtures import (
    QUESTIONS,
    answer_on_disk,
    prepare,
    read_document,
    set_question,
    write_document,
)
from service_paths import CUSTOMER, LOAN, REPO

from scope_lineage import cli_catalog_answers as core
from scope_lineage.render.catalog_context import context_pack, render_context_text
from scope_lineage_service import answers as records_file
from scope_lineage_service.http_server import RequestError, _answer_request
from scope_lineage_service.state import AnswerRefused, CatalogState

ROW = {"unique": "no", "grain_columns": ["customer_id", "dt"]}
CODES = [{"value": "X", "meaning": "其他"}, {"value": "N", "meaning": "不详"}]


@pytest.fixture
def paths(inputs, tmp_path):
    prepare(inputs["semantics"])
    customer = read_document(inputs["semantics"], CUSTOMER)
    customer["summary"]["row"]["grain_source"] = "inferred"
    write_document(inputs["semantics"], CUSTOMER, customer)
    return {**inputs, "answers": tmp_path / "answers.json"}


def _state(paths, writer=True) -> CatalogState:
    return CatalogState(str(paths["ontology"]), semantics=str(paths["semantics"]),
                        answers=str(paths["answers"]), answers_writer=writer,
                        today=lambda: "2026-11-24")


def _asked(state, table, question):
    return records_file.find_question(state.inputs().disk_semantics, table, question)["text"]


def shown_slot(state, table, target, value):
    """The slot as the page shows it: read from the overlaid document."""
    return records_file.slot_of(state.inputs().semantics[table], target, value)


def answer(state, table, question, target, value, *, text=None, slot=None, by="审核人甲"):
    current = state.inputs()
    disk = records_file.disk_answer(records_file.find_question(current.disk_semantics, table, question))
    payload = {"table": table, "question": question, "kind": "answer", "by": by,
               "asked": _asked(state, table, question), "target": target, "value": value,
               "seen": {"disk": disk, "record": current.answers.record(table, question),
                        "slot": slot if slot is not None else shown_slot(state, table, target, value)}}
    if text is not None:
        payload["answer"] = text
    return state.save_answer(_answer_request(payload))


def judged(state, table, question):
    view = state.inputs().answers
    return next(item for item in view.judgement.judged
                if (item.record["table"], item.record["question"]) == (table, question))


def unmatched(state, table, question):
    return next(item for item in state.inputs().answers.unmatched
                if (item.record["table"], item.record["question"]) == (table, question))


def column_of(document, name):
    return next(c for c in document["columns"] if c["column"] == name)


def question_of(document, question):
    return next(q for q in document["summary"]["questions"] if q["id"] == question)


def file_records(paths):
    return json.loads(paths["answers"].read_text(encoding="utf-8"))["answers"]


# ------------------------------------------------------------------ the record


def _record(**extra):
    record = {"table": CUSTOMER, "question": "q3", "asked": "问？", "base": None, "kind": "answer",
              "target": "column:verify_status.code_values", "value": copy.deepcopy(CODES),
              "slot_base": {"X": None, "N": None}, "source": {"kind": "person"}, "by": "甲",
              "date": "2026-11-24"}
    record.update(extra)
    return {key: value for key, value in record.items() if value is not ...}


def test_a_structured_record_is_legal_with_or_without_a_sentence() -> None:
    assert records_file.record_problem(_record()) is None
    assert records_file.record_problem(_record(answer="以码表为准")) is None
    assert records_file.record_problem(_record(
        target="summary.row", value=ROW,
        slot_base={"unique": "yes", "grain_columns": ["customer_id"], "grain_source": "inferred"},
    )) is None
    assert records_file.record_problem(_record(
        target="column:etl_time.meaning", value="装载批次时间", slot_base="装载时间")) is None


@pytest.mark.parametrize("change, words", [
    ({"kind": "partial", "reason": "r"}, "answer"),
    ({"choice": "yes"}, "choice"),
    ({"value": [{"value": " ", "meaning": "空"}], "slot_base": {" ": None}}, "value"),
    ({"value": [{"value": "X", "meaning": "a"}, {"value": "X", "meaning": "b"}],
      "slot_base": {"X": None}}, "twice"),
    ({"value": [{"value": str(i), "meaning": "m"} for i in range(51)],
      "slot_base": {str(i): None for i in range(51)}}, "50"),
    ({"slot_base": {"X": None}}, "slot_base"),
    ({"slot_base": ...}, "slot_base"),
    ({"target": "summary.row", "value": {"unique": "maybe", "grain_columns": ["a"]},
      "slot_base": {"unique": None, "grain_columns": None, "grain_source": None}}, "unique"),
    ({"target": "summary.row", "value": {"unique": "yes", "grain_columns": list("abcdefghi")},
      "slot_base": {"unique": None, "grain_columns": None, "grain_source": None}}, "8"),
    ({"target": "column:etl_time.observed_values"}, "target"),
    ({"target": "column:etl_time.meaning", "value": "一行\n两行", "slot_base": None}, "line break"),
])
def test_a_structured_record_out_of_shape_is_refused(change, words) -> None:
    problem = records_file.record_problem(_record(**change))
    assert problem and words in problem, problem


def test_value_and_slot_base_need_a_target() -> None:
    plain = {"table": CUSTOMER, "question": "q1", "asked": "问？", "base": None, "kind": "answer",
             "answer": "x", "source": {"kind": "person"}, "by": "甲", "date": "2026-11-24"}
    assert records_file.record_problem(plain) is None
    assert "target" in records_file.record_problem({**plain, "value": "x"})
    assert "target" in records_file.record_problem({**plain, "slot_base": None})


def test_the_sentence_is_generated_and_takes_the_note_after_it() -> None:
    assert records_file.sentence(_record()) == "列 verify_status 的码值：X=其他；N=不详"
    assert records_file.sentence(_record(answer="以码表为准")) == (
        "列 verify_status 的码值：X=其他；N=不详；以码表为准")
    assert records_file.sentence(_record(target="summary.row", value=ROW)) == (
        "否：按 (customer_id, dt) 不唯一")
    assert records_file.sentence(_record(
        target="summary.row", value={"unique": "yes", "grain_columns": ["customer_id"]})) == (
        "是：按 (customer_id) 每行唯一")
    assert records_file.sentence(_record(target="column:etl_time.meaning", value="装载批次时间")) == (
        "列 etl_time 的含义：装载批次时间")


# ------------------------------------------------------------------ saving


def test_a_code_value_answer_is_stored_with_the_slot_it_was_given_on(paths) -> None:
    state = _state(paths)

    record = answer(state, CUSTOMER, "q3", "column:verify_status.code_values", CODES)

    assert record["slot_base"] == {"X": None, "N": None}
    assert "answer" not in record
    assert file_records(paths) == [record]
    assert judged(state, CUSTOMER, "q3").state == records_file.EFFECTIVE
    current = state.inputs()
    codes = {c["value"]: c["meaning"] for c in column_of(current.semantics[CUSTOMER],
                                                           "verify_status")["code_values"]}
    assert codes == {"1": "已实名", "0": "未实名", "X": "其他", "N": "不详"}
    asked = question_of(current.semantics[CUSTOMER], "q3")
    assert asked["status"] == "answered"
    assert asked["answer"] == "列 verify_status 的码值：X=其他；N=不详"
    assert current.page_states[(CUSTOMER, "q3")] == {"written": False}
    assert current.page_states[(CUSTOMER, "column:verify_status.code_values:X")] == {"written": False}
    assert current.page_states[(CUSTOMER, "column:verify_status.code_values:N")] == {"written": False}
    # the documents on disk are untouched
    assert len(column_of(current.disk_semantics[CUSTOMER], "verify_status")["code_values"]) == 2


def test_a_row_answer_turns_an_inferred_grain_declared_in_the_overlay(paths) -> None:
    state = _state(paths)

    record = answer(state, CUSTOMER, "q2", "summary.row", ROW, text="跨分区会重复")

    assert record["slot_base"] == {"unique": "yes", "grain_columns": ["customer_id"],
                                   "grain_source": "inferred"}
    row = state.inputs().semantics[CUSTOMER]["summary"]["row"]
    assert (row["unique"], row["grain_columns"], row["grain_source"]) == (
        "no", ["customer_id", "dt"], "declared")
    assert question_of(state.inputs().semantics[CUSTOMER], "q2")["answer"] == (
        "否：按 (customer_id, dt) 不唯一；跨分区会重复")


def test_a_row_answer_on_a_proven_grain_is_refused(paths) -> None:
    """D-H1: the lineage proved the grain; a page row answer would sit beside the proof
    with the source still ``proven``."""
    customer = read_document(paths["semantics"], CUSTOMER)
    customer["summary"]["row"]["grain_source"] = "proven"
    write_document(paths["semantics"], CUSTOMER, customer)
    state = _state(paths)

    with pytest.raises(AnswerRefused) as refused:
        answer(state, CUSTOMER, "q2", "summary.row", ROW)
    assert refused.value.status == 400
    assert "血缘已证明粒度" in refused.value.message
    assert not paths["answers"].exists()


@pytest.mark.parametrize("target, value, words", [
    ("summary.row", {"unique": "yes", "grain_columns": ["no_such_column"]}, "no_such_column"),
    ("column:no_such_column.meaning", "x", "no_such_column"),
    ("column:customer_id.code_values", [{"value": "1", "meaning": "x"}], "identifier"),
    ("column:verified_customer_no.code_values", [{"value": "1", "meaning": "x"}], "identifier"),
    ("column:loan_id.meaning", "x", "loan_id"),
])
def test_an_answer_on_what_the_table_does_not_have_is_refused(paths, target, value, words) -> None:
    state = _state(paths)

    with pytest.raises(AnswerRefused) as refused:
        answer(state, CUSTOMER, "q3", target, value, slot={})
    assert refused.value.status == 400 and words in refused.value.message


def test_a_slot_changed_since_the_page_showed_it_is_409(paths) -> None:
    state = _state(paths)

    with pytest.raises(AnswerRefused) as refused:
        answer(state, CUSTOMER, "q3", "column:etl_time.meaning", "装载批次时间", slot="别的含义")
    assert refused.value.status == 409


def test_the_slot_the_page_shows_is_the_overlaid_one(paths) -> None:
    """Changing one's own answer: the page shows the overlaid meaning, and that is what it
    sends back; the record's ``slot_base`` stays the disk's."""
    state = _state(paths)
    answer(state, CUSTOMER, "q3", "column:etl_time.meaning", "装载批次时间")
    disk_meaning = column_of(state.inputs().disk_semantics[CUSTOMER], "etl_time")["meaning"]

    with pytest.raises(AnswerRefused):
        answer(state, CUSTOMER, "q3", "column:etl_time.meaning", "批次时间", slot=disk_meaning)
    record = answer(state, CUSTOMER, "q3", "column:etl_time.meaning", "批次时间")

    assert record["slot_base"] == disk_meaning
    assert [r["value"] for r in file_records(paths)] == ["批次时间"]


# ------------------------------------------------------------------ condition 3


def test_a_second_record_on_a_slot_another_question_answers_is_refused(paths) -> None:
    state = _state(paths)
    answer(state, CUSTOMER, "q3", "column:verify_status.code_values", CODES)

    with pytest.raises(AnswerRefused) as refused:
        answer(state, CUSTOMER, "q1", "column:verify_status.code_values",
               [{"value": "N", "meaning": "未知"}])
    assert refused.value.status == 400 and "q3" in refused.value.message
    # another value of the same column is another slot
    answer(state, CUSTOMER, "q1", "column:verify_status.code_values",
           [{"value": "Z", "meaning": "注销"}])
    assert len(file_records(paths)) == 2


def test_two_records_on_one_slot_in_the_file_overlay_only_the_first(paths) -> None:
    """A file written by hand (or by two servers) may hold two records on one slot: the
    later one is not overlaid, and says which record holds the slot."""
    state = _state(paths)
    first = answer(state, CUSTOMER, "q3", "summary.row", ROW)
    second = {**first, "question": "q1", "asked": _asked(state, CUSTOMER, "q1"),
              "value": {"unique": "yes", "grain_columns": ["customer_id", "dt"]}}
    records_file.write_records(paths["answers"], [first, second])

    state = _state(paths)
    item = unmatched(state, CUSTOMER, "q1")
    assert item.reason == records_file.NOT_APPLIED and "q3" in item.message
    assert question_of(state.inputs().semantics[CUSTOMER], "q1")["status"] == "open"
    assert state.inputs().semantics[CUSTOMER]["summary"]["row"]["unique"] == "no"
    assert [e["target"] for e in state.export_answers()["confirmations"]] == [
        "summary.row", "question:q3"]


# ------------------------------------------------------------------ judgement


def test_the_disk_catching_up_writes_the_record_back(paths) -> None:
    state = _state(paths)
    record = answer(state, CUSTOMER, "q3", "column:verify_status.code_values", CODES)
    customer = read_document(paths["semantics"], CUSTOMER)
    column_of(customer, "verify_status")["code_values"] += [
        {"value": "X", "meaning": "其他", "sources": ["confirmed"]},
        {"value": "N", "meaning": "不详", "sources": ["confirmed"]}]
    question_of(customer, "q3").update(status="answered", answer=records_file.sentence(record),
                                       answered_by="审核人甲", answered_on="2026-11-24")
    write_document(paths["semantics"], CUSTOMER, customer)

    state.inputs()
    assert file_records(paths) == []


@pytest.mark.parametrize("change, reason", [
    # a column gone: not matched, missing
    (lambda d: d["columns"].remove(column_of(d, "verify_status")), records_file.MISSING),
    # the question rewritten
    (lambda d: question_of(d, "q3").update(text="另一个问题？"), records_file.REWRITTEN),
    # someone else changed the slot, the question still open
    (lambda d: column_of(d, "verify_status")["code_values"].append(
        {"value": "X", "meaning": "别的", "sources": ["comment"]}), records_file.CHANGED),
    # the question answered as the page answered it, but the slot is not the answer
    (lambda d: question_of(d, "q3").update(
        status="answered", answer="列 verify_status 的码值：X=其他；N=不详",
        answered_by="审核人甲", answered_on="2026-11-24"), records_file.CHANGED),
    # the slot written back as answered, but marked unconfirmed
    (lambda d: (column_of(d, "verify_status")["code_values"].extend([
        {"value": "X", "meaning": "其他", "sources": ["comment"], "unconfirmed": True},
        {"value": "N", "meaning": "不详", "sources": ["comment"]}]),
        question_of(d, "q3").update(status="answered",
                                    answer="列 verify_status 的码值：X=其他；N=不详",
                                    answered_by="审核人甲", answered_on="2026-11-24")),
     records_file.CHANGED),
])
def test_each_row_of_the_judgement(paths, change, reason) -> None:
    state = _state(paths)
    answer(state, CUSTOMER, "q3", "column:verify_status.code_values", CODES)
    customer = read_document(paths["semantics"], CUSTOMER)
    change(customer)
    write_document(paths["semantics"], CUSTOMER, customer)

    item = judged(state, CUSTOMER, "q3")
    assert (item.state, item.reason) == (records_file.UNMATCHED, reason)
    assert state.export_answers()["confirmations"] == []


def test_an_unchanged_slot_and_an_open_question_are_in_effect(paths) -> None:
    state = _state(paths)
    answer(state, CUSTOMER, "q3", "column:verify_status.code_values", CODES)
    set_question(paths["semantics"], CUSTOMER, "q1", text="别的问题改写了？")

    assert judged(state, CUSTOMER, "q3").state == records_file.EFFECTIVE


# ------------------------------------------------------------------ export


def test_a_code_value_record_exports_one_entry_per_value_then_the_question(paths) -> None:
    state = _state(paths)
    answer(state, CUSTOMER, "q3", "column:verify_status.code_values", CODES)

    entries = state.export_answers()["confirmations"]

    assert entries == [
        {"table": CUSTOMER, "target": "column:verify_status.code_values",
         "value": {"value": "X", "meaning": "其他"}, "by": "审核人甲", "date": "2026-11-24"},
        {"table": CUSTOMER, "target": "column:verify_status.code_values",
         "value": {"value": "N", "meaning": "不详"}, "by": "审核人甲", "date": "2026-11-24"},
        {"table": CUSTOMER, "target": "question:q3", "value": "列 verify_status 的码值：X=其他；N=不详",
         "by": "审核人甲", "date": "2026-11-24", "asked": _asked(state, CUSTOMER, "q3")},
    ]


def test_the_export_replays_onto_the_disk_as_the_page_showed_it(paths) -> None:
    from scope_lineage.semantics import apply_confirmations

    state = _state(paths)
    answer(state, CUSTOMER, "q2", "summary.row", ROW)
    answer(state, CUSTOMER, "q3", "column:etl_time.meaning", "装载批次时间")
    disk = state.inputs().disk_semantics

    result = apply_confirmations(disk, state.export_answers()["confirmations"], require_asked=True)

    assert result.unmatched == []
    replayed, shown = result.documents[CUSTOMER], state.inputs().semantics[CUSTOMER]
    for key in ("row",):
        assert {k: replayed["summary"][key][k] for k in ("unique", "grain_columns", "grain_source")} == {
            k: shown["summary"][key][k] for k in ("unique", "grain_columns", "grain_source")}
    assert replayed["columns"] == shown["columns"]
    assert replayed["summary"]["questions"] == shown["summary"]["questions"]


# ------------------------------------------------------------------ condition 1


def test_a_refused_entry_takes_the_whole_record_out_of_the_overlay(paths, monkeypatch) -> None:
    """The page overlays a record's structured entry and its ``question:`` entry together:
    when the core refuses one, the question is not answered either."""
    state = _state(paths)
    answer(state, CUSTOMER, "q3", "column:verify_status.code_values", CODES)
    real = core.overlay_answers

    def refusing(semantics, entries, **options):
        entries = list(entries)
        changed, refused = real(semantics, entries, **options)
        return changed, refused + [
            {"table": CUSTOMER, "target": entry["target"], "reason": "refused for the test",
             "index": at} for at, entry in enumerate(entries) if entry["value"] == CODES[1]]

    monkeypatch.setattr(core, "overlay_answers", refusing)
    state = _state(paths)

    item = unmatched(state, CUSTOMER, "q3")
    assert item.reason == records_file.NOT_APPLIED and "refused for the test" in item.message
    overlaid = state.inputs().semantics[CUSTOMER]
    assert question_of(overlaid, "q3")["status"] == "open"
    assert len(column_of(overlaid, "verify_status")["code_values"]) == 2
    assert not any(isinstance(key[1], str) and key[1].startswith("column:")
                   for key in state.inputs().page_states)
    assert state.export_answers()["confirmations"] == []


def test_a_replay_is_not_atomic_where_the_page_is(paths) -> None:
    """``semantic confirm --require-asked`` after a rewrite: the ``question:`` entry is
    unmatched, the structured entry (by column name, without ``asked``) still applies.
    The page, judging the same record, overlays neither."""
    from scope_lineage.semantics import apply_confirmations

    state = _state(paths)
    answer(state, CUSTOMER, "q3", "column:etl_time.meaning", "装载批次时间")
    exported = state.export_answers()["confirmations"]
    set_question(paths["semantics"], CUSTOMER, "q3", text="改写后的问题？")

    disk = state.inputs().disk_semantics
    result = apply_confirmations(disk, exported, require_asked=True)
    assert [item["target"] for item in result.unmatched] == ["question:q3"]
    assert column_of(result.documents[CUSTOMER], "etl_time")["meaning"] == "装载批次时间"
    # the page: rewritten, not matched, nothing overlaid
    assert judged(state, CUSTOMER, "q3").reason == records_file.REWRITTEN
    assert column_of(state.inputs().semantics[CUSTOMER], "etl_time")["meaning"] != "装载批次时间"


# ------------------------------------------------------------------ condition 2


def _plain(question, text="不会。"):
    asked = next(q["text"] for q in QUESTIONS if q["id"] == question)
    return {"table": CUSTOMER, "question": question, "asked": asked, "base": None,
            "kind": "answer", "answer": text, "source": {"kind": "person"}, "by": "甲",
            "date": "2026-11-24"}


def test_refusals_are_mapped_to_records_by_entry_not_by_target(paths) -> None:
    """A refused structured entry names a column, not its question: by ``(table, target
    suffix)`` it maps to no record and its question entry would stay applied."""
    disk = _state(paths).inputs().disk_semantics
    gone = {**_plain("q3"), "target": "column:no_such_column.meaning", "value": "x",
            "slot_base": None}
    del gone["answer"]
    kept = _plain("q1")

    overlaid, refused = records_file.overlay_records(disk, [gone, kept])

    assert list(refused) == [id(gone)] and "unknown column" in refused[id(gone)]
    assert question_of(overlaid[CUSTOMER], "q3")["status"] == "open"
    assert question_of(overlaid[CUSTOMER], "q1")["status"] == "answered"


def test_the_overlay_repeats_until_nothing_is_refused(paths, monkeypatch) -> None:
    disk = _state(paths).inputs().disk_semantics
    records = [_plain("q1"), _plain("q2"), _plain("q3")]
    calls = []
    real = core.overlay_answers

    def refuse_first_of_each_pass(semantics, entries, **options):
        entries = list(entries)
        calls.append([e["target"] for e in entries])
        changed, _ = real(semantics, entries, **options)
        if len(calls) < 3:  # each of the first two passes refuses its first entry
            return changed, [{"table": CUSTOMER, "target": entries[0]["target"],
                              "reason": f"pass {len(calls)}", "index": 0}]
        return changed, []

    monkeypatch.setattr(core, "overlay_answers", refuse_first_of_each_pass)
    overlaid, refused = records_file.overlay_records(disk, records)

    assert calls == [["question:q1", "question:q2", "question:q3"],
                     ["question:q2", "question:q3"], ["question:q3"]]
    assert refused == {id(records[0]): "pass 1", id(records[1]): "pass 2"}
    assert question_of(overlaid[CUSTOMER], "q3")["status"] == "answered"


def test_the_overlay_passes_are_capped(paths, monkeypatch) -> None:
    disk = _state(paths).inputs().disk_semantics
    records = [{**_plain("q1"), "question": f"q{n}"} for n in range(1, 11)]
    calls = []

    def refusing_one_per_pass(semantics, entries, **options):
        entries = list(entries)
        calls.append(len(entries))
        return dict(semantics), [{"table": CUSTOMER, "target": entries[0]["target"],
                                  "reason": f"pass {len(calls)}", "index": 0}] if entries else []

    monkeypatch.setattr(core, "overlay_answers", refusing_one_per_pass)
    overlaid, refused = records_file.overlay_records(disk, records)

    assert len(calls) == records_file.MAX_OVERLAY_PASSES
    assert set(refused) == {id(record) for record in records}
    assert [refused[id(r)] for r in records[-2:]] == ["叠加反复被拒，没有叠加"] * 2
    assert all(overlaid[name] is disk[name] for name in disk)


def test_a_refusal_no_entry_maps_to_overlays_nothing(paths, monkeypatch) -> None:
    disk = _state(paths).inputs().disk_semantics
    records = [_plain("q1"), _plain("q2")]

    def unmappable(semantics, entries, **options):
        entries = list(entries)
        return dict(semantics), [{"table": CUSTOMER, "target": "question:q9", "reason": "?",
                                  "index": len(entries)}]

    monkeypatch.setattr(core, "overlay_answers", unmappable)
    overlaid, refused = records_file.overlay_records(disk, records)

    assert set(refused) == {id(records[0]), id(records[1])}
    assert all(overlaid[name] is disk[name] for name in disk)


# ------------------------------------------------------------------ condition 4


def test_a_changed_code_value_is_exported_with_a_note_to_remove_the_old_entry(paths, capsys) -> None:
    state = _state(paths)
    answer(state, CUSTOMER, "q3", "column:verify_status.code_values",
           [{"value": "0", "meaning": "未认证"}, {"value": "X", "meaning": "其他"}])

    notes = state.answers_summary(state.inputs())["export_notes"]

    (note,) = notes
    assert "verify_status" in note and "'0'" in note
    assert "未实名" in note and "未认证" in note
    assert "删掉" in note and "confirmations/" in note
    # the CLI says the same on stderr
    out = paths["answers"].parent / "exported.json"
    from scope_lineage_service.cli import main as service_main
    code = service_main(["answers", "export", str(paths["answers"]), "--semantics",
                         str(paths["semantics"]), "--out", str(out)])
    assert code == 0
    assert note in capsys.readouterr().err


def test_no_note_without_a_changed_code_value(paths) -> None:
    state = _state(paths)
    answer(state, CUSTOMER, "q3", "column:verify_status.code_values", CODES)
    answer(state, LOAN, "q1", "column:etl_time.meaning", "装载批次时间")

    assert "export_notes" not in state.answers_summary(state.inputs())


# ------------------------------------------------------------------ condition 5


@pytest.fixture(scope="module")
def packet(tmp_path_factory) -> dict:
    """The demo corpus parsed and packed as the docs pack it; the customer table's packet."""
    from scope_lineage.cli import main as core_main

    work = tmp_path_factory.mktemp("structured")
    corpus = REPO / "examples" / "catalog-demo-corpus"
    assert core_main(["parse", "--input-dir", str(corpus / "tasks"), "--schema",
                      str(corpus / "schema_info.json"), "--out", str(work / "lineage")]) == 0
    assert core_main(["semantic", "packet", "--lineage", str(work / "lineage"), "--tasks",
                      str(corpus / "tasks"), "--schema", str(corpus / "schema_info.json"),
                      "--out", str(work / "packets"), "--domain-profile",
                      str(REPO / "examples" / "domain-profile" / "domain-profile.json")]) == 0
    return json.loads((work / "packets" / CUSTOMER / "packet.json").read_text(encoding="utf-8"))


def test_a_code_value_the_sql_never_writes_fails_validation_after_the_replay(
    paths, packet, tmp_path
) -> None:
    """``semantic confirm`` has no packet and takes the code value; validation, which has
    one, fails it as a confirmation to take back to the owner -- not a silent pass."""
    from scope_lineage.semantics import apply_confirmations, validate_document
    from scope_lineage.semantics.confirmed import read_confirmations

    constant = copy.deepcopy(packet)
    for entry in constant["lineage"]["columns"]:
        if entry["column"] == "verify_status":
            for producer in entry["producers"]:
                producer.update(constant_only=True, literal_outputs=["'1'"])
    state = _state(paths)
    answer(state, CUSTOMER, "q3", "column:verify_status.code_values", [{"value": "X", "meaning": "其他"}])
    confirmations = tmp_path / "confirmations" / "page.json"
    confirmations.parent.mkdir()
    confirmations.write_text(json.dumps(state.export_answers(), ensure_ascii=False), encoding="utf-8")

    disk = {CUSTOMER: state.inputs().disk_semantics[CUSTOMER]}
    replayed = apply_confirmations(disk, state.export_answers()["confirmations"], require_asked=True)
    assert replayed.unmatched == []
    document = replayed.documents[CUSTOMER]
    document["packet_digest"] = constant["packet_digest"]
    report = validate_document(document, constant, confirmations=read_confirmations(confirmations))

    failures = [f for f in report["failures"]
                if f["check"] == "code_values" and f["status"] == "fail" and "'X'" in f["message"]]
    assert failures, report["failures"]
    assert "确认与 SQL 矛盾，交回 owner" in failures[0]["message"]


# ------------------------------------------------------------------ the pack and the page


def test_the_pack_marks_what_the_page_answered(paths) -> None:
    state = _state(paths)
    answer(state, CUSTOMER, "q2", "summary.row", ROW)
    answer(state, CUSTOMER, "q3", "column:verify_status.code_values", CODES)

    pack = state.context(tables=[CUSTOMER], columns=[f"{CUSTOMER}.verify_status"]).result
    semantics = pack["tables"][0]["semantics"]
    assert semantics["row"]["written"] is False
    verify = next(c for c in semantics["columns"] if c["column"] == "verify_status")
    assert verify["unwritten"] == ["code_values:N", "code_values:X"]
    assert pack["columns"][0]["semantics"]["unwritten"] == ["code_values:N", "code_values:X"]
    text = state.context(tables=[CUSTOMER]).text()
    assert "（页面填写，尚未写回）" in text and "码值 'N'、'X'" in text


def test_the_table_semantics_answer_lists_the_unwritten_slots(paths) -> None:
    state = _state(paths)
    answer(state, CUSTOMER, "q3", "column:etl_time.meaning", "装载批次时间")
    answer(state, CUSTOMER, "q1", "column:verify_status.code_values", CODES)

    result = state.table_semantics(CUSTOMER).result

    assert result["unwritten"] == ["q1", "q3"]
    assert result["unwritten_slots"] == ["column:etl_time.meaning",
                                         "column:verify_status.code_values:N",
                                         "column:verify_status.code_values:X"]
    assert "unwritten_slots" not in json.dumps(result["document"])


def test_without_structured_records_there_is_no_unwritten_slots_key(paths) -> None:
    from test_service_answers import post

    state = _state(paths)
    post(state, CUSTOMER, "q1", "不会。")

    assert "unwritten_slots" not in state.table_semantics(CUSTOMER).result
    assert "export_notes" not in state.answers_summary(state.inputs())


# ------------------------------------------------------------------ the request


def _payload(**extra):
    payload = {"table": CUSTOMER, "question": "q3", "kind": "answer", "by": "甲", "asked": "问？",
               "target": "column:etl_time.meaning", "value": "装载批次时间",
               "seen": {"disk": None, "record": None, "slot": "装载时间"}}
    payload.update(extra)
    return {key: value for key, value in payload.items() if value is not ...}


@pytest.mark.parametrize("change", [
    {"seen": {"disk": None, "record": None}},
    {"target": "column:etl_time.observed_values"},
    {"value": ...},
    {"kind": "partial", "reason": "x"},
    {"choice": "yes"},
    {"value": "两\n行"},
    {"target": "column:verify_status.code_values", "value": {"value": "X", "meaning": "其他"}},
    {"target": ..., "seen": {"disk": None, "record": None}, "answer": "x"},
])
def test_the_request_is_held_to_its_shape(change) -> None:
    with pytest.raises(RequestError) as refused:
        _answer_request(_payload(**change))
    assert refused.value.status == 400


def test_a_plain_request_is_what_it_was() -> None:
    plain = {"table": CUSTOMER, "question": "q1", "kind": "answer", "by": "甲", "asked": "问？",
             "answer": "不会。", "seen": {"disk": None, "record": None}}
    assert _answer_request(plain) == {**plain}
    with pytest.raises(RequestError):
        _answer_request({**plain, "seen": {"disk": None, "record": None, "slot": None}})
    with pytest.raises(RequestError):
        _answer_request({**plain, "value": "x"})


def test_the_cli_export_writes_the_same_entries_as_the_page(paths) -> None:
    from scope_lineage_service.cli import main as service_main

    state = _state(paths)
    answer(state, CUSTOMER, "q3", "column:verify_status.code_values", CODES)
    out = paths["answers"].parent / "exported.json"

    with redirect_stderr(io.StringIO()):
        assert service_main(["answers", "export", str(paths["answers"]), "--semantics",
                             str(paths["semantics"]), "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8")) == state.export_answers()


def test_a_disk_answer_and_slot_already_as_typed_is_no_change(paths) -> None:
    customer = read_document(paths["semantics"], CUSTOMER)
    column_of(customer, "etl_time")["meaning"] = "装载批次时间"
    write_document(paths["semantics"], CUSTOMER, customer)
    answer_on_disk(paths["semantics"], CUSTOMER, "q3", "列 etl_time 的含义：装载批次时间",
                   "乙", "2026-01-01")
    state = _state(paths)

    with pytest.raises(AnswerRefused) as refused:
        answer(state, CUSTOMER, "q3", "column:etl_time.meaning", "装载批次时间")
    assert refused.value.status == 400


def test_context_text_has_the_slot_mark_once_per_line(paths) -> None:
    state = _state(paths)
    answer(state, CUSTOMER, "q3", "column:etl_time.meaning", "装载批次时间")
    current = state.inputs()

    pack = context_pack(current.document, current.semantics, columns=[f"{CUSTOMER}.etl_time"],
                        page_states=current.page_states)
    lines = render_context_text(pack).splitlines()
    (meaning,) = [line for line in lines if line.startswith("- 含义：")]
    assert meaning.count("（页面填写，尚未写回）") == 1


def test_the_docs_say_how_a_changed_code_value_and_a_constant_column_are_handled() -> None:
    readme = (REPO / "service" / "README.md").read_text(encoding="utf-8")
    assert "确认与 SQL 矛盾，交回 owner" in readme
    assert "single-object" in readme and "remove" in readme
    s12 = (REPO / "skills" / "scope-lineage-ontology" / "references" / "steps" / "S12.md")
    assert "结构化" in s12.read_text(encoding="utf-8")



# ------------------------------------------------------------------ over HTTP


def _http_answer(httpd, table, question, target, value, slot=None):
    from test_service_answers_http import _item, _json, _post, _seen

    item = _item(httpd, table, question)
    document = _json(httpd, "/api/semantics", table=table)["document"]
    seen = {**_seen(item), "slot": records_file.slot_of(document, target, value) if slot is None
            else slot}
    return _post(httpd, "/api/answers", {"table": table, "question": question, "kind": "answer",
                                         "by": "审核人甲", "asked": item["text"], "seen": seen,
                                         "target": target, "value": value})


@pytest.fixture
def server(paths):
    from test_service_answers_http import _serve

    httpd = _serve(_state(paths))
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def test_a_structured_answer_over_http_is_written_back_end_to_end(server, paths, tmp_path, capsys):
    from answer_fixtures import touch_later
    from test_service_answers_http import _get, _json

    from scope_lineage.cli import main as core_main

    status, body = _http_answer(server, CUSTOMER, "q3", "column:verify_status.code_values", CODES)
    assert status == 201 and body["record"]["slot_base"] == {"X": None, "N": None}
    semantics = _json(server, "/api/semantics", table=CUSTOMER)
    assert semantics["unwritten"] == ["q3"]
    assert semantics["unwritten_slots"] == ["column:verify_status.code_values:N",
                                            "column:verify_status.code_values:X"]
    text = _get(server, "/api/context", table=CUSTOMER, format="text")[2].decode("utf-8")
    assert "（页面填写，尚未写回：码值 'N'、'X'）" in text

    file = tmp_path / "semantic-confirmations.json"
    file.write_bytes(_get(server, "/api/answers/export")[2])
    assert core_main(["semantic", "confirm", str(paths["semantics"]), "--confirmations",
                      str(file), "--reviews", str(tmp_path / "reviews"), "--require-asked"]) == 0
    assert "(unmatched=0)" in capsys.readouterr().out
    for path in paths["semantics"].glob("*.json"):
        touch_later(path)
    _get(server, "/api/questions")
    assert file_records(paths) == []
    after = _json(server, "/api/semantics", table=CUSTOMER)
    assert after["unwritten"] == [] and "unwritten_slots" not in after


def test_a_stale_slot_over_http_is_409(server) -> None:
    status, body = _http_answer(server, CUSTOMER, "q3", "column:etl_time.meaning", "装载批次时间",
                                slot="页面看到的旧含义")
    assert status == 409 and body["error"]["kind"] == "changed"


def test_a_bad_structured_value_over_http_is_400(server) -> None:
    status, body = _http_answer(server, CUSTOMER, "q3", "column:verify_status.code_values",
                                [{"value": "", "meaning": "空"}], slot={})
    assert status == 400


def test_a_server_others_reach_refuses_a_structured_answer(paths) -> None:
    from test_service_answers_http import _serve

    httpd = _serve(_state(paths), allow_hosts=["proxy.example"])
    try:
        status, body = _http_answer(httpd, CUSTOMER, "q3", "column:etl_time.meaning", "装载批次时间")
        assert status == 403 and body["error"]["kind"] == "forbidden_remote"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_the_board_carries_the_export_notes(server) -> None:
    from test_service_answers_http import _json

    _http_answer(server, CUSTOMER, "q3", "column:verify_status.code_values",
                 [{"value": "0", "meaning": "未认证"}])
    notes = _json(server, "/api/questions")["answers"]["export_notes"]
    assert len(notes) == 1 and "删掉" in notes[0]
