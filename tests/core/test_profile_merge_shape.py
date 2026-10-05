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
