"""Which joins get a fan-out verdict, and which right sides are proven unique (#21).

1. **#21-a: a blocker withholds the grain, not the path.** A UNION, a LATERAL VIEW or an
   ambiguous bare column makes a scope's row count undecidable, and the grain walk used to
   stop there -- so every join below it (a UNION branch's LEFT JOIN, the subquery a LATERAL
   VIEW expands) got no verdict at all, although its rows reach the output. The walk now
   continues into the blocked scope's inputs; the grain stays unknown. It still does not
   cross an aggregation: a join under a GROUP BY changes an aggregate's value, not the
   output's rows, and is not put on the grain path.
2. **#21-b: a ``row_number() = 1`` one layer down still proves the right side unique.**
   ``(select ... from (select ..., row_number() over (partition by k ...) rn from t) x
   where rn = 1) d`` -- the window inside, the filter outside -- was only recognised when
   both sat in the right side's own scope.
3. **#21-c: an inline VALUES dictionary whose rows differ on the join key is unique.**
   Its rows are literals in the SQL, so their distinctness is provable; equality pins on
   the way down (a ``WHERE kind = 'A'``, or a top-level ``AND d.kind = 'A'`` in the ON
   clause) narrow the rows first.

Every fixture is synthetic.
"""

from __future__ import annotations

from scope_lineage import build_semantic_profile
from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {
    "ods.orders": ["order_id", "shop_id", "amount", "env", "dt"],
    "ods.shop": ["shop_id", "name", "env", "dt"],
    "ods.log": ["order_id", "tags", "start_time", "env", "dt"],
    "dw.t": ["order_id", "shop_id", "name"],
}


def _profile(sql: str) -> dict:
    return build_semantic_profile(to_lineage_dict(parse_scope_lineage(sql, "t", schema=SCHEMA)))


def _risks(profile: dict) -> dict[str, dict]:
    return {item["logic_block_id"]: item for item in profile["output_shape"]["fan_out_risks"]}


# --- #21-a --------------------------------------------------------------------------

UNION_BRANCH_JOIN = (
    "INSERT OVERWRITE TABLE dw.t "
    "SELECT o.order_id, o.shop_id, NULL AS name FROM ods.orders o "
    "UNION ALL SELECT a.order_id, a.shop_id, b.name FROM ods.orders a "
    "LEFT JOIN ods.shop b ON a.shop_id = b.shop_id"
)


def test_a_join_in_a_union_branch_gets_a_grain_path_verdict():
    profile = _profile(UNION_BRANCH_JOIN)
    risk = _risks(profile)["logic:union:main:b02:join:001"]
    assert risk["path"] == "grain"
    assert risk["status"] in ("unknown", "risk")
    shape = profile["output_shape"]
    assert shape["grain"]["basis"] == "unknown"
    assert shape["key_confidence"] == "none"


def test_a_join_in_a_nested_union_branch_gets_a_verdict():
    profile = _profile(
        "INSERT OVERWRITE TABLE dw.t "
        "SELECT o.order_id, o.shop_id, NULL AS name FROM ods.orders o "
        "UNION ALL SELECT u.order_id, u.shop_id, u.name FROM ("
        " SELECT order_id, shop_id, 'x' AS name FROM ods.orders"
        " UNION ALL SELECT a.order_id, a.shop_id, b.name FROM ods.orders a"
        " JOIN ods.shop b ON a.shop_id = b.shop_id) u"
    )
    assert _risks(profile)["logic:union:u:b02:join:001"]["path"] == "grain"


def test_a_join_under_a_lateral_view_gets_a_verdict():
    profile = _profile(
        "INSERT OVERWRITE TABLE dw.t SELECT x.order_id, x.shop_id, tag AS name FROM ("
        " SELECT a.order_id, a.shop_id, l.tags FROM ods.orders a"
        " LEFT JOIN ods.log l ON a.order_id = l.order_id) x"
        " LATERAL VIEW explode(split(x.tags, ',')) t AS tag"
    )
    risk = _risks(profile)["logic:subq:x:join:001"]
    assert risk["path"] == "grain"
    assert profile["output_shape"]["key_confidence"] == "none"


def test_the_walk_does_not_cross_an_aggregation():
    profile = _profile(
        "INSERT OVERWRITE TABLE dw.t SELECT u.order_id, max(u.shop_id), max(u.name) FROM ("
        " SELECT order_id, shop_id, 'x' AS name FROM ods.orders"
        " UNION ALL SELECT a.order_id, a.shop_id, b.name FROM ods.orders a"
        " LEFT JOIN ods.shop b ON a.shop_id = b.shop_id) u GROUP BY u.order_id"
    )
    shape = profile["output_shape"]
    assert "logic:union:u:b02:join:001" not in _risks(profile)
    assert shape["grain"]["basis"] == "group_by"
    assert shape["key_confidence"] == "proven"


def test_a_join_inside_a_right_side_is_not_put_on_the_grain_path():
    profile = _profile(
        "INSERT OVERWRITE TABLE dw.t SELECT a.order_id, a.shop_id, d.name FROM ods.orders a "
        "LEFT JOIN (SELECT s.shop_id, l.tags AS name FROM ods.shop s"
        " LEFT JOIN ods.log l ON s.shop_id = l.order_id) d ON a.shop_id = d.shop_id "
        "UNION ALL SELECT o.order_id, o.shop_id, NULL FROM ods.orders o"
    )
    assert "logic:subq:d:join:001" not in _risks(profile)


