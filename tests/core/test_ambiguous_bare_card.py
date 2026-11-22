"""A bare table name two qualified tables could be borrows neither one's key (audit WP2d).

``dwd.orders`` and ``ods.orders`` are two tables; a consumer that reads a bare
``orders`` gets its own card, flagged ``ambiguous_bare_name``. The card lookup used to
walk the cards in order and take the first suffix match -- ``dwd.orders`` sorts first --
so the consumer's JOIN was proven safe by a producer of a table it may never read. Now
an exact ``table`` / ``aliases`` match wins, a suffix match that hits several cards
finds none, and a card flagged ``ambiguous_bare_name`` offers no key.

Every fixture is synthetic.
"""

from __future__ import annotations

from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.semantic_profile import (
    build_semantic_profile,
    card_key_claim,
    card_lookup,
)
from scope_lineage.render.table_cards import apply_table_cards, build_table_cards
from scope_lineage.scope.scope_builder import parse_scope_lineage

P1 = "INSERT OVERWRITE TABLE dwd.orders SELECT order_id, max(amt) AS amt FROM src.a GROUP BY order_id"
P2 = "INSERT INTO TABLE ods.orders SELECT order_id, amt FROM src.b"
CONS = (
    "INSERT OVERWRITE TABLE dw.t_out SELECT f.fid, o.amt FROM dw.fact f "
    "LEFT JOIN orders o ON f.order_id = o.order_id"
)


def _document(sql: str, task: str) -> dict:
    return to_lineage_dict(parse_scope_lineage(sql, task))


def _cards() -> dict:
    return build_table_cards(
        [
            build_semantic_profile(_document(P1, "p1")),
            build_semantic_profile(_document(P2, "p2")),
            build_semantic_profile(_document(CONS, "cons")),
        ]
    )


def _consumer() -> dict:
    cards = _cards()
    document = _document(CONS, "cons")
    return apply_table_cards(build_semantic_profile(document, table_cards=cards), cards)


def test_the_ambiguous_bare_input_carries_no_borrowed_proven_key() -> None:
    profile = _consumer()
    card = next(item for item in profile["inputs"] if item["table"] == "orders")["card"]
    assert not (card and card.get("key_confidence") == "proven")


def test_the_join_to_an_ambiguous_bare_table_is_not_safe() -> None:
    risks = _consumer()["output_shape"]["fan_out_risks"]
    assert [risk["status"] for risk in risks] != ["safe"]


def test_the_exact_card_wins_over_a_suffix_match() -> None:
    lookup = card_lookup(_cards())
    assert lookup("orders")["table"] == "orders"
    assert lookup("dwd.orders")["table"] == "dwd.orders"


def test_a_suffix_match_hitting_several_cards_finds_none() -> None:
    cards = {"tables": [c for c in _cards()["tables"] if c["table"] != "orders"]}
    assert card_lookup(cards)("orders") is None


def test_a_card_flagged_ambiguous_offers_no_key() -> None:
    producer = next(c for c in _cards()["tables"] if c["table"] == "dwd.orders")
    claim = card_key_claim(producer)
    assert claim is not None and claim.status == "proven"  # the premise
    flagged = {
        **producer,
        "findings": [{"kind": "ambiguous_bare_name", "text": "", "evidence": []}],
    }
    assert card_key_claim(flagged) is None


def test_sentinel_a_qualified_reader_still_borrows_its_producers_key() -> None:
    sql = (
        "INSERT OVERWRITE TABLE dw.t_out SELECT f.fid, o.amt FROM dw.fact f "
        "LEFT JOIN dwd.orders o ON f.order_id = o.order_id"
    )
    cards = build_table_cards(
        [
            build_semantic_profile(_document(P1, "p1")),
            build_semantic_profile(_document(sql, "cons")),
        ]
    )
    profile = build_semantic_profile(_document(sql, "cons"), table_cards=cards)
    assert [risk["status"] for risk in profile["output_shape"]["fan_out_risks"]] == ["safe"]


def test_the_profile_reads_the_finding_kind_the_cards_publish() -> None:
    # semantic_profile cannot import table_cards (it imports semantic_profile).
    from scope_lineage.render import semantic_profile, table_cards

    assert semantic_profile._AMBIGUOUS_BARE_NAME == table_cards.FINDING_AMBIGUOUS_BARE_NAME
