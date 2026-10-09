"""A validity window written by LEAD, and a JOIN that reads it at one point (round-3 G6).

A slowly changing table whose end date is ``LEAD(start) OVER (PARTITION BY p ORDER BY
start)`` has back-to-back intervals per ``p``: row i ends where row i+1 starts. A reader
that keeps ``start <= X AND end > X`` sees at most one row per ``p`` -- two rows i < j
both kept would need ``start_j <= X < end_i = start_{i+1} <= start_j``. Before this the
JOIN onto that read fell through to 「右侧未被证明按连接键唯一」: the card had no key, and
nothing else the profile knew could answer.

The writer states the fact (``output_shape.validity_window``), the table card carries it
(``produced_by[].validity_window``), and the reader's row-subset branch uses it. A MERGE
that rewrites the end date matches on ``(p, start)``, and nothing proves that pair unique
in the table, so a MERGE writer only ever gives ``unknown`` with the condition spelled
out -- never ``safe``. A whole-table overwrite has no such condition.

Every fixture is synthetic.
"""

from __future__ import annotations

from scope_lineage import build_semantic_profile
from scope_lineage.contract import to_lineage_dict
from scope_lineage.contract.task_lineage import to_task_lineage_dict
from scope_lineage.render.table_cards import build_table_cards
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.scope.task_lineage import parse_task_lineage


def _table(*columns: str, types: dict | None = None) -> dict:
    return {
        "column_details": [
            {"name": name, "type": (types or {}).get(name, "string"), "comment": None}
            for name in columns
        ]
    }


SCHEMA = {
    "ods.src": _table("k", "env", "beg", "attr", "ts"),
    "dim.v": _table("k", "env", "beg", "end_d", "attr"),
    "ods.ev": _table("k", "env", "attr", "n"),
    "dw.out": _table("k", "attr", "n"),
}

LEAD_MERGE = (
    "MERGE INTO dim.v t USING (SELECT a.*, LEAD(beg, 1, '99991231') OVER"
    " (PARTITION BY k ORDER BY beg) AS nxt FROM (SELECT * FROM dim.v) a) s"
    " ON t.k = s.k AND t.beg = s.beg WHEN MATCHED THEN UPDATE SET t.end_d = s.nxt"
)

# What a two-statement writer runs first: new versions inserted with an open end, the
# batch deduplicated on more columns than the window partitions by.
INSERT_MERGE = (
    "MERGE INTO dim.v t USING (SELECT k, env, beg, attr, CAST(NULL AS STRING) AS end_d"
    " FROM (SELECT k, env, beg, attr, row_number() OVER (PARTITION BY k, env, beg"
    " ORDER BY ts DESC) AS rn FROM ods.src) a WHERE a.rn = 1) s"
    " ON t.k = s.k AND t.beg = s.beg WHEN NOT MATCHED THEN INSERT *"
)

OVERWRITE = (
    "INSERT OVERWRITE TABLE dim.v SELECT k, env, beg,"
    " LEAD(beg, 1, '99991231') OVER (PARTITION BY k ORDER BY beg) AS end_d, attr FROM dim.v"
)

READ_AT = "(SELECT * FROM dim.v WHERE beg <= '20250101' AND end_d > '20250101')"


def _statement(sql: str, task: str) -> dict:
    return build_semantic_profile(to_lineage_dict(parse_scope_lineage(sql, task, schema=SCHEMA)))


def _task(statements: list[str], task: str) -> dict:
    result = parse_task_lineage(";\n".join(statements) + ";", task_name=task, schema=SCHEMA)
    return build_semantic_profile(to_task_lineage_dict(result))


def _risk(cards: dict, right: str = READ_AT, on: str = "e.k = c.k") -> dict:
    sql = (
        "INSERT OVERWRITE TABLE dw.out SELECT e.k, c.attr, e.n FROM ods.ev e"
        f" LEFT JOIN {right} c ON {on}"
    )
    document = to_lineage_dict(parse_scope_lineage(sql, "c", schema=SCHEMA))
    (risk,) = build_semantic_profile(document, table_cards=cards)["output_shape"]["fan_out_risks"]
    return risk


def _cards(*profiles: dict) -> dict:
    return build_table_cards(list(profiles))


def _window(profile: dict) -> dict | None:
    return profile["output_shape"].get("validity_window")


# ------------------------------------------------------------------ the writer's fact


