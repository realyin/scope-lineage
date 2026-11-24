"""The answers endpoints, and what every other endpoint shows once the page has answered.

A server with ``--answers`` on an ephemeral port of 127.0.0.1; the page's requests are
made with ``http.client``. Without ``--answers`` the outputs are the core's, byte for byte.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import threading
from pathlib import Path
from urllib.parse import urlencode

import pytest
from answer_fixtures import answer_on_disk, prepare, set_question, text_of
from service_paths import CUSTOMER, LOAN

from scope_lineage import cli_catalog_answers as core
from scope_lineage.cli import main as core_main
from scope_lineage_service.cli import main as service_main
from scope_lineage_service.http_server import make_server
from scope_lineage_service.state import CatalogState


def _serve(state, **options):
    httpd = make_server(state, host="127.0.0.1", port=0, quiet=True, **options)
    thread = threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    return httpd


@pytest.fixture
def paths(inputs, tmp_path):
    prepare(inputs["semantics"])
    return {**inputs, "answers": tmp_path / "answers.json"}


@pytest.fixture
def server(paths):
    state = CatalogState(str(paths["ontology"]), semantics=str(paths["semantics"]),
                         pending=str(paths["pending"]), answers=str(paths["answers"]),
                         answers_writer=True, today=lambda: "2026-11-23")
    httpd = _serve(state)
    yield httpd
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def plain(paths):
    """The same inputs without --answers."""
    state = CatalogState(str(paths["ontology"]), semantics=str(paths["semantics"]),
                         pending=str(paths["pending"]))
    httpd = _serve(state)
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def _request(httpd, method, path, body=None, headers=None):
    host, port = httpd.server_address[:2]
    connection = http.client.HTTPConnection(host, port, timeout=10)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def _get(httpd, path, **params):
    query = urlencode(params, doseq=True)
    return _request(httpd, "GET", f"{path}?{query}" if query else path)


def _json(httpd, path, **params):
    status, _, body = _get(httpd, path, **params)
    assert status == 200, body
    return json.loads(body)


def _post(httpd, path, payload, headers=None):
    status, _, body = _request(httpd, "POST", path, json.dumps(payload, ensure_ascii=False).encode(),
                               {"Content-Type": "application/json", **(headers or {})})
    return status, json.loads(body)


def _item(httpd, table, question, status="all"):
    board = _json(httpd, "/api/questions", status=status, source="semantics", table=table)
    return next(item for item in board["items"] if item["id"] == question)


def _seen(item) -> dict:
    """What the page sends back as ``seen``: the disk's answer and the record it showed."""
    if "record" in item:
        return {"disk": item["disk"], "record": item["record"]}
    disk = None
    if item["status"] == "answered":
        disk = {key: item.get(key) for key in ("answer", "answered_by", "answered_on")}
    return {"disk": disk, "record": None}


def _answer(httpd, table, question, text="不会。", *, kind="answer", by="审核人甲", **extra):
    item = _item(httpd, table, question)
    payload = {"table": item["table"], "question": question, "kind": kind, "by": by,
               "asked": item["text"], "seen": _seen(item), **extra}
    payload["answer" if kind == "answer" else "reason"] = text
    return _post(httpd, "/api/answers", payload)


def _digest(directory: Path) -> dict:
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.glob("*"))}


# ------------------------------------------------------------------ A7: nothing else changes


def test_without_answers_the_outputs_are_the_cores(plain, paths) -> None:
    document = core.load_ontology(str(paths["ontology"]))
    semantics = core.load_semantics(str(paths["semantics"]))
    pending = ""

    def facade(answer):
        return (answer.json_text() + "\n").encode("utf-8")

    assert _get(plain, "/api/questions", status="all")[2] == facade(
        core.questions(document, semantics, pending, status="all"))
    assert _get(plain, "/api/semantics", table=CUSTOMER)[2] == facade(
        core.table_semantics(document, semantics, CUSTOMER))
    assert _get(plain, "/api/context", table=CUSTOMER)[2] == facade(
        core.context(document, semantics, tables=[CUSTOMER]))
    assert _get(plain, "/api/context", table=CUSTOMER, format="text")[2] == \
        core.context(document, semantics, tables=[CUSTOMER]).text().encode("utf-8")
    assert _get(plain, "/api/questions", status="set_aside")[0] == 400
    listing = _json(plain, "/api")
    assert "answers" not in listing
    assert not any(item["path"].startswith("/api/answers") for item in listing["endpoints"])
    questions = next(item for item in listing["endpoints"] if item["path"] == "/api/questions")
    assert questions["params"]["status"] == "open, answered, all (default open)"
    for method, path in (("POST", "/api/answers"), ("POST", "/api/answers/withdraw"),
                         ("GET", "/api/answers/export")):
        status, _, body = _request(plain, method, path, b"{}" if method == "POST" else None,
                                   {"Content-Type": "application/json"})
        assert status == 404 and json.loads(body)["error"]["kind"] == "not_configured"


