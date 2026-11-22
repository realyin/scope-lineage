"""A STRUCT path of three or more segments traces as completely as one of two.

`u.info.addr` traced complete while `u.info.addr.city` reported
`trace_complete: false` with `alias_not_bound_to_input_source:addr` (audit PLAN §4,
verify-B §1.13-h side note). The value was already right -- the source was `s.users.info`
-- but the field-ref scan in `expression_refs._qualified_field_refs_uncached` read the
backtick pairs of the expanded path `u`.`info`.`addr`.`city` left to right without
overlap: `u`.`info` (correct), then `addr`.`city`, which it took for column `city` of a
source aliased `addr`. Two segments leave no second pair, so the short path never showed it.

WP13 (670b1f5) gave that scan the guard "a pair never starts after a `.`" for the
`u.profile.u.name` case, which removes the false pair here as well. These tests pin the
depth shapes (and the positions a path can appear in) so the guard cannot regress for
them: each failed before 670b1f5.
"""

from __future__ import annotations

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.scope.task_lineage import parse_task_lineage

SCHEMA = {"s.users": ["info", "id"], "s.v": ["id", "k"]}


def _e2e(sql: str) -> dict[str, dict]:
    result = parse_task_lineage(sql, task_name="t", schema=SCHEMA)
    return {str(item["column"]): item for item in result.end_to_end_lineage}


def _value_sources(item: dict) -> list[tuple]:
    return [
        (source.get("source_kind"), source.get("table"), source.get("column"))
        for source in item.get("value_sources") or []
    ]


@pytest.mark.parametrize(
    "projection",
    [
        "u.info.addr.city",
        "u.info.addr.city.zip",
        "u.info.addr.city.zip.x",
        "`u`.`info`.`addr`.`city`",
        "info.addr.city",
        "upper(u.info.addr.city)",
    ],
)
def test_a_deep_struct_path_traces_complete(projection: str) -> None:
    item = _e2e(f"CREATE TABLE s.t AS SELECT {projection} AS c FROM s.users u")["c"]

    assert _value_sources(item) == [("physical_field", "s.users", "info")]
    assert item["trace_complete"] is True
    assert item["missing_reasons"] == []


def test_a_deep_struct_path_names_no_member_as_an_input() -> None:
    sql = "CREATE TABLE s.t AS SELECT u.info.addr.city AS c FROM s.users u"
    document = to_lineage_dict(parse_scope_lineage(sql, "depth", schema=SCHEMA))
    output = document["scopes"]["ROOT"]["outputs"][0]
    physical = {
        f"{field['table']}.{field['field']}"
        for field in (output.get("expression_resolution") or {}).get("physical_source_fields") or []
    }

    assert output["expanded_expression"] == "`s.users`.`info`.`addr`.`city`"
    assert physical == {"s.users.info"}


@pytest.mark.parametrize(
    "sql",
    [
        # read in a filter as well as projected
        "CREATE TABLE s.t AS SELECT u.info.addr.city AS c FROM s.users u WHERE u.info.addr.zip = '1'",
        # beside a JOIN
        "CREATE TABLE s.t AS SELECT u.info.addr.city AS c, v.k FROM s.users u JOIN s.v v ON u.id = v.id",
        # through a derived table
        "CREATE TABLE s.t AS SELECT x.city AS c FROM (SELECT u.info.addr.city AS city FROM s.users u) x",
        # as a grouping key
        "CREATE TABLE s.t AS SELECT u.info.addr.city AS c FROM s.users u GROUP BY u.info.addr.city",
    ],
)
def test_a_deep_struct_path_traces_complete_in_every_position(sql: str) -> None:
    item = _e2e(sql)["c"]

    assert _value_sources(item) == [("physical_field", "s.users", "info")]
    assert item["trace_complete"] is True


def test_sentinel_two_segment_path_still_traces_complete() -> None:
    item = _e2e("CREATE TABLE s.t AS SELECT u.info.addr AS c FROM s.users u")["c"]

    assert _value_sources(item) == [("physical_field", "s.users", "info")]
    assert item["trace_complete"] is True


def test_sentinel_member_named_like_another_alias_reads_no_column_of_it() -> None:
    # `v` inside `u.info.v.k` is a member, not the joined table `v`: no s.v.k source.
    items = _e2e(
        "CREATE TABLE s.t AS SELECT u.info.v.k AS c, v.id FROM s.users u JOIN s.v v ON u.id = v.id"
    )

    assert _value_sources(items["c"]) == [("physical_field", "s.users", "info")]
    assert _value_sources(items["id"]) == [("physical_field", "s.v", "id")]
