"""The MCP server: each tool answers what the CLI prints -- text by default, ``--json`` on request.

Most cases talk to the server in memory through the SDK's own client; two start it as a
stdio subprocess, once on the current protocol and once with the older initialize
handshake, so the wire itself is exercised too. Nothing leaves the machine.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import anyio
import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from service_paths import CUSTOMER, LOAN

from scope_lineage.cli import main
from scope_lineage_service.mcp_server import build_server
from scope_lineage_service.state import CatalogState

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def state(inputs) -> CatalogState:
    return CatalogState(
        str(inputs["ontology"]), semantics=str(inputs["semantics"]), pending=str(inputs["pending"])
    )


def _call(server, tool: str, arguments: dict):
    async def run():
        async with Client(server) as client:
            return await client.call_tool(tool, arguments)

    return anyio.run(run)


def _tools(server) -> dict:
    async def run():
        async with Client(server) as client:
            return (await client.list_tools()).tools

    return {tool.name: tool for tool in anyio.run(run)}


def _text(result) -> str:
    assert len(result.content) == 1
    return result.content[0].text


def _cli(capsys, *argv) -> str:
    main(list(argv))
    return capsys.readouterr().out


# ------------------------------------------------------------------ acceptance


def test_search_json_is_the_cli_json(state, inputs, capsys) -> None:
    out = _cli(
        capsys, "catalog", "search", str(inputs["ontology"]), "客户", "--semantics",
        str(inputs["semantics"]), "--kind", "concept", "--limit", "3", "--json",
    )
    result = _call(
        build_server(state), "search_catalog",
        {"text": "客户", "kinds": ["concept"], "limit": 3, "format": "json"},
    )

    assert not result.is_error
    assert _text(result) + "\n" == out


def test_search_text_is_the_default(state, inputs, capsys) -> None:
    out = _cli(
        capsys, "catalog", "search", str(inputs["ontology"]), "客户", "--semantics",
        str(inputs["semantics"]),
    )

    assert _text(_call(build_server(state), "search_catalog", {"text": "客户"})) == out


def test_context_json_is_the_cli_json(state, inputs, capsys) -> None:
    out = _cli(
        capsys, "catalog", "context", str(inputs["ontology"]), "--semantics",
        str(inputs["semantics"]), "--table", CUSTOMER, "--columns", "gender_cd",
        "--concept", "customer", "--brief", "--focus", "--json",
    )
    result = _call(build_server(state), "catalog_context", {
        "tables": [CUSTOMER], "columns_of_table": ["gender_cd"], "concepts": ["customer"],
        "brief": True, "focus": True, "format": "json",
    })

    assert _text(result) + "\n" == out


def test_query_json_is_the_cli_json_and_nothing_found_is_not_an_error(
    state, inputs, capsys
) -> None:
    out = _cli(capsys, "catalog", "query", str(inputs["ontology"]), "table", LOAN, "--json")
    assert _text(_call(
        build_server(state), "query_catalog", {"kind": "table", "term": LOAN, "format": "json"}
    )) + "\n" == out

    out = _cli(capsys, "catalog", "query", str(inputs["ontology"]), "table", "x.none")
    result = _call(build_server(state), "query_catalog", {"kind": "table", "term": "x.none"})
    assert not result.is_error and _text(result) == out


def test_check_sql_json_is_the_cli_json(state, inputs, capsys, tmp_path) -> None:
    sql = f"SELECT gender_cd, count(*) FROM {CUSTOMER} GROUP BY gender_cd"
    path = tmp_path / "q.sql"
    path.write_text(sql, encoding="utf-8")
    out = _cli(capsys, "catalog", "check-sql", str(inputs["ontology"]), str(path), "--json")
    result = _call(build_server(state), "check_sql", {"sql": sql, "format": "json"})

    assert _text(result) + "\n" == out


def test_pending_add_then_list(state, inputs, capsys) -> None:
    server = build_server(state)
    result = _call(server, "add_pending", {
        "question": "上月新增客户数", "missing": "注销的客户算不算", "tables": [CUSTOMER],
        "date": "2026-01-02", "format": "json",
    })
    written = [json.loads(line) for line in inputs["pending"].read_text("utf-8").splitlines()]
    assert json.loads(_text(result)) == {"appended": 1, "lines": written}

    out = _cli(
        capsys, "catalog", "pending", "list", str(inputs["pending"]), "--ontology",
        str(inputs["ontology"]), "--semantics", str(inputs["semantics"]), "--json",
    )
    assert _text(_call(server, "list_pending", {"format": "json"})) + "\n" == out


# ------------------------------------------------------------------ tool shapes


def test_tools_describe_themselves(state, inputs) -> None:
    tools = _tools(build_server(state))

    assert set(tools) == {
        "search_catalog", "catalog_context", "query_catalog", "check_sql", "list_pending",
        "add_pending",
    }
    for tool in tools.values():
        assert len(tool.description) > 80
        for name, schema in tool.input_schema.get("properties", {}).items():
            assert schema.get("description"), f"{tool.name}.{name} has no description"
    assert tools["query_catalog"].input_schema["required"] == ["kind", "term"]
    kinds = tools["query_catalog"].input_schema["properties"]["kind"]
    assert "table" in json.dumps(kinds)
    assert tools["check_sql"].annotations.read_only_hint is True
    assert tools["add_pending"].annotations.read_only_hint is False

    bare = _tools(build_server(CatalogState(str(inputs["ontology"]))))
    assert "add_pending" not in bare and "list_pending" not in bare


def test_a_refused_input_is_a_tool_error_with_the_cli_sentence(state, inputs, capsys) -> None:
    main(["catalog", "context", str(inputs["ontology"]), "--columns", "a"])
    err = capsys.readouterr().err.rstrip("\n")
    result = _call(build_server(state), "catalog_context", {"columns_of_table": ["a"]})

    assert result.is_error
    assert err in _text(result)


def test_sql_that_does_not_parse_is_a_tool_error(state) -> None:
    result = _call(build_server(state), "check_sql", {"sql": "SELECT FROM ("})
    assert result.is_error and "catalog check-sql" in _text(result)


# ------------------------------------------------------------------ over stdio


def _stdio(inputs, mode: str):
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m", "scope_lineage_service", "mcp", str(inputs["ontology"]),
            "--semantics", str(inputs["semantics"]),
        ],
        cwd=str(inputs["ontology"].parent),
    )

    async def run():
        async with Client(params, mode=mode, read_timeout_seconds=30) as client:
            tools = (await client.list_tools()).tools
            result = await client.call_tool(
                "query_catalog", {"kind": "table", "term": LOAN, "format": "json"}
            )
            return tools, result

    return anyio.run(run)


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_the_server_answers_over_stdio(inputs, capsys, mode) -> None:
    out = _cli(capsys, "catalog", "query", str(inputs["ontology"]), "table", LOAN, "--json")
    tools, result = _stdio(inputs, mode)

    assert {tool.name for tool in tools} == {
        "search_catalog", "catalog_context", "query_catalog", "check_sql",
    }
    assert _text(result) + "\n" == out


def test_mcp_overlays_an_answers_file_read_only(inputs, tmp_path) -> None:
    """``mcp --answers``: the tools read the page's answers; no tool writes them, and the
    file is never written, not even to delete a record the documents have caught up with."""
    from scope_lineage_service import answers as records_file

    question = json.loads((inputs["semantics"] / f"{CUSTOMER}.json").read_text(
        encoding="utf-8"))["summary"]["questions"][0]
    file = tmp_path / "answers.json"
    records_file.write_records(file, [{
        "table": CUSTOMER, "question": question["id"], "asked": question["text"], "base": None,
        "kind": "answer", "answer": "不会。", "source": {"kind": "person"}, "by": "审核人甲",
        "date": "2026-11-23"}])
    before = file.read_bytes()
    state = CatalogState(str(inputs["ontology"]), semantics=str(inputs["semantics"]),
                         answers=str(file), answers_writer=False)
    result = _call(build_server(state), "catalog_context", {"tables": [CUSTOMER]})

    assert "回答（页面填写，尚未写回）：不会。" in _text(result)
    assert set(_tools(build_server(state))) == {
        "search_catalog", "catalog_context", "query_catalog", "check_sql",
    }
    assert file.read_bytes() == before
