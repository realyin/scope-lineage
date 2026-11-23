"""The JOINs the corpus showed, under one join column of a table's context pack.

The evidence ``catalog build`` attaches is per relation: a count and up to three sample
JOINs, a JOIN inside a producing task naming the column it fills. A join column used to get
every sample of every relation it might realise -- a column naming no ``relation`` is
credited to each parallel relation between the same two concepts, so one JOIN came out once
a relation, and a relation's samples about other tables' columns came out under this one.
The pack now keeps the samples that involve this column, and one entry for the same
evidence however many relations carry it (``relations`` names them). Its count is the
column's own from the build's ``by_column``; a document built before that, whose samples
were cut short, says which JOINs are not recorded instead of dropping them.

``--brief`` lists every sample that involves a catalog table, and folds those whose two
tables are both outside the catalog into one counting line (``seen_outside_catalog``).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scope_lineage.render.catalog_context import context_pack, render_context_text

ONTOLOGY = Path(__file__).parent / "fixtures" / "catalog" / "ontology.json"
LOAN = "demo_dwd.dwd_lending_loan_df"
REPAYMENT = "demo_dwd.dwd_lending_repayment_di"
BORROWER = "demo_dwd.dwd_lending_borrower_df"
RELATION = "rel:repayment.loan"
PARALLEL = "rel:repayment.loan_again"
CATALOG_SAMPLE = f"{LOAN}.loan_no = {REPAYMENT}.loan_no"
SOURCE_SAMPLE = f"demo_ods.ods_repay_txn_di.loan_no = {LOAN}.loan_no"
OUTSIDE_SAMPLE = "demo_ods.ods_repay_txn_di.loan_no = demo_ods.ods_loan_contract_df.loan_no"


@pytest.fixture(scope="module")
def document() -> dict:
    return json.loads(ONTOLOGY.read_text(encoding="utf-8"))


def _loan_join(document: dict, **options) -> dict:
    (entry,) = context_pack(document, None, tables=[REPAYMENT], **options)["tables"]
    (join,) = [join for join in entry["joins"] if join["column"] == "loan_no"]
    return join


def _text(document: dict, **options) -> str:
    return render_context_text(context_pack(document, None, tables=[REPAYMENT], **options))


def _with_parallel_relation(document: dict) -> dict:
    """A second relation between the two concepts, carrying the same evidence: the
    repayment's ``loan_no`` names no ``relation``, so it may realise either."""
    changed = copy.deepcopy(document)
    first = next(r for r in changed["relations"] if r["id"] == RELATION)
    changed["relations"].append({**first, "id": PARALLEL, "name": "again"})
    evidence = changed["evidence"]["relations"]
    evidence[PARALLEL] = copy.deepcopy(evidence[RELATION])
    return changed


def _source_samples(document: dict, *samples: dict, count: int) -> dict:
    changed = copy.deepcopy(document)
    joins = changed["evidence"]["relations"][RELATION]["source_joins"]
    joins["samples"] = joins["samples"] + list(samples)
    joins["count"] = count
    return changed


def _sample(column: str, on: str) -> dict:
    return {"task": "t_other", "statement_id": "stmt:001", "column": column, "on": on}


# --------------------------------------------------------------- one column


def test_evidence_parallel_relations_share_is_listed_once(document: dict) -> None:
    join = _loan_join(_with_parallel_relation(document))
    assert [(seen["where"], seen["relations"]) for seen in join["seen"]] == [
        ("between_catalog_tables", [RELATION, PARALLEL]),
        ("inside_producing_task", [RELATION, PARALLEL]),
    ]
    text = _text(_with_parallel_relation(document))
    assert text.count(f"：{SOURCE_SAMPLE}") == 1
    assert text.count(f"：{CATALOG_SAMPLE}") == 1


def test_a_sample_filling_another_tables_column_is_not_listed(document: dict) -> None:
    other = _sample(f"{LOAN}.orig_loan_no", "demo_ods.ods_loan_contract_df.orig_no = demo_ods.x.no")
    join = _loan_join(_source_samples(document, other, count=2))
    (inside,) = [seen for seen in join["seen"] if seen["where"] == "inside_producing_task"]
    assert inside["on"] == [SOURCE_SAMPLE]
    assert inside["count"] == 1
    assert "demo_ods.x.no" not in _text(_source_samples(document, other, count=2))


