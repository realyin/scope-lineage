"""``catalog render``: the built document as an index, identifier, governance and concept pages.

The pages are recorded whole for the demo built over its corpus (the golden), and the
facts a reader opens a concept page for are asserted one by one, so a golden diff that
moves one of them has a named test beside it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scope_lineage.catalog import build_ontology, load_catalog
from scope_lineage.cli import main
from scope_lineage.render.catalog_pages import render_catalog_pages
from scope_lineage.render.catalog_view import code_value_text, usage_hint

from .catalog_demo import DEMO, demo_tables, parse_demo_corpus

GOLDEN = Path(__file__).parent / "fixtures" / "catalog"
SECTIONS = ("定义与身份", "数据清单", "带本概念标识的表", "属性", "关系", "约束", "治理缺口")


@pytest.fixture(scope="module")
def document(tmp_path_factory) -> dict:
    """The demo built with both kinds of evidence, exactly as the docs run it."""
    root = tmp_path_factory.mktemp("demo")
    lineage = parse_demo_corpus(root / "lineage")
    tables = demo_tables(lineage, root / "tables")
    out = root / "built"
    args = ["catalog", "build", str(DEMO), "--out", str(out)]
    assert main([*args, "--lineage", str(lineage), "--tables", str(tables)]) == 0
    return json.loads((out / "ontology.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def pages(document: dict) -> dict:
    return render_catalog_pages(document)


@pytest.fixture(scope="module")
def plain_pages() -> dict:
    return render_catalog_pages(build_ontology(load_catalog(DEMO)))


def _row(page: str, first_cell: str) -> str:
    rows = [line for line in page.splitlines() if line.startswith(f"| {first_cell}")]
    assert len(rows) == 1, f"expected one row starting {first_cell!r}, got {rows}"
    return rows[0]


def _inventory_row(page: str, table: str) -> str:
    """A table's row in section 2 (section 3 names the same table again)."""
    return _row(page.split("## 2. 数据清单")[1].split("\n## 3.")[0], table)


# ------------------------------------------------------------------- the set


def test_one_page_per_concept_plus_four(pages: dict) -> None:
    concepts = {name for name in pages if name.startswith("concepts/")}

    assert set(pages) - concepts == {"index.md", "identifiers.md", "governance.md", "scopes.md"}
    assert len(concepts) == 10
    assert "concepts/customer.md" in concepts


def test_every_concept_page_has_the_seven_sections_in_order(pages: dict) -> None:
    for name, page in pages.items():
        if not name.startswith("concepts/"):
            continue
        headings = re.findall(r"^## (\d)\. (.+)$", page, flags=re.MULTILINE)
        assert headings == [(str(n), title) for n, title in enumerate(SECTIONS, 1)], name


def test_a_document_of_another_format_is_refused() -> None:
    with pytest.raises(ValueError, match="ontology-json/3"):
        render_catalog_pages({"doc_format": "ontology-json/2"})


def test_the_golden_pages(pages: dict, document: dict) -> None:
    recorded = {"ontology.json": json.dumps(document, ensure_ascii=False, indent=2) + "\n"}
    recorded.update({f"pages/{name}": body for name, body in pages.items()})

    for name, body in recorded.items():
        assert body == (GOLDEN / name).read_text(encoding="utf-8"), name
    on_disk = {p.relative_to(GOLDEN).as_posix() for p in GOLDEN.rglob("*") if p.is_file()}
    assert on_disk == set(recorded)


# ------------------------------------------------------ 1. 定义与身份


def test_identity_lists_every_identifier_with_its_spellings_and_mapping(pages: dict) -> None:
    page = pages["concepts/customer.md"]

    row = _row(page, "客户号 `id:customer_id`（主）")
    assert "`demo_ods.ods_core_customer_df.cust_no`" in row
    assert "应用账户号 一对多，经 `demo_dwd.dwd_party_account_map_df`" in row
    verified = _row(page, "认证客户号")
    assert "（状态：已认证）" in verified
    assert "| 同义词 | 用户 |" in page


def test_identity_shows_the_state_machine(pages: dict) -> None:
    page = pages["concepts/loan.md"]

    assert "状态属性：借据状态 `attr:loan.loan_status`" in page
    assert "| [豁免](fee_waiver.md) | 逾期 | 结清 |" in page


