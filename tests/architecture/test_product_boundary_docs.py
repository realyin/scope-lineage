"""The public statements of what this package is must match what it ships.

The package grew from a parser into three layers -- the fact engine, the views derived
from its contract, and the materials and checks for people and agents who write business
meaning -- while README and CONTRIBUTING still said report builders and business-semantic
work "belong downstream", and the contract section still spoke of one major version.
Those sentences steer API, packaging and contract decisions, so they are checked here
against the code rather than left to drift again.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.cli import main

REPO = Path(__file__).resolve().parents[2]
PUBLIC_STATEMENTS = ("README.md", "README.zh-CN.md", "CONTRIBUTING.md")


@pytest.fixture(scope="module")
def written_versions(tmp_path_factory) -> tuple[str, str]:
    out = tmp_path_factory.mktemp("parse")
    sql = REPO / "examples" / "sql" / "customer_profile_daily.sql"
    assert main(["parse", "--sql-file", str(sql), "--out", str(out)]) == 0
    document = json.loads(next(out.rglob("lineage.json")).read_text(encoding="utf-8"))
    statement = next(iter(document["statement_lineage"].values()))
    return document["schema_version"], statement["schema_version"]


@pytest.mark.parametrize("name", ["README.md", "README.zh-CN.md"])
def test_readmes_name_the_contract_versions_the_cli_writes(name, written_versions) -> None:
    text = (REPO / name).read_text(encoding="utf-8")
    task, statement = written_versions

    assert f'schema_version: "{task}"' in text
    assert f'schema_version: "{statement}"' in text
    assert "Within major version 1" not in text


@pytest.mark.parametrize("name", PUBLIC_STATEMENTS)
def test_the_derived_layers_are_not_disowned(name) -> None:
    text = (REPO / name).read_text(encoding="utf-8")

    for stale in (
        "business-semantic generation remain downstream",
        "业务语义生成属于下游",
        "report builders",
    ):
        assert stale not in text, f"{name} still says {stale!r}"


@pytest.mark.parametrize("name", PUBLIC_STATEMENTS)
def test_the_three_layers_are_named(name) -> None:
    text = (REPO / name).read_text(encoding="utf-8")

    for package in ("`scope`", "`render`", "`semantics`"):
        assert package in text, f"{name} does not place {package}"
