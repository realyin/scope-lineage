"""A MERGE's grain, its keys and WHEN conditions, and the USING dedup vs the merge key (#22).

1. **H3: a ``row_number() = 1`` below ROOT sets that scope's grain.** ``select ... from
   (select ..., row_number() over (partition by k ...) rn from t) a where rn = 1`` is
   one row per ``k``; only the same shape written at ROOT used to be recognised, so a
   deduplicating subquery read as the driving table's rows.
2. **``output_shape.merge``.** A MERGE's shape and grain are unknown (its written rows
   are not its source's rows), so nothing said on which keys it merges, under which WHEN
   conditions, or whether the USING side can hold two rows for one merge key. The profile
   now restates the contract's ``merge_spec`` and compares the USING side's dedup keys --
   lifted from the scope that defines them to the USING output, renames followed -- with
   the merge key: ``covered``, ``dedup_wider`` (it deduplicates on more columns than it
   merges on, so one merge key can still meet several USING rows), ``no_dedup`` or
   ``unknown``.

Every fixture is synthetic.
"""

from __future__ import annotations

from scope_lineage import build_semantic_profile
from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {
    "dw.m": ["order_id", "env", "amount", "dt"],
    "dw.t": ["order_id", "amount"],
    "ods.log": ["order_id", "name", "env", "amount", "ts", "dt"],
}


def _shape(sql: str) -> dict:
    document = to_lineage_dict(parse_scope_lineage(sql, "t", schema=SCHEMA))
    return build_semantic_profile(document)["output_shape"]


def test_a_row_number_filter_below_root_sets_the_grain():
    shape = _shape(
        "INSERT OVERWRITE TABLE dw.t SELECT x.order_id, x.amount FROM ("
        " SELECT * FROM (SELECT order_id, amount, row_number() OVER ("
        "  PARTITION BY order_id ORDER BY ts DESC) AS rn FROM ods.log) a"
        " WHERE a.rn = 1) x"
    )
    assert shape["grain"]["basis"] == "window_partition"
    assert [key["name"] for key in shape["grain"]["keys"]] == ["order_id"]


def test_a_row_number_filter_at_root_is_unchanged():
    shape = _shape(
        "INSERT OVERWRITE TABLE dw.t SELECT a.order_id, a.amount FROM ("
        " SELECT order_id, amount, row_number() OVER ("
        "  PARTITION BY order_id ORDER BY ts DESC) AS rn FROM ods.log) a WHERE a.rn = 1"
    )
    assert shape["shape"] == "deduplicated"
    assert shape["grain"]["basis"] == "window_partition"
    assert shape["key_confidence"] == "proven"


def test_a_join_beside_the_filter_is_a_fan_out_risk_on_that_grain():
    shape = _shape(
        "INSERT OVERWRITE TABLE dw.t SELECT x.order_id, x.amount FROM ("
        " SELECT a.order_id, b.amount FROM (SELECT order_id, row_number() OVER ("
        "  PARTITION BY order_id ORDER BY ts DESC) AS rn FROM ods.log) a"
        " LEFT JOIN ods.log b ON a.order_id = b.order_id WHERE a.rn = 1) x"
    )
    assert shape["grain"]["basis"] == "window_partition"
    assert [risk["status"] for risk in shape["fan_out_risks"]] == ["unknown"]
    assert shape["key_confidence"] == "none"


def _merge(using: str, on: str = "target.order_id = source.order_id") -> str:
    return (
        f"MERGE INTO dw.m target USING ({using}) source ON {on} "
        "WHEN MATCHED AND target.dt = '20260101' THEN UPDATE SET target.amount = source.amount "
        "WHEN NOT MATCHED THEN INSERT *"
    )


def _ranked(partition: str, select: str = "x.order_id, x.env, x.amount, x.dt") -> str:
    return (
        f"SELECT {select} FROM (SELECT order_id, name, env, amount, dt, row_number() OVER ("
        f" PARTITION BY {partition} ORDER BY ts DESC) AS rn FROM ods.log) x WHERE x.rn = 1"
    )


