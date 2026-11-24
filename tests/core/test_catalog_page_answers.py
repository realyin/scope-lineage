"""Answers in the context pack and on the questions board, and the page's states.

A table-semantics question that is answered carries its answer, who gave it and when into
both places a reader meets it: the context pack (under a table and under a named column,
in JSON and in text) and the questions board. A browsing page may also hold answers and
notes not yet written back to the documents; the core takes them as an optional mapping
keyed by ``(table, question id)`` and marks them, never adding a key to a document.
Without that mapping every output is what it was before (``catalog-answers-before.json``
holds the sha256 of each output, recorded before answers were carried; the only
difference allowed is the answer of an answered question).

``overlay_answers`` applies a page's ``question:<id>`` answers to copies of the documents
it names and leaves every other document the very object it was.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scope_lineage import cli_catalog_answers as answers
from scope_lineage.render.catalog_browse import BOARD_STATUSES, questions_board
from scope_lineage.render.catalog_context import context_pack, render_context_text
from scope_lineage.render.catalog_pending import pending_line, pending_report
from scope_lineage.semantics.schema import DOC_FORMAT, schema_errors

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures"
ONTOLOGY = FIXTURES / "catalog" / "ontology.json"
BEFORE = FIXTURES / "catalog-answers-before.json"
CUSTOMER = "demo_dwd.dwd_party_customer_info_df"
WAIVER = "demo_dwd.dwd_collection_fee_waiver_di"
LOAN = "demo_dwd.dwd_lending_loan_df"
DOCUMENT_FILES = (
    ROOT / "examples" / "table-semantics" / f"{CUSTOMER}.json",
    FIXTURES / "table-semantics" / "documents" / f"{WAIVER}.json",
)
ANSWER_KEYS = ("answer", "answered_by", "answered_on")


def _load_document() -> dict:
    return json.loads(ONTOLOGY.read_text(encoding="utf-8"))


def _load_semantics() -> dict:
    found = {}
    for path in DOCUMENT_FILES:
        doc = json.loads(path.read_text(encoding="utf-8"))
        found[doc["table"]] = doc
    return found


@pytest.fixture()
def document() -> dict:
    return _load_document()


@pytest.fixture()
def semantics() -> dict:
    return _load_semantics()


def _table_sem(pack: dict, table: str) -> dict:
    (entry,) = [t for t in pack["tables"] if t["table"] == table]
    return entry["semantics"]


def _question(items: list, qid: str) -> dict:
    (found,) = [q for q in items if q.get("id") == qid]
    return found


def _board_item(board: dict, table: str, qid: str) -> dict:
    (found,) = [
        i for i in board["items"]
        if i["source"] == "semantics" and i["table"] == table and i["id"] == qid
    ]
    return found


# ------------------------------------------------------------ answers carried


def test_an_answered_question_carries_its_answer_under_the_table(document, semantics) -> None:
    sem = _table_sem(context_pack(document, semantics, tables=[WAIVER]), WAIVER)

    answered = _question(sem["questions"], "q1")
    assert answered["status"] == "answered"
    assert answered["answer"] == "是，1 表示成功。"
    assert answered["answered_by"] == "demo-reviewer"
    assert answered["answered_on"] == "2026-09-26"
    assert "written" not in answered and "page" not in answered
    still_open = _question(sem["questions"], "q2")
    assert not set(ANSWER_KEYS) & set(still_open)


def test_an_answered_question_carries_its_answer_under_a_named_column(document, semantics) -> None:
    pack = context_pack(document, semantics, columns=[f"{WAIVER}.waiver_status"])

    (column,) = pack["columns"]
    answered = _question(column["questions"], "q1")
    assert answered["answer"] == "是，1 表示成功。"
    assert answered["answered_by"] == "demo-reviewer"
    assert answered["answered_on"] == "2026-09-26"


def test_the_text_gives_the_answer_after_the_question(document, semantics) -> None:
    text = render_context_text(context_pack(
        document, semantics, tables=[WAIVER], columns=[f"{WAIVER}.waiver_status"],
    ))
    alone = render_context_text(context_pack(document, semantics, columns=[f"{WAIVER}.waiver_status"]))

    lines = text.splitlines()
    at = lines.index("- q1（answered）：处理状态 1 是不是「成功」？ [column:waiver_status]")
    assert lines[at + 1] == "  - 回答：是，1 表示成功。（demo-reviewer，2026-09-26）"
    column_lines = alone.splitlines()
    at = column_lines.index("- 待确认问题 q1（answered）：处理状态 1 是不是「成功」？ [column:waiver_status]")
    assert column_lines[at + 1] == "  - 回答：是，1 表示成功。（demo-reviewer，2026-09-26）"


def test_an_answer_without_who_or_when_says_only_what_it_has(document, semantics) -> None:
    question = semantics[WAIVER]["summary"]["questions"][0]
    del question["answered_by"], question["answered_on"]

    text = render_context_text(context_pack(document, semantics, tables=[WAIVER]))

    assert "  - 回答：是，1 表示成功。" in text.splitlines()


def test_the_board_carries_the_answer_of_an_answered_question(document, semantics) -> None:
    board = questions_board(document, semantics, status="all")

    answered = _board_item(board, WAIVER, "q1")
    assert {key: answered[key] for key in ANSWER_KEYS} == {
        "answer": "是，1 表示成功。", "answered_by": "demo-reviewer", "answered_on": "2026-09-26",
    }
    assert not set(ANSWER_KEYS) & set(_board_item(board, WAIVER, "q2"))


# ------------------------------------------------------------ no page states: unchanged


def _strip_answers(value):
    """``value`` with the answer keys of every answered question removed."""
    if isinstance(value, dict):
        if value.get("status") == "answered":
            value = {k: v for k, v in value.items() if k not in ANSWER_KEYS}
        return {k: _strip_answers(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_answers(v) for v in value]
    return value


def _strip_answer_lines(text: str) -> str:
    return "".join(
        line for line in text.splitlines(keepends=True) if not line.startswith("  - 回答：")
    )


def outputs(**page) -> dict:
    """Every output the pin covers: packs (JSON and text) and boards on the fixtures."""
    document, semantics = _load_document(), _load_semantics()
    tables = [rep["table"] for rep in document["representations"]]
    requests = {
        "tables": {"tables": tables},
        "tables-brief": {"tables": tables, "brief": True},
        "focus": {"tables": [WAIVER, CUSTOMER], "table_columns": ["waiver_status", "gender_cd"],
                  "focus": True},
        "focus-brief": {"tables": [WAIVER], "table_columns": ["waiver_type"], "focus": True,
                        "brief": True},
        "columns": {"columns": [f"{WAIVER}.waiver_status", f"{WAIVER}.waiver_type",
                                f"{CUSTOMER}.gender_cd"]},
    }
    found = {}
    for name, request in requests.items():
        pack = context_pack(document, semantics, **request, **page)
        found[f"context:{name}:json"] = json.dumps(pack, ensure_ascii=False, indent=2)
        found[f"context:{name}:text"] = render_context_text(pack)
    entries = [{**pending_line(missing="还款口径", question="q", date="2026-01-01",
                               tables=[LOAN]), "line": 1}]
    report = pending_report(entries, document=document, semantics=semantics)
    for status in BOARD_STATUSES:
        for label, pending in (("none", None), ("pending", report)):
            board = questions_board(document, semantics, pending, status=status, **page)
            found[f"board:{status}:{label}"] = json.dumps(board, ensure_ascii=False, indent=2)
    return found


def _canonical(name: str, value: str) -> str:
    """An output as it was before answers were carried: answer keys / answer lines removed.

    JSON is re-serialised as the outputs serialise it, so key order counts too."""
    if name.endswith(":text"):
        return _strip_answer_lines(value)
    return json.dumps(_strip_answers(json.loads(value)), ensure_ascii=False, indent=2)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("page", [{}, {"page_states": None}, {"page_states": {}}])
def test_without_page_states_every_output_is_as_before(page) -> None:
    # ``BEFORE`` holds the sha256 of each output as main produced it, before this change
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    now = outputs(**page)

    assert set(now) == set(before)
    changed = [name for name, value in now.items() if _digest(_canonical(name, value)) != before[name]]
    assert changed == [], f"outputs that differ from before: {changed}"
    # and the stripping is not vacuous: the fixtures hold an answered question
    assert "  - 回答：" in now["context:tables:text"]
    assert '"answered_by"' in now["board:all:none"]


# ------------------------------------------------------------ page states

NOTE = {"reason": "只答了一半", "by": "demo-owner", "date": "2026-11-23"}


def _note(kind: str, **extra) -> dict:
    return {"kind": kind, **NOTE, **extra}


def _overlaid(semantics: dict) -> dict:
    """``semantics`` with the customer table's q1 answered from the page."""
    changed, unmatched = answers.overlay_answers(semantics, [{
        "table": CUSTOMER, "target": "question:q1", "value": "不会。",
        "by": "demo-owner", "date": "2026-11-23",
    }])
    assert unmatched == []
    return changed