def test_an_event_names_its_participants_and_a_role_its_player(pages: dict) -> None:
    assert "| 参与者 payer | [客户](customer.md)（一个） |" in pages["concepts/repayment.md"]
    borrower = pages["concepts/borrower.md"]
    assert "| 承担者 | [客户](customer.md) |" in borrower
    assert "本概念是[客户](customer.md)的角色" in borrower


# ------------------------------------------------------------ 2. 数据清单


def test_the_inventory_groups_tables_by_how_they_carry_the_concept(pages: dict) -> None:
    page = pages["concepts/loan.md"]
    inventory = page.split("## 2. 数据清单")[1].split("## 3.")[0]

    assert re.findall(r"^### (.+)$", inventory, flags=re.MULTILINE) == ["核心", "状态历史", "汇总"]


def test_an_inventory_row_carries_grain_time_refresh_scope_and_producer(pages: dict) -> None:
    row = _inventory_row(pages["concepts/loan.md"], "`demo_dwd.dwd_lending_loan_df`")

    assert "借据号（已证明）；血缘候选 `loan_no`" in row
    assert (
        "| daily；调度 day | each dt partition is the full snapshot of that day "
        "| dwd_lending_loan_daily |"
    ) in row
    history = _inventory_row(pages["concepts/loan.md"], "`demo_dwd.dwd_lending_loan_status_his`")
    assert "| — | 全部 | — |" in history


def test_an_inventory_row_shows_the_table_comment_and_the_catalogs_notes(pages: dict) -> None:
    row = _inventory_row(pages["concepts/loan.md"], "`demo_dwd.dwd_lending_loan_df`")
    waiver = _inventory_row(pages["concepts/fee_waiver.md"], "`demo_dwd.dwd_collection_fee_waiver_di`")

    assert "| `demo_dwd.dwd_lending_loan_df` | 表注释：Loan snapshot；备注：A renewal loan" in row
    assert "| 备注：Kept as JSON on purpose" in waiver


def test_an_inventory_row_says_how_to_read_a_snapshot_and_a_zipper(pages: dict) -> None:
    snapshot = _inventory_row(pages["concepts/loan.md"], "`demo_dwd.dwd_lending_loan_df`")
    zipper = _inventory_row(pages["concepts/loan.md"], "`demo_dwd.dwd_lending_loan_status_his`")

    assert "| 快照；按单个 dt 分区取数 |" in snapshot
    assert "| 拉链；按有效期窗口取数（start_date ≤ 查询日 < end_date，端点开闭以表口径为准） |" in zipper


@pytest.mark.parametrize(
    ("time", "columns", "hint"),
    [
        ("snapshot", ["id", "ds"], "按单个 ds 分区取数"),
        ("snapshot", ["id"], "按单个 dt 分区取数"),
        ("zipper", ["id", "eff_date", "exp_date"], "按有效期窗口取数（eff_date ≤ 查询日 < exp_date"),
        ("zipper", ["id"], "按有效期窗口取数（开始日 ≤ 查询日 < 结束日"),
        ("incremental", ["id", "dt"], None),
    ],
)
def test_the_usage_hint_names_the_tables_own_columns(time: str, columns: list, hint) -> None:
    rep = {"time": time, "bindings": [{"column": column} for column in columns]}

    found = usage_hint(rep)

    assert found == hint if hint is None else found.startswith(hint)


def test_a_deprecated_table_names_its_replacement(pages: dict) -> None:
    row = _inventory_row(pages["concepts/loan.md"], "`demo_dws.dws_lending_loan_summary_1d`")

    assert "已废弃" in row
    assert "由 `demo_dws.dws_lending_loan_summary_v2_1d` 替代" in row


def test_the_inventory_shows_one_hop_of_lineage(pages: dict) -> None:
    assert (
        "- `demo_dwd.dwd_party_customer_info_df` 血缘一跳：上游 "
        "`demo_ods.ods_core_customer_df`；下游"
    ) in pages["concepts/customer.md"]


# ------------------------------------------------------ 3. 带本概念标识的表


