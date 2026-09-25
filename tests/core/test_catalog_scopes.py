"""Record scope and validity: every table's scope lines grouped by the kind of filter they
state (``scopes.md``), the rules that cite a table, and ``catalog query scope``.

Runs against the recorded demo document, the same file ``test_catalog_pages`` pins.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.render.catalog_pages import render_catalog_pages
from scope_lineage.render.catalog_query import query_catalog, render_query_text
from scope_lineage.render.catalog_scopes import classify_scope

ONTOLOGY = Path(__file__).parent / "fixtures" / "catalog" / "ontology.json"


@pytest.fixture(scope="module")
def document() -> dict:
    return json.loads(ONTOLOGY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def page(document: dict) -> str:
    return render_catalog_pages(document)["scopes.md"]


def _section(page: str, title: str) -> str:
    return page.split(f"## {title}\n")[1].split("\n## ")[0]


# ------------------------------------------------------------------ classifier


@pytest.mark.parametrize(
    ("line", "kinds"),
    [
        ("只保留有效记录", ["validity"]),
        ("record_status = 'A'", ["validity"]),
        ("is_deleted = 0", ["deletion"]),
        ("已注销账户不入表", ["deletion"]),
        ("按 update_time 取最新一条", ["dedup"]),
        ("row_number() = 1 per account", ["dedup"]),
        ("每个 dt 分区一份全量", ["partition"]),
        ("snapshot of the day", ["partition"]),
        ("有效且未删除的客户", ["validity", "deletion"]),
        ("customers holding at least one loan", ["other"]),
        ("the width of a window", ["other"]),
    ],
)
def test_a_scope_line_is_classified_by_its_keywords(line: str, kinds: list) -> None:
    assert classify_scope(line) == kinds


# ------------------------------------------------------------------- the page


def test_the_page_groups_scope_lines_by_kind(page: str) -> None:
    validity = _section(page, "有效记录/记录状态")
    deletion = _section(page, "删除/注销")

    assert (
        "| `demo_dwd.dwd_party_customer_info_df` | [客户](concepts/customer.md) "
        "| 快照；按单个 dt 分区取数 | only customers whose customer_status is active |"
    ) in validity
    assert "注销客户不入表" in deletion
    assert "`demo_dwd.dwd_party_account_map_df`" in _section(page, "去重/最新")
    assert "`demo_dwd.dwd_lending_loan_df`" in _section(page, "分区/快照日期")
    assert "customers holding at least one loan" in _section(page, "其他")


def test_the_page_lists_tables_that_declare_no_scope(page: str) -> None:
    section = _section(page, "未声明记录范围的表")

    assert "- `demo_dwd.dwd_lending_loan_status_his`（[借据](concepts/loan.md)）" in section
    assert "dwd_party_customer_info_df" not in section


def test_the_page_lists_business_rules_and_value_domains_that_cite_a_table(page: str) -> None:
    section = _section(page, "引用了表的业务规则与值域约束")

    assert "| `demo_dwd.dwd_party_customer_info_df` | `cons:active_customers_only` | 业务规则 |" in (
        section
    )
    assert "| `demo_dwd.dwd_lending_loan_df` | `cons:principal_positive` | 值域 |" in section
    assert "cons:loan_no_unique" not in section


def test_the_index_links_to_the_scope_page(document: dict) -> None:
    index = render_catalog_pages(document)["index.md"]

    assert "[scopes.md](scopes.md)" in index


# ------------------------------------------------------------------ the query


def test_a_scope_query_by_kind_returns_the_tables_and_their_lines(document: dict) -> None:
    matches = query_catalog(document, "scope", "删除")["matches"]

    assert [m["table"] for m in matches] == ["demo_dwd.dwd_party_customer_info_df"]
    assert matches[0]["matched_by"] == "kind"
    assert [line["line"] for line in matches[0]["scope"]] == [
        "注销客户不入表（is_cancelled = 1 的行被过滤）"
    ]


def test_a_scope_query_by_keyword_searches_lines_and_rules(document: dict) -> None:
    matches = query_catalog(document, "scope", "customer_status")["matches"]

    assert [m["table"] for m in matches] == ["demo_dwd.dwd_party_customer_info_df"]
    assert matches[0]["matched_by"] == "keyword"
    assert [c["id"] for c in matches[0]["constraints"]] == ["cons:active_customers_only"]


def test_a_scope_query_by_kind_id_matches_like_its_label(document: dict) -> None:
    by_id = query_catalog(document, "scope", "partition")["matches"]
    by_label = query_catalog(document, "scope", "分区/快照日期")["matches"]

    assert by_id == by_label
    assert by_id[0]["usage"] == "按单个 dt 分区取数"


def test_the_scope_text(document: dict) -> None:
    text = render_query_text(query_catalog(document, "scope", "去重"))

    assert text.splitlines() == [
        "demo_dwd.dwd_party_account_map_df · 应用账户 concept:app_account · 快照；按单个 dt 分区取数",
        "  - 去重/最新：latest row per account and channel (row_number = 1 by update_time)",
    ]


def test_a_scope_query_matching_nothing_is_empty(document: dict) -> None:
    assert query_catalog(document, "scope", "no such filter")["matches"] == []