def test_an_answer_from_the_page_is_marked_not_written(document, semantics) -> None:
    states = {(CUSTOMER.upper(), "q1"): {"written": False}}
    overlaid = _overlaid(semantics)

    pack = context_pack(document, overlaid, tables=[CUSTOMER],
                        columns=[f"{CUSTOMER}.gender_cd"], page_states=states)
    board = questions_board(document, overlaid, status="answered", page_states=states)

    for question in (_question(_table_sem(pack, CUSTOMER)["questions"], "q1"),
                     _question(pack["columns"][0]["questions"], "q1"),
                     _board_item(board, CUSTOMER, "q1")):
        assert question["status"] == "answered"
        assert question["answer"] == "不会。"
        assert question["written"] is False
    text = render_context_text(pack).splitlines()
    assert text.count("  - 回答（页面填写，尚未写回）：不会。（demo-owner，2026-11-23）") == 2
    # a written answer on another table is not marked
    waiver = questions_board(document, overlaid, status="answered", page_states=states)
    assert "written" not in _board_item(waiver, WAIVER, "q1")


@pytest.mark.parametrize("kind, label", [
    ("partial", "部分回答"), ("deferred", "暂缓"), ("redirect", "转问 demo-team"),
])
def test_a_note_that_keeps_the_question_open(document, semantics, kind, label) -> None:
    extra = {"to": "demo-team"} if kind == "redirect" else {}
    states = {(WAIVER, "q2"): _note(kind, **extra)}

    pack = context_pack(document, semantics, tables=[WAIVER], page_states=states)
    board = questions_board(document, semantics, page_states=states)

    question = _question(_table_sem(pack, WAIVER)["questions"], "q2")
    item = _board_item(board, WAIVER, "q2")
    for entry in (question, item):
        assert entry["status"] == "open"
        assert entry["page"] == _note(kind, **extra)
    assert (
        f"- q2（open）：豁免类型实际存的是字母码还是数字码？ [column:waiver_type]"
        f"（{label}：只答了一半；demo-owner，2026-11-23）"
    ) in render_context_text(pack).splitlines()


