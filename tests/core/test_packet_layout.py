"""How ``packet.md`` lays out facts the packet already holds (C-P5, C-P8, D-G6).

These are rendering changes only; ``packet.json`` -- and so ``packet_digest`` -- does not
move, and a document written against a packet does not go stale:

- 4.2 has a 位置 column (``stmt:00N / <scope>``), so two rules with the same expression
  in two subqueries can be told apart;
- section 3 lists a partition filter or a date filter once, with the rules (``pN``) it
  comes from, instead of once per rule;
- a 4.1 step cell whose chain is long says its last step and how many steps there are,
  and points at ``packet.json`` for the rest, so no table row grows without bound;
- an input column read in (``select *``) but used by nothing says 读入未用, not 是;
- a 4.2 row whose expression holds a date literal of its task says how far that literal
  sits from the task's expected run date, as 2.x does -- an offset, never a batch date.

Every name is synthetic.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.semantics.packet import build_packets, packet_digest
from scope_lineage.semantics.packet_markdown import (
    STEPS_CELL_LIMIT,
    _rule_note,
    _rules,
    _steps,
    render_packet_markdown,
)

from .table_semantics_demo import DEMO_TABLE, EXAMPLE, demo_packets, packet_of, read_json

SCHEMA = {
    "ods.log": ["k", "s", "v", "dt"],
    "ods.shop": ["s", "name", "dt"],
    "dw.t_out": ["k", "v", "w"],
}

TWICE = (
    "INSERT OVERWRITE TABLE dw.t_out SELECT c.k, c.v, f.v AS w FROM "
    "(SELECT x.k, y.name AS v FROM ods.log x LEFT JOIN ods.shop y ON x.s = y.s "
    "WHERE x.dt = '20250115') c "
    "LEFT JOIN (SELECT x.k, max(y.name) AS v FROM ods.log x LEFT JOIN ods.shop y ON x.s = y.s "
    "WHERE x.dt = '20250115' GROUP BY x.k) f ON c.k = f.k"
)


def _pack(sql: str) -> dict:
    document = to_lineage_dict(parse_scope_lineage(sql, "t0", schema=SCHEMA))
    (packet,) = build_packets([(document, None)])
    return packet


def _row(text: str, rule_id: str) -> list[str]:
    line = next(line for line in text.splitlines() if line.startswith(f"| {rule_id} |"))
    return line.strip("| ").split(" | ")


def _section(text: str, start: str, end: str) -> str:
    return text[text.index(start):text.index(end)]


# ------------------------------------------------------------------ C-P5 位置


def test_the_rules_table_has_a_position_column() -> None:
    text = render_packet_markdown(_pack(TWICE))
    assert "| 编号 | 类型 | 位置 | 表达式 | 分区过滤 | 涉及表 | 行数放大 | 说明 |" in text


def test_the_same_join_in_two_subqueries_is_told_apart_by_its_position() -> None:
    packet = _pack(TWICE)
    first, second = [rule for rule in packet["lineage"]["rules"]
                     if rule["kind"] == "join" and rule["expression"] == "`x`.`s` = `y`.`s`"]
    text = render_packet_markdown(packet)
    one, two = _row(text, first["id"]), _row(text, second["id"])
    assert one[3] == two[3]
    assert (one[2], two[2]) == ("stmt:001 / subq:c", "stmt:001 / subq:f")


def test_a_packet_of_several_tasks_names_the_task_in_the_position() -> None:
    rules = [
        {"id": "p1", "kind": "filter", "task": "t_one", "statement_id": "stmt:001",
         "scope": "ROOT", "expression": "a.k = 1", "partition_filter": False, "tables": []},
        {"id": "p2", "kind": "filter", "task": "t_two", "statement_id": "stmt:001",
         "scope": "ROOT", "expression": "a.k = 1", "partition_filter": False, "tables": []},
    ]
    text = "\n".join(_rules(rules, []))
    assert _row(text, "p1")[2] == "t_one / stmt:001 / ROOT"
    assert _row(text, "p2")[2] == "t_two / stmt:001 / ROOT"


# ------------------------------------------------------------------ C-P5 section 3


def test_a_partition_filter_read_twice_is_listed_once_with_its_rules() -> None:
    packet = _pack(TWICE)
    ids = [rule["id"] for rule in packet["lineage"]["rules"] if rule["partition_filter"]]
    assert len(ids) == 2
    section = _section(render_packet_markdown(packet), "### `ods.log`", "### `ods.shop`")
    assert f"（`` `x`.`dt` = '20250115' ``（{ids[0]}、{ids[1]}））" in section
    assert section.count("`x`.`dt` = '20250115'") == 1


def test_a_date_filter_in_two_statements_is_listed_once_with_its_rules() -> None:
    from scope_lineage.semantics.packet_markdown import _inputs

    rule = {"kind": "filter", "task": "t", "scope": "ROOT", "partition_filter": False,
            "expression": "a.open_date >= '2025-01-01'", "tables": ["ods.src"]}
    rules = [{**rule, "id": "p1", "statement_id": "stmt:001"},
             {**rule, "id": "p4", "statement_id": "stmt:002"}]
    entry = {
        "table": "ods.src", "comment": "源", "roles": ["driving"], "driving": True,
        "layer": None, "producers": [], "partition_columns": [], "partitioned": False,
        "partition_read": "none", "partition_filters": [], "name_convention": "unknown",
        "full_snapshot": False, "columns": [],
        "date_filters": [
            {"column": "open_date", "expression": rule["expression"],
             "statement_id": "stmt:001", "shape": "window"},
            {"column": "open_date", "expression": rule["expression"],
             "statement_id": "stmt:002", "shape": "window"},
        ],
    }
    text = "\n".join(_inputs([entry], rules))
    assert "`open_date`：`a.open_date >= '2025-01-01'`（窗口；p1、p4）" in text
    assert text.count("a.open_date >= '2025-01-01'") == 1


# ------------------------------------------------------------------ C-P8 4.1 and 读入未用


def test_a_column_read_by_select_star_but_unused_says_so() -> None:
    packet = _pack(
        "INSERT OVERWRITE TABLE dw.t_out SELECT t.k, t.v, t.v AS w FROM "
        "(SELECT * FROM ods.log) t"
    )
    (log,) = [entry for entry in packet["inputs"] if entry["table"] == "ods.log"]
    unused = [column["name"] for column in log["columns"]
              if column["used"] and not column["usages"]]
    assert unused, "the star must read a column nothing uses"
    section = _section(render_packet_markdown(packet), "## 3.", "## 4.")
    for name in unused:
        assert f"| `{name}` |" in section
        line = next(line for line in section.splitlines() if line.startswith(f"| `{name}` |"))
        assert line.endswith("| 读入未用（select * 等） |")
    assert "| 是 |" not in section


def test_a_short_chain_keeps_every_step_in_its_cell() -> None:
    producer = {"steps": ["直接投影自 ods.a.k", "直接投影自 subq:a.k"]}
    assert _steps(producer) == "直接投影自 ods.a.k；直接投影自 subq:a.k"


def test_a_long_chain_says_its_last_step_and_how_many_steps_there_are() -> None:
    # One computing step too long for 「计算步骤」 keeps this chain on the 「末层」 path.
    steps = (["表达式 " + "y" * STEPS_CELL_LIMIT]
             + [f"直接投影自 subq:s{index}.k" for index in range(40)] + ["合并 3 个分支（来自 b1、b2、b3）"])
    producer = {"steps": steps, "sql_comments": ["作者说明"]}
    said = _steps(producer, "头注释：2025-01-01 才加入")
    assert said.startswith("头注释：2025-01-01 才加入；注释：作者说明；")
    assert "末层：合并 3 个分支（来自 b1、b2、b3）" in said
    assert f"共 {len(steps)} 步" in said
    assert "packet.json" in said
    assert "subq:s0" not in said
    assert len(said) < STEPS_CELL_LIMIT


def test_a_long_last_step_is_cut_at_the_limit() -> None:
    steps = [f"直接投影自 subq:s{index}.k" for index in range(20)] + ["表达式 " + "x" * 1000]
    said = _steps({"steps": steps})
    assert said.startswith("末层：表达式 xxx")
    assert "…（共 21 步" in said
    assert len(said) < 2 * STEPS_CELL_LIMIT


# ------------------------------------------------------------------ D-G6 date offsets in 4.2


TASKS = [
    {"name": "t_one", "date_literals": [
        {"literal": "'20250115'", "count": 2, "days_from_expect_date": -1},
        {"literal": "'20240101'", "count": 1, "days_from_expect_date": -380},
    ]},
    {"name": "t_two"},
]


def _dated(task: str, expression: str) -> dict:
    return {"id": "p1", "kind": "filter", "task": task, "statement_id": "stmt:001",
            "scope": "ROOT", "expression": expression, "text": "规则文字", "right_of": ["p9"],
            "partition_filter": False, "tables": []}


def test_a_rule_names_the_offset_of_its_tasks_date_literals() -> None:
    note = _rule_note(_dated("t_one", "x.dt = '20250115' AND x.b >= '20240101'"), [], TASKS)
    assert "日期字面量 '20250115'（期望日期 −1 天）、'20240101'（不在期望日期前后一个月内）" in note
    assert note.index("规则文字") < note.index("日期字面量") < note.index("在 p9 右侧")
    assert "批次日" not in note


def test_another_tasks_literal_and_an_unquoted_number_say_nothing() -> None:
    assert "日期字面量" not in _rule_note(_dated("t_two", "x.dt = '20250115'"), [], TASKS)
    assert "日期字面量" not in _rule_note(_dated("t_one", "x.dt = 20250115"), [], TASKS)
    assert "日期字面量" not in _rule_note(_dated("t_one", "x.dt = '20250115'"), [])


def test_the_rules_table_carries_the_offsets() -> None:
    text = "\n".join(_rules([_dated("t_one", "x.dt = '20250115'")], [], TASKS))
    assert "日期字面量 '20250115'（期望日期 −1 天）" in _row(text, "p1")[-1]


# ------------------------------------------------------------------ the JSON does not move


@pytest.fixture(scope="module")
def packets(tmp_path_factory) -> Path:
    return demo_packets(tmp_path_factory.mktemp("layout"))


def test_rendering_leaves_the_packet_and_its_digest_alone(packets: Path) -> None:
    packet = packet_of(packets)
    before = copy.deepcopy(packet)
    render_packet_markdown(packet)
    assert packet == before
    assert packet_digest(packet) == packet["packet_digest"]


def test_the_demo_packets_digest_is_the_one_the_example_was_stamped_with(packets: Path) -> None:
    assert packet_of(packets, DEMO_TABLE)["packet_digest"] == read_json(EXAMPLE)["packet_digest"]
