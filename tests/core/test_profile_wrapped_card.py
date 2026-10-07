"""A JOIN onto a row subset of a carded table reads the card too (G5a step 2).

``LEFT JOIN dim.item d`` was decided from the table card; the same table wrapped in
``(SELECT * FROM dim.item WHERE attr IS NOT NULL) d`` fell through to 「右侧未被证明按
连接键唯一」, because only a physical right side looked at a card. A WHERE drops rows and
never makes a unique key repeat, so a right side that is one table's rows -- filters
only, the join columns passed through unchanged -- is answered from that table's card.

A MERGE writes the batch it proved unique into a table that keeps every other row, so
its key says nothing about the table: the card's appending-producer defeater answers
``unknown``, never ``safe`` (now that M1 gives a MERGE producer a key).

Every fixture is synthetic.
"""

from __future__ import annotations

from scope_lineage import build_semantic_profile
from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.render.table_cards import build_table_cards
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {
    "ods.item_src": ["item_id", "attr", "ts"],
    "dim.item": ["item_id", "attr"],
    "ods.ev": ["item_id", "n"],
    "dw.out": ["item_id", "attr", "n"],
}

GROUPED_PRODUCER = (
    "INSERT OVERWRITE TABLE dim.item SELECT item_id, max(attr) AS attr FROM ods.item_src"
    " GROUP BY item_id"
)

MERGE_PRODUCER = (
    "MERGE INTO dim.item tgt USING (SELECT item_id, attr FROM (SELECT item_id, attr,"
    " row_number() OVER (PARTITION BY item_id ORDER BY ts DESC) rn FROM ods.item_src) a"
    " WHERE a.rn = 1) src ON tgt.item_id = src.item_id"
    " WHEN MATCHED THEN UPDATE SET tgt.attr = src.attr WHEN NOT MATCHED THEN INSERT *"
)

UNKEYED_PRODUCER = "INSERT OVERWRITE TABLE dim.item SELECT item_id, attr FROM ods.item_src"


def _profile(sql: str, task: str) -> dict:
    return build_semantic_profile(to_lineage_dict(parse_scope_lineage(sql, task, schema=SCHEMA)))


def _risk(producer: str, right: str) -> dict:
    cards = build_table_cards([_profile(producer, "p")])
    sql = (
        "INSERT OVERWRITE TABLE dw.out SELECT e.item_id, d.attr, e.n FROM ods.ev e"
        f" LEFT JOIN {right} d ON e.item_id = d.item_id"
    )
    document = to_lineage_dict(parse_scope_lineage(sql, "c", schema=SCHEMA))
    (risk,) = build_semantic_profile(document, table_cards=cards)["output_shape"]["fan_out_risks"]
    return risk


def test_a_row_subset_of_a_carded_table_is_decided_by_the_card():
    risk = _risk(GROUPED_PRODUCER, "(SELECT * FROM dim.item WHERE attr IS NOT NULL)")
    assert risk["status"] == "safe"
    assert risk["basis"] == "table_card"
    assert "表卡" in risk["reason"]


def test_the_physical_table_itself_is_unchanged():
    risk = _risk(GROUPED_PRODUCER, "dim.item")
    assert risk["status"] == "safe" and risk["basis"] == "table_card"


def test_a_card_without_a_key_leaves_the_subset_at_risk():
    risk = _risk(UNKEYED_PRODUCER, "(SELECT * FROM dim.item WHERE attr IS NOT NULL)")
    assert risk["status"] == "risk"
    assert "basis" not in risk


def test_a_renamed_join_column_is_not_the_card_s_column():
    risk = _risk(
        GROUPED_PRODUCER,
        "(SELECT attr AS item_id, attr FROM dim.item WHERE attr IS NOT NULL)",
    )
    assert risk["status"] == "risk"
    assert "basis" not in risk


def test_a_merge_producer_s_proven_batch_key_gives_unknown_not_safe():
    producer = _profile(MERGE_PRODUCER, "p")
    assert producer["output_shape"]["key_confidence"] == "proven"
    risk = _risk(MERGE_PRODUCER, "(SELECT * FROM dim.item WHERE attr IS NOT NULL)")
    assert risk["status"] == "unknown"
    assert risk["basis"] == "table_card"
    assert "追加或合并" in risk["reason"]