def test_a_merge_restates_its_keys_and_when_conditions():
    merge = _shape(_merge(_ranked("order_id")))["merge"]
    assert merge["merge_keys"] == [{"target": "order_id", "source": "order_id"}]
    assert [(item["clause"], item["action"]) for item in merge["whens"]] == [
        ("matched", "update"),
        ("not_matched", "insert"),
    ]
    assert "'20260101'" in merge["whens"][0]["condition"]


def test_using_deduplicated_on_the_merge_key_is_covered():
    merge = _shape(_merge(_ranked("order_id")))["merge"]
    assert merge["using_grain"]["basis"] == "window_partition"
    assert merge["coverage"] == "covered"
    assert "extra_keys" not in merge


def test_using_deduplicated_on_more_than_the_merge_key_is_dedup_wider():
    merge = _shape(_merge(_ranked("order_id, env")))["merge"]
    assert merge["coverage"] == "dedup_wider"
    assert merge["extra_keys"] == ["env"]


def test_a_renamed_dedup_key_is_lifted_from_its_own_scope():
    using = _ranked("name", select="x.name AS order_id, x.env, x.amount, x.dt")
    merge = _shape(_merge(using))["merge"]
    assert merge["coverage"] == "covered"


def test_a_derived_dedup_key_counts_as_an_extra_key():
    using = _ranked(
        "order_id, env", select="x.order_id, concat('p_', x.env) AS env, x.amount, x.dt"
    )
    merge = _shape(_merge(using))["merge"]
    assert merge["coverage"] == "dedup_wider"
    assert merge["extra_keys"] == ["env"]
    assert merge["dedup_keys"][1] == {"column": "env", "derived": True}


def test_using_without_a_dedup_is_no_dedup():
    merge = _shape(_merge("SELECT order_id, env, amount, dt FROM ods.log"))["merge"]
    assert merge["coverage"] == "no_dedup"


def test_using_a_union_is_unknown():
    using = (
        "SELECT order_id, env, amount, dt FROM ods.log "
        "UNION ALL SELECT order_id, env, amount, dt FROM ods.log"
    )
    assert _shape(_merge(using))["merge"]["coverage"] == "unknown"


def test_an_insert_has_no_merge_block():
    shape = _shape("INSERT OVERWRITE TABLE dw.t SELECT order_id, amount FROM ods.log")
    assert "merge" not in shape


def test_a_join_after_the_dedup_withholds_covered():
    using = (
        "SELECT x.order_id, x.env, x.amount, x.dt FROM (SELECT order_id, env, amount, dt,"
        " row_number() OVER (PARTITION BY order_id ORDER BY ts DESC) AS rn FROM ods.log) x"
        " LEFT JOIN ods.log y ON x.order_id = y.order_id WHERE x.rn = 1"
    )
    merge = _shape(_merge(using))["merge"]
    assert merge["coverage"] == "unknown"
    assert merge["joins_after_dedup"]


# ---------------------------------------------- M1: the batch a MERGE writes has a grain
#
# Every USING row updates or inserts at most one target row -- a matched target row meeting
# two source rows is a cardinality error -- and a WHEN that does not hold writes nothing,
# so the written rows are a subset of the USING rows, one for one. A key the USING side
# proves unique is unique in the written batch too: the grain, the candidate keys and the
# key claim of a MERGE are those of its USING side (the subject stays the write batch).

MERGE_SCHEMA = {
    "dw.m": ["k", "env", "v", "note", "dt"],
    "ods.s": ["k", "sk", "env", "v", "ts", "dt"],
    "ods.lk": ["k", "note"],
}


def _merge_profile(sql: str) -> dict:
    document = to_lineage_dict(parse_scope_lineage(sql, "t", schema=MERGE_SCHEMA))
    return build_semantic_profile(document)


