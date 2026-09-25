"""The one-page overview that opens every concept page: plain Chinese, names only, no ids.

Built from the recorded demo document (the same file ``test_catalog_pages`` pins), so each
field is checked against a concept a reader would open: the customer (an entity with two
identifiers and a state), the loan (a non-linear state machine, a deprecated table), the
repayment (an event) and the borrower (a role).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scope_lineage.render.catalog_overview import (
    arises_words,
    clip,
    concept_overview,
    overview_lines,
    scope_words,
    state_flow,
)
from scope_lineage.render.catalog_pages import render_catalog_pages
from scope_lineage.render.catalog_view import CatalogView

ONTOLOGY = Path(__file__).parent / "fixtures" / "catalog" / "ontology.json"


@pytest.fixture(scope="module")
def view() -> CatalogView:
    return CatalogView(json.loads(ONTOLOGY.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def pages(view: CatalogView) -> dict:
    return render_catalog_pages(view.document)


def _overview(page: str) -> str:
    return page.split("## 一页纸概览")[1].split("\n## 附录")[0]


# ------------------------------------------------------------- the wording


def _two_concepts() -> CatalogView:
    return CatalogView({
        "concepts": [
            {"id": "concept:customer", "name": "客户"},
            {"id": "concept:app", "name": "App"},
            {"id": "concept:channel", "name": "渠道"},
        ]
    })


@pytest.mark.parametrize(
    ("scope", "words"),
    [
        ("global", "全局唯一"),
        ({"per": ["concept:channel"]}, "每个渠道一个"),
        ({"per": ["concept:customer", "concept:app"]}, "每个客户×App 一个"),
    ],
)
def test_a_scope_in_words(scope, words: str) -> None:
    assert scope_words(_two_concepts(), scope) == words


def test_an_identifier_without_arises_when_is_there_from_the_start(view: CatalogView) -> None:
    assert arises_words(view, None) == "一开始就有"


def test_arises_when_says_the_condition_and_the_state_it_names(view: CatalogView) -> None:
    arises = {"condition": "assigned on verification", "state": "concept:customer#verified"}

    assert arises_words(view, arises) == "assigned on verification（进入「已认证」状态时）"
    assert arises_words(view, {"condition": "on first login"}) == "on first login"


def test_a_long_arising_condition_is_cut_to_one_short_phrase(view: CatalogView) -> None:
    long_text = "assigned when the customer finishes the whole verification flow in any channel"
    words = arises_words(view, {"condition": long_text})
    assert len(words) == 30 and words.endswith("…")


@pytest.mark.parametrize(
    ("text", "limit", "clipped"),
    [
        ("短句", 30, "短句"),
        ("一二三四五六", 6, "一二三四五六"),
        ("一二三四五六七", 6, "一二三四五…"),
    ],
)
def test_clip_keeps_the_limit_counting_the_ellipsis(text: str, limit: int, clipped: str) -> None:
    assert clip(text, limit) == clipped


def test_a_linear_state_machine_reads_as_one_chain(view: CatalogView) -> None:
    states = view.concepts["concept:customer"]["states"]

    assert state_flow(view, states) == "未认证 —实名认证→ 已认证"


def test_transitions_off_the_chain_are_added_after_it(view: CatalogView) -> None:
    states = view.concepts["concept:loan"]["states"]

    assert state_flow(view, states) == (
        "正常 → 逾期 —豁免→ 结清（另：逾期 —还款→ 正常；正常 —还款→ 结清）"
    )


# ------------------------------------------------------------- the fields


def test_the_customer_overview(view: CatalogView) -> None:
    overview = concept_overview(view, "concept:customer")

    assert (overview["kind"], overview["domain"], overview["drafted_percent"]) == (
        "实体",
        "客户与账户",
        35,
    )
    assert overview["identified_by"][0] == {
        "name": "客户号",
        "arises": "一开始就有",
        "scope": "全局唯一",
        "primary": True,
        "confirmed": True,
    }
    assert overview["data"][0] == {
        "table": "demo_dwd.dwd_party_customer_info_df",
        "about": "Customer master, one row per …",
        "replaced_by": None,
        "confirmed": True,
    }
    assert overview["carriers"] == {"tables": 4, "domains": 2}
    assert overview["owns"] == [{"text": "holds 应用账户", "confirmed": True}]
    assert overview["events"] == [
        {"domain": "客户与账户", "events": [{"name": "实名认证", "confirmed": False}]},
        {"domain": "贷款", "events": [{"name": "还款", "confirmed": True}]},
    ]


def test_a_relation_is_read_from_this_concepts_side(view: CatalogView) -> None:
    """The inverse name when this concept is the target; without one, the whole reading."""
    loan = concept_overview(view, "concept:loan")
    account = concept_overview(view, "concept:app_account")

    assert [a["text"] for a in loan["associates"]] == [
        "is owed by 借款人",
        "分期借据 is a kind of 借据",
        "renews 借据",
    ]
    assert [a["text"] for a in account["associates"]] == ["is opened in 渠道", "is held by 客户"]


def test_a_deprecated_table_names_its_replacement(view: CatalogView) -> None:
    data = concept_overview(view, "concept:loan")["data"]

    assert data[-1]["table"] == "demo_dws.dws_lending_loan_summary_1d"
    assert data[-1]["replaced_by"] == "demo_dws.dws_lending_loan_summary_v2_1d"


def test_watch_lists_hard_rules_and_business_rules_confirmed_first(view: CatalogView) -> None:
    loan = concept_overview(view, "concept:loan")["watch"]
    customer = concept_overview(view, "concept:customer")["watch"]

    assert [w["text"] for w in loan] == [
        "no two loans share a loan_no, whatever the channel",
        "principal > 0",
        "a settled loan never changes status again",
    ]
    assert customer == [
        {"text": "customer counts read only rows whose customer_status is act…", "confirmed": False}
    ]


def test_an_event_overview_names_participants_time_and_tables(view: CatalogView) -> None:
    overview = concept_overview(view, "concept:repayment")

    assert overview["participants"] == [
        {"role_name": "payer", "concept": "客户"},
        {"role_name": "loan", "concept": "借据"},
    ]
    assert overview["occurred_at"] == "还款时间"
    assert [d["table"] for d in overview["data"]] == ["demo_dwd.dwd_lending_repayment_di"]
    assert overview["carriers"] == {"tables": 0, "domains": 0}
    assert len(overview["watch"][0]["text"]) == 60


def test_a_role_overview_names_its_player_and_condition(view: CatalogView) -> None:
    overview = concept_overview(view, "concept:borrower")

    assert overview["player"] == "客户"
    assert overview["condition"] == "holds at least one loan whose status is not settled"
    assert [d["table"] for d in overview["data"]] == ["demo_dwd.dwd_lending_borrower_df"]
    assert overview["events"] == [
        {"domain": "贷款", "events": [{"name": "放款", "confirmed": True}]},
        {"domain": "催收", "events": [{"name": "豁免", "confirmed": False}]},
    ]


def test_a_player_overview_lists_its_roles_with_a_short_condition(view: CatalogView) -> None:
    roles = concept_overview(view, "concept:customer")["roles"]

    assert roles == [
        {"name": "借款人", "condition": "holds at least one loan whose…", "confirmed": True}
    ]


# ------------------------------------------------------------- the markdown


def test_the_customer_overview_markdown(view: CatalogView) -> None:
    lines = overview_lines(concept_overview(view, "concept:customer"))

    assert "\n".join(lines) == "\n".join([
        "**是什么**：A person the shop has registered, whether or not they ever borrow.",
        "",
        "**怎么认出来**：",
        "",
        "- 客户号：一开始就有，全局唯一（主标识） ✓",
        "- 认证客户号：assigned when the customer pa…"
        "（进入「已认证」状态时），全局唯一",
        "",
        "**状态**：未认证 —实名认证→ 已认证",
        "",
        "**数据在哪**：",
        "",
        "- `demo_dwd.dwd_party_customer_info_df`（Customer master, one row per …） ✓",
        "- `demo_dwd.dwd_party_customer_ext_df`",
        "- 另有 4 张表带本概念的标识，分布在 2 个域（见附录 A3）",
        "",
        "**拥有的**：holds 应用账户 ✓",
        "",
        "**参与的事件**：",
        "",
        "- 客户与账户：实名认证",
        "- 贷款：还款 ✓",
        "",
        "**扮演的角色**：",
        "",
        "- 借款人：holds at least one loan whose… ✓",
        "",
        "**要注意**：",
        "",
        "- customer counts read only rows whose customer_status is act…",
    ])


def test_an_event_is_recorded_in_its_tables_and_a_role_names_its_player(
    view: CatalogView,
) -> None:
    event = "\n".join(overview_lines(concept_overview(view, "concept:repayment")))
    role = "\n".join(overview_lines(concept_overview(view, "concept:borrower")))

    assert "**参与者**：payer → 客户；loan → 借据" in event
    assert "**发生时间**：还款时间" in event
    assert "**记录在**：\n\n- `demo_dwd.dwd_lending_repayment_di`（Repayments） ✓" in event
    assert "**数据在哪**" not in event
    assert "**承担者**：客户；**成立条件**：holds at least one loan whose status is not settled" in role
    assert "**扮演的角色**" not in role


def test_with_no_table_listed_the_carriers_are_not_called_others(
    view: CatalogView,
) -> None:
    lines = overview_lines(concept_overview(view, "concept:channel"))

    assert "- 2 张表带本概念的标识，分布在 2 个域（见附录 A3）" in lines
    assert not any("另有" in line for line in lines)


# ------------------------------------------------------------- on the page


def test_every_concept_page_opens_with_the_overview_then_the_appendix(pages: dict) -> None:
    titles = ("定义与身份", "数据清单", "带本概念标识的表", "属性", "关系", "约束", "治理缺口")
    for name, page in pages.items():
        if not name.startswith("concepts/"):
            continue
        headings = re.findall(r"^(##|###) (.+)$", page, flags=re.MULTILINE)
        assert headings == [
            ("##", "一页纸概览"),
            ("##", "附录"),
            *[("###", f"A{n} {title}") for n, title in enumerate(titles, 1)],
        ], name


def test_the_status_line_names_kind_domain_and_the_drafted_share(pages: dict) -> None:
    page = pages["concepts/customer.md"]

    assert page.splitlines()[2] == (
        "实体 · [客户与账户](../index.md) · 本页 35% 草拟、已确认的条目标 ✓"
    )
    assert "| 编号 | `concept:customer` |" in page


def test_the_overview_has_no_ids_and_no_wide_tables(pages: dict) -> None:
    for name, page in pages.items():
        if not name.startswith("concepts/"):
            continue
        overview = _overview(page)
        assert not re.search(r"\b(concept|id|attr|rel|cons|code|domain):", overview), name
        assert "|" not in overview, name
