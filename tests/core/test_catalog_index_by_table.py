"""``catalog render`` index: what to look at before using the catalog, and a row per table.

The gap summary leads the index, with two fixed sentences: the page states what the
catalog has and lacks structurally (whether answers are right is for acceptance), and
question answering uses the built catalog file together with the table-semantics
documents. Given the table-semantics documents (``--docs``), the summary gains two rows
-- unique keys with lineage evidence, and measure attributes whose unit the material
supports -- and a table per catalog table follows it, ordered by name. Without the
documents the index is what it was, the summary moved to the top.

The documents here are invented for the demo catalog; each number below is counted by
hand from them and the demo's lineage evidence.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scope_lineage.catalog import build_ontology, load_catalog
from scope_lineage.cli import main
from scope_lineage.render.catalog_context import context_pack, render_context_text
from scope_lineage.render.catalog_pages import render_catalog_pages
from scope_lineage.render.catalog_units import (
    SUPPORTED,
    UNJUDGED,
    UNSUPPORTED,
    unit_support,
)
from scope_lineage.render.catalog_view import CatalogView

from .catalog_demo import DEMO

FIXTURES = Path(__file__).parent / "fixtures"
ONTOLOGY = FIXTURES / "catalog" / "ontology.json"
# index.md of the demo as rendered before the summary moved to the top
BEFORE = FIXTURES / "catalog-index-before-move.md"

WAIVER = "demo_dwd.dwd_collection_fee_waiver_di"
BORROWER = "demo_dwd.dwd_lending_borrower_df"
LOAN = "demo_dwd.dwd_lending_loan_df"
HISTORY = "demo_dwd.dwd_lending_loan_status_his"
REPAYMENT = "demo_dwd.dwd_lending_repayment_di"
ACCOUNT = "demo_dwd.dwd_party_account_map_df"
EXTENSION = "demo_dwd.dwd_party_customer_ext_df"
CUSTOMER = "demo_dwd.dwd_party_customer_info_df"
SUMMARY = "demo_dws.dws_lending_loan_summary_1d"
ALL_TABLES = (WAIVER, BORROWER, LOAN, HISTORY, REPAYMENT, ACCOUNT, EXTENSION, CUSTOMER, SUMMARY)

HEADING = "## 用之前先看"
STRUCTURE_ONLY = "本页只说明目录在结构上有什么、缺什么；答得对不对要靠验收。"
ANSWERING_USES = "问数用的是构建出的目录文件，加上表语义文档目录。"
BY_TABLE = "## 按表看"
KEY_ROW = "唯一键有血缘证据的表"
UNIT_ROW = "单位有材料依据的度量属性"


def _doc(table: str, unique: str = "unknown", watch=(), columns=()) -> dict:
    """A table-semantics document carrying only what the index reads."""
    return {
        "doc_format": "table-semantics/1",
        "table": table,
        "summary": {
            "row": {"unique": unique},
            "watch": [{"kind": kind, "text": f"note {i}"} for i, kind in enumerate(watch)],
        },
        "columns": [
            {"column": name, "category": "measure", **({"unit": unit} if unit else {})}
            for name, unit in columns
        ],
    }


# The demo's measure attributes and the columns bound to them: principal (loan
# principal_amt), overdue penalty (loan penalty_amt), repayment amount (repay_amt),
# credit limit (borrower credit_limit), waiver amount (waive_amt); the disbursement amount
# is bound to no column. Lineage proves the key of the borrower, repayment, account map,
# customer and summary tables.
DOCS = {
    LOAN: _doc(LOAN, "yes", ["risk"], [("principal_amt", "元"), ("penalty_amt", None)]),
    REPAYMENT: _doc(REPAYMENT, "unknown", [], [("repay_amt", None)]),
    BORROWER: _doc(BORROWER, "yes", [], [("credit_limit", "元")]),
    WAIVER: _doc(WAIVER, "unknown", ["conflict", "coverage", "conflict"], [("waive_amt", None)]),
    CUSTOMER: _doc(CUSTOMER, "no", ["conflict", "risk"]),
    HISTORY: _doc(HISTORY),
    ACCOUNT: _doc(ACCOUNT, "yes"),
    EXTENSION: _doc(EXTENSION),
    SUMMARY: _doc(SUMMARY, "yes"),
}
PARTIAL = {table: DOCS[table] for table in (LOAN, REPAYMENT, CUSTOMER)}


@pytest.fixture(scope="module")
def document() -> dict:
    """The demo built with lineage and table-card evidence (the golden)."""
    return json.loads(ONTOLOGY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def plain() -> dict:
    """The demo built without any evidence."""
    return build_ontology(load_catalog(DEMO))


def _index(document: dict, docs=None, links=None) -> str:
    return render_catalog_pages(document, links, docs)["index.md"]


def _section(page: str, heading: str) -> str:
    """From ``heading`` up to the next ``## `` heading."""
    return (heading + page.split(heading, 1)[1].split("\n## ", 1)[0]).rstrip("\n")