def _carriers(page: str) -> str:
    return page.split("## 3. 带本概念标识的表")[1].split("\n## ")[0]


def test_carriers_list_every_table_holding_the_concepts_identifier(pages: dict) -> None:
    """The channel has no table of its own, yet two tables carry its code."""
    section = _carriers(pages["concepts/channel.md"])

    assert "（目录未登记" not in section
    assert (
        "| `demo_dwd.dwd_party_account_map_df` | [应用账户](app_account.md) | `channel_code` "
        "| 渠道编码 `id:channel_code` | 外部标识符 |"
    ) in section
    assert "| `demo_dws.dws_lending_loan_summary_1d` | [借据](loan.md) | `channel_code` |" in section


def test_carriers_include_the_concepts_own_tables_and_self_references(pages: dict) -> None:
    section = _carriers(pages["concepts/loan.md"])

    assert "| `demo_dwd.dwd_lending_loan_df` | 本概念 | `loan_no` | 借据号 `id:loan_no` | 标识符 |" in section
    assert "| `orig_loan_no` | 借据号 `id:loan_no` | 外部标识符（自关联） |" in section
    assert "| `demo_dwd.dwd_collection_fee_waiver_di` | [豁免](fee_waiver.md) | `loan_no` |" in section


def test_a_role_has_no_identifier_of_its_own_to_carry(pages: dict) -> None:
    section = _carriers(pages["concepts/borrower.md"])

    assert "角色没有自己的标识符" in section
    assert "[客户](customer.md)" in section


# ---------------------------------------------------------------- 4. 属性


def test_an_attribute_lists_every_column_that_holds_it(pages: dict) -> None:
    row = _row(pages["concepts/customer.md"], "性别 `attr:customer.gender`")

    assert "F=female；M=male；U=unknown（停用）" in row
    assert "`demo_dwd.dwd_lending_borrower_df.gender_cd`" in row
    assert "`demo_dwd.dwd_party_customer_info_df.gender_cd`（码值映射 F→female" in row


def test_a_denormalised_column_is_listed_on_the_owning_concepts_page(pages: dict) -> None:
    """The loan table repeats the customer's gender next to customer_id."""
    row = _row(pages["concepts/customer.md"], "性别 `attr:customer.gender`")

    assert "`demo_dwd.dwd_lending_loan_df.customer_gender_cd` 冗余（经 `customer_id`）" in row


def test_derivation_prefers_the_hand_written_one_and_labels_lineage(pages: dict) -> None:
    customer = pages["concepts/customer.md"]

    registered = _row(customer, "注册时间")
    assert "register_time`：from_unixtime(register_ts)" in registered
    assert "血缘" not in registered
    principal = _row(pages["concepts/loan.md"], "本金")
    assert "principal_amt` = `` `l`.`principal` ``（血缘）" in principal


def test_an_unused_declared_column_is_flagged_where_it_is_bound(pages: dict) -> None:
    row = _row(pages["concepts/loan.md"], "借据状态 `attr:loan.loan_status`")

    assert "`demo_dwd.dwd_lending_loan_status_his.loan_status`（元数据有、语料未用）" in row


def test_a_code_value_whose_meaning_is_not_confirmed_says_so(pages: dict) -> None:
    status = _row(pages["concepts/loan.md"], "借据状态 `attr:loan.loan_status`")
    waiver = _row(pages["concepts/fee_waiver.md"], "豁免类型 `attr:fee_waiver.waiver_type`")

    assert "3=settled；9（含义待确认：疑似核销）|" in status.replace(" |", "|")
    assert "INT=interest waived；OTH（含义待确认：other charges）" in waiver


@pytest.mark.parametrize(
    ("value", "text"),
    [
        ({"value": "1", "meaning": "normal"}, "1=normal"),
        ({"value": "9", "meaning": ""}, "9（含义待确认）"),
        ({"value": "9", "meaning": "待确认"}, "9（含义待确认）"),
        ({"value": "9", "meaning": "待确认：written off?"}, "9（含义待确认：written off?）"),
        ({"value": "9", "meaning": "frozen", "unconfirmed": True}, "9（含义待确认：frozen）"),
    ],
)
def test_a_code_value_text(value: dict, text: str) -> None:
    assert code_value_text(value) == text


