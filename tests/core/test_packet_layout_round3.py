"""Round 3 ``packet.md`` layout (D-G4, D-G5, D-G7b): rendering only, the JSON does not move.

- a long 4.1 step chain says its computing steps first -- the direct projections and
  UNION merges left out, a repeated step listed once -- and falls back to its last step
  only when those still do not fit, or there are none (G5);
- 4.1 and 4.2 say once, under their heading, that a one-argument ``FROM_UNIXTIME`` /
  ``UNIX_TIMESTAMP`` carries the default format, which SQLGlot leaves out (G4);
- section 3's partition read names a partition column no condition fixes, with its
  comment, when another partition column is fixed (G7b).

Every name is synthetic.
"""

from __future__ import annotations

import copy

import pytest

from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.render import semantic_text
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.semantics.packet import build_packets, packet_digest
from scope_lineage.semantics.packet_markdown import (
    DEFAULT_TIME_FORMAT_NOTE,
    STEPS_CELL_LIMIT,
    _steps,
    render_packet_markdown,
)

SCHEMA = {
    "ods.ev": ["k", "ts", "s", "dt", "src"],
    "dw.t_out": ["k", "d", "u"],
}

META = {
    "ods.ev": {
        "partitioned": True,
        "partition_columns": ["dt", "src"],
        "columns": [
            {"name": "k", "type": "string", "comment": "键"},
            {"name": "ts", "type": "bigint", "comment": "毫秒时间"},
            {"name": "s", "type": "string", "comment": "时间文本"},
            {"name": "dt", "type": "string", "comment": "数据日期"},
            {"name": "src", "type": "string", "comment": "来源,为x"},
        ],
    },
}.get

EVENTS = (
    "INSERT OVERWRITE TABLE dw.t_out SELECT e.k, "
    "from_unixtime(cast(e.ts / 1000 as bigint), 'yyyy-MM-dd HH:mm:ss') AS d, e.s AS u "
    "FROM ods.ev e WHERE e.dt = '20250115' "
    "AND unix_timestamp(e.s, 'yyyy-MM-dd HH:mm:ss') > 0"
)

# The digest of EVENTS' packet before this layout change: packet.md moved, packet.json
# did not, so no document written against it goes stale.
EVENTS_DIGEST = "a3fe4f3d98acc3fd"


def _pack(sql: str) -> dict:
    document = to_lineage_dict(parse_scope_lineage(sql, "t0", schema=SCHEMA))
    (packet,) = build_packets([(document, None)], metadata=META)
    return packet


def _section(text: str, start: str, end: str) -> str:
    return text[text.index(start):text.index(end)]


def _partition_line(text: str, table: str) -> str:
    section = _section(text, f"### `{table}`", "## 4.")
    return next(line for line in section.splitlines() if "分区读取" in line)


# ------------------------------------------------------------------ the JSON does not move


def test_the_packet_json_is_the_one_before_the_layout_change() -> None:
    packet = _pack(EVENTS)
    before = copy.deepcopy(packet)
    text = render_packet_markdown(packet)
    assert packet == before
    assert packet_digest(packet) == packet["packet_digest"] == EVENTS_DIGEST
    assert DEFAULT_TIME_FORMAT_NOTE in text and "未限定的分区列" in text


# ------------------------------------------------------------------ G5 computing steps


def test_a_long_chain_says_its_computing_steps_first() -> None:
    steps = ([f"直接投影自 subq:s{index}.k" for index in range(5)] + ["表达式 X"]
             + ["合并 2 个分支（来自 b1、b2）", "合并上游分支", "表达式 X", "空值回填为 ''"]
             + [f"直接投影自 subq:t{index}.kkkkkkkkkkkkkkkkkkkkkkkkkkkkkk" for index in range(8)])
    assert len("；".join(steps)) > STEPS_CELL_LIMIT
    said = _steps({"steps": steps}, "头注释：2025-01-01 才加入")
    assert said.startswith("头注释：2025-01-01 才加入；计算步骤：表达式 X；空值回填为 ''（")
    assert "略去 15 个直接投影 / 合并步骤、1 个重复步骤" in said
    assert "packet.json 该列 producers[].steps" in said
    assert "末层" not in said and "subq:" not in said


def test_computing_steps_that_still_do_not_fit_fall_back_to_the_last_step() -> None:
    steps = ["直接投影自 subq:a.k", "表达式 " + "y" * STEPS_CELL_LIMIT, "直接投影自 subq:b.k"]
    said = _steps({"steps": steps})
    assert said.startswith("末层：直接投影自 subq:b.k（共 3 步")
    assert "计算步骤" not in said


def test_a_long_chain_of_pass_throughs_only_says_it_computes_nothing() -> None:
    """B-T3a: 「末层」 of a chain that only passes its value on hides that nothing computes it."""
    steps = [f"直接投影自 subq:s{index}.k" for index in range(40)] + ["合并上游分支"]
    said = _steps({"steps": steps})
    assert said == ("全部 41 步都是直接投影 / 合并，没有计算步骤（来源见「来源列」；"
                    "完整步骤见同目录 packet.json 该列 producers[].steps）")
    assert "末层" not in said and "计算步骤：" not in said