# --- #21-b --------------------------------------------------------------------------


def _ranked_right(partition: str, on: str, outer: str = "x.order_id", function: str = "row_number") -> str:
    return (
        "INSERT OVERWRITE TABLE dw.t SELECT a.order_id, a.shop_id, d.start_time AS name "
        "FROM ods.orders a LEFT JOIN ("
        f" SELECT {outer}, x.start_time FROM ("
        f"  SELECT order_id, env, start_time, {function}() OVER ("
        f"   PARTITION BY {partition} ORDER BY start_time DESC) AS rn FROM ods.log) x"
        f" WHERE x.rn = 1) d ON {on}"
    )


def _verdict(sql: str) -> str:
    (risk,) = _profile(sql)["output_shape"]["fan_out_risks"]
    return risk["status"]


def test_a_row_number_filtered_one_layer_up_proves_the_right_side_unique():
    assert _verdict(_ranked_right("order_id", "a.order_id = d.order_id")) == "safe"


def test_a_renamed_partition_key_still_proves_it():
    sql = _ranked_right("order_id", "a.order_id = d.oid", outer="x.order_id AS oid")
    assert _verdict(sql) == "safe"


def test_a_join_between_the_window_and_the_filter_keeps_the_risk():
    sql = (
        "INSERT OVERWRITE TABLE dw.t SELECT a.order_id, a.shop_id, d.name "
        "FROM ods.orders a LEFT JOIN ("
        " SELECT x.order_id, s.name FROM ("
        "  SELECT order_id, shop_id, row_number() OVER ("
        "   PARTITION BY order_id ORDER BY start_time DESC) AS rn FROM ods.log) x"
        " LEFT JOIN ods.shop s ON x.shop_id = s.shop_id"
        " WHERE x.rn = 1) d ON a.order_id = d.order_id"
    )
    assert _verdict(sql) == "risk"


def test_a_partition_wider_than_the_join_key_keeps_the_risk():
    assert _verdict(_ranked_right("order_id, env", "a.order_id = d.order_id")) == "risk"


def test_rank_keeps_the_risk():
    for function in ("rank", "dense_rank"):
        sql = _ranked_right("order_id", "a.order_id = d.order_id", function=function)
        assert _verdict(sql) == "risk"


# --- #21-c --------------------------------------------------------------------------

DICT = (
    "WITH k2 AS (SELECT * FROM VALUES ('A', '1', 'one'), ('A', '2', 'two'), ('B', '1', 'uno')"
    " AS t(grp, code, label)) "
)


def _dict_join(on: str, where: str = "") -> str:
    right = f"(SELECT * FROM k2 WHERE {where})" if where else "k2"
    return (
        DICT + "INSERT OVERWRITE TABLE dw.t SELECT a.order_id, a.shop_id, d.label AS name "
        f"FROM ods.orders a LEFT JOIN {right} d ON {on}"
    )


def test_a_values_dictionary_unique_after_its_pin_is_safe():
    profile = _profile(_dict_join("a.shop_id = d.code", where="grp = 'A'"))
    (risk,) = profile["output_shape"]["fan_out_risks"]
    assert risk["status"] == "safe"
    assert "VALUES" in risk["reason"]


def test_without_the_pin_a_repeated_code_keeps_the_risk():
    assert _verdict(_dict_join("a.shop_id = d.code")) == "risk"


def test_a_repeated_code_after_the_pin_keeps_the_risk():
    sql = (
        "WITH k2 AS (SELECT * FROM VALUES ('A', '1', 'one'), ('A', '1', 'two')"
        " AS t(grp, code, label)) "
        "INSERT OVERWRITE TABLE dw.t SELECT a.order_id, a.shop_id, d.label AS name "
        "FROM ods.orders a LEFT JOIN (SELECT * FROM k2 WHERE grp = 'A') d "
        "ON a.shop_id = d.code"
    )
    assert _verdict(sql) == "risk"


def test_a_pin_in_the_on_clause_counts():
    assert _verdict(_dict_join("a.shop_id = d.code AND d.grp = 'A'")) == "safe"


def test_a_pin_inside_an_or_does_not_count():
    sql = _dict_join("a.shop_id = d.code AND (d.grp = 'A' OR d.grp = 'B')")
    assert _verdict(sql) == "risk"


def test_a_cell_that_is_an_expression_is_not_proven():
    sql = (
        "WITH k2 AS (SELECT * FROM VALUES ('A', concat('1', ''), 'one'), ('A', '2', 'two')"
        " AS t(grp, code, label)) "
        "INSERT OVERWRITE TABLE dw.t SELECT a.order_id, a.shop_id, d.label AS name "
        "FROM ods.orders a LEFT JOIN k2 d ON a.shop_id = d.code"
    )
    assert _verdict(sql) == "risk"


def test_codes_equal_as_numbers_are_not_proven_distinct():
    sql = (
        "WITH k2 AS (SELECT * FROM VALUES ('1', 'one'), ('01', 'also one')"
        " AS t(code, label)) "
        "INSERT OVERWRITE TABLE dw.t SELECT a.order_id, a.shop_id, d.label AS name "
        "FROM ods.orders a LEFT JOIN k2 d ON a.shop_id = d.code"
    )
    assert _verdict(sql) == "risk"