def test_a_lead_merge_states_its_validity_window_and_its_condition():
    assert _window(_statement(LEAD_MERGE, "p")) == {
        "start": "beg",
        "end": "end_d",
        "partition": ["k"],
        "default": "'99991231'",
        "condition": "validity_rows_unique",
    }


def test_the_key_follows_merge_and_precedes_tag():
    keys = list(_statement(LEAD_MERGE, "p")["output_shape"])
    assert keys.index("merge") < keys.index("validity_window") < keys.index("tag")


def test_a_whole_table_overwrite_has_no_condition():
    assert _window(_statement(OVERWRITE, "p")) == {
        "start": "beg",
        "end": "end_d",
        "partition": ["k"],
        "default": "'99991231'",
    }


def test_the_card_carries_the_writer_s_window():
    cards = _cards(_task([INSERT_MERGE, LEAD_MERGE], "p"))
    (card,) = [item for item in cards["tables"] if item["table"] == "dim.v"]
    windows = [entry.get("validity_window") for entry in card["produced_by"]]
    assert windows == [None, _window(_statement(LEAD_MERGE, "p"))]
    order = list(card["produced_by"][1])
    assert order.index("key_confidence") < order.index("validity_window") < order.index("fields")


def test_a_coalesce_around_the_lead_is_its_default():
    sql = LEAD_MERGE.replace("LEAD(beg, 1, '99991231')", "LEAD(beg)").replace(
        "UPDATE SET t.end_d = s.nxt", "UPDATE SET t.end_d = COALESCE(s.nxt, '99991231')"
    )
    window = _window(_statement(sql, "p"))
    assert window is not None and window["default"] == "'99991231'"


def test_no_window_without_a_partition():
    sql = LEAD_MERGE.replace("PARTITION BY k ", "").replace("t.k = s.k AND ", "")
    assert _window(_statement(sql, "p")) is None


def test_no_window_when_the_using_side_filters_the_table():
    sql = LEAD_MERGE.replace("(SELECT * FROM dim.v)", "(SELECT * FROM dim.v WHERE attr <> '')")
    assert _window(_statement(sql, "p")) is None


def test_no_window_for_a_descending_order():
    assert _window(_statement(LEAD_MERGE.replace("ORDER BY beg", "ORDER BY beg DESC"), "p")) is None


def test_no_window_when_lead_reads_another_column_than_it_orders_by():
    sql = LEAD_MERGE.replace("LEAD(beg, 1,", "LEAD(attr, 1,")
    assert _window(_statement(sql, "p")) is None


def test_no_window_for_an_offset_other_than_one():
    assert _window(_statement(LEAD_MERGE.replace("LEAD(beg, 1,", "LEAD(beg, 2,"), "p")) is None


def test_no_window_when_the_merge_is_not_on_partition_and_start():
    sql = LEAD_MERGE.replace(" AND t.beg = s.beg", "")
    assert _window(_statement(sql, "p")) is None


def test_no_window_when_the_matched_update_has_a_condition():
    sql = LEAD_MERGE.replace("WHEN MATCHED THEN", "WHEN MATCHED AND t.end_d IS NULL THEN")
    assert _window(_statement(sql, "p")) is None


def test_no_window_for_a_hash_compare_writer():
    sql = (
        "INSERT OVERWRITE TABLE dim.v SELECT k, env, beg,"
        " CASE WHEN attr = '' THEN '99991231' ELSE beg END AS end_d, attr FROM dim.v"
    )
    assert _window(_statement(sql, "p")) is None


def test_a_later_statement_writing_the_end_drops_the_window():
    later = "INSERT INTO dim.v SELECT k, env, beg, '20991231' AS end_d, attr FROM ods.src"
    profile = _task([LEAD_MERGE, later], "p")
    assert _window(profile["statements"][0]) is None


def test_an_earlier_statement_writing_the_end_keeps_it():
    profile = _task([INSERT_MERGE, LEAD_MERGE], "p")
    assert _window(profile["statements"][1]) is not None


# ------------------------------------------------------------------ the reader's verdict


def test_a_point_read_of_a_lead_merge_table_is_unknown_with_its_condition():
    risk = _risk(_cards(_statement(LEAD_MERGE, "p")))
    assert risk["status"] == "unknown"
    assert risk["basis"] == "table_card"
    assert "至多一行有效" in risk["reason"]
    assert "LEAD(beg) OVER (PARTITION BY k ORDER BY beg)" in risk["reason"]
    assert "(k, beg) 重复" in risk["reason"]
    # The consequence is said of this table's rows, so a writer who copies it passes check 10.
    assert "不成立时（(k, beg) 重复）右侧同一 k 可能多行有效、会放大" in risk["reason"]
    claim = risk["claim"]
    assert claim["rule"] == "R-VALIDITY-WINDOW"
    assert claim["status"] == "conditional"
    assert claim["content"] == ["k"]
    assert claim["conditions"] == [["validity_rows_unique", ["k", "beg"]]]
    assert claim["assumptions"] == ["A-WRITERS-CLOSED"]
    assert claim["subject"]["kind"] == "read_view"


