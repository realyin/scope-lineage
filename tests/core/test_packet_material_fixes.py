"""Packet material a weaker writer copies as given (quality plan 2026-10-18, W1-W9).

Each test names its work item. Every name is synthetic.
"""

from __future__ import annotations

import re

from scope_lineage import parse_task_lineage
from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.contract.task_lineage import to_task_lineage_dict
from scope_lineage.render import semantic_text
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.semantics.packet import build_packets
from scope_lineage.semantics.packet_markdown import render_packet_markdown


def _pack(sql: str, schema: dict, meta: dict | None = None) -> dict:
    document = to_lineage_dict(parse_scope_lineage(sql, "t0", schema=schema))
    (packet,) = build_packets([(document, None)], metadata=(meta or {}).get)
    return packet


def _section(text: str, start: str, end: str) -> str:
    return text[text.index(start):text.index(end)]


# ------------------------------------------------------------------ W1 control characters

W1_SCHEMA = {"ods.src": ["k", "v"], "dw.out": ["k", "v"]}
W1_META = {
    "ods.src": {"columns": [
        {"name": "k", "type": "string", "comment": "键\x00"},
        {"name": "v", "type": "string", "comment": "值\x01\x1f\t说明"},
    ]},
}


def test_w1_packet_md_holds_no_c0_control_character_but_tab_and_newline() -> None:
    packet = _pack("INSERT OVERWRITE TABLE dw.out SELECT s.k, s.v FROM ods.src s",
                   W1_SCHEMA, W1_META)
    text = render_packet_markdown(packet)
    assert not re.search(r"[\x00-\x08\x0b-\x1f\x7f]", text)
    assert "| 键 |" in text and "值\t说明" in text


# ------------------------------------------------------------------ W2 extra ON conditions

W2_SCHEMA = {"ods.a": ["k", "flag"], "ods.b": ["k", "v", "st", "ts"], "dw.out": ["k", "v"]}
W2_SQL = (
    "INSERT OVERWRITE TABLE dw.out SELECT a.k, b.v FROM ods.a a LEFT JOIN ("
    "SELECT k, v, st, row_number() OVER (PARTITION BY k ORDER BY ts DESC) rn FROM ods.b) b "
    "ON a.k = b.k AND b.rn = 1 AND b.st = '1' AND a.flag <> 'x'"
)


def _usages(packet: dict, table: str) -> dict[str, list[str]]:
    entry = next(item for item in packet["inputs"] if item["table"] == table)
    return {column["name"]: column["usages"] for column in entry["columns"]}


def test_w2_a_physical_column_in_an_extra_on_condition_is_a_join_condition_usage() -> None:
    packet = _pack(W2_SQL, W2_SCHEMA)
    assert "join_condition" in _usages(packet, "ods.b")["st"]
    assert "join_condition" in _usages(packet, "ods.a")["flag"]


def test_w2_a_derived_column_in_an_extra_on_condition_lends_no_usage_to_its_inputs() -> None:
    packet = _pack(W2_SQL, W2_SCHEMA)
    assert "join_condition" not in _usages(packet, "ods.b")["ts"]
    assert "join_condition" not in _usages(packet, "ods.b")["k"]


def test_w2_packet_md_no_longer_calls_an_on_condition_column_read_unused() -> None:
    text = render_packet_markdown(_pack(W2_SQL, W2_SCHEMA))
    row = next(line for line in text.splitlines() if line.startswith("| `st` |"))
    assert "join_condition" in row and "读入未用" not in row


# ------------------------------------------------------------------ W3 qualifiers kept


def test_w3_a_name_under_two_qualifiers_keeps_its_qualifiers() -> None:
    node = semantic_text.parse_expression(
        "NOT a.id IS NULL AND NOT b.id IS NULL AND a.h <> b.h AND a.only_a = 1")
    text = semantic_text.expression_text(node)
    assert "a.id" in text and "b.id" in text and "a.h <> b.h" in text
    assert "only_a = 1" in text and "a.only_a" not in text


def test_w3_names_under_one_qualifier_still_read_plain() -> None:
    node = semantic_text.parse_expression("COALESCE(a.x, b.y) + a.x")
    assert semantic_text.expression_text(node) == "COALESCE(x, y) + x"


# ------------------------------------------------------------------ W6 statement numbers

W6_SCHEMA = {"ods.src": ["k", "v"], "tmp.mid": ["k", "v"], "dw.out": ["k", "v"]}
W6_SQL = (
    "SET a=1;\n"
    "-- step one\n"
    "INSERT OVERWRITE TABLE tmp.mid SELECT s.k, s.v FROM ods.src s;\n"
    "INSERT OVERWRITE TABLE dw.out\n"
    "SELECT m.k, m.v FROM tmp.mid m; INSERT OVERWRITE TABLE tmp.mid SELECT k, v FROM dw.out;\n"
)


def _task_packet(sql: str, schema: dict, table: str) -> dict:
    document = to_task_lineage_dict(parse_task_lineage(sql, task_name="t0", schema=schema))
    (packet,) = build_packets([(document, None)], tasks=[{"name": "t0", "sql": sql}],
                              only=[table])
    return packet


def test_w6_the_task_lists_every_statement_it_writes_with() -> None:
    (task,) = _task_packet(W6_SQL, W6_SCHEMA, "dw.out")["tasks"]
    assert [(item["statement_id"], item["table"]) for item in task["writes"]] == [
        ("stmt:002", "tmp.mid"), ("stmt:003", "dw.out"), ("stmt:004", "tmp.mid")]


def test_w6_the_sql_block_numbers_each_write_statement() -> None:
    text = render_packet_markdown(_task_packet(W6_SQL, W6_SCHEMA, "dw.out"))
    sql = text[text.index("```sql"):]
    lines = sql.splitlines()
    first = lines.index("-- [stmt:002] 写 tmp.mid")
    assert lines[first - 1] == "-- step one"
    assert lines[first + 1].startswith("INSERT OVERWRITE TABLE tmp.mid")
    second = lines.index("-- [stmt:003] 写 dw.out")
    assert lines[second + 1] == "INSERT OVERWRITE TABLE dw.out"
    third = lines.index("-- [stmt:004] 写 tmp.mid")
    assert lines[third - 1] == "SELECT m.k, m.v FROM tmp.mid m;"
    assert lines[third + 1].startswith("INSERT OVERWRITE TABLE tmp.mid SELECT k, v")
    assert "SET a=1;" in lines


def test_w6_a_script_of_one_write_gets_no_numbers() -> None:
    sql = "SET a=1;\nINSERT OVERWRITE TABLE dw.out SELECT s.k, s.v FROM ods.src s;\n"
    packet = _task_packet(sql, W6_SCHEMA, "dw.out")
    assert "writes" not in packet["tasks"][0]
    assert "-- [stmt:" not in render_packet_markdown(packet)