def test_a_partial_answer_shows_its_choice(document, semantics) -> None:
    states = {(WAIVER, "q2"): _note("partial", choice="no")}

    text = render_context_text(context_pack(document, semantics, tables=[WAIVER], page_states=states))

    assert "（部分回答，否：只答了一半；demo-owner，2026-11-23）" in text


@pytest.mark.parametrize("kind, label", [("invalid", "问题有误"), ("not_applicable", "不适用")])
def test_a_set_aside_question_stays_listed_apart(document, semantics, kind, label) -> None:
    states = {(WAIVER, "q3"): _note(kind)}

    pack = context_pack(document, semantics, tables=[WAIVER],
                        columns=[f"{WAIVER}.waiver_type"], page_states=states)

    question = _question(_table_sem(pack, WAIVER)["questions"], "q3")
    assert question["status"] == "set_aside" and question["page"] == _note(kind)
    lines = render_context_text(pack).splitlines()
    heading = lines.index("## 待确认问题")
    section = lines[heading + 1:lines.index("", heading + 1)]
    expected = (
        f"- 已搁置：q3 同一产品编码在产品表里会不会有多个版本同时生效？ [rule:r3]"
        f"（{label}：只答了一半；demo-owner，2026-11-23）"
    )
    assert section[-1] == expected
    assert not any(line.startswith("- q3（") for line in section)


