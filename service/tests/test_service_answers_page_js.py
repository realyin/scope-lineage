"""The page's answer cards: their pure functions, run with node when it is on PATH.

What a card shows for a board item, what it sends back (``seen``, the request bodies), the
checks before sending and the read-only sentence are pure functions of ``views.js``; the
last test builds a body in node from a live server's board item and posts it, so the page
and the server agree on ``seen``. Drawing and clicking are not exercised here.
"""

from __future__ import annotations

import http.client
import json
import shutil
import subprocess
import threading
from importlib import resources

import pytest
from answer_fixtures import prepare
from service_paths import CUSTOMER

from scope_lineage_service.http_server import make_server
from scope_lineage_service.state import CatalogState

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not on PATH")


def _call(function: str, *args):
    static = resources.files("scope_lineage_service") / "static"
    base = static.joinpath("views.js").as_uri()
    values = ", ".join(json.dumps(arg, ensure_ascii=False) for arg in args)
    module = (f"import * as views from '{base}';\n"
              f"const out = views.{function}({values});\n"
              "console.log(JSON.stringify(out === undefined ? null : out));")
    done = subprocess.run([NODE, "--input-type=module", "-e", module], capture_output=True,
                          text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


OPEN = {"source": "semantics", "table": CUSTOMER, "id": "q1", "text": "问题一？", "status": "open"}
ANSWERED = {**OPEN, "status": "answered", "answer": "会。", "answered_by": "乙",
            "answered_on": "2026-01-01"}
RECORD = {"table": CUSTOMER, "question": "q1", "asked": "问题一？", "base": None,
          "kind": "answer", "answer": "不会。", "choice": "no", "source": {"kind": "person"},
          "by": "甲", "date": "2026-11-23"}
UNWRITTEN = {**OPEN, "status": "answered", "answer": "否：不会。", "answered_by": "甲",
             "answered_on": "2026-11-23", "written": False, "record": RECORD,
             "record_state": "effective", "disk": None}
NOTE = {"kind": "redirect", "reason": "不归我们管", "to": "数据组", "by": "甲",
        "date": "2026-11-23"}
NOTED = {**OPEN, "page": NOTE, "disk": None, "record_state": "effective",
         "record": {**RECORD, "kind": "redirect", "reason": "不归我们管", "to": "数据组",
                    "answer": None}}
ASIDE = {**NOTED, "status": "set_aside", "page": {**NOTE, "kind": "invalid"}}
UNMATCHED = {**ANSWERED, "record": RECORD, "record_state": "unmatched",
             "disk": {"answer": "会。", "answered_by": "乙", "answered_on": "2026-01-01"}}


def test_the_status_filter_offers_set_aside_only_with_answers() -> None:
    assert [value for value, _ in _call("statusChoices", False)] == ["open", "answered", "all"]
    assert ["set_aside", "已搁置"] in _call("statusChoices", True)


@pytest.mark.parametrize("item, mode, unmatched, can_note", [
    (OPEN, "open", False, True),
    (ANSWERED, "answered", False, False),
    (UNWRITTEN, "unwritten", False, True),
    (NOTED, "note", False, True),
    (ASIDE, "set_aside", False, True),
    (UNMATCHED, "answered", True, False),
])
def test_card_state(item, mode, unmatched, can_note) -> None:
    state = _call("cardState", item)
    assert (state["mode"], state["unmatched"], state["canNote"]) == (mode, unmatched, can_note)


def test_seen_is_the_disk_answer_and_the_record_shown() -> None:
    assert _call("seenOf", OPEN) == {"disk": None, "record": None}
    assert _call("seenOf", ANSWERED) == {"disk": {"answer": "会。", "answered_by": "乙",
                                                  "answered_on": "2026-01-01"}, "record": None}
    # an overlaid answer: the document's answer is the record's disk, not what is shown
    assert _call("seenOf", UNWRITTEN) == {"disk": None, "record": RECORD}
    assert _call("seenOf", UNMATCHED)["disk"]["answer"] == "会。"


def test_request_bodies() -> None:
    body = _call("answerBody", OPEN, {"kind": "answer", "text": "不会。", "choice": "no",
                                      "to": "x", "by": " 甲 "})
    assert body == {"table": CUSTOMER, "question": "q1", "kind": "answer", "asked": "问题一？",
                    "seen": {"disk": None, "record": None}, "by": "甲", "answer": "不会。",
                    "choice": "no"}
    deferred = _call("answerBody", OPEN, {"kind": "deferred", "text": "等等", "choice": "yes",
                                          "by": "甲"})
    assert "choice" not in deferred and deferred["reason"] == "等等" and "answer" not in deferred
    redirect = _call("answerBody", OPEN, {"kind": "redirect", "text": "问他", "to": "数据组",
                                          "by": "甲"})
    assert redirect["to"] == "数据组"
    assert _call("withdrawBody", CUSTOMER, "q1", RECORD) == {
        "table": CUSTOMER, "question": "q1", "seen": RECORD}


def test_the_page_sends_what_was_typed() -> None:
    """No NFKC on the page either: full-width punctuation in the text and the name stays."""
    body = _call("answerBody", OPEN, {"kind": "answer", "text": "会：是（测试），对？",
                                      "by": " 名（甲） "})
    assert body["answer"] == "会：是（测试），对？" and body["by"] == "名（甲）"


def test_answering_again_uses_the_question_as_it_is_now() -> None:
    entry = {"table": CUSTOMER, "question": "q1", "record": RECORD, "reason": "changed",
             "now": {"text": "新问题？", "status": "answered", "answer": "会。",
                     "answered_by": "乙", "answered_on": "2026-01-01"}}
    body = _call("againBody", entry, {"kind": "answer", "text": "还是不会。", "by": "甲"})
    assert body["asked"] == "新问题？"
    assert body["seen"] == {"disk": {"answer": "会。", "answered_by": "乙",
                                     "answered_on": "2026-01-01"}, "record": RECORD}


@pytest.mark.parametrize("form, problem", [
    ({"kind": "answer", "text": "x", "by": ""}, "先填回答人"),
    ({"kind": "answer", "text": "  ", "by": "甲"}, "不能是空的"),
    ({"kind": "answer", "text": "a\nb", "by": "甲"}, "一行"),
    ({"kind": "answer", "text": "字" * 1001, "by": "甲"}, "1000"),
    ({"kind": "answer", "text": "x", "by": "名" * 61}, "60"),
    ({"kind": "redirect", "text": "x", "by": "甲", "to": ""}, "该问谁"),
    ({"kind": "answer", "text": "字" * 1000, "by": "甲"}, None),
])
def test_form_problems(form, problem) -> None:
    found = _call("formProblem", form)
    assert (found is None) if problem is None else (problem in found)


def test_record_text() -> None:
    assert _call("recordText", RECORD) == "否：不会。"
    assert _call("recordText", NOTE) == "该问 数据组：不归我们管"
    assert _call("recordText", {"kind": "partial", "reason": "一半", "choice": "yes"}) == \
        "部分回答：是：一半"


def test_read_only_sentences() -> None:
    assert "--answers FILE" in _call("readOnlyReason", None)
    assert "--answers-allow-remote" in _call("readOnlyReason", {"status": "ok", "writable": False,
                                                                 "refused": "..."})
    assert "读不了" in _call("readOnlyReason", {"status": "unreadable", "reason": "坏了"})
    assert _call("readOnlyReason", {"status": "ok", "writable": True}) is None
    assert "semantic confirm" in _call("writeBackCommand")


def test_table_page_marks() -> None:
    assert _call("pageMarks", {"document": {}}) is None
    marks = _call("pageMarks", {"document": {}, "unwritten": ["q1"], "page": {"q2": NOTE}})
    assert marks["page"] == {"q2": NOTE}


def test_a_body_built_by_the_page_is_taken_by_the_server(inputs, tmp_path) -> None:
    prepare(inputs["semantics"])
    state = CatalogState(str(inputs["ontology"]), semantics=str(inputs["semantics"]),
                         answers=str(tmp_path / "answers.json"), answers_writer=True)
    httpd = make_server(state, port=0, quiet=True)
    thread = threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True)
    thread.start()

    def request(method, path, payload=None):
        connection = http.client.HTTPConnection(*httpd.server_address[:2], timeout=10)
        try:
            body = json.dumps(payload).encode() if payload is not None else None
            connection.request(method, path, body=body,
                               headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def item():
        board = request("GET", f"/api/questions?status=all&source=semantics&table={CUSTOMER}")[1]
        return next(found for found in board["items"] if found["id"] == "q1")

    try:
        form = {"kind": "answer", "text": "不会。", "choice": "no", "by": "甲"}
        assert request("POST", "/api/answers", _call("answerBody", item(), form))[0] == 201
        shown = item()
        assert _call("cardState", shown)["mode"] == "unwritten"
        changed = {"kind": "deferred", "text": "其实不确定", "by": "乙"}
        assert request("POST", "/api/answers", _call("answerBody", shown, changed))[0] == 201
        # the first page, still showing the answer, is refused
        assert request("POST", "/api/answers", _call("answerBody", shown, changed))[0] == 409
        noted = item()
        withdraw = _call("withdrawBody", noted["table"], noted["id"], noted["record"])
        assert request("POST", "/api/answers/withdraw", withdraw)[0] == 200
        assert _call("cardState", item())["mode"] == "open"
    finally:
        httpd.shutdown()
        httpd.server_close()


# ------------------------------------------------------------------ structured answers


ROW_VALUE = {"unique": "no", "grain_columns": ["customer_id", "dt"]}
CODE_VALUE = [{"value": "X", "meaning": "其他"}, {"value": "1", "meaning": "已实名"}]


@pytest.mark.parametrize("target, value", [
    ("summary.row", ROW_VALUE),
    ("summary.row", {"unique": "yes", "grain_columns": ["customer_id"]}),
    ("column:etl_time.meaning", "装载批次时间"),
    ("column:verify_status.code_values", CODE_VALUE),
])
def test_the_page_writes_the_servers_sentence_and_reads_its_slot(target, value) -> None:
    from service_paths import SEMANTICS

    from scope_lineage_service import answers as records_file

    document = json.loads((SEMANTICS / f"{CUSTOMER}.json").read_text(encoding="utf-8"))
    assert _call("structuredSentence", target, value) == records_file.structured_sentence(target, value)
    assert _call("slotOf", document, target, value) == records_file.slot_of(document, target, value)


STRUCTURED = {"mode": "code_values", "column": "verify_status", "by": "甲", "text": "",
              "codes": [{"value": "X", "meaning": "其他"}, {"value": "", "meaning": ""}]}


@pytest.mark.parametrize("change, problem", [
    ({}, None),
    ({"by": ""}, "先填回答人"),
    ({"column": ""}, "先选列"),
    ({"codes": [{"value": "", "meaning": "空"}]}, "码值不能是空的"),
    ({"codes": [{"value": "X", "meaning": ""}]}, "含义不能是空的"),
    ({"codes": [{"value": "X", "meaning": "a"}, {"value": "X", "meaning": "b"}]}, "两次"),
    ({"codes": [{"value": "字" * 65, "meaning": "a"}]}, "64"),
    ({"mode": "meaning", "meaning": ""}, "含义不能是空的"),
    ({"mode": "meaning", "meaning": "装载批次时间"}, None),
    ({"mode": "row", "unique": "", "columns": "customer_id"}, "是否唯一"),
    ({"mode": "row", "unique": "no", "columns": ""}, "粒度列"),
    ({"mode": "row", "unique": "no", "columns": "a, a"}, "重复"),
    ({"mode": "row", "unique": "no", "columns": "a b c d e f g h i"}, "8"),
    ({"mode": "row", "unique": "no", "columns": "customer_id，dt"}, None),
    ({"text": "补充\n两行"}, "一行"),
])
def test_structured_form_problems(change, problem) -> None:
    found = _call("structuredProblem", {**STRUCTURED, **change})
    assert (found is None) if problem is None else (problem in found), found


def test_structured_body() -> None:
    slot = {"X": None}
    body = _call("structuredBody", OPEN, {**STRUCTURED, "text": " 以码表为准 "}, slot)
    assert body == {"table": CUSTOMER, "question": "q1", "kind": "answer", "asked": "问题一？",
                    "seen": {"disk": None, "record": None, "slot": slot}, "by": "甲",
                    "target": "column:verify_status.code_values",
                    "value": [{"value": "X", "meaning": "其他"}], "answer": " 以码表为准 "}
    row = _call("structuredBody", OPEN, {"mode": "row", "unique": "no", "columns": "a, b",
                                         "by": "甲", "text": ""}, {})
    assert row["target"] == "summary.row" and "answer" not in row
    assert row["value"] == {"unique": "no", "grain_columns": ["a", "b"]}


def test_structured_record_text_and_marks() -> None:
    record = {**RECORD, "target": "column:etl_time.meaning", "value": "装载批次时间"}
    del record["answer"]
    del record["choice"]
    assert _call("recordText", record) == "列 etl_time 的含义：装载批次时间"
    assert _call("recordText", {**record, "answer": "补充"}) == "列 etl_time 的含义：装载批次时间；补充"
    assert _call("columnChoices", {"columns": [{"column": "gender_cd"}]}, None) == ["gender_cd"]
    assert _call("columnChoices", {"columns": []}, {"columns": [{"column": "a"}, {"column": "b"}]}) == ["a", "b"]


def test_table_page_slot_marks() -> None:
    static = resources.files("scope_lineage_service") / "static"
    base = static.joinpath("views.js").as_uri()
    module = (f"import * as views from '{base}';\n"
              "const marks = views.pageMarks({document: {}, unwritten: [], page: {}, unwritten_slots: "
              "['row', 'column:gender_cd.meaning', 'column:gender_cd.code_values:X', "
              "'column:gender_cd.code_values:N']});\n"
              "console.log(JSON.stringify([views.slotMarks(marks, 'gender_cd'), "
              "views.slotMarks(marks, 'etl_time'), marks.slots.has('row'), "
              "views.slotMarks(views.pageMarks({document: {}, unwritten: []}), 'gender_cd')]));")
    done = subprocess.run([NODE, "--input-type=module", "-e", module], capture_output=True,
                          text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == ["含义、码值 N、X", None, True, None]


def test_a_structured_body_built_by_the_page_is_taken_by_the_server(inputs, tmp_path) -> None:
    prepare(inputs["semantics"])
    state = CatalogState(str(inputs["ontology"]), semantics=str(inputs["semantics"]),
                         answers=str(tmp_path / "answers.json"), answers_writer=True)
    httpd = make_server(state, port=0, quiet=True)
    thread = threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True)
    thread.start()

    def request(method, path, payload=None):
        connection = http.client.HTTPConnection(*httpd.server_address[:2], timeout=10)
        try:
            body = json.dumps(payload).encode() if payload is not None else None
            connection.request(method, path, body=body,
                               headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def item():
        board = request("GET", f"/api/questions?status=all&source=semantics&table={CUSTOMER}")[1]
        return next(found for found in board["items"] if found["id"] == "q1")

    def shown():
        return request("GET", f"/api/semantics?table={CUSTOMER}")[1]["document"]

    try:
        form = {"mode": "code_values", "column": "gender_cd", "by": "甲", "text": "",
                "codes": [{"value": "X", "meaning": "其他"}]}
        target, value = "column:gender_cd.code_values", [{"value": "X", "meaning": "其他"}]
        slot = _call("slotOf", shown(), target, value)
        assert request("POST", "/api/answers", _call("structuredBody", item(), form, slot))[0] == 201
        answered = item()
        assert _call("cardState", answered)["mode"] == "unwritten"
        assert answered["answer"] == "列 gender_cd 的码值：X=其他"
        # a page still showing the slot as it was before is refused
        changed = {**form, "codes": [{"value": "X", "meaning": "别的"}]}
        assert request("POST", "/api/answers",
                       _call("structuredBody", answered, changed, slot))[0] == 409
        fresh = _call("slotOf", shown(), target, value)
        assert fresh == {"X": "其他"}
        assert request("POST", "/api/answers",
                       _call("structuredBody", answered, changed, fresh))[0] == 201
    finally:
        httpd.shutdown()
        httpd.server_close()