def _row(page: str, first_cell: str) -> str:
    rows = [line for line in page.splitlines() if line.startswith(f"| {first_cell} ")]
    assert len(rows) == 1, f"expected one row starting {first_cell!r}, got {rows}"
    return rows[0]


def _cells(row: str) -> list[str]:
    return [cell.strip() for cell in row.strip("|").split(" | ")]


def _by_table(page: str) -> dict[str, list[str]]:
    """``table -> cells`` of the by-table table, the table cell's markup dropped."""
    rows = [line for line in _section(page, BY_TABLE).splitlines() if line.startswith("| ")]
    head, rule, *body = rows
    assert set(_cells(rule)) == {"---"}
    found = {}
    for row in body:
        cells = _cells(row)
        found[cells[0].split("`")[1]] = cells
    return {"head": _cells(head), **found}


# ------------------------------------------------------------- the summary first


def test_the_summary_comes_before_the_concepts(document: dict) -> None:
    page = _index(document)
    assert page.index(HEADING) < page.index("## 概念")
    assert "## 治理缺口" not in page
    assert page.index("| 未绑定列 | 1 |") < page.index("## 概念")


def test_the_summary_says_what_the_page_is_and_what_answering_uses(document: dict) -> None:
    for docs in (None, DOCS):
        summary = _section(_index(document, docs), HEADING)
        assert f"{HEADING}\n\n{STRUCTURE_ONLY}\n\n{ANSWERING_USES}\n\n| 缺口 | 数量 |" in summary


def test_without_documents_only_the_summarys_place_and_two_sentences_change(
    document: dict,
) -> None:
    """Undo the move on today's page and it is the page as it was rendered before."""
    page = _index(document)
    summary = _section(page, HEADING)
    rest = page.replace(summary + "\n\n", "", 1)
    old_summary = summary.replace(HEADING, "## 治理缺口", 1).replace(
        f"{STRUCTURE_ONLY}\n\n{ANSWERING_USES}\n\n", "", 1
    )
    restored = rest.replace("## 记录范围与有效性", f"{old_summary}\n\n## 记录范围与有效性", 1)
    assert restored == BEFORE.read_text(encoding="utf-8")
    assert KEY_ROW not in page and UNIT_ROW not in page and BY_TABLE not in page


def test_with_documents_only_the_new_rows_and_the_table_are_added(document: dict) -> None:
    without, with_docs = _index(document), _index(document, DOCS)
    added = _section(with_docs, BY_TABLE)
    stripped = with_docs.replace(added + "\n\n", "", 1)
    stripped = "\n".join(
        line for line in stripped.split("\n")
        if not line.startswith((f"| {KEY_ROW} ", f"| {UNIT_ROW} "))
    )
    assert stripped == without


# ------------------------------------------------------------- the two new rows


def test_the_key_row_counts_proven_keys_and_those_the_documents_call_not_unique(
    document: dict,
) -> None:
    assert _row(_index(document, DOCS), KEY_ROW) == f"| {KEY_ROW} | 5/9；其中表语义说不唯一的 1 张 |"


def test_the_unit_row_counts_measure_attributes_the_material_supports(document: dict) -> None:
    assert _row(_index(document, DOCS), UNIT_ROW) == (
        f"| {UNIT_ROW} | 2/5；另有 1 个没法判断（所绑的列没有一列被表语义描述） |"
    )


# ------------------------------------------------------------- the by-table table


def test_the_table_has_one_row_per_table_in_name_order(document: dict) -> None:
    page = _index(document, DOCS)
    body = [
        line for line in _section(page, BY_TABLE).splitlines()[1:] if line.startswith("| ")
    ][2:]
    assert [line.split("`")[1] for line in body] == sorted(ALL_TABLES)
    assert page.index(BY_TABLE) < page.index("## 概念")