def test_a_merge_reports_the_grain_of_the_batch_it_writes():
    shape = _merge_profile(
        "MERGE INTO dw.m tgt USING (SELECT k, env, v, note, dt FROM (SELECT k, env, v,"
        " '' AS note, dt, row_number() OVER (PARTITION BY k ORDER BY ts DESC) rn FROM ods.s) a"
        " WHERE a.rn = 1) src ON tgt.k = src.k"
        " WHEN MATCHED THEN UPDATE SET tgt.v = src.v WHEN NOT MATCHED THEN INSERT *"
    )["output_shape"]
    assert shape["shape"] == "unknown"
    assert shape["grain"]["basis"] == "window_partition"
    assert shape["candidate_keys"] == ["k"]
    assert shape["key_confidence"] == "proven"
    assert shape["key_claim"]["subject"]["kind"] == "write_batch"
    assert shape["merge"]["table_key"] == {"keys": ["k"], "status": "hypothesis"}


def test_the_table_key_adds_the_dedup_keys_the_merge_key_lacks():
    shape = _merge_profile(
        "MERGE INTO dw.m tgt USING (SELECT k, env, v, note, dt FROM (SELECT k, env, v,"
        " '' AS note, dt, row_number() OVER (PARTITION BY k, env ORDER BY ts DESC) rn"
        " FROM ods.s) a WHERE a.rn = 1) src ON tgt.k = src.k WHEN NOT MATCHED THEN INSERT *"
    )["output_shape"]
    assert shape["merge"]["coverage"] == "dedup_wider"
    assert shape["merge"]["table_key"] == {"keys": ["k", "env"], "status": "hypothesis"}


def test_an_update_only_merge_does_not_decide_the_table_key():
    shape = _merge_profile(
        "MERGE INTO dw.m tgt USING (SELECT k, v FROM ods.s) src ON tgt.k = src.k"
        " WHEN MATCHED THEN UPDATE SET tgt.v = src.v"
    )["output_shape"]
    assert shape["grain"]["basis"] == "driving_table_rows"
    assert shape["merge"]["table_key"] == {"keys": [], "status": "update_only"}


def test_a_matched_merge_writes_its_on_key_through_the_target_column_it_equals():
    """M1 fix 2: ``tgt.k = src.sk`` holds on every matched row, so a dedup by ``sk``
    identifies the updated rows by ``k`` although ``sk`` is never written."""
    shape = _merge_profile(
        "MERGE INTO dw.m tgt USING (SELECT sk, v FROM (SELECT sk, v, row_number() OVER"
        " (PARTITION BY sk ORDER BY ts DESC) rn FROM ods.s) a WHERE a.rn = 1) src"
        " ON tgt.k = src.sk WHEN MATCHED THEN UPDATE SET tgt.v = src.v"
    )["output_shape"]
    assert shape["candidate_keys"] == ["k"]
    assert shape["key_confidence"] == "proven"
    assert shape["unexposed_keys"] == []


def test_without_a_matched_branch_the_on_key_exposes_nothing():
    """Guard: an unmatched row meets no target row, so ``ON tgt.k = src.kk`` says nothing
    about the value an INSERT writes into ``k``."""
    shape = _merge_profile(
        "MERGE INTO dw.m tgt USING (SELECT sk AS kk, env, v, '' note, dt FROM (SELECT sk, env,"
        " v, dt, row_number() OVER (PARTITION BY sk ORDER BY ts DESC) rn FROM ods.s) a"
        " WHERE a.rn = 1) src ON tgt.k = src.kk WHEN NOT MATCHED THEN"
        " INSERT (k, env, v, note, dt) VALUES (src.env, src.env, src.v, src.note, src.dt)"
    )["output_shape"]
    assert shape["candidate_keys"] == []
    assert shape["key_confidence"] == "proven_unexposed"
    assert [key["name"] for key in shape["unexposed_keys"]] == ["sk"]


# ------------------------------------- M2: what a matched UPDATE leaves or may blank out

M2_SQL = (
    "MERGE INTO dw.m tgt USING (SELECT s.k, s.env, s.v, l.note, s.dt FROM ods.s s"
    " LEFT JOIN ods.lk l ON s.k = l.k) src ON tgt.k = src.k"
    " WHEN MATCHED THEN UPDATE SET tgt.v = src.v, tgt.note = src.note,"
    " tgt.env = coalesce(src.env, tgt.env)"
    " WHEN NOT MATCHED THEN INSERT *"
)