def test_a_join_between_catalog_tables_on_another_column_is_not_listed(document: dict) -> None:
    changed = copy.deepcopy(document)
    joins = changed["evidence"]["relations"][RELATION]["joins"]
    joins["samples"].append({
        "task": "t_other", "statement_id": "stmt:002",
        "on": f"{BORROWER}.customer_id = {REPAYMENT}.customer_id",
    })
    joins["count"] = 2
    (between,) = [s for s in _loan_join(changed)["seen"] if s["where"] == "between_catalog_tables"]
    assert between["on"] == [CATALOG_SAMPLE]
    assert between["count"] == 1


def _old_build(document: dict) -> dict:
    """The document as a build before per-column counts wrote it."""
    changed = copy.deepcopy(document)
    for entry in changed["evidence"]["relations"].values():
        for joins in entry.values():
            joins.pop("by_column", None)
    return changed


def test_complete_samples_without_column_counts_read_as_before(document: dict) -> None:
    """Every JOIN of the relation is sampled, so the samples are the whole record."""
    old = _old_build(document)
    assert _loan_join(old)["seen"] == _loan_join(document)["seen"]
    other = _sample(f"{LOAN}.orig_loan_no", "demo_ods.ods_loan_contract_df.orig_no = demo_ods.x.no")
    join = _loan_join(_source_samples(old, other, count=2))
    (inside,) = [seen for seen in join["seen"] if seen["where"] == "inside_producing_task"]
    assert inside == {
        "relation": RELATION, "where": "inside_producing_task", "count": 1, "on": [SOURCE_SAMPLE],
    }


def test_truncated_samples_none_of_them_this_columns_say_so(document: dict) -> None:
    """An older build kept three samples of five, all about another column: whether this
    column is among the other two is not recorded, and the pack says that, not nothing."""
    other = _sample(f"{LOAN}.orig_loan_no", "demo_ods.a.k = demo_ods.b.k")
    changed = _old_build(document)
    joins = changed["evidence"]["relations"][RELATION]["source_joins"]
    joins["samples"] = [other, other, other]
    joins["count"] = 5
    (inside,) = [s for s in _loan_join(changed)["seen"] if s["where"] == "inside_producing_task"]
    assert inside["count"] == 0 and inside["on"] == []
    assert inside["unsampled"] == 2 and inside["relation_count"] == 5
    text = _text(changed)
    assert (
        "  - 产出任务内部见过 5 次连接，留下的样例都是别的列的，其余 2 次是否涉及本列没有记录"
        "（重新 build 可知）"
    ) in text
    assert "（重新 build 可知）" in _text(changed, brief=True)


def test_truncated_samples_some_of_them_this_columns_count_what_is_known(document: dict) -> None:
    same = _sample(f"{REPAYMENT}.loan_no", SOURCE_SAMPLE.replace("ods_repay_txn_di", "ods_repay_adj_di"))
    join = _loan_join(_source_samples(_old_build(document), same, count=5))
    (inside,) = [seen for seen in join["seen"] if seen["where"] == "inside_producing_task"]
    assert inside["count"] == 2 and len(inside["on"]) == 2
    assert inside["unsampled"] == 3
    assert "；另有 3 次没留样例，是否涉及本列没有记录（重新 build 可知）" in _text(
        _source_samples(_old_build(document), same, count=5)
    )


def test_column_counts_give_the_exact_count_even_without_a_sample(document: dict) -> None:
    other = _sample(f"{LOAN}.orig_loan_no", "demo_ods.a.k = demo_ods.b.k")
    changed = copy.deepcopy(document)
    joins = changed["evidence"]["relations"][RELATION]["source_joins"]
    joins.update(count=10, samples=[other, other, other], by_column={
        f"{LOAN}.orig_loan_no": 3, f"{REPAYMENT}.loan_no": 7,
    })
    (inside,) = [s for s in _loan_join(changed)["seen"] if s["where"] == "inside_producing_task"]
    assert inside == {"relation": RELATION, "where": "inside_producing_task", "count": 7, "on": []}
    assert "  - 语料中见过 7 次（产出任务内部），没有留下样例\n" in _text(changed)


