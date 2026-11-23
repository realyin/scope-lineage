"""Which tables a constraint comes from, and what that means for the table it is listed under.

A constraint is drafted from the table-semantics rules of one or more tables (``rules``,
``<db.table>#rN``) or cites tables in its ``evidence`` and expression. ``constraint_tables``
is the one judgement every reader shares: a table is a source when ``rules`` names it or
when the rule citation ``catalog query table`` has always used accepts it (the union), so
no reader drops a constraint it listed before.

Under a table, ``catalog context`` splits its concept's constraints by how each source
relates to that table in the catalog's lineage evidence: this table's own, an upstream
table's (the condition may already be carried in -- or may not apply, when the table is
only joined for extra fields), a downstream table's (not done here), or a table with no
lineage relation. A constraint on an attribute the table binds no column to is counted,
not listed. Without lineage evidence only "this table" and "other tables" are told apart.

Every case runs on the recorded demo ontology, changed where a case needs it.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scope_lineage.render.catalog_concept_page import render_concept_page
from scope_lineage.render.catalog_context import (
    CONTEXT_FORMAT,
    context_pack,
    render_context_text,
)
from scope_lineage.render.catalog_query import query_catalog, render_query_text
from scope_lineage.render.catalog_scopes import RULE_KINDS, constraint_tables
from scope_lineage.render.catalog_view import CatalogView

ONTOLOGY = Path(__file__).parent / "fixtures" / "catalog" / "ontology.json"
LOAN = "demo_dwd.dwd_lending_loan_df"
HISTORY = "demo_dwd.dwd_lending_loan_status_his"
SUMMARY = "demo_dws.dws_lending_loan_summary_1d"
BORROWER = "demo_dwd.dwd_lending_borrower_df"
WAIVER = "demo_dwd.dwd_collection_fee_waiver_di"
REPAYMENT = "demo_dwd.dwd_lending_repayment_di"
CUSTOMER = "demo_dwd.dwd_party_customer_info_df"
CUSTOMER_EXT = "demo_dwd.dwd_party_customer_ext_df"

UPSTREAM_HEAD = "- 约束（上游表的规则带出）"
DOWNSTREAM_HEAD = "- 约束（下游表的规则带出）"
UNRELATED_HEAD = "- 约束（与本表没有血缘关系的表的规则带出）"
OWN_HEAD = "- 约束（本表的规则带出）"
OTHER_HEAD = "- 约束（其他表的规则带出）"


@pytest.fixture(scope="module")
def document() -> dict:
    return json.loads(ONTOLOGY.read_text(encoding="utf-8"))


def _constraint(cid: str, on: str, rules=(), evidence=(), kind="business_rule") -> dict:
    return {
        "id": cid, "kind": kind, "on": on, "expression": f"expression of {cid}",
        "strength": "soft", "status": "drafted", "source": "sql",
        "evidence": list(evidence), **({"rules": list(rules)} if rules else {}),
    }


def _with(document: dict, *constraints: dict) -> dict:
    changed = copy.deepcopy(document)
    changed["constraints"] = changed["constraints"] + list(constraints)
    return changed


def _table(document: dict, table: str, **options) -> dict:
    (entry,) = context_pack(document, None, tables=[table], **options)["tables"]
    return entry


def _by_id(entry: dict) -> dict:
    return {c["id"]: c for c in entry["constraints"]}


def _text(document: dict, table: str) -> str:
    return render_context_text(context_pack(document, None, tables=[table]))


# ------------------------------------------------------------ the judgement


def test_the_sources_are_the_tables_rules_name_or_the_citation_accepts(document: dict) -> None:
    view = CatalogView(document)
    named = _constraint("cons:x", "concept:loan", rules=[f"{SUMMARY}#r1"], evidence=[LOAN])
    assert constraint_tables(view, named) == [LOAN, SUMMARY]


def test_without_rules_the_evidence_decides(document: dict) -> None:
    """The fallback branch: no ``rules``, the evidence (or expression) names the table."""
    view = CatalogView(document)
    cited = _constraint("cons:x", "concept:loan", evidence=[f"{LOAN}.principal_amt"])
    assert constraint_tables(view, cited) == [LOAN]


def test_a_rule_names_its_table_whatever_the_case_and_prefix(document: dict) -> None:
    view = CatalogView(document)
    cited = _constraint("cons:x", "concept:loan", rules=[f"hive.{LOAN.upper()}#r2"])
    assert constraint_tables(view, cited) == [LOAN]


def test_a_constraint_naming_nothing_has_no_source(document: dict) -> None:
    view = CatalogView(document)
    assert constraint_tables(view, _constraint("cons:x", "concept:loan")) == []


def test_query_table_lists_a_rule_its_rules_name_and_keeps_those_the_evidence_cites(
    document: dict,
) -> None:
    changed = _with(document, _constraint("cons:by_rule", "concept:loan", rules=[f"{LOAN}#r1"]))
    (match,) = query_catalog(changed, "table", LOAN)["matches"]
    assert [c["id"] for c in match["constraints"]] == ["cons:by_rule", "cons:principal_positive"]
    (customer,) = query_catalog(changed, "table", CUSTOMER)["matches"]
    assert [c["id"] for c in customer["constraints"]] == ["cons:active_customers_only"]


def test_query_table_and_the_packs_own_segment_name_the_same_rules(document: dict) -> None:
    changed = _with(
        document,
        _constraint("cons:by_rule", "concept:loan", rules=[f"{LOAN}#r1"]),
        _constraint("cons:by_other", "concept:loan", rules=[f"{SUMMARY}#r1"]),
        _constraint("cons:unique_here", "concept:loan", rules=[f"{LOAN}#r2"], kind="unique"),
    )
    (match,) = query_catalog(changed, "table", LOAN)["matches"]
    own = {
        c["id"] for c in _table(changed, LOAN)["constraints"]
        if c.get("relation") == "this_table" and c["kind"] in RULE_KINDS
    }
    assert own == {c["id"] for c in match["constraints"]} == {"cons:by_rule", "cons:principal_positive"}


# ------------------------------------------------------------- the segments


def test_a_constraint_from_this_tables_rules_is_its_own(document: dict) -> None:
    entry = _table(document, LOAN)
    principal = _by_id(entry)["cons:principal_positive"]
    assert principal["relation"] == "this_table"
    assert principal["tables"] == [LOAN]
    text = _text(document, LOAN)
    assert OWN_HEAD in text
    assert "  - 约束 cons:principal_positive（value_domain，针对 本金）：principal > 0" in text


def test_a_constraint_from_an_upstream_table_says_both_cases(document: dict) -> None:
    changed = _with(document, _constraint("cons:from_loan", "concept:loan", rules=[f"{LOAN}#r1"]))
    found = _by_id(_table(changed, SUMMARY))["cons:from_loan"]
    assert found["relation"] == "upstream"
    assert found["tables"] == [LOAN]
    text = _text(changed, SUMMARY)
    head = next(line for line in text.splitlines() if line.startswith(UPSTREAM_HEAD))
    assert "条件已经带进来" in head and "不适用" in head and "分不出" in head
    assert f"  - 约束 cons:from_loan（business_rule，针对 借据；来源 {LOAN}）" in text


def test_an_upstream_table_counts_through_catalog_tables(document: dict) -> None:
    """Transitive: the loan table feeds the borrower table, which (here) feeds the history."""
    changed = _with(document, _constraint("cons:from_loan", "concept:loan", rules=[f"{LOAN}#r1"]))
    reps = changed["evidence"]["representations"]
    reps.setdefault(HISTORY, {})["upstream_tables"] = [BORROWER]
    reps[BORROWER]["downstream_tables"] = sorted(reps[BORROWER]["downstream_tables"] + [HISTORY])
    assert _by_id(_table(changed, HISTORY))["cons:from_loan"]["relation"] == "upstream"


def test_an_upstream_chain_through_a_table_outside_the_catalog_does_not_count(
    document: dict,
) -> None:
    changed = _with(document, _constraint("cons:from_loan", "concept:loan", rules=[f"{LOAN}#r1"]))
    reps = changed["evidence"]["representations"]
    reps.setdefault(HISTORY, {})["upstream_tables"] = ["demo_ads.ads_collection_overdue_loan_df"]
    assert _by_id(_table(changed, HISTORY))["cons:from_loan"]["relation"] == "unrelated"


def test_uniqueness_from_upstream_is_not_said_to_carry_over(document: dict) -> None:
    changed = _with(
        document,
        _constraint("cons:one_per_key", "concept:loan", rules=[f"{LOAN}#r2"], kind="unique"),
    )
    assert _by_id(_table(changed, SUMMARY))["cons:one_per_key"]["relation"] == "upstream"
    text = _text(changed, SUMMARY)
    assert "  - 上游的唯一性在本表不一定还成立：本表的粒度可能与上游不同" in text
    unique_at = text.index("上游的唯一性")
    assert text.index("cons:one_per_key") > unique_at


def test_a_constraint_from_a_downstream_table_is_not_done_here(document: dict) -> None:
    changed = _with(document, _constraint("cons:from_summary", "concept:loan", rules=[f"{SUMMARY}#r1"]))
    found = _by_id(_table(changed, LOAN))["cons:from_summary"]
    assert found["relation"] == "downstream"
    text = _text(changed, LOAN)
    head = next(line for line in text.splitlines() if line.startswith(DOWNSTREAM_HEAD))
    assert "本表没有做" in head


def test_a_constraint_from_a_table_with_no_lineage_relation_is_unknown(document: dict) -> None:
    changed = _with(document, _constraint("cons:from_loan", "concept:loan", rules=[f"{LOAN}#r1"]))
    assert _by_id(_table(changed, HISTORY))["cons:from_loan"]["relation"] == "unrelated"
    text = _text(changed, HISTORY)
    head = next(line for line in text.splitlines() if line.startswith(UNRELATED_HEAD))
    assert "不知道" in head


def test_a_table_both_upstream_and_downstream_goes_upstream_with_a_note(document: dict) -> None:
    changed = _with(document, _constraint("cons:from_loan", "concept:loan", rules=[f"{LOAN}#r1"]))
    reps = changed["evidence"]["representations"]
    reps[SUMMARY]["downstream_tables"] = [LOAN]
    found = _by_id(_table(changed, SUMMARY))["cons:from_loan"]
    assert found["relation"] == "upstream"
    assert found["also_downstream"] == [LOAN]
    assert f"{LOAN} 也读本表" in _text(changed, SUMMARY)


def test_sources_on_both_sides_go_upstream_naming_the_reader(document: dict) -> None:
    """One source upstream (the loan table), another reading this table (here, the summary)."""
    changed = _with(
        document,
        _constraint("cons:two_sides", "concept:customer", rules=[f"{LOAN}#r1", f"{SUMMARY}#r1"]),
    )
    found = _by_id(_table(changed, CUSTOMER))["cons:two_sides"]
    assert found["relation"] == "downstream"
    reps = changed["evidence"]["representations"]
    reps[CUSTOMER]["upstream_tables"] = sorted(reps[CUSTOMER]["upstream_tables"] + [LOAN])
    found = _by_id(_table(changed, CUSTOMER))["cons:two_sides"]
    assert found["relation"] == "upstream"
    assert found["also_downstream"] == [SUMMARY]


def test_this_tables_rules_win_over_other_sources(document: dict) -> None:
    """Nearest neighbour: a rule naming this table and an upstream one stays this table's."""
    changed = _with(
        document, _constraint("cons:both", "concept:loan", rules=[f"{LOAN}#r1", f"{SUMMARY}#r1"])
    )
    found = _by_id(_table(changed, SUMMARY))["cons:both"]
    assert found["relation"] == "this_table"
    assert found["tables"] == [LOAN, SUMMARY]