def test_the_bounds_may_be_written_the_other_way_round():
    right = "(SELECT * FROM dim.v WHERE '20250101' >= beg AND '20250101' < end_d)"
    assert _risk(_cards(_statement(LEAD_MERGE, "p")), right)["status"] == "unknown"


def test_a_parameter_is_one_point_too():
    right = "(SELECT * FROM dim.v WHERE beg <= '${d}' AND end_d > '${d}')".replace("'", "")
    assert _risk(_cards(_statement(LEAD_MERGE, "p")), right)["status"] == "unknown"


def test_a_whole_table_overwrite_makes_the_read_safe():
    risk = _risk(_cards(_statement(OVERWRITE, "p")))
    assert risk["status"] == "safe"
    assert "至多一行有效" in risk["reason"]
    assert risk["claim"]["status"] == "proven"
    assert risk["claim"]["conditions"] == []


def test_write_keys_wider_than_the_partition_are_named_and_an_extra_on_column_may_miss():
    cards = _cards(_task([INSERT_MERGE, LEAD_MERGE], "p"))
    risk = _risk(cards, on="e.k = c.k AND e.env = c.env")
    assert risk["status"] == "unknown"
    assert "写入键比窗口分区多出 env" in risk["reason"]
    assert "ON 另按 env 关联" in risk["reason"]
    assert "关联不到" in risk["reason"]


def test_write_keys_wider_than_the_partition_without_the_column_in_on():
    risk = _risk(_cards(_task([INSERT_MERGE, LEAD_MERGE], "p")))
    assert risk["status"] == "unknown"
    assert "写入键比窗口分区多出 env" in risk["reason"]
    assert "ON 另按" not in risk["reason"]


def test_a_closed_upper_bound_stays_at_risk():
    right = "(SELECT * FROM dim.v WHERE beg <= '20250101' AND end_d >= '20250101')"
    assert _risk(_cards(_statement(LEAD_MERGE, "p")), right)["status"] == "risk"


def test_two_different_points_stay_at_risk():
    right = "(SELECT * FROM dim.v WHERE beg <= '20250101' AND end_d > '20250102')"
    assert _risk(_cards(_statement(LEAD_MERGE, "p")), right)["status"] == "risk"


def test_an_on_clause_without_the_partition_stays_at_risk():
    risk = _risk(_cards(_statement(LEAD_MERGE, "p")), on="e.attr = c.attr")
    assert risk["status"] == "risk"


def test_a_using_side_filter_stays_at_risk():
    sql = LEAD_MERGE.replace("(SELECT * FROM dim.v)", "(SELECT * FROM dim.v WHERE attr <> '')")
    assert _risk(_cards(_statement(sql, "p")))["status"] == "risk"


def test_a_descending_order_stays_at_risk():
    sql = LEAD_MERGE.replace("ORDER BY beg", "ORDER BY beg DESC")
    assert _risk(_cards(_statement(sql, "p")))["status"] == "risk"


def test_another_task_writing_the_end_stays_at_risk():
    other = _statement(
        "INSERT INTO dim.v SELECT k, env, beg, '20991231' AS end_d, attr FROM ods.src", "q"
    )
    assert _risk(_cards(_statement(LEAD_MERGE, "p"), other))["status"] == "risk"


def test_start_and_end_of_different_types_stay_at_risk():
    schema = {**SCHEMA, "dim.v": _table("k", "env", "beg", "end_d", "attr", types={"end_d": "int"})}
    cards = _cards(_statement(LEAD_MERGE, "p"))
    sql = (
        "INSERT OVERWRITE TABLE dw.out SELECT e.k, c.attr, e.n FROM ods.ev e"
        f" LEFT JOIN {READ_AT} c ON e.k = c.k"
    )
    document = to_lineage_dict(parse_scope_lineage(sql, "c", schema=schema))
    (risk,) = build_semantic_profile(document, table_cards=cards)["output_shape"]["fan_out_risks"]
    assert risk["status"] == "risk"