def test_column_counts_with_a_sample_count_this_column_only(document: dict) -> None:
    other = _sample(f"{LOAN}.orig_loan_no", "demo_ods.a.k = demo_ods.b.k")
    changed = _source_samples(document, other, count=6)
    changed["evidence"]["relations"][RELATION]["source_joins"]["by_column"] = {
        f"{LOAN}.orig_loan_no": 2, f"{REPAYMENT}.loan_no": 4,
    }
    (inside,) = [s for s in _loan_join(changed)["seen"] if s["where"] == "inside_producing_task"]
    assert inside["count"] == 4 and inside["on"] == [SOURCE_SAMPLE]
    assert "unsampled" not in inside


def test_a_column_the_counts_do_not_name_gets_no_line(document: dict) -> None:
    changed = copy.deepcopy(document)
    changed["evidence"]["relations"][RELATION]["source_joins"]["by_column"] = {f"{LOAN}.x": 1}
    assert [s["where"] for s in _loan_join(changed)["seen"]] == ["between_catalog_tables"]


def test_the_demo_self_reference_no_longer_borrows_the_key_columns_joins(document: dict) -> None:
    """The loan's ``orig_loan_no`` holds the loan's own key and names no relation, so it was
    credited with every relation of the loan's concept; none of their samples is about it."""
    (entry,) = context_pack(document, None, tables=[LOAN])["tables"]
    (orig,) = [join for join in entry["joins"] if join["column"] == "orig_loan_no"]
    assert orig["seen"] == []
    assert "rel:repayment.loan" not in render_context_text(
        context_pack(document, None, tables=[LOAN])
    )


def test_the_full_pack_is_unchanged_where_nothing_was_wrong(document: dict) -> None:
    assert _loan_join(document)["seen"] == [
        {"relation": RELATION, "where": "between_catalog_tables", "count": 1, "on": [CATALOG_SAMPLE]},
        {"relation": RELATION, "where": "inside_producing_task", "count": 1, "on": [SOURCE_SAMPLE]},
    ]


def test_a_join_column_with_no_evidence_prints_as_before(document: dict) -> None:
    (entry,) = context_pack(document, None, tables=[REPAYMENT])["tables"]
    (customer,) = [join for join in entry["joins"] if join["column"] == "customer_id"]
    assert customer["seen"] == []
    assert "seen_outside_catalog" not in customer


# -------------------------------------------------------------------- brief


def test_brief_folds_joins_between_tables_outside_the_catalog(document: dict) -> None:
    outside = _sample(f"{REPAYMENT}.loan_no", OUTSIDE_SAMPLE)
    changed = _source_samples(document, outside, count=2)
    full = _loan_join(changed)
    (inside,) = [seen for seen in full["seen"] if seen["where"] == "inside_producing_task"]
    assert inside["on"] == [SOURCE_SAMPLE, OUTSIDE_SAMPLE]
    assert "seen_outside_catalog" not in full
    brief = _loan_join(changed, brief=True)
    (inside,) = [seen for seen in brief["seen"] if seen["where"] == "inside_producing_task"]
    assert inside["on"] == [SOURCE_SAMPLE]
    assert brief["seen_outside_catalog"] == 1
    text = _text(changed, brief=True)
    assert OUTSIDE_SAMPLE not in text
    assert "  - 另有 1 条产出任务内部的连接证据两边的表都不在目录里，去掉 --brief 可看" in text
    assert OUTSIDE_SAMPLE in _text(changed)


def test_brief_drops_an_entry_with_only_outside_joins(document: dict) -> None:
    changed = copy.deepcopy(document)
    joins = changed["evidence"]["relations"][RELATION]["source_joins"]
    joins["samples"] = [_sample(f"{REPAYMENT}.loan_no", OUTSIDE_SAMPLE)]
    brief = _loan_join(changed, brief=True)
    assert [seen["where"] for seen in brief["seen"]] == ["between_catalog_tables"]
    assert brief["seen_outside_catalog"] == 1


def test_brief_always_lists_joins_involving_a_catalog_table(document: dict) -> None:
    assert _loan_join(document, brief=True)["seen"] == _loan_join(document)["seen"]
    assert f"：{SOURCE_SAMPLE}" in _text(document, brief=True)
