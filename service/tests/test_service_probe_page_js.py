"""The page's platform-query parts: their pure functions, run with node when it is on PATH.

What a card says of a query and of a draft, and the bodies it sends back, are pure
functions of ``views.js``; the last test builds the confirmation body in node from a live
server's draft and posts it, so the page and the server agree on ``seen``.
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
from test_service_probe_results import PROBES, ROW_PASTE

from scope_lineage_service.http_server import make_server
from scope_lineage_service.state import CatalogState

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not on PATH")

EVIDENCE = {"probe": "cust_q2_p1", "partition": {"column": "dt", "values": ["20261122"]},
            "on": "2026-11-25", "sha256": "0123456789abcdef" * 4}
ROW = {"query": "cust_q2_p1", "on": "2026-11-25", "rows": 900,
       "partition": {"column": "dt", "values": ["20261122"]}, "engine": "spark",
       "grain_columns": ["customer_id"], "unique": "yes", "within": "each_partition",
       "keys": 900, "duplicate_keys": 0}


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


def test_where_a_query_lands_in_words() -> None:
    assert _call("landsText", None) == "不落槽位，只作回答依据"
    assert _call("landsText", "summary.row.observed") == "可落：行粒度观测"
    assert _call("landsText", "column:gender_cd.observed_values") == "可落：列 gender_cd 的取值观测"
    assert _call("landsText", "input:db.t") == "可落：输入表 db.t 的唯一性观测"


def test_a_draft_says_every_number_the_partition_and_the_query() -> None:
    said = _call("draftText", {"target": "summary.row.observed", "value": ROW})
    assert said.startswith("行粒度：") and "查询 cust_q2_p1" in said
    assert "分区 dt=20261122" in said and "900 行" in said and "900 个键" in said
    values = _call("draftText", {"target": "column:gender_cd.observed_values", "value": {
        "query": "q", "on": "2026-11-25", "rows": 9, "partition": {"column": "dt", "values": ["1"]},
        "values": [{"value": "M", "count": 5}, {"value": "F", "count": 4}], "complete": True}})
    assert values.startswith("列 gender_cd：") and "M（5 行）" in values and "已列全" in values
    assert _call("evidenceText", EVIDENCE).startswith(
        "依据：查询 cust_q2_p1，分区 dt=20261122，2026-11-25 执行")


def test_the_bodies_the_page_sends() -> None:
    drafted = {"draft": {"target": "summary.row.observed", "value": ROW, "evidence": EVIDENCE},
               "pasted_sha256": "f" * 64}
    assert _call("observationBody", "cust_q2_p1", "{}", " 甲 ", drafted) == {
        "probe": "cust_q2_p1", "pasted": "{}", "by": "甲",
        "seen": {"target": "summary.row.observed", "value": ROW, "evidence": EVIDENCE,
                 "pasted_sha256": "f" * 64}}
    item = {"source": "semantics", "table": CUSTOMER, "id": "q1", "text": "问？", "status": "open"}
    body = _call("evidenceAnswerBody", item, "p2", "{}", {"text": "没有空值", "by": "甲"})
    assert body["probe_result"] == {"probe": "p2", "pasted": "{}"}
    assert body["kind"] == "answer" and body["answer"] == "没有空值"
    assert body["seen"] == {"disk": None, "record": None} and body["asked"] == "问？"


def test_unwritten_observation_slots_are_marked() -> None:
    marks = {"unwritten": ["q1"], "page": {},
             "unwritten_slots": ["column:gender_cd.observed_values", "input:db.b", "input:db.a"]}
    # the marks hold Sets, which do not survive JSON: they are built and read inside node
    static = resources.files("scope_lineage_service") / "static"
    base = static.joinpath("views.js").as_uri()
    script = (f"import * as views from '{base}';\n"
              f"const marks = views.pageMarks({json.dumps(marks)});\n"
              "console.log(JSON.stringify([views.slotMarks(marks, 'gender_cd'), "
              "views.inputSlotMarks(marks), views.slotMarks(marks, 'customer_id')]));")
    done = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True,
                          text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == ["观测取值", ["db.a", "db.b"], None]


def test_the_page_body_confirms_a_live_draft(inputs, tmp_path) -> None:
    prepare(inputs["semantics"])
    probes = tmp_path / "question-probes.json"
    probes.write_text(json.dumps(PROBES, ensure_ascii=False), encoding="utf-8")
    state = CatalogState(str(inputs["ontology"]), semantics=str(inputs["semantics"]),
                         answers=str(tmp_path / "answers.json"), answers_writer=True,
                         probes=str(probes), today=lambda: "2026-11-26")
    httpd = make_server(state, host="127.0.0.1", port=0, quiet=True)
    threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True).start()
    host, port = httpd.server_address[:2]

    def post(path, payload):
        connection = http.client.HTTPConnection(host, port, timeout=10)
        try:
            connection.request("POST", path, json.dumps(payload, ensure_ascii=False).encode(),
                               {"Content-Type": "application/json"})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    try:
        status, drafted = post("/api/probe-results/draft", {"probe": "cust_q2_p1", "pasted": ROW_PASTE})
        assert status == 200 and "draft" in drafted
        body = _call("observationBody", "cust_q2_p1", ROW_PASTE, "审核人甲", drafted)
        status, stored = post("/api/observations", body)
        assert status == 201, stored
    finally:
        httpd.shutdown()
        httpd.server_close()