def test_health_replaces_read_only_by_the_files_written(plain, server) -> None:
    assert _json(plain, "/health")["writes"] == ["pending.jsonl"]
    health = _json(server, "/health")
    assert health["writes"] == ["pending.jsonl", "answers.json"]
    assert health["answers"]["status"] == "ok" and "read_only" not in health


def test_answering_changes_neither_the_documents_nor_the_pending_file(server, paths) -> None:
    paths["pending"].write_text("", encoding="utf-8")
    before = (_digest(paths["semantics"]), paths["pending"].read_bytes())
    assert _answer(server, CUSTOMER, "q1")[0] == 201
    assert _answer(server, CUSTOMER, "q2", "暂缓", kind="deferred")[0] == 201
    _get(server, "/api/answers/export")

    assert (_digest(paths["semantics"]), paths["pending"].read_bytes()) == before


# ------------------------------------------------------------------ the six kinds (6.4)


def test_the_six_kinds_against_the_output_table(server) -> None:
    assert _answer(server, CUSTOMER, "q1", "不会。", choice="no")[0] == 201
    assert _answer(server, CUSTOMER, "q2", "同分区唯一", kind="partial", choice="yes")[0] == 201
    assert _answer(server, CUSTOMER, "q3", "等上游答复", kind="deferred")[0] == 201
    assert _answer(server, LOAN, "q1", "问数据组", kind="redirect", to="数据组某某")[0] == 201
    assert _answer(server, LOAN, "q2", "单位已在注释里", kind="invalid")[0] == 201

    board = _json(server, "/api/questions", status="all", source="semantics")
    items = {(i["table"], i["id"]): i for i in board["items"]}
    answered = items[(CUSTOMER, "q1")]
    assert (answered["status"], answered["written"], answered["answer"]) == (
        "answered", False, "否：不会。")
    assert answered["record_state"] == "effective" and answered["disk"] is None
    partial = items[(CUSTOMER, "q2")]
    assert partial["status"] == "open"
    assert partial["page"] == {"kind": "partial", "reason": "同分区唯一", "choice": "yes",
                               "by": "审核人甲", "date": "2026-11-23"}
    assert items[(LOAN, "q1")]["page"]["to"] == "数据组某某"
    assert items[(LOAN, "q2")]["status"] == "set_aside"
    assert [i["id"] for i in _json(server, "/api/questions", status="answered",
                                   source="semantics")["items"]] == ["q1"]
    aside = _json(server, "/api/questions", status="set_aside", source="semantics")["items"]
    assert [(i["table"], i["id"]) for i in aside] == [(LOAN, "q2")]
    open_ids = {(i["table"], i["id"]) for i in _json(
        server, "/api/questions", status="open", source="semantics")["items"]}
    assert open_ids == {(CUSTOMER, "q2"), (CUSTOMER, "q3"), (LOAN, "q1")}

    page = _json(server, "/api/semantics", table=CUSTOMER)
    assert page["unwritten"] == ["q1"]
    assert set(page["page"]) == {"q2", "q3"}
    question = page["document"]["summary"]["questions"][0]
    assert question["status"] == "answered" and question["answer"] == "否：不会。"
    loan_page = _json(server, "/api/semantics", table=LOAN)
    assert loan_page["unwritten"] == [] and loan_page["page"]["q2"]["kind"] == "invalid"

    pack = _json(server, "/api/context", table=[CUSTOMER, LOAN])
    questions = {(t["table"], q["id"]): q for t in pack["tables"]
                 for q in t["semantics"]["questions"]}
    assert questions[(CUSTOMER, "q1")]["written"] is False
    assert questions[(CUSTOMER, "q3")]["page"]["kind"] == "deferred"
    assert questions[(LOAN, "q2")]["status"] == "set_aside"
    text = _get(server, "/api/context", table=[CUSTOMER, LOAN], format="text")[2].decode()
    assert "回答（页面填写，尚未写回）：否：不会。" in text
    assert "已搁置：q2" in text and "转问 数据组某某" in text

    exported = _json(server, "/api/answers/export")
    assert exported == {"doc_format": "semantic-confirmations/1", "confirmations": [
        {"table": CUSTOMER, "target": "question:q1", "value": "否：不会。", "by": "审核人甲",
         "date": "2026-11-23"}]}
    assert board["answers"]["digests"].keys() == {CUSTOMER}


