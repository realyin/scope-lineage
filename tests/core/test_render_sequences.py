"""The one order-preserving dedupe the render modules share.

Five copies of the same four lines had drifted apart -- one compared dicts by ``repr``,
one by a sorted JSON dump, one dropped falsy entries, one scanned a list rather than a
set -- and a reader could not tell which of those differences were decisions. They are
one function now, and each caller's difference is written down as its ``key``.
"""

from __future__ import annotations

import json

from scope_lineage.render.sequences import unique_ordered


def test_the_first_occurrence_is_the_one_that_is_kept() -> None:
    assert unique_ordered(["b", "a", "b", "c", "a"]) == ["b", "a", "c"]


def test_an_empty_input_is_an_empty_list() -> None:
    assert unique_ordered([]) == []


def test_without_a_key_the_item_is_its_own_key() -> None:
    assert unique_ordered([1, "1", 1, True]) == [1, "1"]


def test_a_key_says_what_makes_two_items_the_same() -> None:
    items = [
        {"column": "dt", "value": "20260814", "evidence": "rule:001"},
        {"column": "dt", "value": "20260814", "evidence": "rule:002"},
        {"column": "dt", "value": "20260815", "evidence": "rule:003"},
    ]

    kept = unique_ordered(items, lambda item: (item["column"], item["value"]))

    assert [item["evidence"] for item in kept] == ["rule:001", "rule:003"]


def test_a_json_key_compares_dicts_by_content_whatever_their_key_order() -> None:
    items = [{"type": "w", "at": 1}, {"at": 1, "type": "w"}]

    key = lambda item: json.dumps(item, sort_keys=True, default=str)  # noqa: E731

    assert unique_ordered(items, key) == [{"type": "w", "at": 1}]


def test_the_items_themselves_are_returned_not_their_keys() -> None:
    """The caller gets its own objects back, identity included."""
    first = {"id": 1}
    items = [first, {"id": 1}]

    assert unique_ordered(items, lambda item: item["id"])[0] is first