def test_set_aside_is_not_special_in_the_focus_counts(document, semantics) -> None:
    states = {(WAIVER, "q2"): _note("invalid")}
    request = {"tables": [WAIVER], "table_columns": ["waiver_status"], "focus": True}

    plain = _table_sem(context_pack(document, semantics, **request), WAIVER)
    noted = _table_sem(context_pack(document, semantics, **request, page_states=states), WAIVER)

    assert noted["focus"] == plain["focus"]
    assert [q["id"] for q in noted["questions"]] == [q["id"] for q in plain["questions"]]


def test_the_board_files_a_set_aside_question_under_its_own_status(document, semantics) -> None:
    states = {(WAIVER, "q3"): _note("not_applicable"), (WAIVER, "q2"): _note("deferred")}

    opened = questions_board(document, semantics, page_states=states)
    aside = questions_board(document, semantics, status="set_aside", page_states=states)
    every = questions_board(document, semantics, status="all", page_states=states)

    assert [(i["table"], i["id"]) for i in opened["items"]] == [(WAIVER, "q2"), (CUSTOMER, "q1")]
    (item,) = aside["items"]
    assert item["id"] == "q3" and item["status"] == "set_aside"
    assert item["page"] == _note("not_applicable")
    assert aside["counts"]["semantics"] == 1
    # counts and facets follow the status filter, as they do for open and answered
    assert [facet["count"] for facet in aside["concepts"]] == [1]
    assert "q3" in [i["id"] for i in every["items"] if i["table"] == WAIVER]
    assert every["total"] == 4


def test_set_aside_is_a_status_only_with_page_states(document, semantics) -> None:
    assert "set_aside" not in BOARD_STATUSES
    with pytest.raises(ValueError) as caught:
        questions_board(document, semantics, status="set_aside")
    assert str(caught.value) == "status must be one of open, answered, all, not 'set_aside'"
    with pytest.raises(answers.CatalogAnswerError) as wrapped:
        answers.questions(document, semantics, status="set_aside")
    assert wrapped.value.exit_code == 2

    empty = questions_board(document, semantics, status="set_aside", page_states={})
    assert empty["items"] == []
    with pytest.raises(ValueError) as extended:
        questions_board(document, semantics, status="closed", page_states={})
    assert str(extended.value) == (
        "status must be one of open, answered, set_aside, all, not 'closed'"
    )


def test_a_note_on_an_answered_question_is_ignored(document, semantics) -> None:
    states = {(WAIVER, "q1"): _note("invalid")}

    board = questions_board(document, semantics, status="all", page_states=states)
    pack = context_pack(document, semantics, tables=[WAIVER], page_states=states)

    for entry in (_board_item(board, WAIVER, "q1"), _question(_table_sem(pack, WAIVER)["questions"], "q1")):
        assert entry["status"] == "answered" and "page" not in entry


def test_a_page_state_that_is_neither_shape_is_refused(document, semantics) -> None:
    for bad in ({"kind": "closed", **NOTE}, {"written": True}, "x"):
        with pytest.raises(ValueError):
            questions_board(document, semantics, page_states={(WAIVER, "q2"): bad})
        with pytest.raises(ValueError):
            context_pack(document, semantics, tables=[WAIVER], page_states={(WAIVER, "q2"): bad})
    with pytest.raises(answers.CatalogAnswerError) as caught:
        answers.context(document, semantics, tables=[WAIVER],
                        page_states={(WAIVER, "q2"): {"kind": "closed"}})
    assert caught.value.exit_code == 2