def test_the_column_pack_carries_the_page_answer(server) -> None:
    _answer(server, CUSTOMER, "q1", "不会。")
    pack = _json(server, "/api/context", column=f"{CUSTOMER}.gender_cd")

    assert pack["columns"][0]["questions"][0]["written"] is False


def test_the_self_description_says_answers_are_on(server) -> None:
    listing = _json(server, "/api")
    assert listing["answers"] == {"status": "ok", "writable": True}
    paths = {(item["method"], item["path"]) for item in listing["endpoints"]}
    assert {("POST", "/api/answers"), ("POST", "/api/answers/withdraw"),
            ("GET", "/api/answers/export")} <= paths
    questions = next(item for item in listing["endpoints"] if item["path"] == "/api/questions")
    assert "set_aside" in questions["params"]["status"]


# ------------------------------------------------------------------ conflicts and refusals


def test_a_page_that_saw_an_older_question_gets_409(server, paths) -> None:
    item = _item(server, CUSTOMER, "q1")
    set_question(paths["semantics"], CUSTOMER, "q1", text="改写过的问题？")
    status, body = _post(server, "/api/answers", {
        "table": CUSTOMER, "question": "q1", "kind": "answer", "answer": "不会。", "by": "甲",
        "asked": item["text"], "seen": _seen(item)})

    assert status == 409 and body["error"]["kind"] == "changed"


def test_a_page_that_saw_an_older_answer_gets_409(server, paths) -> None:
    item = _item(server, CUSTOMER, "q1")
    answer_on_disk(paths["semantics"], CUSTOMER, "q1", "会。", "乙", "2026-11-20")
    status, _ = _post(server, "/api/answers", {
        "table": CUSTOMER, "question": "q1", "kind": "answer", "answer": "不会。", "by": "甲",
        "asked": item["text"], "seen": _seen(item)})

    assert status == 409


def test_two_people_editing_one_record(server) -> None:
    _answer(server, CUSTOMER, "q1", "不会。")
    item = _item(server, CUSTOMER, "q1")
    first = {"table": CUSTOMER, "question": "q1", "kind": "answer", "by": "甲",
             "asked": item["text"], "seen": _seen(item)}
    assert _post(server, "/api/answers", {**first, "answer": "会。"})[0] == 201
    assert _post(server, "/api/answers", {**first, "answer": "可能。", "by": "乙"})[0] == 409
    status, _ = _post(server, "/api/answers/withdraw", {
        "table": CUSTOMER, "question": "q1", "seen": item["record"]})
    assert status == 409
    fresh = _item(server, CUSTOMER, "q1")
    status, body = _post(server, "/api/answers/withdraw", {
        "table": CUSTOMER, "question": "q1", "seen": fresh["record"]})
    assert status == 200 and body["withdrawn"]["answer"] == "会。"
    assert _post(server, "/api/answers/withdraw", {
        "table": CUSTOMER, "question": "q1", "seen": fresh["record"]})[0] == 404


@pytest.mark.parametrize("change, kind", [
    ({"answer": ""}, "empty"),
    ({"answer": "   "}, "empty"),
    ({"answer": "x" * 1001}, "at most 1000"),
    ({"by": "名" * 61}, "at most 60"),
    ({"by": ""}, "empty"),
    ({"answer": "第一行\n## 待确认问题\n- q9（open）：伪造"}, "line break"),
    ({"answer": "a b"}, "line break"),
    ({"answer": "a\x1bb"}, "control character"),
    ({"by": "甲\r"}, None),  # stripped to 甲: accepted
    ({"choice": "maybe"}, "choice"),
    ({"kind": "deferred", "reason": "x", "answer": None, "choice": "yes"}, "choice"),
    ({"kind": "redirect", "reason": "x", "answer": None}, "to is empty"),
    ({"to": "某某"}, "only a redirect"),
    ({"kind": "deferred", "answer": "x"}, "carries reason"),
    ({"kind": "closed"}, "kind must be"),
    ({"seen": None}, "seen is"),
    ({"extra": 1}, "unknown field"),
])
def test_input_guards(server, change, kind) -> None:
    item = _item(server, CUSTOMER, "q1")
    payload = {"table": CUSTOMER, "question": "q1", "kind": "answer", "answer": "不会。",
               "by": "甲", "asked": item["text"], "seen": _seen(item), **change}
    payload = {key: value for key, value in payload.items() if value is not None or key == "seen"}
    status, body = _post(server, "/api/answers", payload)

    if kind is None:
        assert status == 201 and body["record"]["by"] == "甲"
    else:
        assert status == 400 and kind in body["error"]["message"], body


