"""A dynamic-partition INSERT OVERWRITE replaces the whole table under Spark's default.

`INSERT OVERWRITE TABLE t PARTITION(dt)` names the partition column without a value. What
that does depends on `spark.sql.sources.partitionOverwriteMode`, whose default is STATIC: all
existing partitions are dropped before the new data lands. Only when the mode is explicitly
DYNAMIC do untouched partitions survive.

The write effect was chosen from `target_partition_mode != "none"`, so a valued spec
(`PARTITION(dt='20260101')`) and a dynamic one were treated alike -- both kept the target's
previous `value_sources`, and every column of the target came back carrying a
`prior_table_state` edge from a state the overwrite had in fact destroyed (PARTOVR-001).

That edge is not merely redundant. It asserts that the new value may be the old one, which is
what a consumer folding state-evolution edges relies on to decide a column was left alone.
A valued spec keeps the edge because only the named partitions are replaced; the rest of the
table genuinely survives, which is why the two shapes must not be collapsed.
"""

from __future__ import annotations

import pytest

from scope_lineage.scope.task_lineage import parse_task_lineage

SCHEMA = {"ods.a": ["id", "v", "dt"], "mart.t": ["id", "v", "dt"]}


def _prior_state_columns(sql: str, table: str = "mart.t") -> set[str]:
    """Target columns that claim a value carried over from the table's previous state."""
    result = parse_task_lineage(sql, task_name="t", schema=SCHEMA)
    return {
        str(item.get("column"))
        for item in result.end_to_end_lineage
        if item.get("table") == table
        for source in item.get("value_sources") or []
        if source.get("source_kind") == "prior_table_state"
    }


def _seed(sql: str) -> str:
    """Give the target a previous state, so prior_table_state edges are possible at all."""
    return "INSERT INTO mart.t SELECT id, v, dt FROM ods.a;\n" + sql


def test_dynamic_partition_overwrite_drops_the_previous_state():
    sql = _seed("INSERT OVERWRITE TABLE mart.t PARTITION(dt) SELECT id, v, dt FROM ods.a")

    assert _prior_state_columns(sql) == set()


def test_valued_partition_overwrite_keeps_the_previous_state():
    """Only the named partition is replaced; the rest of the table survives."""
    sql = _seed("INSERT OVERWRITE TABLE mart.t PARTITION(dt='20260101') SELECT id, v FROM ods.a")

    assert _prior_state_columns(sql)


def test_mixed_partition_overwrite_keeps_the_previous_state():
    """A static prefix bounds the blast radius, so other prefixes survive."""
    schema = {"ods.a": ["id", "v", "dt", "region"], "mart.t": ["id", "v", "dt", "region"]}
    sql = (
        "INSERT INTO mart.t SELECT id, v, dt, region FROM ods.a;\n"
        "INSERT OVERWRITE TABLE mart.t PARTITION(region='mx', dt) SELECT id, v, dt FROM ods.a"
    )
    result = parse_task_lineage(sql, task_name="t", schema=schema)
    prior = {
        str(item.get("column"))
        for item in result.end_to_end_lineage
        if item.get("table") == "mart.t"
        for source in item.get("value_sources") or []
        if source.get("source_kind") == "prior_table_state"
    }

    assert prior


def test_an_explicit_dynamic_mode_keeps_the_previous_state():
    """With the mode set to DYNAMIC, untouched partitions really do survive."""
    sql = _seed(
        "set spark.sql.sources.partitionOverwriteMode=dynamic;\n"
        "INSERT OVERWRITE TABLE mart.t PARTITION(dt) SELECT id, v, dt FROM ods.a"
    )

    assert _prior_state_columns(sql)


@pytest.mark.parametrize("setting", ["static", "STATIC"])
def test_an_explicit_static_mode_matches_the_default(setting):
    sql = _seed(
        f"set spark.sql.sources.partitionOverwriteMode={setting};\n"
        "INSERT OVERWRITE TABLE mart.t PARTITION(dt) SELECT id, v, dt FROM ods.a"
    )

    assert _prior_state_columns(sql) == set()


def test_the_setting_only_applies_to_statements_after_it():
    """A mode set after the write cannot change what that write did."""
    sql = _seed(
        "INSERT OVERWRITE TABLE mart.t PARTITION(dt) SELECT id, v, dt FROM ods.a;\n"
        "set spark.sql.sources.partitionOverwriteMode=dynamic"
    )

    assert _prior_state_columns(sql) == set()


def test_an_unpartitioned_overwrite_is_unchanged():
    """Already a full replace; this fix must not touch it."""
    sql = _seed("INSERT OVERWRITE TABLE mart.t SELECT id, v, dt FROM ods.a")

    assert _prior_state_columns(sql) == set()


def test_an_append_is_unchanged():
    """INSERT INTO keeps the previous state and must stay that way."""
    sql = _seed("INSERT INTO mart.t SELECT id, v, dt FROM ods.a")

    assert _prior_state_columns(sql)


def test_a_merge_target_is_unchanged():
    """MERGE genuinely retains unmatched rows; this fix must not reach it."""
    sql = (
        "INSERT INTO mart.t SELECT id, v, dt FROM ods.a;\n"
        "MERGE INTO mart.t t USING (SELECT id, v, dt FROM ods.a) s ON t.id = s.id\n"
        "WHEN NOT MATCHED THEN INSERT (id, v, dt) VALUES (s.id, s.v, s.dt)"
    )

    assert _prior_state_columns(sql)


def test_a_column_the_write_does_not_supply_matches_an_unpartitioned_overwrite():
    """A full replace says nothing about a column it never writes, however it is spelled.

    The target column `extra` is not in the SELECT. After a full replace its old values are
    gone, so no row is the honest answer -- and that is already what an unpartitioned
    INSERT OVERWRITE produces. A dynamic-partition overwrite is the same kind of write and
    must not disagree with it, while a valued spec keeps the row because those partitions
    really do survive.
    """
    schema = {"ods.a": ["id", "v", "dt"], "mart.t": ["id", "v", "dt", "extra"]}
    seed = "INSERT INTO mart.t SELECT id, v, dt, 'x' FROM ods.a;\n"

    def extra_sources(write: str):
        result = parse_task_lineage(seed + write, task_name="t", schema=schema)
        row = next(
            (i for i in result.end_to_end_lineage
             if i.get("table") == "mart.t" and i.get("column") == "extra"),
            None,
        )
        return None if row is None else sorted(
            {s.get("source_kind") for s in row.get("value_sources") or []}
        )

    unpartitioned = extra_sources("INSERT OVERWRITE TABLE mart.t SELECT id, v, dt FROM ods.a")
    dynamic = extra_sources("INSERT OVERWRITE TABLE mart.t PARTITION(dt) SELECT id, v, dt FROM ods.a")
    valued = extra_sources(
        "INSERT OVERWRITE TABLE mart.t PARTITION(dt='20260101') SELECT id, v FROM ods.a"
    )

    assert unpartitioned is None
    assert dynamic == unpartitioned
    assert valued == ["prior_table_state"]