def test_the_table_columns(document: dict) -> None:
    rows = _by_table(_index(document, DOCS))
    assert rows["head"] == [
        "表", "概念", "唯一键的证据", "表语义的说法", "度量列", "其中单位无材料依据",
        "未绑定列", "注意事项",
    ]
    assert rows[LOAN] == [
        f"`{LOAN}`", "[借据](concepts/loan.md)", "无", "唯一", "2", "1/2（50%）", "0",
        "1（与材料矛盾 0）",
    ]
    assert rows[REPAYMENT][2:] == ["已证明", "未知", "1", "1/1（100%）", "0", "0"]
    assert rows[BORROWER][2:] == ["已证明", "唯一", "1", "0/1（0%）", "0", "0"]
    assert rows[WAIVER][2:] == ["无", "未知", "1", "1/1（100%）", "0", "3（与材料矛盾 2）"]
    assert rows[EXTENSION][2:] == ["无", "未知", "0", "0", "1", "0"]
    assert rows[HISTORY][1] == "[借据](concepts/loan.md)"


def test_proven_by_lineage_while_the_document_says_not_unique_shows_both(
    document: dict,
) -> None:
    rows = _by_table(_index(document, DOCS))
    assert rows[CUSTOMER][1:4] == ["[客户](concepts/customer.md)", "已证明", "不唯一"]
    assert rows[CUSTOMER][-1] == "2（与材料矛盾 1）"


def test_a_table_links_to_its_semantics_page_from_the_index(document: dict) -> None:
    links = {LOAN: f"../semantics/{LOAN}.md"}
    rows = _by_table(_index(document, DOCS, links))
    assert rows[LOAN][0] == f"[`{LOAN}`](semantics/{LOAN}.md)"
    assert rows[REPAYMENT][0] == f"`{REPAYMENT}`"


def test_the_unmapped_columns_add_up_to_the_summary(document: dict) -> None:
    page = _index(document, DOCS)
    rows = _by_table(page)
    total = sum(int(cells[6]) for table, cells in rows.items() if table != "head")
    assert _row(page, "未绑定列") == f"| 未绑定列 | {total} |"


def test_units_not_supported_add_up_to_the_context_packs_marks(document: dict) -> None:
    """Every table and every column asked of the context pack marks the same columns."""
    rows = _by_table(_index(document, DOCS))
    on_page = sum(int(cells[5].split("/")[0]) for table, cells in rows.items() if table != "head")
    view = CatalogView(document)
    columns = [
        f"{rep['table']}.{binding['column']}"
        for rep in view.representations.values() for binding in rep["bindings"]
    ]
    pack = context_pack(document, DOCS, columns=columns)
    marked = [c for c in pack["columns"] if (c["catalog"] or {}).get("material_unit") == {"given": False}]
    text = render_context_text(pack)
    lines = [line for line in text.splitlines() if line.startswith("  - 单位：") and "材料未给" in line]
    assert on_page == len(marked) == len(lines) == 3


# ------------------------------------------------------------- missing inputs


def test_without_lineage_evidence_the_key_columns_and_row_are_not_shown(plain: dict) -> None:
    page = _index(plain, DOCS)
    assert KEY_ROW not in page
    rows = _by_table(page)
    assert rows["head"] == ["表", "概念", "度量列", "其中单位无材料依据", "未绑定列", "注意事项"]
    assert rows[LOAN][1:] == ["[借据](concepts/loan.md)", "2", "1/2（50%）", "0", "1（与材料矛盾 0）"]
    assert _row(page, UNIT_ROW) == (
        f"| {UNIT_ROW} | 2/5；另有 1 个没法判断（所绑的列没有一列被表语义描述） |"
    )


def test_without_documents_nothing_depending_on_them_is_shown(
    document: dict, plain: dict
) -> None:
    for built in (document, plain):
        page = _index(built)
        assert KEY_ROW not in page and UNIT_ROW not in page and BY_TABLE not in page
        assert "0/" not in _section(page, HEADING).replace("43/123", "")


