"""The ``notes`` of a metric and of an attribute reach the agent asking about them.

The drafting prompts record in ``notes`` what decides how a measure may be summed (which
keys to take one row per in which table) and other cautions. ``catalog context`` prints a
metric's ``notes`` in its entry and a bound attribute's ``notes`` in a column's full answer;
``catalog query attribute`` prints the attribute's. An answer whose item has no notes is
byte-identical to what it was. The sentence leaving the unit to the owner is not repeated
where the answer already says the unit is not given by the material (``material_unit``).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scope_lineage.render.catalog_context import context_pack, render_context_text
from scope_lineage.render.catalog_query import query_catalog, render_query_text

ONTOLOGY = Path(__file__).parent / "fixtures" / "catalog" / "ontology.json"
LOAN = "demo_dwd.dwd_lending_loan_df"
REPAYMENT = "demo_dwd.dwd_lending_repayment_di"
NOTE = "在 demo_dwd.dwd_lending_loan_df 里同 loan_no 的多行带同一个值，按 loan_no 每组取一行后再加"
UNIT = "待 owner 确认：单位"
METRIC = {
    "id": "metric:repaid_amount", "name": "还款金额", "definition": "把各笔还款的金额加总。",
    "on": "concept:repayment", "measure": "attr:repayment.amount", "aggregation": "sum",
    "constraints": [], "dimensions": [], "additivity": "additive", "unit": "元",
    "status": "drafted", "source": "sql", "evidence": [],
}


@pytest.fixture(scope="module")
def document() -> dict:
    return json.loads(ONTOLOGY.read_text(encoding="utf-8"))


def _attribute(document: dict, attribute_id: str) -> dict:
    return next(a for c in document["concepts"] for a in c.get("attributes") or []
                if a["id"] == attribute_id)


def _with_notes(document: dict, attribute_notes=None, metric_notes=None) -> dict:
    changed = copy.deepcopy(document)
    changed["metrics"] = [dict(METRIC, **({"notes": metric_notes} if metric_notes else {}))]
    if attribute_notes:
        _attribute(changed, "attr:loan.principal")["notes"] = attribute_notes
        _attribute(changed, "attr:repayment.amount")["notes"] = attribute_notes
    return changed


def _column(document: dict, term: str, semantics=None) -> tuple[dict, str]:
    pack = context_pack(document, semantics, columns=[term])
    return pack["columns"][0], render_context_text(pack)


def _concept(document: dict) -> tuple[dict, str]:
    pack = context_pack(document, None, concepts=["metric:repaid_amount"])
    return pack["concepts"][0]["metrics"][0], render_context_text(pack)


def test_a_metric_entry_carries_its_notes(document: dict) -> None:
    metric, text = _concept(_with_notes(document, metric_notes=NOTE))
    assert metric["notes"] == NOTE
    assert f"  - 备注：{NOTE}" in text


def test_a_columns_full_answer_carries_its_attributes_notes(document: dict) -> None:
    answer, text = _column(_with_notes(document, attribute_notes=NOTE), f"{LOAN}.principal_amt")
    assert answer["catalog"]["notes"] == NOTE
    assert f"  - 备注：{NOTE}" in text


def test_query_attribute_carries_its_notes(document: dict) -> None:
    result = query_catalog(_with_notes(document, attribute_notes=NOTE), "attribute", "attr:loan.principal")
    assert result["matches"][0]["notes"] == NOTE
    assert f"  备注：{NOTE}" in render_query_text(result)


def test_answers_without_notes_are_byte_identical(document: dict) -> None:
    plain = _with_notes(document)
    for build in (
        lambda d: render_context_text(context_pack(d, None, concepts=["metric:repaid_amount"])),
        lambda d: json.dumps(context_pack(d, None, concepts=["metric:repaid_amount"]), ensure_ascii=False),
        lambda d: render_context_text(context_pack(d, None, columns=[f"{LOAN}.principal_amt"])),
        lambda d: json.dumps(context_pack(d, None, columns=[f"{LOAN}.principal_amt"]), ensure_ascii=False),
        lambda d: render_query_text(query_catalog(d, "attribute", "attr:loan.principal")),
    ):
        text = build(plain)
        assert "备注" not in text and '"notes"' not in text


def test_brief_keeps_a_metrics_notes(document: dict) -> None:
    changed = _with_notes(document, metric_notes=NOTE)
    pack = context_pack(changed, None, concepts=["metric:repaid_amount"], tables=[REPAYMENT], brief=True)
    assert pack["concepts"][0]["metrics"][0]["notes"] == NOTE


def test_the_unit_sentence_is_not_repeated_beside_a_unit_mark(document: dict) -> None:
    """With semantics that give no unit, the unit line already says 材料未给; the notes keep
    their other sentences and drop the one that says the same."""
    changed = _with_notes(document, attribute_notes=f"{UNIT}。按借据号每组取一行")
    _attribute(changed, "attr:repayment.amount").pop("unit", None)
    semantics = {REPAYMENT: {"table": REPAYMENT, "columns": [
        {"column": "repay_amt", "meaning": "还款金额", "category": "measure"},
    ]}}
    answer, text = _column(changed, f"{REPAYMENT}.repay_amt", semantics)
    assert answer["catalog"]["material_unit"] == {"given": False}
    assert answer["catalog"]["notes"] == "按借据号每组取一行"
    assert UNIT not in text
    plain, plain_text = _column(changed, f"{REPAYMENT}.repay_amt")
    assert plain["catalog"]["notes"] == f"{UNIT}。按借据号每组取一行"


def test_notes_that_are_only_the_unit_sentence_vanish_beside_a_unit_mark(document: dict) -> None:
    changed = _with_notes(document, attribute_notes=UNIT)
    _attribute(changed, "attr:repayment.amount").pop("unit", None)
    semantics = {REPAYMENT: {"table": REPAYMENT, "columns": [
        {"column": "repay_amt", "meaning": "还款金额", "category": "measure"},
    ]}}
    answer, text = _column(changed, f"{REPAYMENT}.repay_amt", semantics)
    assert "notes" not in answer["catalog"]
    assert "备注" not in text