# ---------------------------------------------------------------- 5. 关系


def test_a_relation_is_read_from_this_concepts_side(pages: dict) -> None:
    loan = _row(pages["concepts/loan.md"], "owes `rel:borrower_owes_loan`")
    customer = _row(pages["concepts/customer.md"], "holds `rel:customer_holds_app_account`")

    assert "| 借据 is owed by 借款人 | [借款人](borrower.md) |" in loan
    assert "1 次（如 `demo_dwd.dwd_lending_borrower_df.customer_id = " in loan
    assert (
        "| 客户 holds 应用账户 | [应用账户](app_account.md) | 客户 1 : 应用账户 0..* |" in customer
    )


def test_a_self_relation_names_the_columns_that_carry_it(pages: dict) -> None:
    row = _row(pages["concepts/loan.md"], "renews `rel:loan_renews_loan`")

    assert "| 借据 renews 借据 |" in row
    assert "| 本概念（自关联，经 `demo_dwd.dwd_lending_loan_df.orig_loan_no`） |" in row


def test_the_events_a_concept_takes_part_in(pages: dict) -> None:
    page = pages["concepts/loan.md"]

    assert "| [还款](repayment.md) | loan | 1 | 1 次（如" in page
    assert "| [豁免](fee_waiver.md) | loan | 1 | 0 次；同表携带两端：" in page
    assert "| [放款](disbursement.md) | loan | 0 | —（一端无表现表） |" in page


def test_a_relation_no_join_backs_falls_back_to_the_catalogs_own_evidence(pages: dict) -> None:
    """The channel has no table, so no JOIN is counted; the catalog still shows where the
    relation lives: the account map carries both ends, and the relation cites its column."""
    row = _row(pages["concepts/channel.md"], "is opened in `rel:app_account_opened_in_channel`")

    assert (
        "| —（一端无表现表）；同表携带两端：`demo_dwd.dwd_party_account_map_df`；"
        "目录证据：`demo_dwd.dwd_party_account_map_df.channel_code` |"
    ) in row


def test_a_relation_counted_at_zero_joins_shows_the_tables_carrying_both_ends(
    document: dict,
) -> None:
    zero = json.loads(json.dumps(document))
    zero["evidence"]["relations"]["rel:loan_renews_loan"]["joins"] = {"count": 0, "samples": []}

    row = _row(render_catalog_pages(zero)["concepts/loan.md"], "renews `rel:loan_renews_loan`")

    assert (
        "| 0 次；同表携带两端：`demo_dwd.dwd_lending_loan_df`；"
        "目录证据：`demo_dwd.dwd_lending_loan_df.orig_loan_no` |"
    ) in row


def test_a_player_page_links_to_its_roles(pages: dict) -> None:
    assert (
        "| [借款人](borrower.md) | 贷款 | holds at least one loan whose status is not settled | 1 |"
        in pages["concepts/customer.md"]
    )


# ---------------------------------------------------------------- 6. 约束


def test_constraints_on_the_concept_its_attributes_identifiers_and_relations(pages: dict) -> None:
    constraints = pages["concepts/loan.md"].split("## 6. 约束")[1].split("## 7.")[0]
    ids = re.findall(r"^\| `(cons:[a-z_]+)`", constraints, flags=re.MULTILINE)

    assert ids == [
        "cons:loan_no_unique",
        "cons:principal_positive",
        "cons:settled_is_final",
        "cons:penalty_rule",
    ]
    assert "| 硬 |" in constraints and "| 软 |" in constraints


# --------------------------------------------------------------- 7. 治理缺口


def test_gaps_name_the_conflict_the_unmapped_column_and_the_missing_table(pages: dict) -> None:
    loan = pages["concepts/loan.md"]

    assert "目录声明粒度已证明，血缘只到候选（`loan_no`）" in loan
    assert "| 无连接证据的关系 | `rel:fee_waiver.loan`；`rel:loan_renews_loan` |" in loan
    assert (
        "| 未绑定列 | `demo_dwd.dwd_party_customer_ext_df.ext_json` |"
        in pages["concepts/customer.md"]
    )
    installment = pages["concepts/installment_loan.md"]
    assert "| 没有表现表 | 是 |" in installment
    assert "| 未落表属性 | `attr:installment_loan.term_count` |" in installment


