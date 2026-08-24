"""Self-join `join_relation_detail` must keep the two sides apart.

`alias_by_source` was keyed by source_id, so a table joined to itself collapsed both
sides onto the later alias (`left_alias == right_alias == "b"`), and the equality
conjuncts were refused as key pairs because both refs resolve to the same scope —
rendering `a.batch_id = b.batch_id` as the tautology `ods.nodes.batch_id =
ods.nodes.batch_id` (issue: v1-v2-contract-gaps 4.1 / join-alias-overwrite-on-self-join).
"""

from __future__ import annotations

from scope_lineage.scope.scope_builder import parse_scope_lineage

SQL = (
    "INSERT INTO mart.t "
    "SELECT a.id FROM ods.nodes a JOIN ods.nodes b "
    "ON a.id = b.parent_id AND a.batch_id = b.batch_id AND b.status = 'ok'"
)

SCHEMA = {"ods.nodes": ["id", "parent_id", "batch_id", "status"]}


def _detail():
    result = parse_scope_lineage(SQL, task_name="demo", schema=SCHEMA)
    for block in result.scopes["ROOT"].logic_blocks:
        if block.logic_type == "join":
            return block.join_relation_detail
    raise AssertionError("no join logic block")


def test_each_side_keeps_its_own_alias():
    detail = _detail()
    assert detail["left_alias"] == "a"
    assert detail["right_alias"] == "b"


def test_equality_conjuncts_become_key_pairs_oriented_by_qualifier():
    detail = _detail()
    pairs = {
        (p["left"]["qualifier"], p["left"]["column"],
         p["right"]["qualifier"], p["right"]["column"])
        for p in detail["join_key_pairs"]
    }
    assert pairs == {
        ("a", "id", "b", "parent_id"),
        ("a", "batch_id", "b", "batch_id"),
    }
    assert "missing_join_key_pairs" not in detail["missing_reasons"]


def test_the_literal_conjunct_stays_a_condition_filter():
    detail = _detail()
    assert [f["expression"] for f in detail["condition_filters"]] == ["`b`.`status` = 'ok'"]


def test_a_distinct_table_join_is_unchanged():
    result = parse_scope_lineage(
        "INSERT INTO mart.t SELECT a.id FROM ods.a a JOIN ods.b b ON a.id = b.a_id",
        task_name="demo",
        schema={"ods.a": ["id"], "ods.b": ["a_id"]},
    )
    for block in result.scopes["ROOT"].logic_blocks:
        if block.logic_type == "join":
            detail = block.join_relation_detail
            assert (detail["left_alias"], detail["right_alias"]) == ("a", "b")
            assert len(detail["join_key_pairs"]) == 1
            return
    raise AssertionError("no join logic block")


CHAIN_SQL = (
    "INSERT INTO mart.t "
    "SELECT b.accountname FROM ods.nodes b "
    "LEFT JOIN ods.nodes d ON b.parent_id = d.id AND b.parent_id <> '' "
    "LEFT JOIN ods.nodes d1 ON d.parent_id = d1.id AND d.parent_id <> '' "
    "LEFT JOIN ods.nodes d2 ON d1.parent_id = d2.id AND d1.parent_id <> ''"
)

CHAIN_SCHEMA = {"ods.nodes": ["id", "parent_id", "accountname"]}


def _chain_details():
    result = parse_scope_lineage(CHAIN_SQL, task_name="demo", schema=CHAIN_SCHEMA)
    details = [
        block.join_relation_detail
        for block in result.scopes["ROOT"].logic_blocks
        if block.logic_type == "join"
    ]
    assert len(details) == 3, "premise: three chained self-joins"
    return result, details


def test_chained_self_joins_split_keys_at_every_hop():
    # hop N's ON references the alias joined at hop N-1, not the FROM base alias;
    # a single guessed left_alias ("b") refused every later hop's key pair
    _, details = _chain_details()
    pairs = [
        (p["left"]["qualifier"], p["left"]["column"],
         p["right"]["qualifier"], p["right"]["column"])
        for detail in details
        for p in detail["join_key_pairs"]
    ]
    assert pairs == [
        ("b", "parent_id", "d", "id"),
        ("d", "parent_id", "d1", "id"),
        ("d1", "parent_id", "d2", "id"),
    ]
    for detail in details:
        assert detail["trace_status"] == "complete"
        assert "missing_join_key_pairs" not in detail["missing_reasons"]


def test_chained_self_join_left_alias_is_the_preceding_hop():
    _, details = _chain_details()
    assert [(d["left_alias"], d["right_alias"]) for d in details] == [
        ("b", "d"), ("d", "d1"), ("d1", "d2"),
    ]


def test_equalities_between_two_left_side_aliases_stay_filters():
    # b and d are both already on the left when d1 joins: an equality between them
    # is a filter on the accumulated relation, not a key of this join
    sql = (
        "INSERT INTO mart.t SELECT b.accountname FROM ods.nodes b "
        "LEFT JOIN ods.nodes d ON b.parent_id = d.id "
        "LEFT JOIN ods.nodes d1 ON d.parent_id = d1.id AND b.batch_id = d.batch_id"
    )
    result = parse_scope_lineage(
        sql, task_name="demo",
        schema={"ods.nodes": ["id", "parent_id", "accountname", "batch_id"]},
    )
    last = [
        block.join_relation_detail
        for block in result.scopes["ROOT"].logic_blocks
        if block.logic_type == "join"
    ][-1]
    assert [
        (p["left"]["qualifier"], p["right"]["qualifier"])
        for p in last["join_key_pairs"]
    ] == [("d", "d1")]
    assert ["`b`.`batch_id` = `d`.`batch_id`"] == [
        f["expression"] for f in last["condition_filters"]
    ]


def test_unsplit_join_keys_emit_a_diagnostic_warning():
    # keys that cannot be split are already ⚠-marked in the documents; the
    # diagnostics stream must carry the same signal so consumers see it
    result = parse_scope_lineage(
        "INSERT INTO mart.t SELECT a.id FROM ods.nodes a JOIN ods.nodes b "
        "ON a.status = 'ok' AND b.status = 'ok'",
        task_name="demo",
        schema={"ods.nodes": ["id", "status"]},
    )
    warnings = [w for w in result.diagnostics.warnings if w.type == "join_keys_not_split"]
    assert len(warnings) == 1
    assert warnings[0].scope == "ROOT"


def test_split_join_keys_do_not_emit_the_unsplit_warning():
    result = parse_scope_lineage(CHAIN_SQL, task_name="demo", schema=CHAIN_SCHEMA)
    assert not [w for w in result.diagnostics.warnings if w.type == "join_keys_not_split"]