def test_the_wrappers_pass_page_states_through(document, semantics) -> None:
    states = {(WAIVER, "q2"): _note("deferred")}

    pack = answers.context(document, semantics, tables=[WAIVER], page_states=states)
    board = answers.questions(document, semantics, status="all", page_states=states)

    assert _question(_table_sem(pack.result, WAIVER)["questions"], "q2")["page"]["kind"] == "deferred"
    assert "（暂缓：" in pack.text()
    assert _board_item(board.result, WAIVER, "q2")["page"]["kind"] == "deferred"


def test_page_states_never_add_a_key_to_a_document(document, semantics) -> None:
    before = copy.deepcopy(semantics)
    states = {(WAIVER, "q2"): _note("partial"), (WAIVER, "q3"): _note("invalid"),
              (WAIVER, "q1"): {"written": False}}

    context_pack(document, semantics, tables=[WAIVER], columns=[f"{WAIVER}.waiver_type"],
                 page_states=states)
    questions_board(document, semantics, status="all", page_states=states)

    assert semantics == before
    for doc in semantics.values():
        assert schema_errors(doc, DOC_FORMAT) == []


# ------------------------------------------------------------ overlay


def _confirmation(table: str, target: str, value="不会。") -> dict:
    return {"table": table, "target": target, "value": value, "by": "demo-owner",
            "date": "2026-11-23"}


def test_overlay_answers_the_named_documents_only(semantics) -> None:
    before = copy.deepcopy(semantics)

    changed, unmatched = answers.overlay_answers(
        semantics, [_confirmation(CUSTOMER.upper(), "question:q1")]
    )

    assert unmatched == []
    assert set(changed) == set(semantics) and changed is not semantics
    assert changed[WAIVER] is semantics[WAIVER]
    question = changed[CUSTOMER]["summary"]["questions"][0]
    assert question["status"] == "answered" and question["answer"] == "不会。"
    assert question["answered_by"] == "demo-owner" and question["answered_on"] == "2026-11-23"
    assert schema_errors(changed[CUSTOMER], DOC_FORMAT) == []
    assert semantics == before


def test_overlay_keeps_the_callers_keys(semantics) -> None:
    keyed = {name.upper(): doc for name, doc in semantics.items()}

    changed, unmatched = answers.overlay_answers(keyed, [_confirmation(CUSTOMER, "question:q1")])

    assert unmatched == [] and set(changed) == set(keyed)
    assert changed[CUSTOMER.upper()]["summary"]["questions"][0]["status"] == "answered"
    assert changed[WAIVER.upper()] is keyed[WAIVER.upper()]


def test_overlay_lists_what_it_could_not_apply(semantics) -> None:
    changed, unmatched = answers.overlay_answers(semantics, [
        _confirmation("demo_dwd.no_such_table", "question:q1"),
        _confirmation(CUSTOMER, "question:q9"),
        _confirmation(CUSTOMER, "column:gender_cd.meaning", "性别"),
        _confirmation(CUSTOMER, "summary.row", "一行一个客户"),
    ])

    reasons = {(item["table"], item["target"]): item["reason"] for item in unmatched}
    assert len(unmatched) == 4
    assert reasons[("demo_dwd.no_such_table", "question:q1")].startswith("unknown table")
    assert reasons[(CUSTOMER, "question:q9")].startswith("unknown question")
    for target in ("column:gender_cd.meaning", "summary.row"):
        assert reasons[(CUSTOMER, target)] == "only question:<id> answers are overlaid"
    assert all(changed[name] is semantics[name] for name in semantics)
    assert changed[CUSTOMER]["columns"] == semantics[CUSTOMER]["columns"]


def test_overlay_without_semantics_matches_nothing() -> None:
    changed, unmatched = answers.overlay_answers(None, [_confirmation(CUSTOMER, "question:q1")])

    assert changed == {}
    assert [item["reason"][:13] for item in unmatched] == ["unknown table"]