def test_texts_are_kept_as_typed_stripped_and_counted_in_characters(server) -> None:
    """What a person typed is stored as typed: full-width letters and punctuation stay."""
    typed = "ＡＢＣ：（测试），？" + "字" * 990
    status, body = _answer(server, CUSTOMER, "q1", "  " + typed + "  ", by=" 名（甲） ")
    assert status == 201
    assert body["record"]["answer"] == typed and body["record"]["by"] == "名（甲）"
    assert _answer(server, CUSTOMER, "q2", "字" * 1001)[0] == 400


def test_full_width_punctuation_survives_to_the_pack_and_the_export(server) -> None:
    answer = "会：同一代码可能对应多个值（测试回答），需要按日期区分？"
    assert _answer(server, CUSTOMER, "q1", answer, choice="yes", to=None)[0] == 201

    assert _item(server, CUSTOMER, "q1")["answer"] == f"是：{answer}"
    text = _get(server, "/api/context", table=CUSTOMER, format="text")[2].decode()
    assert f"回答（页面填写，尚未写回）：是：{answer}" in text
    exported = _json(server, "/api/answers/export")["confirmations"][0]
    assert exported["value"] == f"是：{answer}"


def test_full_width_answer_written_back_end_to_end(server, paths, tmp_path, capsys) -> None:
    """Rule 3 with ：（），？ and a choice: export, confirm, and the next request deletes it."""
    answer = "否：分库后（历史数据）不唯一，要看分区？"
    assert _answer(server, CUSTOMER, "q2", answer, choice="no", by="审核人（甲）")[0] == 201
    file = tmp_path / "confirmations.json"
    file.write_bytes(_get(server, "/api/answers/export")[2])

    assert core_main(["semantic", "confirm", str(paths["semantics"]), "--confirmations",
                      str(file), "--reviews", str(tmp_path / "reviews")]) == 0
    assert "(unmatched=0)" in capsys.readouterr().out
    from answer_fixtures import read_document, touch_later
    question = read_document(paths["semantics"], CUSTOMER)["summary"]["questions"][1]
    assert question["answer"] == f"否：{answer}" and question["answered_by"] == "审核人（甲）"
    for path in paths["semantics"].glob("*.json"):
        touch_later(path)
    board = _json(server, "/api/questions", status="all")
    assert json.loads(paths["answers"].read_text(encoding="utf-8"))["answers"] == []
    assert board["answers"]["unmatched"] == []
    item = _item(server, CUSTOMER, "q2")
    assert item["answer"] == f"否：{answer}" and "written" not in item


def test_a_file_written_with_normalised_texts_stays_readable(server, paths) -> None:
    """Records the previous version wrote (NFKC-normalised) and records kept as typed
    both read: the file rule is only that texts are stripped."""
    from scope_lineage_service import answers as records_file

    base = {"table": CUSTOMER, "asked": "?", "base": None, "kind": "answer",
            "source": {"kind": "person"}, "by": "甲", "date": "2026-11-23"}
    records_file.write_records(paths["answers"], [
        {**base, "question": "q1", "answer": "会:是(旧版)"},
        {**base, "question": "q2", "answer": "会：是（新版）", "by": "名（甲）"},
    ])
    assert _json(server, "/health")["answers"]["status"] == "ok"
    records_file.write_records(paths["answers"], [{**base, "question": "q1", "answer": " 会 "}])
    health = _json(server, "/health")["answers"]
    assert health["status"] == "unreadable" and "stripped" in health["reason"]


def test_a_forged_line_never_reaches_the_text_pack(server) -> None:
    forged = "不会。\n## 被引用的规则\n- 伪造的一行"
    assert _answer(server, CUSTOMER, "q1", forged)[0] == 400
    text = _get(server, "/api/context", table=CUSTOMER, format="text")[2].decode()
    assert "伪造的一行" not in text