def test_columns_only_the_insert_writes_are_listed_without_the_merge_key():
    merge = _merge_profile(M2_SQL)["output_shape"]["merge"]
    # `k` is not updated either, but ON makes tgt.k = src.k on every matched row.
    assert merge["insert_only_columns"] == ["dt"]
    assert "update_columns" not in merge


def test_an_update_from_a_left_join_may_overwrite_with_null():
    merge = _merge_profile(M2_SQL)["output_shape"]["merge"]
    # `env` reads the target's own value as the fallback, so a miss keeps the old value.
    assert merge["update_nullable_by_join"] == ["note"]


def test_a_constant_null_is_not_an_overwrite_by_join():
    merge = _merge_profile(
        "MERGE INTO dw.m tgt USING (SELECT s.k, s.env, s.v, CAST(NULL AS STRING) AS note, s.dt"
        " FROM ods.s s) src ON tgt.k = src.k"
        " WHEN MATCHED THEN UPDATE SET tgt.v = src.v, tgt.note = src.note"
        " WHEN NOT MATCHED THEN INSERT *"
    )["output_shape"]["merge"]
    assert "update_nullable_by_join" not in merge


def test_an_update_only_merge_lists_the_columns_it_changes():
    merge = _merge_profile(
        "MERGE INTO dw.m tgt USING (SELECT k, v, env FROM ods.s) src ON tgt.k = src.k"
        " WHEN MATCHED THEN UPDATE SET tgt.v = src.v, tgt.env = src.env"
    )["output_shape"]["merge"]
    assert merge["update_columns"] == ["v", "env"]
    assert "insert_only_columns" not in merge


# -------------------------------------------- M3: a UNION USING side, branch by branch


def test_each_union_branch_reports_its_own_dedup_and_coverage_stays_unknown():
    merge = _merge_profile(
        "MERGE INTO dw.m tgt USING (SELECT k, env, v, note, dt FROM (SELECT k, env, v, '' note,"
        " dt, row_number() OVER (PARTITION BY k ORDER BY ts DESC) rn FROM ods.s) a WHERE a.rn = 1"
        " UNION ALL SELECT sk AS k, env, v, note, dt FROM (SELECT sk, env, v, '' note, dt,"
        " row_number() OVER (PARTITION BY sk ORDER BY ts DESC) rn FROM ods.s) b WHERE b.rn = 1"
        " UNION ALL SELECT k, env, v, '' note, dt FROM ods.s) src"
        " ON tgt.k = src.k WHEN NOT MATCHED THEN INSERT *"
    )["output_shape"]["merge"]
    # Each branch unique by k does not make the union unique by k: one key may come from
    # two branches.
    assert merge["coverage"] == "unknown"
    branches = [
        (
            item["branch"],
            item["basis"],
            [key["column"] for key in item.get("dedup_keys") or []],
            item.get("coverage"),
        )
        for item in merge["union_branches"]
    ]
    assert branches == [
        (1, "window_partition", ["k"], "covered"),
        (2, "window_partition", ["k"], "covered"),
        (3, "driving_table_rows", [], None),
    ]


def test_a_branch_joining_after_its_dedup_is_not_covered():
    merge = _merge_profile(
        "MERGE INTO dw.m tgt USING (SELECT a.k, a.env, a.v, l.note, a.dt FROM (SELECT k, env,"
        " v, dt, row_number() OVER (PARTITION BY k ORDER BY ts DESC) rn FROM ods.s) a"
        " LEFT JOIN ods.lk l ON a.k = l.k WHERE a.rn = 1"
        " UNION ALL SELECT k, env, v, '' note, dt FROM ods.s) src"
        " ON tgt.k = src.k WHEN NOT MATCHED THEN INSERT *"
    )["output_shape"]["merge"]
    first = merge["union_branches"][0]
    assert first["basis"] == "window_partition"
    assert first["coverage"] == "unknown"
    assert first["joins_after_dedup"]
