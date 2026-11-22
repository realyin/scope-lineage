"""A MERGE's ON and WHEN conditions are logic on its ROOT scope (WP3l, 1.13-j).

The MERGE ROOT carried only its SET / INSERT values: a constant ``UPDATE SET t.flag = 1``
left ``ROOT.depends_on`` empty, so nothing in the scope graph said the write reads the
USING relation, and the ON / WHEN predicates appeared in no logic block. ON is now a
join of the target and the USING relation, and each WHEN condition a filter.

Every name here is synthetic.
"""

from __future__ import annotations

from scope_lineage.contract import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {"s.src": ["id", "v", "w"], "m.t": ["id", "flag", "c"]}


def _root(sql: str) -> dict:
    return to_lineage_dict(parse_scope_lineage(sql, "t", schema=SCHEMA))["scopes"]["ROOT"]


def _blocks(root: dict, logic_type: str) -> list[dict]:
    return [block for block in root.get("logic_blocks", []) if block["logic_type"] == logic_type]


CONSTANT_SET = (
    "MERGE INTO m.t t USING (SELECT id, v FROM s.src) u ON t.id = u.id "
    "WHEN MATCHED THEN UPDATE SET t.flag = 1"
)


def test_a_constant_set_merge_depends_on_its_using_relation() -> None:
    root = _root(CONSTANT_SET)

    assert "subq:u" in root["depends_on"]


def test_the_on_condition_is_a_join_of_target_and_using() -> None:
    root = _root(CONSTANT_SET)

    [join] = root["joins"]
    assert join["condition_expression"] == "`t`.`id` = `u`.`id`"
    assert (join["join_type"], join["left_scope"], join["right_scope"]) == (
        "MERGE", "m.t", "subq:u",
    )
    assert {(c["scope"], c["column"]) for c in join["condition_columns"]} == {
        ("m.t", "id"), ("subq:u", "id"),
    }
    # The ON is a match against the write target, described by merge_spec; a ROOT join
    # block would be read as a SELECT join fanning out the FROM item.
    assert _blocks(root, "join") == []


def test_the_target_a_condition_reads_is_not_an_upstream_dependency() -> None:
    root = _root(
        "MERGE INTO m.t t USING (SELECT id FROM s.src) u ON t.id = u.id "
        "WHEN MATCHED AND t.flag = 0 THEN UPDATE SET t.c = 1"
    )

    assert root["depends_on"] == ["subq:u"]


def test_each_when_condition_is_a_filter() -> None:
    root = _root(
        "MERGE INTO m.t t USING (SELECT id, v, w FROM s.src) u ON t.id = u.id "
        "WHEN MATCHED AND u.v > 0 THEN UPDATE SET t.c = u.v "
        "WHEN MATCHED THEN UPDATE SET t.c = u.w "
        "WHEN NOT MATCHED AND u.w IS NOT NULL THEN INSERT (id, c) VALUES (u.id, u.w)"
    )

    filters = _blocks(root, "filter")
    assert [block["raw_expression"] for block in filters] == [
        "`u`.`v` > 0", "NOT `u`.`w` IS NULL",
    ]
    assert {(f["scope"], f["column"]) for f in filters[0]["fields"]} == {("subq:u", "v")}
    assert {
        block["filter_predicate_detail"]["predicate_type"] for block in filters
    } == {"merge_when"}


def test_a_by_source_condition_reads_the_target_only() -> None:
    root = _root(
        "MERGE INTO m.t t USING (SELECT id FROM s.src) u ON t.id = u.id "
        "WHEN NOT MATCHED BY SOURCE AND t.flag = 0 THEN DELETE"
    )

    [block] = _blocks(root, "filter")
    assert {(f["scope"], f["column"]) for f in block["fields"]} == {("m.t", "flag")}


def test_the_merge_values_are_unchanged() -> None:
    root = _root(CONSTANT_SET)

    [column] = root["columns"]
    assert (column["name"], column["transform"], column.get("merge_branch")) == (
        "flag", "CONSTANT", "matched",
    )