def test_a_constraint_on_an_attribute_the_table_has_no_column_for_is_counted(
    document: dict,
) -> None:
    """The summary table binds no principal column: the loan table's rule on it is counted."""
    entry = _table(document, SUMMARY)
    assert "cons:principal_positive" not in _by_id(entry)
    assert entry["constraints_unbound"] == {"upstream": 1}
    text = _text(document, SUMMARY)
    assert "cons:principal_positive" not in text
    assert "  - 另有 1 条约束针对本表没有绑定列的属性，未列出" in text


def test_without_lineage_evidence_only_this_table_and_others_are_told_apart(
    document: dict,
) -> None:
    changed = _with(document, _constraint("cons:from_loan", "concept:loan", rules=[f"{LOAN}#r1"]))
    changed["evidence"]["inputs"].pop("lineage")
    for entry in changed["evidence"]["representations"].values():
        entry.pop("upstream_tables", None)
        entry.pop("downstream_tables", None)
    assert _by_id(_table(changed, SUMMARY))["cons:from_loan"]["relation"] == "other_table"
    text = _text(changed, SUMMARY)
    assert OTHER_HEAD in text
    assert "上游" not in text and "下游" not in text


def test_the_json_names_each_source_and_keeps_its_format(document: dict) -> None:
    pack = context_pack(document, None, tables=[LOAN])
    assert pack["doc_format"] == CONTEXT_FORMAT == "catalog-context/1"
    (entry,) = pack["tables"]
    assert all(set(c) >= {"tables", "relation"} for c in entry["constraints"] if c.get("tables"))


