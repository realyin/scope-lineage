"""The ask panel's pure JavaScript (askview.js), run with node when it is on PATH.

As in ``test_service_page_js.py``: node imports the page's own module and prints JSON; the
assertions are Python. The events fed to the view model come from a real run of the loop
with the development fake model over the demo catalog, so the shapes are the server's.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from importlib import resources

import pytest
from service_paths import CUSTOMER

from scope_lineage_service.ask import walk
from scope_lineage_service.ask.fake_model import FakeModel
from scope_lineage_service.ask.loop import Limits, Run, run_question
from scope_lineage_service.ask.tools import ToolBox
from scope_lineage_service.state import CatalogState

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not on PATH")


def _call(function: str, *args):
    static = resources.files("scope_lineage_service") / "static"
    module = static.joinpath("askview.js").as_uri()
    arguments = ", ".join(json.dumps(arg, ensure_ascii=False) for arg in args)
    script = (f"import * as view from '{module}';\n"
              f"console.log(JSON.stringify(view.{function}({arguments})));")
    done = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True,
                          text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.fixture
def state(inputs) -> CatalogState:
    return CatalogState(str(inputs["ontology"]), semantics=str(inputs["semantics"]),
                        pending=str(inputs["pending"]))


def test_placeholders_are_the_ones_check_sql_finds(state) -> None:
    sql = (
        f"SELECT COUNT(*) FROM {CUSTOMER} c -- 待确认：按哪天的状态\n"
        "WHERE c.gender_cd IN (/* 待确认：性别码还有哪些值 */ 'F', 'M')\n"
        "  AND c.note <> '/* 待确认：字符串里的不算 */'\n"
        "  AND c.name <> 'it''s -- 待确认：也不算'\n"
        "  AND /* 普通注释 */ /* 待确认:半角冒号也算 */ 1 = 1"
    )
    found = _call("extractPlaceholders", sql)
    server = [item["text"] for item in state.check_sql(sql).result["placeholders"]]

    assert [item["text"] for item in found] == ["按哪天的状态", "性别码还有哪些值", "半角冒号也算"]
    assert sorted(server) == sorted(item["text"] for item in found)


def test_the_brief_splits_into_its_labelled_lines() -> None:
    brief = (
        "问题：上月新增客户数\n结论：见 SQL\nSQL：SELECT COUNT(*)\nFROM t\n"
        "表：db.t — 一行是一个客户\n关联：无\n"
        "条件：t.dt = '2024-01-31' — db.t · 目录 · 分区\n条件：t.status = 'A' — 约束 c1\n"
        "假设：无\n待确认：注销的算不算 — status；无；已记入\ncheck-sql：错误 0，警告 1"
    )
    parsed = _call("parseBrief", brief)

    assert parsed["question"] == "上月新增客户数" and parsed["sql"] == "SELECT COUNT(*)\nFROM t"
    assert parsed["conditions"] == [
        {"text": "t.dt = '2024-01-31'", "basis": "db.t · 目录 · 分区"},
        {"text": "t.status = 'A'", "basis": "约束 c1"},
    ]
    assert parsed["tables"] == [{"text": "db.t", "basis": "一个客户"}]
    assert parsed["joins"] == [] and parsed["assumptions"] == []
    assert parsed["pending"] == ["注销的算不算 — status；无；已记入"]


def test_a_real_run_becomes_the_view_model(state) -> None:
    job = Run("r", "客户数")
    tools = ToolBox(state, max_sql=8192)
    run_question(job, FakeModel(state, delay=0), tools, walk.system_blocks(True), Limits())
    vm = _call("viewModel", job.events)

    assert vm["status"] == "done" and vm["question"] == "客户数"
    tools_used = [step["name"] for step in vm["steps"] if step["kind"] == "tool"]
    assert tools_used == ["search_catalog", "query_catalog", "search_catalog", "catalog_context",
                          "check_sql"]
    assert all(step["done"] and step["ok"] for step in vm["steps"] if step["kind"] == "tool")
    assert vm["candidates"] and vm["taken"]["tables"]
    assert [check["round"] for check in vm["checks"]] == [1]
    assert vm["answer"]["sql"] and vm["answer"]["placeholders"][0]["column"]
    assert vm["answer"]["parsed"]["question"] == "客户数"
    notes = [step["text"] for step in vm["steps"] if step["kind"] == "note"]
    assert vm["answer"]["text"] not in notes  # the answer is shown once, as the answer
    assert vm["usage"]["turns"] == 5 and vm["usage"]["tool_calls"] == 5


def test_without_the_server_list_placeholders_come_from_the_sql() -> None:
    events = [
        {"seq": 1, "type": "started", "question": "q", "follow_up": False, "t": 0},
        {"seq": 2, "type": "answer", "text": "x", "sql": "SELECT /* 待确认：口径 */ 1",
         "brief": "问题：q", "brief_missing": False, "placeholders": [],
         "placeholder_check_error": "parse error", "t": 1},
        {"seq": 3, "type": "finished", "status": "done", "reason": None, "detail": None,
         "usage": None, "t": 1.5},
    ]
    vm = _call("viewModel", events)

    assert vm["answer"]["placeholders"] == [{"text": "口径", "table": None, "column": None}]
    assert vm["elapsed"] == 1.5


def test_usage_reads_as_one_line() -> None:
    usage = {"input_tokens": 1200, "output_tokens": 110, "cache_creation_input_tokens": 5200,
             "cache_read_input_tokens": 50000, "turns": 2, "tool_calls": 1}

    assert _call("usageText", usage) == (
        "输入 1,200 · 缓存读 50,000 · 缓存写 5,200 · 输出 110 · 2 轮 · 1 次工具调用")
    assert _call("usageText", None) == ""