def test_documents_for_some_tables_leave_the_others_dashed_and_say_so(document: dict) -> None:
    page = _index(document, PARTIAL)
    rows = _by_table(page)
    assert rows[BORROWER][2:] == ["已证明", "—", "1", "—", "0", "—"]
    assert rows[LOAN][2:] == ["无", "唯一", "2", "1/2（50%）", "0", "1（与材料矛盾 0）"]
    assert _row(page, KEY_ROW) == (
        f"| {KEY_ROW} | 5/9；其中表语义说不唯一的 1 张（只数表语义覆盖到的 3 张表） |"
    )
    assert _row(page, UNIT_ROW) == (
        f"| {UNIT_ROW} | 1/3；另有 3 个没法判断（所绑的列没有一列被表语义描述） |"
    )
    assert "表语义只覆盖 3/9 张表；没覆盖到的表，依赖表语义的格子显示「—」。" in _section(page, BY_TABLE)


# ------------------------------------------------------------- the unit rule


def test_the_unit_rule_has_three_outcomes(document: dict) -> None:
    view = CatalogView(document)
    measure = {a["id"]: a for a, _ in view.attributes.values()}
    material = {table.lower(): doc for table, doc in DOCS.items()}

    supported = unit_support(view, measure["attr:loan.principal"], material)
    assert supported is not None and supported.outcome == SUPPORTED
    assert supported.units == ("元",)
    unsupported = unit_support(view, measure["attr:loan.overdue_penalty"], material)
    assert unsupported is not None and unsupported.outcome == UNSUPPORTED
    unjudged = unit_support(view, measure["attr:disbursement.amount"], material)
    assert unjudged is not None and unjudged.outcome == UNJUDGED
    assert unit_support(view, measure["attr:borrower.credit_limit"], {}).outcome == UNJUDGED
    assert unit_support(view, measure["attr:loan.loan_status"], material) is None


def _pack_digest(document: dict, docs) -> str:
    view = CatalogView(document)
    columns = [
        f"{rep['table']}.{binding['column']}"
        for rep in view.representations.values() for binding in rep["bindings"]
    ]
    metric = copy.deepcopy(document)
    metric["metrics"] = [{
        "id": "metric:repaid_amount", "name": "还款金额", "definition": "把各笔还款的金额加总。",
        "on": "concept:repayment", "measure": "attr:repayment.amount", "aggregation": "sum",
        "constraints": [], "dimensions": [], "additivity": "additive", "unit": "元",
        "status": "drafted", "source": "sql", "evidence": [],
    }]
    packs = [
        context_pack(document, docs, columns=columns),
        context_pack(document, docs, tables=list(ALL_TABLES)),
        context_pack(metric, docs, concepts=sorted(view.concepts) + ["metric:repaid_amount"]),
    ]
    blob = "".join(
        json.dumps(pack, ensure_ascii=False, sort_keys=True) + render_context_text(pack)
        for pack in packs
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def test_the_context_pack_is_unchanged_by_sharing_the_unit_rule(document: dict) -> None:
    """Pinned before the unit rule moved out of the context pack: JSON and text alike.

    A deliberate change to the context pack updates these digests.
    """
    assert _pack_digest(document, DOCS) == PACK_DIGEST
    assert _pack_digest(document, PARTIAL) == PARTIAL_PACK_DIGEST


PACK_DIGEST = "cadce1c4e98728b0a02c9014bb854b0a796603a7aa5301bcac9d2a4e9cf9f4ec"
PARTIAL_PACK_DIGEST = "98d00c8a7cb49764c6c17530ec4f91b56bd705c22e84a72a6d7d1cff25e5add5"


# ------------------------------------------------------------- the command


def test_render_reads_the_documents_directory(document: dict, tmp_path: Path) -> None:
    source = tmp_path / "ontology.json"
    source.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    for table, doc in DOCS.items():
        (docs / f"{table}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "pages"

    assert main(["catalog", "render", str(source), "--out", str(out), "--docs", str(docs)]) == 0
    assert (out / "index.md").read_text(encoding="utf-8") == _index(document, DOCS)


def test_render_refuses_a_documents_directory_that_does_not_exist(
    document: dict, tmp_path: Path, capsys
) -> None:
    source = tmp_path / "ontology.json"
    source.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    args = ["catalog", "render", str(source), "--out", str(tmp_path / "out")]
    assert main([*args, "--docs", str(tmp_path / "nope")]) == 2
    assert "--docs directory does not exist" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()