# ----------------------------------------------------------- what stays put


def test_a_constraint_naming_no_table_is_listed_as_before(document: dict) -> None:
    entry = _table(document, REPAYMENT)
    found = _by_id(entry)["cons:repaid_after_disbursed"]
    assert set(found) == {"id", "kind", "on", "expression", "strength"}
    text = _text(document, REPAYMENT)
    assert (
        "- 约束 cons:repaid_after_disbursed（temporal，针对 还款）："
        "repaid_at is not earlier than the disbursed_at of every loan"
    ) in text
    for head in (OWN_HEAD, UPSTREAM_HEAD, DOWNSTREAM_HEAD, UNRELATED_HEAD, OTHER_HEAD):
        assert head not in text


def test_a_single_table_concept_has_only_its_own_segment(document: dict) -> None:
    changed = _with(
        document, _constraint("cons:waiver_rule", "concept:fee_waiver", rules=[f"{WAIVER}#r1"])
    )
    text = _text(changed, WAIVER)
    assert OWN_HEAD in text
    for head in (UPSTREAM_HEAD, DOWNSTREAM_HEAD, UNRELATED_HEAD, OTHER_HEAD):
        assert head not in text
    assert "条件已经带进来" not in text and "本表没有做" not in text and "不知道" not in text


def test_evidence_alone_still_places_a_constraint(document: dict) -> None:
    """The demo rule cites the customer table in its evidence only (no ``rules``)."""
    assert _by_id(_table(document, CUSTOMER))["cons:active_customers_only"]["relation"] == (
        "this_table"
    )
    assert _by_id(_table(document, CUSTOMER_EXT))["cons:active_customers_only"]["relation"] == (
        "unrelated"
    )


