"""4.5-a: what a table card keeps of its producer's grain.

``_producer_entry`` kept only ``basis`` and ``keys`` of the producing statement's grain:

* ``evidence`` was dropped, so a consumer's ``grain_text`` for an upstream task that could
  not decide its grain always said 「结构未记录原因」 although the producer's own semantic
  document had the reason (a UNION, say);
* a logical key the SELECT never projected has ``name: null``, and ``str(None)`` wrote the
  literal ``None`` into tables.json, the card's markdown and every downstream sentence.
"""

from __future__ import annotations

from scope_lineage.contract.task_lineage import to_task_lineage_dict
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.render.table_cards import (
    apply_table_cards,
    build_table_cards,
    render_table_card_markdown,
)
from scope_lineage.scope.task_lineage import parse_task_lineage

UNION_PRODUCER = "INSERT OVERWRITE TABLE dw.u SELECT id, v FROM src.a UNION ALL SELECT id, v FROM src.b"
UNION_CONSUMER = "INSERT OVERWRITE TABLE dw.u_read SELECT id, v FROM dw.u"
UNPROJECTED_PRODUCER = "INSERT OVERWRITE TABLE dw.w SELECT max(v) AS v FROM src.a GROUP BY id, upper(k)"
UNPROJECTED_CONSUMER = "INSERT OVERWRITE TABLE dw.w_read SELECT v FROM dw.w"
NAMED_PRODUCER = "INSERT OVERWRITE TABLE dw.g SELECT id, max(v) AS v FROM src.a GROUP BY id"


def _profile(sql: str, task: str) -> dict:
    return build_semantic_profile(to_task_lineage_dict(parse_task_lineage(sql, task_name=task)))


def _card(cards: dict, table: str) -> dict:
    return next(item for item in cards["tables"] if item["table"] == table)


def _consumer_grain_text(producer_sql: str, consumer_sql: str) -> str:
    cards = build_table_cards([_profile(producer_sql, "p1"), _profile(consumer_sql, "c1")])
    enriched = apply_table_cards(_profile(consumer_sql, "c1"), cards)
    statement = (enriched.get("statements") or [enriched])[0]
    return statement["inputs"][0]["card"]["grain_text"]


def test_the_producer_s_reason_reaches_the_consumer_s_grain_text() -> None:
    text = _consumer_grain_text(UNION_PRODUCER, UNION_CONSUMER)
    assert text.startswith("生产任务 p1 未能判定粒度（")
    assert "UNION" in text
    assert "结构未记录原因" not in text


def test_tables_json_carries_the_grain_evidence() -> None:
    cards = build_table_cards([_profile(UNION_PRODUCER, "p1")])
    grain = _card(cards, "dw.u")["produced_by"][0]["grain"]
    assert grain["basis"] == "unknown"
    assert any("UNION" in item for item in grain["evidence"])


def test_an_unprojected_key_is_written_as_its_expression() -> None:
    cards = build_table_cards([_profile(UNPROJECTED_PRODUCER, "p1")])
    card = _card(cards, "dw.w")
    keys = card["produced_by"][0]["grain"]["keys"]
    assert "None" not in keys
    assert keys == ["`a`.`id`", "UPPER(`a`.`k`)"]
    assert "None" not in render_table_card_markdown(card)
    assert "None" not in _consumer_grain_text(UNPROJECTED_PRODUCER, UNPROJECTED_CONSUMER)


def test_a_projected_key_is_still_written_by_its_name() -> None:
    """Sentinel: the common case reads the same."""
    cards = build_table_cards([_profile(NAMED_PRODUCER, "p1")])
    grain = _card(cards, "dw.g")["produced_by"][0]["grain"]
    assert grain["basis"] == "group_by"
    assert grain["keys"] == ["id"]
