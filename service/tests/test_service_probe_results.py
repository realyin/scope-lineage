"""Platform results pasted back on the questions board (``--probes``).

A server started with ``--probes FILE`` (``question-probes/1``) shows each question's queries;
a result pasted for a query whose result may land becomes a draft observation the server
never stores, and a person's 「确认」 stores it under ``observations`` in the answers file
(the pasted text parsed again and compared with the draft shown: 409 when it changed).
The export carries confirmed observations as observation confirmations with ``evidence``.
A result of a query that lands nothing can only back a sentence answer, by reference.
Without ``--probes`` and without observations every output is what it was. The results are
synthesised over the demo tables.
"""

from __future__ import annotations

import copy
import hashlib
import http.client
import json
import threading

import pytest
from answer_fixtures import QUESTIONS, prepare, read_document, set_question, write_document
from service_paths import CUSTOMER

from scope_lineage.semantics.confirm import apply_confirmations
from scope_lineage_service import answers as records_file
from scope_lineage_service.cli import main as service_main
from scope_lineage_service.http_server import make_server
from scope_lineage_service.state import CatalogState

INPUT = "demo_ods.ods_core_customer_df"
ROW_SQL = (
    "SELECT SUM(n) AS rows, COUNT(*) AS keys, "
    "SUM(CASE WHEN n > 1 THEN 1 ELSE 0 END) AS duplicate_keys "
    f"FROM (SELECT customer_id, COUNT(*) AS n FROM {CUSTOMER} "
    "WHERE dt = '${bizdate}' GROUP BY customer_id) g"
)
VALUES_SQL = (
    f"SELECT gender_cd AS value, COUNT(*) AS cnt FROM {CUSTOMER} "
    "WHERE dt = '${bizdate}' GROUP BY gender_cd ORDER BY cnt DESC LIMIT 51"
)
BLANK_SQL = (
    "SELECT COUNT(*) AS rows, COUNT(CASE WHEN register_time IS NULL THEN 1 END) AS blank_rows "
    f"FROM {CUSTOMER} WHERE dt = '${{bizdate}}'"
)


def _item(id_, question, shape, sql, lands, part=1):
    asked = next(q["text"] for q in QUESTIONS if q["id"] == question)
    return {"id": id_, "table": CUSTOMER, "question": question, "asked": asked, "part": part,
            "ask": "子问题", "class": "data", "shape": shape, "sql": sql,
            "partitions": [{"table": CUSTOMER, "column": "dt", "want": "${bizdate}",
                            "fallback": "latest_available"}],
            "engine": "spark", "lands": lands, "how_to_read": "照固定列读"}


PROBES = {"doc_format": "question-probes/1", "placeholders": {"${bizdate}": "20260101"},
          "items": [
              _item("cust_q2_p1", "q2", "uniqueness", ROW_SQL, "summary.row.observed"),
              _item("cust_q1_p1", "q1", "value_set", VALUES_SQL, "column:gender_cd.observed_values"),
              _item("cust_q1_p2", "q1", "conditional_count", BLANK_SQL, None, part=2),
          ]}


def _pasted(id_, sql, columns, rows, **extra) -> str:
    result = {"sql_id": id_, "status": "ok", "run_on": "2026-11-25", "bizdate": "20261122",
              "sql_executed": sql.replace("${bizdate}", "20261122"), "columns": columns,
              "rows": rows, "note": ""}
    result.update(extra)
    return json.dumps(result, ensure_ascii=False, indent=2)


ROW_PASTE = _pasted("cust_q2_p1", ROW_SQL, ["rows", "keys", "duplicate_keys"], [["900", "900", "0"]])
VALUES_PASTE = _pasted("cust_q1_p1", VALUES_SQL, ["value", "cnt"], [["M", "500"], ["F", "400"]])
BLANK_PASTE = _pasted("cust_q1_p2", BLANK_SQL, ["rows", "blank_rows"], [["900", "0"]])


def _serve(state, **options):
    httpd = make_server(state, host="127.0.0.1", port=0, quiet=True, **options)
    threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True).start()
    return httpd