def test_brief_and_focus_leave_the_constraints_alone(document: dict) -> None:
    full = _table(document, SUMMARY)
    assert _table(document, SUMMARY, brief=True)["constraints"] == full["constraints"]
    assert _table(document, SUMMARY, brief=True)["constraints_unbound"] == full["constraints_unbound"]


# ------------------------------------------------------- concept and page


def test_a_concept_pack_names_each_constraints_sources(document: dict) -> None:
    pack = context_pack(document, None, concepts=["concept:loan"])
    (concept,) = pack["concepts"]
    found = {c["id"]: c for c in concept["constraints"]}
    assert found["cons:principal_positive"]["tables"] == [LOAN]
    assert "tables" not in found["cons:penalty_rule"]
    text = render_context_text(pack)
    assert f"- 约束 cons:principal_positive（value_domain，针对 本金；来源 {LOAN}）" in text


def test_the_concept_page_names_each_constraints_sources(document: dict) -> None:
    page = render_concept_page(CatalogView(document), "concept:loan")
    (row,) = [line for line in page.splitlines() if line.startswith("| `cons:principal_positive`")]
    assert f"来源表：`{LOAN}`" in row
    (row,) = [line for line in page.splitlines() if line.startswith("| `cons:penalty_rule`")]
    assert "来源表" not in row


def test_query_table_text_is_unchanged_in_form(document: dict) -> None:
    text = render_query_text(query_catalog(document, "table", LOAN))
    assert "  规则：cons:principal_positive（值域）principal > 0" in text
