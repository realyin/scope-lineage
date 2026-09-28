"""One set of lineage composition rules for the statement, task and fold levels (WP5).

Three places composed lineage hops and deduplicated sources, each its own way, and F6
was the fold disagreeing with the statement-level trace. ``scope.composition`` is the
one place the rules live now: what makes two sources the same, how a hop's transform
combines with the one below it, and how a list is deduplicated.
"""

from __future__ import annotations

from scope_lineage.scope.composition import (
    compose_hop,
    dedupe_sources,
    dominant_transform,
    source_identity,
)


def test_a_path_carries_its_strongest_transform() -> None:
    assert dominant_transform("DIRECT", "EXPRESSION") == "EXPRESSION"
    assert dominant_transform("AGGREGATE", "DIRECT") == "AGGREGATE"
    assert dominant_transform("WINDOW", "AGGREGATE") == "AGGREGATE"


def test_two_constants_are_two_sources() -> None:
    a = {"source_kind": "generated", "value": "'A'", "transform": "CONSTANT"}
    b = {"source_kind": "generated", "value": "'B'", "transform": "CONSTANT"}

    assert source_identity(a) != source_identity(b)


def test_one_column_by_two_paths_is_two_sources() -> None:
    direct = {"source_kind": "physical_field", "table": "t", "column": "c", "transform": "DIRECT"}
    windowed = {**direct, "transform": "WINDOW"}

    assert source_identity(direct) != source_identity(windowed)


def test_identity_does_not_depend_on_key_order() -> None:
    assert source_identity({"a": 1, "b": {"x": 1, "y": 2}}) == source_identity(
        {"b": {"y": 2, "x": 1}, "a": 1}
    )


def test_a_hop_through_a_relation_keeps_what_it_applied() -> None:
    hop = {"table": "tv", "column": "v", "transform": "EXPRESSION"}
    leaf = {"source_kind": "physical_field", "table": "t", "column": "v", "transform": "DIRECT"}

    assert compose_hop(hop, leaf)["transform"] == "EXPRESSION"
    assert compose_hop({"table": "tv", "column": "v"}, leaf) is leaf


def test_dedupe_keeps_the_first_of_each_and_the_order() -> None:
    a = {"table": "t", "column": "a"}
    b = {"table": "t", "column": "b"}

    assert dedupe_sources([a, b, dict(a)]) == [a, b]
