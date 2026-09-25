"""``semantic render``: one page per table-semantics document, an index, and the links
between those pages and the concept pages ``catalog render`` writes.

Two documents are rendered: the demo example (``examples/table-semantics/``) and a second
synthetic one for the demo catalog's fee-waiver table that exercises every element --
branches, conflicts, unconfirmed and confirmed code values, an answered question, and a
validation report with failures. Both are recorded whole, with and without the optional
inputs (the goldens); the facts a reader opens the page for are asserted one by one.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
from pathlib import Path

import pytest

from scope_lineage.render.catalog_pages import render_catalog_pages
from scope_lineage.semantics import render_semantic_pages

from .table_semantics_demo import (
    CONFIRMATIONS,
    DEMO_TABLE,
    demo_packets,
    example,
    read_json,
    run,
    write_json,
)

FIXTURES = Path(__file__).parent / "fixtures" / "table-semantics"
CATALOG = Path(__file__).parent / "fixtures" / "catalog"
WAIVER = "demo_dwd.dwd_collection_fee_waiver_di"
SECTIONS = ["一页纸", "字段", "加工过程", "规则（原文）", "来源说明"]
SUMMARY_LABELS = [
    "这张表是什么",
    "一行是什么",
    "更新与取数",
    "收哪些数据",
    "数据从哪来",
    "谁在用",
    "适合用来",
    "不适合",
    "要注意",
    "待确认问题",
]


def _documents() -> list[dict]:
    return [example(), read_json(FIXTURES / "documents" / f"{WAIVER}.json")]


@pytest.fixture(scope="module")
def ontology() -> dict:
    return read_json(CATALOG / "ontology.json")


@pytest.fixture(scope="module")
def validation() -> dict:
    return read_json(FIXTURES / "validation.json")


@pytest.fixture(scope="module")
def pages(ontology: dict, validation: dict) -> dict:
    return render_semantic_pages(_documents(), validation=validation, ontology=ontology)


@pytest.fixture(scope="module")
def plain() -> dict:
    return render_semantic_pages(_documents())


def _golden(directory: Path, pages: dict) -> None:
    for name, body in pages.items():
        assert body == (directory / name).read_text(encoding="utf-8"), name
    on_disk = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
    assert on_disk == set(pages)


def _section(page: str, title: str) -> str:
    return page.split(f"\n## {title}\n", 1)[1].split("\n## ", 1)[0]


def _row(text: str, first_cell: str) -> str:
    rows = [line for line in text.splitlines() if line.startswith(f"| {first_cell}")]
    assert len(rows) == 1, f"expected one row starting {first_cell!r}, got {rows}"
    return rows[0]


# ------------------------------------------------------------------ the set


def test_the_golden_pages_with_ontology_and_validation(pages: dict) -> None:
    _golden(FIXTURES / "pages", pages)


def test_the_golden_pages_without_optional_inputs(plain: dict) -> None:
    _golden(FIXTURES / "plain", plain)


def test_one_page_per_table_and_an_index(plain: dict) -> None:
    assert set(plain) == {"index.md", f"{DEMO_TABLE}.md", f"{WAIVER}.md"}


def test_a_page_has_the_sample_layout(pages: dict, plain: dict) -> None:
    for page in plain.values():
        if page.startswith("# 表语义目录"):
            continue
        assert re.findall(r"^## (.+)$", page, flags=re.MULTILINE) == SECTIONS
    assert re.findall(r"^## (.+)$", pages[f"{WAIVER}.md"], flags=re.MULTILINE) == [
        *SECTIONS, "校验"
    ]


def test_the_summary_answers_the_nine_questions_in_order(plain: dict) -> None:
    summary = _section(plain[f"{WAIVER}.md"], "一页纸")
    labels = re.findall(r"^\*\*(.+?)\*\*：", summary, flags=re.MULTILINE)
    assert labels == SUMMARY_LABELS


def test_documents_of_another_format_are_refused() -> None:
    with pytest.raises(ValueError, match="table-semantics/1"):
        render_semantic_pages([{"doc_format": "table-semantics-packet/1"}])


# ------------------------------------------------------------------ header


def test_the_header_names_table_domain_concept_and_confirmed_count(pages: dict) -> None:
    lines = pages[f"{WAIVER}.md"].splitlines()
    assert lines[0] == f"# {WAIVER}"
    assert lines[2] == (
        "域：催收 · 本表是[豁免](../concepts/fee_waiver.md)的事件明细表 · "
        "本页 3 项已确认，✓ 表示已确认 · 校验通过率 93.8%（4 项未通过，见文末「校验」）"
    )


def test_without_an_ontology_the_database_stands_in_for_the_domain(plain: dict) -> None:
    lines = plain[f"{DEMO_TABLE}.md"].splitlines()
    assert lines[2] == (
        "库：demo_dwd · 本表是 `concept:customer` 的核心表 · 本页 0 项已确认，✓ 表示已确认"
    )


def test_a_concept_link_points_at_a_page_catalog_render_writes(pages: dict) -> None:
    for name, page in pages.items():
        for target in re.findall(r"\]\(\.\./(concepts/[^)]+)\)", page):
            assert (CATALOG / "pages" / target).is_file(), (name, target)


def test_the_ontology_wins_over_the_documents_own_concept(ontology: dict) -> None:
    document = example()
    document["concept"] = {"concept": "concept:loan", "representation_kind": "summary"}
    page = render_semantic_pages([document], ontology=ontology)[f"{DEMO_TABLE}.md"]
    assert "本表是[客户](../concepts/customer.md)的核心表" in page


# ------------------------------------------------------------------ summary


def test_the_row_statement_carries_grain_uniqueness_and_its_watch(plain: dict) -> None:
    summary = _section(plain[f"{WAIVER}.md"], "一页纸")
    line = next(x for x in summary.splitlines() if x.startswith("**一行是什么**"))
    assert "粒度按 `waiver_seq`，来源为推断，**不能保证唯一**" in line
    assert line.endswith("⚠ 两类序号可能撞号")


def test_refresh_says_how_to_read(plain: dict) -> None:
    summary = _section(plain[f"{DEMO_TABLE}.md"], "一页纸")
    assert "**更新与取数**：每天跑一次，每个分区是一份**全量快照**。取某一天的客户用" in summary


def test_scope_items_cite_their_rules_and_show_watch(plain: dict) -> None:
    summary = _section(plain[f"{WAIVER}.md"], "一页纸")
    assert "- 两类都要能在产品表里找到产品，否则整行不进表。（规则 r3） ⚠ 产品表没有按生效日期过滤" in summary


def test_upstream_is_a_table_of_roles(plain: dict) -> None:
    summary = _section(plain[f"{WAIVER}.md"], "一页纸")
    assert _row(summary, "`demo_ods.ods_loan_account_df`") == (
        "| `demo_ods.ods_loan_account_df`（补充字段） | 线下豁免的客户号与借据号补充 |"
    )


def test_questions_show_their_answer_once_confirmed(plain: dict) -> None:
    summary = _section(plain[f"{WAIVER}.md"], "一页纸")
    assert (
        "1. 处理状态 1 是不是「成功」？（q1） ✓ 回答：是，1 表示成功。（demo-reviewer，2026-09-26）"
    ) in summary
    assert "2. 豁免类型实际存的是字母码还是数字码？（q2）" in summary


# ------------------------------------------------------------------ fields


def test_fields_are_grouped_like_the_sample(plain: dict) -> None:
    fields = _section(plain[f"{WAIVER}.md"], "字段")
    assert re.findall(r"^### (.+)$", fields, flags=re.MULTILINE) == [
        "标识与关联", "状态与码值", "金额", "时间", "描述与技术列"
    ]
    assert "| 字段 | 含义 | 码值 | 口径 | 来源 |" in fields
    assert "描述与技术列\n\n`remark` 备注（取交易主表的备注）；技术列 `etl_time` 装载时间" in fields


def test_branches_are_spelt_out_and_watch_shows_a_warning(plain: dict) -> None:
    fields = _section(plain[f"{WAIVER}.md"], "字段")
    assert _row(fields, "`loan_no`") == (
        "| `loan_no` | 借据号 | 线上：取借据号；线下：取贷款账号 ⚠ 两者不完全等同 | SQL + 注释（中置信） |"
    )


def test_a_column_named_by_the_summary_watch_is_flagged(plain: dict) -> None:
    fields = _section(plain[f"{WAIVER}.md"], "字段")
    assert "⚠ 表注释与 SQL 注释给了两套码值" in _row(fields, "`waiver_type`")


def test_code_values_show_confirmed_and_unconfirmed_meanings(plain: dict) -> None:
    fields = _section(plain[f"{WAIVER}.md"], "字段")
    assert "INT 利息、PEN 罚息、2（含义待确认）、3（含义待确认）" in _row(fields, "`waiver_type`")
    assert "0 申请、1 成功 ✓、2 失败、9（含义待确认）" in _row(fields, "`waiver_status`")


def test_a_confirmed_meaning_is_ticked(plain: dict) -> None:
    fields = _section(plain[f"{WAIVER}.md"], "字段")
    assert _row(fields, "`customer_id`").startswith("| `customer_id` | 客户号 ✓ |")


def test_a_unit_follows_the_meaning(plain: dict) -> None:
    fields = _section(plain[f"{WAIVER}.md"], "字段")
    assert _row(fields, "`waive_amt`").startswith("| `waive_amt` | 豁免金额（元） |")


# ------------------------------------------------------------------ process and rules


def test_the_process_names_the_task_and_its_steps(plain: dict) -> None:
    process = _section(plain[f"{DEMO_TABLE}.md"], "加工过程")
    assert "**产出任务**：`dwd_party_customer_info_daily`（每天）：每天从核心系统" in process
    assert "\n1. 取核心系统客户注册表当天分区的记录。\n" in process


def test_rules_quote_their_sql_with_pipes_escaped(plain: dict) -> None:
    rules = _section(plain[f"{WAIVER}.md"], "规则（原文）")
    assert _row(rules, "r3 关联") == (
        "| r3 关联 | 找不到产品的交易不进表 ⚠ 没有按生效日期过滤 "
        "| `INNER JOIN demo_ods.ods_product_main_df p ON t.prod_cd = p.prod_cd` |"
    )
    assert "`COALESCE(reduce_amt, 0) \\|\\| ''`" in _row(rules, "r5 派生")


def test_the_sources_note_names_the_prompt_and_packet(plain: dict) -> None:
    note = _section(plain[f"{WAIVER}.md"], "来源说明")
    assert "table-semantics-prompt@2（hand-written fixture）" in note
    assert "0f1e2d3c4b5a6978" in note


# ------------------------------------------------------------------ validation


def test_failed_items_are_marked_where_they_stand(pages: dict) -> None:
    page = pages[f"{WAIVER}.md"]
    assert _row(_section(page, "字段"), "`loan_no` ✗1").startswith("| `loan_no` ✗1 | 借据号 |")
    assert _row(_section(page, "规则（原文）"), "r5 派生 ✗3")
    assert "| `demo_ods.ods_product_main_df`（过滤） ✗4 |" in _section(page, "一页纸")


def test_the_validation_section_lists_every_failure_and_warning(pages: dict) -> None:
    section = _section(pages[f"{WAIVER}.md"], "校验")
    assert section.startswith("\n通过率 93.8%：64 项检查，4 项未通过、2 项警告。")
    assert _row(section, "✗2") == (
        "| ✗2 | 未通过 | 5 规则 | `rules` | 过滤 record_status = 0（dwd_collection_fee_waiver_daily）"
        "没有被任何 rules[].sql 引用；补一条 filter 规则（照抄 SQL 原文），并在 summary.scope 里用 "
        "rule_refs 引用它 |"
    )
    assert len([line for line in section.splitlines() if line.startswith("| — | 警告 |")]) == 2


def test_a_clean_table_says_so(pages: dict) -> None:
    section = _section(pages[f"{DEMO_TABLE}.md"], "校验")
    assert section.strip() == "通过率 100.0%：52 项检查全部通过。"


def test_a_table_missing_from_the_report_says_so(validation: dict) -> None:
    report = copy.deepcopy(validation)
    report["tables"] = report["tables"][:1]
    page = render_semantic_pages([example()], validation=report)[f"{DEMO_TABLE}.md"]
    assert _section(page, "校验").strip() == "校验报告里没有这张表。"


def test_without_a_report_nothing_is_marked(plain: dict) -> None:
    for page in plain.values():
        assert "✗" not in page
        assert "\n## 校验\n" not in page


# ------------------------------------------------------------------ index


def test_the_index_groups_tables_by_domain_and_by_concept(pages: dict) -> None:
    index = pages["index.md"]
    assert re.findall(r"^### (.+)$", index, flags=re.MULTILINE) == [
        "催收", "客户与账户", "[客户](../concepts/customer.md)", "[豁免](../concepts/fee_waiver.md)"
    ]
    row = _row(_section(index, "按域"), f"[`{WAIVER}`]({WAIVER}.md)")
    assert row.endswith("| 93.8% | 2 |")
    assert row.startswith(f"| [`{WAIVER}`]({WAIVER}.md) | 借据上发生的每一笔豁免")


def test_the_plain_index_groups_by_database(plain: dict) -> None:
    index = plain["index.md"]
    assert re.findall(r"^### (.+)$", index, flags=re.MULTILINE) == [
        "库 demo_dwd", "`concept:customer`", "`concept:fee_waiver`"
    ]
    assert _row(index, f"[`{DEMO_TABLE}`]({DEMO_TABLE}.md) | 客户主表").endswith("| — | 1 |")


def test_a_table_without_a_concept_is_listed_apart(plain: dict) -> None:
    document = example()
    del document["concept"]
    index = render_semantic_pages([document])["index.md"]
    assert "### 未关联概念" in index


# ------------------------------------------------------------------ command line


def _catalog_pages(tmp_path: Path) -> Path:
    out = tmp_path / "site"
    assert run("catalog", "render", CATALOG / "ontology.json", "--out", out) == 0
    return out


def test_render_end_to_end_after_validate(tmp_path: Path, capsys) -> None:
    packets = demo_packets(tmp_path / "work")
    documents = tmp_path / "docs"
    write_json(documents / f"{DEMO_TABLE}.json", example(packets))
    shutil.copy(CONFIRMATIONS, documents / "confirmations.json")
    capsys.readouterr()
    assert run("semantic", "validate", documents, "--packets", packets, "--json") == 0
    report = write_json(tmp_path / "report.json", json.loads(capsys.readouterr().out))
    site = _catalog_pages(tmp_path)
    out = site / "semantics"

    code = run(
        "semantic", "render", documents, "--out", out,
        "--validation", report, "--ontology", CATALOG / "ontology.json",
    )

    assert code == 0
    assert sorted(p.name for p in out.iterdir()) == [f"{DEMO_TABLE}.md", "index.md"]
    page = (out / f"{DEMO_TABLE}.md").read_text(encoding="utf-8")
    assert "校验通过率 100.0%" in page
    target = re.search(r"\]\((\.\./concepts/customer\.md)\)", page).group(1)
    assert (out / target).resolve().is_file()


def test_a_failed_check_from_validate_reaches_the_page(tmp_path: Path, capsys) -> None:
    packets = demo_packets(tmp_path / "work")
    document = example(packets)
    document["rules"][0]["sql"] = "WHERE dt = 'yesterday'"
    documents = tmp_path / "docs"
    write_json(documents / f"{DEMO_TABLE}.json", document)
    capsys.readouterr()
    run("semantic", "validate", documents, "--packets", packets, "--json")
    report = write_json(tmp_path / "report.json", json.loads(capsys.readouterr().out))

    assert run("semantic", "render", documents, "--out", tmp_path / "out", "--validation", report) == 0

    page = (tmp_path / "out" / f"{DEMO_TABLE}.md").read_text(encoding="utf-8")
    assert "| r1 过滤 ✗" in page
    assert "| 未通过 | 5 规则 | `rules[0].sql` |" in page


def test_confirmed_items_are_ticked_after_confirm(tmp_path: Path) -> None:
    documents = write_json(tmp_path / "docs" / f"{DEMO_TABLE}.json", example()).parent
    assert run("semantic", "confirm", documents, "--confirmations", CONFIRMATIONS) == 0
    assert run("semantic", "render", documents, "--out", tmp_path / "out") == 0

    page = (tmp_path / "out" / f"{DEMO_TABLE}.md").read_text(encoding="utf-8")
    assert "本页 6 项已确认" in page
    assert "| `verify_status` | 实名认证状态 ✓ |" in page
    assert "F 女 ✓、M 男 ✓、U 未知 ✓" in page
    assert "回答：不会。注册系统只允许 F、M、U 三个值。（demo-reviewer，2026-09-26）" in page


def test_a_document_failing_its_schema_is_skipped_with_exit_1(tmp_path: Path, capsys) -> None:
    documents = tmp_path / "docs"
    write_json(documents / f"{DEMO_TABLE}.json", example())
    broken = example()
    broken["table"] = "demo_dwd.broken_df"
    del broken["summary"]["what"]
    write_json(documents / "broken.json", broken)
    shutil.copy(CONFIRMATIONS, documents / "confirmations.json")

    assert run("semantic", "render", documents, "--out", tmp_path / "out") == 1

    assert "broken.json" in capsys.readouterr().err
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == [f"{DEMO_TABLE}.md", "index.md"]


def test_a_validation_file_of_another_format_is_refused(tmp_path: Path) -> None:
    documents = write_json(tmp_path / "docs" / f"{DEMO_TABLE}.json", example()).parent
    code = run(
        "semantic", "render", documents, "--out", tmp_path / "out", "--validation", CONFIRMATIONS
    )
    assert code == 1
    assert not (tmp_path / "out").exists()


# ------------------------------------------------------------------ catalog render --semantics


def test_catalog_render_without_semantics_is_unchanged(tmp_path: Path) -> None:
    site = _catalog_pages(tmp_path)
    _golden(CATALOG / "pages", {
        p.relative_to(site).as_posix(): p.read_text(encoding="utf-8")
        for p in site.rglob("*") if p.is_file()
    })
    document = read_json(CATALOG / "ontology.json")
    assert render_catalog_pages(document, semantic_pages={}) == render_catalog_pages(document)


def test_concept_pages_link_each_table_to_its_semantics_page(tmp_path: Path) -> None:
    site = tmp_path / "site"
    pages = render_semantic_pages(_documents())
    for name, body in pages.items():
        (site / "semantics").mkdir(parents=True, exist_ok=True)
        (site / "semantics" / name).write_text(body, encoding="utf-8")

    code = run(
        "catalog", "render", CATALOG / "ontology.json", "--out", site,
        "--semantics", site / "semantics",
    )

    assert code == 0
    customer = (site / "concepts" / "customer.md").read_text(encoding="utf-8")
    link = f"[`{DEMO_TABLE}`](../semantics/{DEMO_TABLE}.md)"
    overview = customer.split("\n## 附录\n")[0]
    inventory = customer.split("### A2 数据清单")[1].split("\n### A3 ")[0]
    assert f"- {link}（Customer master, one row per …） ✓" in overview
    assert f"| {link} |" in inventory
    assert f"[`{WAIVER}`](../semantics/{WAIVER}.md)" in (
        site / "concepts" / "fee_waiver.md"
    ).read_text(encoding="utf-8")
    for target in re.findall(r"\]\((\.\./semantics/[^)]+)\)", customer):
        assert (site / "concepts" / target).resolve().is_file()
    loan = (site / "concepts" / "loan.md").read_text(encoding="utf-8")
    assert loan == (CATALOG / "pages" / "concepts" / "loan.md").read_text(encoding="utf-8")