def test_without_evidence_the_pages_say_so_rather_than_guess(plain_pages: dict) -> None:
    loan = plain_pages["concepts/loan.md"]

    assert "血缘" not in loan
    assert "证据与目录矛盾" not in loan
    owes = _row(loan, "owes `rel:borrower_owes_loan`")
    assert "次" not in owes
    assert "同表携带两端：`demo_dwd.dwd_lending_loan_df`、`demo_dwd.dwd_lending_repayment_di`" in owes
    assert "证据" not in plain_pages["index.md"].split("## 概念")[0]


# ------------------------------------------------------ index and governance


def test_the_index_lists_concepts_by_domain_with_links(pages: dict) -> None:
    index = pages["index.md"]

    assert "### 客户与账户 `domain:party`" in index
    assert "| [客户](concepts/customer.md) | 实体 | A person the shop has registered" in index
    assert "| 2 | 已确认（owner） |" in _row(index, "[客户](concepts/customer.md)")
    assert "| 证据与目录矛盾 | 1 |" in index
    assert "| 没有表现表的概念 | 4 |" in index


def test_identifiers_page_shows_the_bound_columns(pages: dict) -> None:
    page = pages["identifiers.md"]
    block = page.split("## 借据号 `id:loan_no`")[1].split("\n## ")[0]

    assert "`demo_dwd.dwd_lending_loan_df.loan_no`（标识符）" in block
    assert "`demo_dwd.dwd_lending_repayment_di.loan_no`（外部标识符）" in block
    assert "`demo_dwd.dwd_lending_loan_df.orig_loan_no`（外部标识符，自关联）" in block


def test_governance_lists_each_kind_of_gap(pages: dict) -> None:
    page = pages["governance.md"]

    assert "## 没有表现表的概念\n\n- [渠道](concepts/channel.md)" in page
    assert "- `rel:repayment.payer`：还款 payer 客户" in page


def test_governance_lists_code_values_whose_meaning_is_not_confirmed(pages: dict) -> None:
    section = pages["governance.md"].split("## 含义待确认的码值")[1].split("\n## ")[0]

    assert (
        "| 借据状态 `code:loan_status` | `9`（疑似核销） | 借据状态 `attr:loan.loan_status` |"
        in section
    )
    assert "| 豁免类型 `code:waiver_type` | `OTH`（other charges） |" in section
    assert "| 含义待确认的码值 | 2 |" in pages["index.md"]


def test_governance_counts_denormalised_columns_per_table_without_calling_them_gaps(
    pages: dict,
) -> None:
    page = pages["governance.md"]
    section = page.split("## 冗余属性列（按表）")[1]

    assert "| `demo_dwd.dwd_lending_loan_df` | 1 | `customer_gender_cd`：客户.性别（经 `customer_id`） |" in section
    assert "冗余属性" not in page.split("## 冗余属性列（按表）")[0]
    assert "冗余" not in pages["index.md"]


# ----------------------------------------------------------------------- CLI


def test_render_writes_every_page(document: dict, tmp_path: Path, capsys) -> None:
    source = tmp_path / "ontology.json"
    source.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "pages"

    assert main(["catalog", "render", str(source), "--out", str(out)]) == 0

    written = {p.relative_to(out).as_posix() for p in out.rglob("*.md")}
    assert written == set(render_catalog_pages(document))
    assert "Rendered 14 page(s) (10 concept page(s))" in capsys.readouterr().out


def test_render_refuses_another_format(tmp_path: Path, capsys) -> None:
    source = tmp_path / "ontology.json"
    source.write_text(json.dumps({"doc_format": "ontology-json/2"}), encoding="utf-8")

    assert main(["catalog", "render", str(source), "--out", str(tmp_path / "out")]) == 1
    assert "ontology-json/3" in capsys.readouterr().err


def test_render_of_a_missing_file_exits_two(tmp_path: Path, capsys) -> None:
    assert main(["catalog", "render", str(tmp_path / "nope.json"), "--out", str(tmp_path)]) == 2
    assert "does not exist" in capsys.readouterr().err