@pytest.fixture
def paths(inputs, tmp_path):
    prepare(inputs["semantics"])
    probes = tmp_path / "question-probes.json"
    probes.write_text(json.dumps(PROBES, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**inputs, "answers": tmp_path / "answers.json", "probes": probes}


def _state(paths, probes=True, answers=True):
    return CatalogState(str(paths["ontology"]), semantics=str(paths["semantics"]),
                        answers=str(paths["answers"]) if answers else None, answers_writer=True,
                        probes=str(paths["probes"]) if probes else None,
                        today=lambda: "2026-11-26")


@pytest.fixture
def server(paths):
    httpd = _serve(_state(paths))
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def _request(httpd, method, path, body=None, headers=None):
    host, port = httpd.server_address[:2]
    connection = http.client.HTTPConnection(host, port, timeout=10)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def _get(httpd, path):
    status, body = _request(httpd, "GET", path)
    return status, json.loads(body)


def _post(httpd, path, payload):
    status, body = _request(httpd, "POST", path, json.dumps(payload, ensure_ascii=False).encode(),
                            {"Content-Type": "application/json"})
    return status, json.loads(body)


def _draft(httpd, probe, pasted):
    status, body = _post(httpd, "/api/probe-results/draft", {"probe": probe, "pasted": pasted})
    assert status == 200, body
    return body


def _confirm(httpd, probe, pasted, seen, by="审核人甲"):
    return _post(httpd, "/api/observations", {"probe": probe, "pasted": pasted, "by": by,
                                              "seen": seen})


def _board_item(httpd, question):
    _, board = _get(httpd, f"/api/questions?table={CUSTOMER}&status=all")
    return next(item for item in board["items"]
                if item["source"] == "semantics" and item["id"] == question), board


def _file(paths):
    return json.loads(paths["answers"].read_text(encoding="utf-8"))


# ------------------------------------------------------------------ showing the queries


def test_the_board_shows_each_questions_queries(server) -> None:
    item, _ = _board_item(server, "q1")
    assert [p["id"] for p in item["probes"]] == ["cust_q1_p1", "cust_q1_p2"]
    first = item["probes"][0]
    assert first["sql"] == VALUES_SQL and first["how_to_read"] == "照固定列读"
    assert first["lands"] == "column:gender_cd.observed_values" and first["stale"] is False
    status, listing = _get(server, f"/api/probes?table={CUSTOMER}")
    assert status == 200 and [p["id"] for p in listing["items"]] == [
        "cust_q2_p1", "cust_q1_p1", "cust_q1_p2"]
    assert len(listing["sha256"]) == 64 and listing["placeholders"] == {"${bizdate}": "20260101"}


def test_a_rewritten_question_marks_its_queries_stale(server, paths) -> None:
    set_question(paths["semantics"], CUSTOMER, "q1", text="性别码值还有别的取值吗？")
    item, _ = _board_item(server, "q1")
    assert all(p["stale"] for p in item["probes"])


# ------------------------------------------------------------------ the draft


def test_a_good_result_drafts_and_nothing_is_written(server, paths) -> None:
    body = _draft(server, "cust_q2_p1", ROW_PASTE)
    assert body["draft"]["target"] == "summary.row.observed"
    assert body["draft"]["value"]["grain_columns"] == ["customer_id"]
    assert body["draft"]["value"]["rows"] == 900 and body["draft"]["value"]["unique"] == "yes"
    assert body["draft"]["evidence"]["probe"] == "cust_q2_p1"
    assert body["draft"]["evidence"]["sha256"] == hashlib.sha256(
        paths["probes"].read_bytes()).hexdigest()
    assert body["pasted_sha256"] == hashlib.sha256(ROW_PASTE.encode("utf-8")).hexdigest()
    assert "by" not in body["draft"] and not paths["answers"].exists()


@pytest.mark.parametrize("pasted, words", [
    (_pasted("cust_q2_p1", ROW_SQL, ["rows", "keys", "duplicate_keys"], [["null", "0", "null"]]),
     "null"),
    (_pasted("cust_q2_p1", ROW_SQL, ["rows", "keys", "duplicate_keys"], [["9", "9", "0"]],
             status="error"), "status"),
    (_pasted("cust_q1_p1", ROW_SQL, ["rows", "keys", "duplicate_keys"], [["9", "9", "0"]]),
     "sql_id"),
    ("rows\tkeys\tduplicate_keys\n9\t9\t0", "JSON"),
])
def test_a_bad_result_is_refused_with_the_reason(server, pasted, words) -> None:
    body = _draft(server, "cust_q2_p1", pasted)
    assert "draft" not in body and words in body["refused"]


def test_an_unknown_probe_or_an_oversized_paste_is_a_bad_request(server) -> None:
    status, _ = _post(server, "/api/probe-results/draft", {"probe": "nope", "pasted": ROW_PASTE})
    assert status == 404
    status, _ = _post(server, "/api/probe-results/draft",
                      {"probe": "cust_q2_p1", "pasted": ROW_PASTE + " " * 70000})
    assert status == 400


# ------------------------------------------------------------------ confirming


def test_confirming_stores_the_observation_and_the_export_carries_it(server, paths) -> None:
    seen = _draft(server, "cust_q1_p1", VALUES_PASTE)
    status, body = _confirm(server, "cust_q1_p1", VALUES_PASTE,
                            {**seen["draft"], "pasted_sha256": seen["pasted_sha256"]})
    assert status == 201, body
    stored = _file(paths)
    assert stored["answers"] == [] and len(stored["observations"]) == 1
    record = stored["observations"][0]
    assert record["by"] == "审核人甲" and record["date"] == "2026-11-26"
    assert record["target"] == "column:gender_cd.observed_values" and record["question"] == "q1"
    # the observation is no overlay: the document shows it only as a slot not written back
    _, semantics = _get(server, f"/api/semantics?table={CUSTOMER}")
    assert "column:gender_cd.observed_values" in semantics["unwritten_slots"]
    gender = next(c for c in semantics["document"]["columns"] if c["column"] == "gender_cd") \
        if "document" in semantics else None
    assert gender is None or "observed_values" not in gender
    _, board = _board_item(server, "q1")
    assert board["answers"]["observations"]["effective"] == 1
    status, raw = _request(server, "GET", "/api/answers/export")
    exported = json.loads(raw)
    assert status == 200 and exported["confirmations"] == [
        {"table": CUSTOMER, "target": "column:gender_cd.observed_values",
         "value": seen["draft"]["value"], "by": "审核人甲", "date": "2026-11-26",
         "evidence": seen["draft"]["evidence"]}]
    documents = {CUSTOMER: read_document(paths["semantics"], CUSTOMER)}
    applied = apply_confirmations(documents, exported["confirmations"])
    assert applied.unmatched == []


def test_a_changed_paste_between_preview_and_confirm_is_409(server, paths) -> None:
    seen = _draft(server, "cust_q2_p1", ROW_PASTE)
    changed = _pasted("cust_q2_p1", ROW_SQL, ["rows", "keys", "duplicate_keys"],
                      [["901", "901", "0"]])
    assert changed != ROW_PASTE
    status, body = _confirm(server, "cust_q2_p1", changed,
                            {**seen["draft"], "pasted_sha256": seen["pasted_sha256"]})
    assert status == 409, body
    assert not paths["answers"].exists()


def test_a_refused_result_cannot_be_confirmed(server) -> None:
    bad = _pasted("cust_q2_p1", ROW_SQL, ["rows", "keys", "duplicate_keys"], [["0", "0", "0"]])
    status, body = _confirm(server, "cust_q2_p1", bad, {"target": "summary.row.observed"})
    assert status == 400 and "rows" in body["error"]["message"]


def test_a_later_observation_of_the_same_slot_replaces_the_earlier(server, paths) -> None:
    for rows in (["900", "900", "0"], ["950", "940", "10"]):
        pasted = _pasted("cust_q2_p1", ROW_SQL, ["rows", "keys", "duplicate_keys"], [rows])
        seen = _draft(server, "cust_q2_p1", pasted)
        status, _ = _confirm(server, "cust_q2_p1", pasted,
                             {**seen["draft"], "pasted_sha256": seen["pasted_sha256"]})
        assert status == 201
    stored = _file(paths)["observations"]
    assert len(stored) == 1 and stored[0]["value"]["unique"] == "no"


def test_a_question_rewritten_since_the_query_was_written_is_refused(server, paths) -> None:
    seen = _draft(server, "cust_q2_p1", ROW_PASTE)
    set_question(paths["semantics"], CUSTOMER, "q2", text="客户号是否全表唯一？")
    status, body = _confirm(server, "cust_q2_p1", ROW_PASTE,
                            {**seen["draft"], "pasted_sha256": seen["pasted_sha256"]})
    assert status == 400 and "rewritten" in body["error"]["message"]


def test_a_written_back_observation_leaves_the_file_as_it_was(server, paths) -> None:
    seen = _draft(server, "cust_q2_p1", ROW_PASTE)
    _confirm(server, "cust_q2_p1", ROW_PASTE, {**seen["draft"], "pasted_sha256": seen["pasted_sha256"]})
    _, raw = _request(server, "GET", "/api/answers/export")
    documents = {CUSTOMER: read_document(paths["semantics"], CUSTOMER)}
    applied = apply_confirmations(documents, json.loads(raw)["confirmations"])
    write_document(paths["semantics"], CUSTOMER, applied.documents[CUSTOMER])
    _, semantics = _get(server, f"/api/semantics?table={CUSTOMER}")
    assert "unwritten_slots" not in semantics
    assert _file(paths) == {"doc_format": "question-answers/1", "answers": []}


def test_withdrawing_an_observation(server, paths) -> None:
    seen = _draft(server, "cust_q2_p1", ROW_PASTE)
    _, body = _confirm(server, "cust_q2_p1", ROW_PASTE,
                       {**seen["draft"], "pasted_sha256": seen["pasted_sha256"]})
    stale = copy.deepcopy(body["observation"])
    stale["by"] = "别人"
    assert _post(server, "/api/observations/withdraw", {"seen": stale})[0] == 409
    status, _ = _post(server, "/api/observations/withdraw", {"seen": body["observation"]})
    assert status == 200 and "observations" not in _file(paths)


# ------------------------------------------------------------------ evidence for a sentence


def test_a_non_landing_result_backs_a_sentence_answer_by_reference(server, paths) -> None:
    body = _draft(server, "cust_q1_p2", BLANK_PASTE)
    assert "draft" not in body and body["evidence"]["probe"] == "cust_q1_p2"
    item, _ = _board_item(server, "q1")
    status, saved = _post(server, "/api/answers", {
        "table": CUSTOMER, "question": "q1", "kind": "answer", "answer": "注册时间没有空值",
        "by": "审核人甲", "asked": item["text"], "seen": {"disk": None, "record": None},
        "probe_result": {"probe": "cust_q1_p2", "pasted": BLANK_PASTE}})
    assert status == 201, saved
    assert saved["record"]["source"] == {"kind": "query", **body["evidence"]}
    _, raw = _request(server, "GET", "/api/answers/export")
    entry = json.loads(raw)["confirmations"][0]
    assert entry["target"] == "question:q1" and entry["evidence"] == body["evidence"]
    assert "rows" not in json.dumps(json.loads(paths["answers"].read_text(encoding="utf-8")))


def test_a_landing_or_refused_result_cannot_back_a_sentence(server) -> None:
    item, _ = _board_item(server, "q2")
    status, body = _post(server, "/api/answers", {
        "table": CUSTOMER, "question": "q2", "kind": "answer", "answer": "唯一", "by": "甲",
        "asked": item["text"], "seen": {"disk": None, "record": None},
        "probe_result": {"probe": "cust_q2_p1", "pasted": ROW_PASTE}})
    assert status == 400 and "lands" in body["error"]["message"]
    item, _ = _board_item(server, "q1")
    status, body = _post(server, "/api/answers", {
        "table": CUSTOMER, "question": "q1", "kind": "answer", "answer": "无空值", "by": "甲",
        "asked": item["text"], "seen": {"disk": None, "record": None},
        "probe_result": {"probe": "cust_q1_p2", "pasted": BLANK_PASTE.replace('"ok"', '"error"')}})
    assert status == 400


def test_the_record_file_holds_the_query_source() -> None:
    record = {"table": CUSTOMER, "question": "q1", "asked": "问？", "base": None,
              "kind": "answer", "answer": "答", "by": "甲", "date": "2026-11-26",
              "source": {"kind": "query", "probe": "p1",
                         "partition": {"column": "dt", "values": ["20261122"]},
                         "on": "2026-11-25", "sha256": "a" * 64}}
    assert records_file.record_problem(record) is None
    assert records_file.record_problem({**record, "source": {"kind": "query", "probe": "p1"}})
    assert records_file.record_problem(
        {**record, "source": {**record["source"], "rows": [["1"]]}})
    note = {key: value for key, value in record.items() if key != "answer"}
    assert records_file.record_problem({**note, "kind": "deferred", "reason": "等"})


# ------------------------------------------------------------------ guards


def test_writes_are_refused_on_a_server_others_reach(paths) -> None:
    httpd = make_server(_state(paths), host="127.0.0.1", port=0, quiet=True,
                        allow_hosts=["proxy.example"])
    threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True).start()
    try:
        seen = _draft(httpd, "cust_q2_p1", ROW_PASTE)
        status, body = _confirm(httpd, "cust_q2_p1", ROW_PASTE,
                                {**seen["draft"], "pasted_sha256": seen["pasted_sha256"]})
        assert status == 403 and body["error"]["kind"] == "forbidden_remote"
        assert _post(httpd, "/api/observations/withdraw", {"seen": {}})[0] == 403
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert not paths["answers"].exists()