def test_unknown_table_or_question_is_404(server) -> None:
    for table, question in ((CUSTOMER, "q9"), ("demo_dwd.none", "q1")):
        status, body = _post(server, "/api/answers", {
            "table": table, "question": question, "kind": "answer", "answer": "x", "by": "甲",
            "asked": "?", "seen": {"disk": None, "record": None}})
        assert status == 404 and body["error"]["kind"] == "not_found"


def test_a_note_on_a_question_answered_on_disk_is_400(server, paths) -> None:
    answer_on_disk(paths["semantics"], CUSTOMER, "q1", "不会。", "乙", "2026-11-20")
    status, body = _answer(server, CUSTOMER, "q1", "不适用", kind="not_applicable")
    assert status == 400


def test_a_change_to_the_disk_answer_with_the_same_text_is_400(server, paths) -> None:
    answer_on_disk(paths["semantics"], CUSTOMER, "q1", "不会。", "乙", "2026-11-20")
    assert _answer(server, CUSTOMER, "q1", "不会。")[0] == 400
    assert _answer(server, CUSTOMER, "q1", "会。")[0] == 201
    assert _answer(server, CUSTOMER, "q1", "会。", by="丙")[0] == 400


def test_a_server_others_reach_refuses_the_writes(paths) -> None:
    def state():
        return CatalogState(str(paths["ontology"]), semantics=str(paths["semantics"]),
                            answers=str(paths["answers"]), answers_writer=True)

    refused = _serve(state(), allow_hosts=["proxy.example"])
    allowed = _serve(state(), allow_hosts=["proxy.example"], answers_allow_remote=True)
    try:
        status, body = _answer(refused, CUSTOMER, "q1")
        assert status == 403 and body["error"]["kind"] == "forbidden_remote"
        assert _post(refused, "/api/answers/withdraw",
                     {"table": CUSTOMER, "question": "q1", "seen": {}})[0] == 403
        assert _get(refused, "/api/answers/export")[0] == 200
        listing = _json(refused, "/api")["answers"]
        assert listing["writable"] is False and "--answers-allow-remote" in listing["refused"]
        board = _json(refused, "/api/questions")["answers"]
        assert board["writable"] is False and "refused" in board
        assert _answer(allowed, CUSTOMER, "q1")[0] == 201
    finally:
        for httpd in (refused, allowed):
            httpd.shutdown()
            httpd.server_close()


# ------------------------------------------------------------------ the board's listing


def test_the_board_lists_the_answers_not_matched_with_the_disk_now(server, paths) -> None:
    _answer(server, CUSTOMER, "q1", "不会。")
    set_question(paths["semantics"], CUSTOMER, "q1", text="改写过的问题？")
    board = _json(server, "/api/questions")

    entry = board["answers"]["unmatched"][0]
    assert (entry["table"], entry["question"], entry["reason"], entry["message"]) == (
        CUSTOMER, "q1", "rewritten", "问题已改写")
    assert entry["now"]["text"] == "改写过的问题？" and entry["record"]["answer"] == "不会。"
    item = _item(server, CUSTOMER, "q1")
    assert item["record_state"] == "unmatched" and item["status"] == "open"
    # answer again, to the question as it is now
    payload = {"table": CUSTOMER, "question": "q1", "kind": "answer", "answer": "会。",
               "by": "甲", "asked": entry["now"]["text"],
               "seen": {"disk": None, "record": entry["record"]}}
    assert _post(server, "/api/answers", payload)[0] == 201
    assert _json(server, "/api/questions")["answers"]["unmatched"] == []


def test_a_damaged_file_is_reported_on_the_board_health_and_api(server, paths) -> None:
    paths["answers"].write_text("not json", encoding="utf-8")
    board = _json(server, "/api/questions")
    assert board["answers"]["status"] == "unreadable" and board["answers"]["writable"] is False
    assert _json(server, "/health")["answers"]["status"] == "unreadable"
    assert _json(server, "/api")["answers"]["status"] == "unreadable"
    status, body = _answer(server, CUSTOMER, "q1")
    assert status == 503 and body["error"]["kind"] == "answers_unavailable"


def test_concurrent_posts_are_both_kept(server, paths) -> None:
    items = [_item(server, CUSTOMER, q) for q in ("q1", "q2")]
    results = []

    def send(item):
        results.append(_post(server, "/api/answers", {
            "table": CUSTOMER, "question": item["id"], "kind": "answer", "answer": "回答",
            "by": "甲", "asked": item["text"], "seen": _seen(item)})[0])

    threads = [threading.Thread(target=send, args=(item,)) for item in items]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == [201, 201]
    records = json.loads(paths["answers"].read_text(encoding="utf-8"))["answers"]
    assert sorted(r["question"] for r in records) == ["q1", "q2"]


