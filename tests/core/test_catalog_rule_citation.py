"""6.3-d: a rule's expression cites a table by the whole name, not by a substring.

``_cites`` tested ``table in expression``, so a rule about ``demo_x.t_order_refund`` was
also hung on ``demo_x.t_order`` in scopes.md and ``catalog query``.
"""

from __future__ import annotations

import pytest

from scope_lineage.render.catalog_scopes import _cites


def _rule(expression: str, evidence=()) -> dict:
    return {"id": "cons:r", "kind": "business_rule", "expression": expression, "evidence": list(evidence)}


RULE = _rule("demo_x.t_order_refund.refund_amt never exceeds the paid amount")


def test_a_longer_table_name_does_not_cite_its_prefix() -> None:
    assert not _cites(RULE, "demo_x.t_order")
    assert not _cites(_rule("see xdemo_x.t_order"), "demo_x.t_order")


@pytest.mark.parametrize(
    "expression",
    [
        "demo_x.t_order_refund.refund_amt never exceeds the paid amount",
        "demo_x.t_order_refund rows are refunds",
        "(demo_x.t_order_refund) only",
        "rows of `demo_x.t_order_refund`",
    ],
)
def test_the_whole_name_still_cites_the_table(expression: str) -> None:
    """Sentinel: the name alone, or followed by `.column`, still cites the table."""
    assert _cites(_rule(expression), "demo_x.t_order_refund")


def test_evidence_matching_is_unchanged() -> None:
    assert _cites(_rule("x", ["demo_x.t_order.amt"]), "demo_x.t_order")
    assert not _cites(_rule("x", ["demo_x.t_order_refund.amt"]), "demo_x.t_order")
