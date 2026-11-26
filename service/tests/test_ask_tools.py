"""The ask panel's tools: the catalog answers, with the MCP tools' words and checked inputs."""

from __future__ import annotations

import ast
import json

import pytest
from service_paths import CUSTOMER, REPO

from scope_lineage_service.ask.tools import ToolBox, check_input
from scope_lineage_service.state import CatalogState

MCP_SOURCE = REPO / "service" / "scope_lineage_service" / "mcp_server.py"


@pytest.fixture
def state(inputs) -> CatalogState:
    return CatalogState(
        str(inputs["ontology"]), semantics=str(inputs["semantics"]), pending=str(inputs["pending"])
    )


@pytest.fixture
def tools(state) -> ToolBox:
    return ToolBox(state, max_sql=4096)


def _words(text: str) -> str:
    return " ".join(text.split())


def _mcp_tools() -> dict[str, dict]:
    """Each MCP tool's docstring and parameter descriptions, read from the source (the
    ``mcp`` package need not be installed)."""
    found = {}
    for node in ast.walk(ast.parse(MCP_SOURCE.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.FunctionDef) or not any(
            isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "tool" for d in node.decorator_list
        ):
            continue
        params = {}
        for arg in node.args.args:
            for call in ast.walk(arg.annotation) if arg.annotation else ():
                if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "Field":
                    for keyword in call.keywords:
                        if keyword.arg == "description":
                            params[arg.arg] = ast.literal_eval(keyword.value)
        found[node.name] = {"doc": ast.get_docstring(node), "params": params}
    return found


def test_the_tools_say_what_the_mcp_tools_say(tools) -> None:
    mcp = _mcp_tools()

    for tool in tools.definitions():
        assert tool["name"] in mcp, tool["name"]
        assert _words(tool["description"]) == _words(mcp[tool["name"]]["doc"])
        for name, spec in tool["input_schema"]["properties"].items():
            assert spec["description"] == mcp[tool["name"]]["params"][name], (tool["name"], name)
        assert tool["input_schema"]["additionalProperties"] is False


def test_the_model_has_no_tool_that_writes_the_pending_file(inputs, tools) -> None:
    bare = ToolBox(CatalogState(str(inputs["ontology"])), max_sql=4096)
    read_only = ["search_catalog", "catalog_context", "query_catalog", "check_sql"]

    # with a pending file or without: the asker records a gap with the page's button
    assert tools.pending is True and bare.pending is False
    assert [t["name"] for t in tools.definitions()] == read_only
    assert [t["name"] for t in bare.definitions()] == read_only
    for box in (tools, bare):
        outcome = box.call("add_pending", {"question": "q", "missing": "m"})
        assert not outcome.ok and "no tool named" in outcome.text
    assert not inputs["pending"].exists()


def test_the_mcp_add_pending_says_to_record_only_after_the_asker_agrees() -> None:
    doc = _words(_mcp_tools()["add_pending"]["doc"])

    assert "only after the asker agrees" in doc


def test_a_result_is_the_command_text_and_the_page_gets_a_summary(state, tools) -> None:
    outcome = tools.call("search_catalog", {"text": "客户", "limit": 3})

    assert outcome.ok and outcome.exit_code == 0
    assert outcome.text == state.search("客户", None, 3).text()
    assert [hit["id"] for hit in outcome.data["hits"]] == [
        hit["id"] for hit in state.search("客户", None, 3).result["hits"]]


def test_context_summary_names_the_tables_and_columns_taken(state, tools) -> None:
    outcome = tools.call("catalog_context", {
        "tables": [CUSTOMER], "columns_of_table": ["gender_cd"], "brief": True, "focus": True})

    assert outcome.ok
    assert outcome.text == state.context(
        tables=[CUSTOMER], columns=[], columns_of_table=["gender_cd"], concepts=[], brief=True,
        focus=True).text()
    assert outcome.data["tables"] == [CUSTOMER]
    assert outcome.data["columns"] == [f"{CUSTOMER}.gender_cd"]


def test_check_sql_summary_counts_findings_and_lists_placeholders(tools) -> None:
    sql = (f"SELECT COUNT(*) FROM {CUSTOMER} c "
           "WHERE c.gender_cd IN (/* 待确认：哪些算有效 */ 'F')")
    outcome = tools.call("check_sql", {"sql": sql})

    assert outcome.ok
    assert outcome.data["placeholders"][0]["text"] == "哪些算有效"
    assert outcome.data["placeholders"][0]["column"] == "gender_cd"
    assert outcome.data["infos"] >= 1 and outcome.data["sql"] == sql


def test_nothing_found_is_an_ordinary_result(tools) -> None:
    outcome = tools.call("query_catalog", {"kind": "table", "term": "x.none"})

    assert outcome.ok and outcome.exit_code == 1


@pytest.mark.parametrize(
    ("name", "args", "says"),
    [
        ("drop_table", {}, "no tool"),
        ("search_catalog", {}, "text is required"),
        ("search_catalog", {"text": "x", "path": "/etc"}, "unknown argument"),
        ("search_catalog", {"text": "x", "limit": 0}, ">= 1"),
        ("search_catalog", {"text": "x", "limit": True}, "integer"),
        ("search_catalog", {"text": "x", "kinds": ["nonsense"]}, "must be one of"),
        ("query_catalog", {"kind": "table"}, "term is required"),
        ("catalog_context", {"tables": "db.t"}, "takes a list"),
        ("catalog_context", {"brief": "yes", "tables": [CUSTOMER]}, "true or false"),
        ("check_sql", {"sql": "SELECT 1" + " " * 5000}, "longer than"),
        ("search_catalog", ["x"], "JSON object"),
    ],
)
def test_inputs_that_do_not_fit_are_tool_errors(tools, name, args, says) -> None:
    outcome = tools.call(name, args)

    assert not outcome.ok and says in outcome.text


def test_an_input_the_command_refuses_is_an_error_with_its_sentence(state, tools) -> None:
    outcome = tools.call("catalog_context", {"columns_of_table": ["a"]})

    assert not outcome.ok and outcome.exit_code == 2
    assert "give at least one --table" in outcome.text
    assert not tools.call("check_sql", {"sql": "SELECT FROM ("}).ok


def test_a_long_result_is_cut_with_a_note(state) -> None:
    tools = ToolBox(state, max_sql=4096, max_result_chars=100)
    outcome = tools.call("catalog_context", {"tables": [CUSTOMER]})

    assert outcome.ok and outcome.text.startswith(state.context(tables=[CUSTOMER]).text()[:100])
    assert "输出过长" in outcome.text


def test_check_input_takes_only_the_schema_subset() -> None:
    schema = {"type": "object", "properties": {"a": {"type": "array", "items": {"type": "string"}}},
              "required": [], "additionalProperties": False}

    assert check_input(schema, {"a": ["x"]}) is None
    assert "string" in check_input(schema, {"a": [1]})


def test_the_context_tool_carries_the_pages_answers(inputs, tmp_path) -> None:
    """With an answers file the panel's model reads the page's answer, marked unwritten."""
    from scope_lineage_service import answers as records_file

    question = json.loads((inputs["semantics"] / f"{CUSTOMER}.json").read_text(
        encoding="utf-8"))["summary"]["questions"][0]
    file = tmp_path / "answers.json"
    records_file.write_records(file, [{
        "table": CUSTOMER, "question": question["id"], "asked": question["text"], "base": None,
        "kind": "answer", "answer": "不会。", "source": {"kind": "person"}, "by": "审核人甲",
        "date": "2026-11-23"}])
    state = CatalogState(str(inputs["ontology"]), semantics=str(inputs["semantics"]),
                         answers=str(file))
    outcome = ToolBox(state, max_sql=4096).call("catalog_context", {"tables": [CUSTOMER]})

    assert outcome.ok and "回答（页面填写，尚未写回）：不会。" in outcome.text