def test_confirming_needs_an_answers_file(paths) -> None:
    httpd = _serve(_state(paths, answers=False))
    try:
        assert _draft(httpd, "cust_q2_p1", ROW_PASTE)["draft"]
        status, body = _confirm(httpd, "cust_q2_p1", ROW_PASTE, {})
        assert status == 404 and body["error"]["kind"] == "not_configured"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_without_probes_nothing_changes(paths) -> None:
    plain = _serve(_state(paths, probes=False))
    try:
        _, listing = _get(plain, "/api")
        paths_listed = [e["path"] for e in listing["endpoints"]]
        assert not any("probe" in p or "observation" in p for p in paths_listed)
        assert "probes" not in json.dumps(_get(plain, "/health")[1])
        item, board = _board_item(plain, "q1")
        assert "probes" not in item and "observations" not in board["answers"]
        for path in ("/api/probes?table=x", "/api/probe-results/draft", "/api/observations"):
            method = "GET" if path.startswith("/api/probes") else "POST"
            status, raw = _request(plain, method, path, b"{}", {"Content-Type": "application/json"})
            assert status == 404 and json.loads(raw)["error"]["kind"] == "not_configured"
        status, body = _post(plain, "/api/answers", {
            "table": CUSTOMER, "question": "q1", "kind": "answer", "answer": "答", "by": "甲",
            "asked": item["text"], "seen": {"disk": None, "record": None},
            "probe_result": {"probe": "x", "pasted": "{}"}})
        assert status == 400 and "unknown field" in body["error"]["message"]
        status, _ = _post(plain, "/api/answers", {
            "table": CUSTOMER, "question": "q1", "kind": "answer", "answer": "答", "by": "甲",
            "asked": item["text"], "seen": {"disk": None, "record": None}})
        assert status == 201
    finally:
        plain.shutdown()
        plain.server_close()
    text = paths["answers"].read_text(encoding="utf-8")
    assert "observations" not in text
    records = json.loads(text)["answers"]
    expected = json.dumps({"doc_format": "question-answers/1", "answers": records},
                          ensure_ascii=False, indent=2) + "\n"
    assert text == expected


def test_a_probes_file_that_is_not_question_probes_stops_the_start(paths, capsys) -> None:
    paths["probes"].write_text('{"doc_format": "other"}', encoding="utf-8")
    code = service_main(["http", str(paths["ontology"]), "--semantics", str(paths["semantics"]),
                         "--probes", str(paths["probes"]), "--port", "0"])
    assert code == 2 and "question-probes/1" in capsys.readouterr().err


def test_answers_export_on_the_command_line_carries_observations(server, paths, tmp_path) -> None:
    seen = _draft(server, "cust_q2_p1", ROW_PASTE)
    _confirm(server, "cust_q2_p1", ROW_PASTE, {**seen["draft"], "pasted_sha256": seen["pasted_sha256"]})
    out = tmp_path / "confirmations.json"
    code = service_main(["answers", "export", str(paths["answers"]), "--semantics",
                         str(paths["semantics"]), "--out", str(out)])
    exported = json.loads(out.read_text(encoding="utf-8"))
    assert code == 0 and [e["target"] for e in exported["confirmations"]] == ["summary.row.observed"]
    assert exported["confirmations"][0]["evidence"] == seen["draft"]["evidence"]
