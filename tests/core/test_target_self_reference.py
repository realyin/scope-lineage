"""Target-table self-reference annotation on join_relation_detail.

A statement that reads its own target table is a structural fact worth surfacing:
when both the target partition and the self-reference's partition predicate are
literal dates, the day offset is provable (a negative offset is the classic
carry-forward/backfill shape); otherwise the reference is annotated unproven
rather than guessed. Naming stays domain-neutral — the tool states the offset,
the consumer decides what to call it.
"""

from __future__ import annotations

from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.mapping_markdown import render_mapping_markdown
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {"tmp.mid": ["id", "v", "dt"], "app.t": ["id", "v", "dt"]}


def _self_ref(sql: str, schema=None):
    result = parse_scope_lineage(sql, "case", schema=schema or SCHEMA)
    refs = []
    for scope in result.scopes.values():
        for block in scope.logic_blocks:
            if block.logic_type == "join" and block.join_relation_detail:
                annotation = block.join_relation_detail.get("target_self_reference")
                if annotation:
                    refs.append(annotation)
    return result, refs


def test_literal_partition_offset_is_proven() -> None:
    _, refs = _self_ref(
        "INSERT OVERWRITE TABLE app.t PARTITION (dt='20260819') "
        "SELECT m.id, CASE WHEN m.v='' THEN d.v ELSE m.v END AS v "
        "FROM tmp.mid m LEFT JOIN app.t d ON m.id=d.id AND d.dt='20260818'"
    )
    assert len(refs) == 1
    annotation = refs[0]
    assert annotation["alias"] == "d"
    assert annotation["partition_column"] == "dt"
    assert annotation["partition_offset_days"] == -1
    assert annotation["offset_proven"] is True


def test_dashed_date_literals_also_prove_the_offset() -> None:
    _, refs = _self_ref(
        "INSERT OVERWRITE TABLE app.t PARTITION (dt='2026-08-19') "
        "SELECT m.id, m.v FROM tmp.mid m "
        "LEFT JOIN app.t d ON m.id=d.id AND d.dt='2026-08-18'"
    )
    assert refs and refs[0]["partition_offset_days"] == -1
    assert refs[0]["offset_proven"] is True


def test_non_literal_partition_predicate_stays_unproven() -> None:
    _, refs = _self_ref(
        "INSERT OVERWRITE TABLE app.t "
        "SELECT m.id, m.v FROM tmp.mid m "
        "LEFT JOIN app.t d ON m.id=d.id AND d.dt = m.dt"
    )
    assert len(refs) == 1
    assert refs[0]["offset_proven"] is False
    assert "partition_offset_days" not in refs[0]


def test_non_target_self_join_is_not_annotated() -> None:
    _, refs = _self_ref(
        "INSERT INTO mart.out SELECT b.id FROM ods.nodes b "
        "LEFT JOIN ods.nodes d ON b.parent_id = d.id",
        schema={"ods.nodes": ["id", "parent_id"], "mart.out": ["id"]},
    )
    assert refs == []


def test_renderer_states_the_self_reference_under_the_join() -> None:
    result = parse_scope_lineage(
        "INSERT OVERWRITE TABLE app.t PARTITION (dt='20260819') "
        "SELECT m.id, CASE WHEN m.v='' THEN d.v ELSE m.v END AS v "
        "FROM tmp.mid m LEFT JOIN app.t d ON m.id=d.id AND d.dt='20260818'",
        "case",
        schema=SCHEMA,
    )
    rendered = render_mapping_markdown(to_lineage_dict(result))
    assert "  - 目标表自引用：分区偏移 -1 天（dt：20260818 ← 目标 20260819）" in rendered


def test_renderer_states_the_unproven_self_reference() -> None:
    result = parse_scope_lineage(
        "INSERT OVERWRITE TABLE app.t "
        "SELECT m.id, m.v FROM tmp.mid m "
        "LEFT JOIN app.t d ON m.id=d.id AND d.dt = m.dt",
        "case",
        schema=SCHEMA,
    )
    rendered = render_mapping_markdown(to_lineage_dict(result))
    assert "  - 目标表自引用：分区偏移未证实（无可比字面日期）" in rendered
