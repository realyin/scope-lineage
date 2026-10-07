"""What the 说明 column of a packet's rules table says, and in which order.

Several facts end up in one cell: the rule's own text, where a filter sits relative to a
LEFT JOIN, the author's notes, the SQL somebody switched off beside the condition (C-P2),
whether anybody reads a CASE, and the findings about the rule. They are joined in one
fixed order (README 裁决 11), so a later change only fills its own place. Every name is
synthetic.
"""

from __future__ import annotations

from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.semantics.packet import build_packets
from scope_lineage.semantics.packet_markdown import _rule_note, render_packet_markdown

SCHEMA = {"ods.t_a": ["k", "s", "x", "dt"], "dw.t_out": ["k", "v", "c", "dt"]}


def _pack(sql: str) -> dict:
    document = to_lineage_dict(parse_scope_lineage(sql, "t0", schema=SCHEMA))
    (packet,) = build_packets([(document, None)])
    return packet


def _row(packet: dict, rule_id: str) -> str:
    return next(line for line in render_packet_markdown(packet).splitlines()
                if line.startswith(f"| {rule_id} |"))


def test_a_rules_switched_off_sql_is_carried_and_said_to_have_no_effect() -> None:
    packet = _pack(
        "INSERT OVERWRITE TABLE dw.t_out SELECT t.k, t.s AS v, t.x AS c, t.dt FROM ods.t_a t "
        "WHERE t.dt = '2026-01-01' /* and t.x <> 'y' */"
    )
    (rule,) = [rule for rule in packet["lineage"]["rules"] if rule["kind"] == "filter"]
    assert rule["commented_out_sql"] == ["and t.x <> 'y'"]
    assert "sql_comments" not in rule
    assert "相邻的注释掉的 SQL（不生效）：and t.x <> 'y'" in _row(packet, rule["id"])


def test_a_rule_without_switched_off_sql_carries_no_key() -> None:
    packet = _pack(
        "INSERT OVERWRITE TABLE dw.t_out SELECT t.k, t.s AS v, t.x AS c, t.dt FROM ods.t_a t "
        "WHERE t.dt = '2026-01-01' /* 只要当天 */"
    )
    (rule,) = [rule for rule in packet["lineage"]["rules"] if rule["kind"] == "filter"]
    assert "commented_out_sql" not in rule
    assert rule["sql_comments"] == ["只要当天"]


def test_the_note_parts_come_in_one_fixed_order() -> None:
    rule = {
        "id": "p3", "kind": "filter", "text": "规则文字",
        "right_of": ["p1"],
        "sql_comments": ["作者说明"],
        "commented_out_sql": ["and t.x <> 'y'"],
        "consumed": False,
    }
    findings = [{"text": "线索文字", "rules": ["p3"]}, {"text": "别的规则", "rules": ["p9"]}]
    note = _rule_note(rule, findings)
    parts = ["规则文字", "在 p1 右侧", "注释：作者说明", "相邻的注释掉的 SQL（不生效）",
             "未被消费", "线索文字"]
    positions = [note.index(part) for part in parts]
    assert positions == sorted(positions)
    assert "别的规则" not in note


def test_an_empty_note_is_a_dash() -> None:
    assert _rule_note({"id": "p1", "kind": "filter"}, []) == "—"