def test_a_pass_through_chain_keeps_its_comments_before_saying_it_computes_nothing() -> None:
    steps = [f"直接投影自 subq:s{index}.kkkkkkkkkk" for index in range(12)]
    assert len("；".join(steps)) > STEPS_CELL_LIMIT
    said = _steps({"steps": steps, "sql_comments": ["作者说明"]}, "头注释：2025-01-01 才加入")
    assert said.startswith("头注释：2025-01-01 才加入；注释：作者说明；全部 12 步都是直接投影 / 合并")


def test_a_short_chain_is_untouched() -> None:
    steps = ["直接投影自 ods.a.k", "表达式 X", "直接投影自 subq:a.k"]
    assert _steps({"steps": steps}) == "；".join(steps)


def test_every_pass_through_step_type_words_its_step_with_its_prefix() -> None:
    """The renderer tells a pass-through by its words; the words and the types stay one set."""
    prefixes = semantic_text.PASS_THROUGH_TEXT_PREFIXES
    assert set(prefixes) == set(semantic_text.PASS_THROUGH_STEP_TYPES)
    for step_type, prefix in prefixes.items():
        for inputs in ([], ["subq:a.k"], ["subq:a.k", "subq:b.k"]):
            text = semantic_text.describe_step(step_type, None, input_fields=inputs)
            assert text.startswith(prefix), (step_type, text)


@pytest.mark.parametrize(("step_type", "expression"), [
    ("expression", "concat(a, b)"),
    ("case_when", "case when a = 1 then 'x' else 'y' end"),
    ("aggregate", "sum(a)"),
    ("constant", "'x'"),
    ("window", "row_number() over (partition by a order by b)"),
])
def test_a_computing_step_does_not_read_as_a_pass_through(step_type, expression) -> None:
    text = semantic_text.describe_step(step_type, expression, input_fields=["a", "b"]) or ""
    assert not text.startswith(tuple(semantic_text.PASS_THROUGH_TEXT_PREFIXES.values()))


# ------------------------------------------------------------------ G4 default time format


def test_a_one_argument_unix_time_call_gets_one_note_in_4_1_and_in_4_2() -> None:
    text = render_packet_markdown(_pack(EVENTS))
    assert "FROM_UNIXTIME(CAST(" in text and "UNIX_TIMESTAMP(" in text
    rows = [line for line in _section(text, "## 4.", "### 4.3").splitlines()
            if line.startswith("|")]
    assert not any("'yyyy-MM-dd HH:mm:ss'" in row for row in rows)
    assert _section(text, "### 4.1", "### 4.2").count(DEFAULT_TIME_FORMAT_NOTE) == 1
    assert _section(text, "### 4.2", "### 4.3").count(DEFAULT_TIME_FORMAT_NOTE) == 1
    assert "默认的 'yyyy-MM-dd HH:mm:ss'" in DEFAULT_TIME_FORMAT_NOTE


def test_a_written_format_gets_no_note() -> None:
    sql = (EVENTS.replace("'yyyy-MM-dd HH:mm:ss') AS d", "'yyyy-MM-dd') AS d")
           .replace("unix_timestamp(e.s, 'yyyy-MM-dd HH:mm:ss')", "unix_timestamp(e.s, 'yyyyMMdd')"))
    text = render_packet_markdown(_pack(sql))
    assert "FROM_UNIXTIME(CAST(" in text
    assert DEFAULT_TIME_FORMAT_NOTE not in text


def test_the_note_goes_only_where_the_call_is() -> None:
    sql = EVENTS.replace(" AND unix_timestamp(e.s, 'yyyy-MM-dd HH:mm:ss') > 0", "")
    text = render_packet_markdown(_pack(sql))
    assert DEFAULT_TIME_FORMAT_NOTE in _section(text, "### 4.1", "### 4.2")
    assert DEFAULT_TIME_FORMAT_NOTE not in _section(text, "### 4.2", "### 4.3")


# ------------------------------------------------------------------ G7b unfixed partition column


def test_a_partition_column_no_condition_fixes_is_named_with_its_comment() -> None:
    line = _partition_line(render_packet_markdown(_pack(EVENTS)), "ods.ev")
    assert "；未限定的分区列：`src`（注释：来源,为x）" in line
    assert "`dt`（注释" not in line


def test_every_partition_column_fixed_names_none() -> None:
    sql = EVENTS.replace("WHERE e.dt = '20250115'", "WHERE e.dt = '20250115' AND e.src = 'x'")
    assert "未限定的分区列" not in _partition_line(render_packet_markdown(_pack(sql)), "ods.ev")


def test_no_partition_condition_at_all_names_none() -> None:
    sql = EVENTS.replace("WHERE e.dt = '20250115' AND", "WHERE")
    assert "未限定的分区列" not in _partition_line(render_packet_markdown(_pack(sql)), "ods.ev")
