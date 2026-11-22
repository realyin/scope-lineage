"""A JOIN with no usable key pair onto a carded table says so (audit verify-D 4.1-3).

``LEFT JOIN dim.item d ON e.item_id = d.item_id OR e.alt_id = d.item_id`` leaves the
contract with no join key pair. When the table card proves ``dim.item`` one row per
``item_id``, the verdict stays ``unknown`` -- nothing in this ON clause pins a key --
but the reason said 「物理表无主键事实」, which the card contradicts. The reason now names
what is actually missing: this JOIN's key. Only the text changes.

Every fixture is synthetic.
"""

from __future__ import annotations

from scope_lineage import build_semantic_profile
from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.render.table_cards import build_table_cards
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {
    "ods.item_src": ["item_id", "attr"],
    "dim.item": ["item_id", "attr"],
    "ods.ev": ["item_id", "alt_id", "n"],
    "dw.out": ["item_id", "attr", "n"],
}

GROUPED_PRODUCER = (
    "INSERT OVERWRITE TABLE dim.item SELECT item_id, max(attr) AS attr FROM ods.item_src"
    " GROUP BY item_id"
)

NO_KEY_PAIR = "e.item_id = d.item_id OR e.alt_id = d.item_id"
NO_PRIMARY_KEY_FACT = "物理表无主键事实"
NO_JOIN_KEY = "该 JOIN 无可证明的连接键，右侧唯一性无从判定"


def _risk(on: str, *, carded: bool) -> dict:
    cards = None
    if carded:
        producer = to_lineage_dict(parse_scope_lineage(GROUPED_PRODUCER, "p", schema=SCHEMA))
        cards = build_table_cards([build_semantic_profile(producer)])
    sql = (
        "INSERT OVERWRITE TABLE dw.out SELECT e.item_id, d.attr, e.n FROM ods.ev e"
        f" LEFT JOIN dim.item d ON {on}"
    )
    document = to_lineage_dict(parse_scope_lineage(sql, "c", schema=SCHEMA))
    profile = build_semantic_profile(document, table_cards=cards)
    (risk,) = profile["output_shape"]["fan_out_risks"]
    return risk


def test_a_carded_table_joined_without_a_key_pair_names_the_missing_join_key():
    risk = _risk(NO_KEY_PAIR, carded=True)

    assert risk["status"] == "unknown"
    assert risk["reason"] == NO_JOIN_KEY


def test_without_a_card_the_physical_table_reason_is_unchanged():
    """Sentinel: with no card there is indeed no key fact for the table."""
    risk = _risk(NO_KEY_PAIR, carded=False)

    assert risk["status"] == "unknown"
    assert risk["reason"] == NO_PRIMARY_KEY_FACT


def test_a_carded_table_joined_on_its_key_is_still_safe():
    """Sentinel: the card still decides a JOIN whose key pair covers its key."""
    risk = _risk("e.item_id = d.item_id", carded=True)

    assert risk["status"] == "safe"
    assert risk["basis"] == "table_card"


def test_a_carded_table_joined_on_another_column_is_unchanged():
    """Sentinel: a key pair that misses the card's key keeps the old reason."""
    risk = _risk("e.n = d.attr", carded=True)

    assert risk["status"] == "unknown"
    assert risk["reason"] == NO_PRIMARY_KEY_FACT