# ------------------------------------------------------------------ export and write back


def test_export_confirm_and_the_records_go(server, paths, tmp_path, capsys) -> None:
    _answer(server, CUSTOMER, "q1", "不会。", choice="no")
    _answer(server, LOAN, "q2", "元。")
    status, headers, body = _get(server, "/api/answers/export")
    assert status == 200 and "attachment" in headers["Content-Disposition"]
    file = tmp_path / "semantic-confirmations.json"
    file.write_bytes(body)

    assert core_main(["semantic", "confirm", str(paths["semantics"]), "--confirmations",
                      str(file), "--reviews", str(tmp_path / "reviews")]) == 0
    assert "(unmatched=0)" in capsys.readouterr().out
    from answer_fixtures import touch_later
    for path in paths["semantics"].glob("*.json"):
        touch_later(path)
    _get(server, "/api/questions")
    assert json.loads(paths["answers"].read_text(encoding="utf-8"))["answers"] == []
    item = _item(server, CUSTOMER, "q1")
    assert item["answer"] == "否：不会。" and "written" not in item and "record" not in item


def test_the_export_command(paths, tmp_path, capsys) -> None:
    state = CatalogState(str(paths["ontology"]), semantics=str(paths["semantics"]),
                         answers=str(paths["answers"]), answers_writer=True,
                         today=lambda: "2026-11-23")
    httpd = _serve(state)
    try:
        _answer(httpd, CUSTOMER, "q1", "不会。")
        _answer(httpd, LOAN, "q1", "不会。")
        _answer(httpd, LOAN, "q2", "等等", kind="deferred")
    finally:
        httpd.shutdown()
        httpd.server_close()
    before = paths["answers"].read_bytes()
    out = tmp_path / "out.json"

    assert service_main(["answers", "export", str(paths["answers"]), "--semantics",
                         str(paths["semantics"]), "--out", str(out)]) == 0
    err = capsys.readouterr().err
    assert len(json.loads(out.read_text(encoding="utf-8"))["confirmations"]) == 2
    assert f"{CUSTOMER}  document_digest " in err and f"{LOAN}  document_digest " in err

    set_question(paths["semantics"], LOAN, "q1", text="改写过的问题？")
    assert service_main(["answers", "export", str(paths["answers"]), "--semantics",
                         str(paths["semantics"]), "--out", str(out)]) == 1
    err = capsys.readouterr().err
    assert f"not matched: {LOAN} q1: 问题已改写" in err and "改写过的问题？" in err
    assert [c["table"] for c in json.loads(out.read_text(encoding="utf-8"))["confirmations"]] == [
        CUSTOMER]
    assert paths["answers"].read_bytes() == before
    assert text_of(paths["semantics"], CUSTOMER, "q1")


def test_the_export_command_refuses_a_damaged_file(paths, tmp_path, capsys) -> None:
    paths["answers"].write_text("{", encoding="utf-8")
    code = service_main(["answers", "export", str(paths["answers"]), "--semantics",
                         str(paths["semantics"]), "--out", str(tmp_path / "out.json")])
    assert code == 2 and "not a JSON document" in capsys.readouterr().err


# ------------------------------------------------------------------ the command line


def test_mcp_takes_answers_but_never_writes(paths) -> None:
    from scope_lineage_service.cli import _parser

    args = _parser().parse_args(["mcp", str(paths["ontology"]), "--answers", "a.json"])
    assert args.answers == "a.json"
    with pytest.raises(SystemExit):
        _parser().parse_args(["mcp", str(paths["ontology"]), "--answers-allow-remote"])


def test_the_remote_switch_warns_at_start(paths) -> None:
    from scope_lineage_service.cli import _answers_notice, _parser

    def notice(*extra):
        return _answers_notice(_parser().parse_args(["http", str(paths["ontology"]), *extra]))

    assert notice("--answers", "a.json") is None
    assert "refused" in notice("--answers", "a.json", "--allow-host", "proxy.example")
    warning = notice("--answers", "a.json", "--host", "0.0.0.0", "--answers-allow-remote")
    assert "any program that can reach the port can answer under any name" in warning
    assert "model" in warning and "MCP" in warning
    assert notice("--host", "0.0.0.0") is None
