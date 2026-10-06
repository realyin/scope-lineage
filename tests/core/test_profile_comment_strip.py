"""The profile's ``expression`` texts are the SQL with its comments taken out.

A comment is a note to the next engineer, not part of what an expression computes. The
profile already lifts every note into ``sql_comments``; it used to also leave it inside
``expression``, so the same note was published twice -- and a reader judging the text
(is this filter an equality?) judged the comment too: ``dt = 'x' /* and s <> 'y' */``
read as a range. Six places write an expression: filter, JOIN (its condition and its
extra conditions) and CASE rules, a field, a derivation step, and the stage's JOIN
sentence. Every fixture is synthetic.
"""

from __future__ import annotations

import json

import pytest

from scope_lineage import build_semantic_profile
from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.render.semantic_markdown import render_semantic_markdown
from scope_lineage.render.semantic_profile import _without_comments
from scope_lineage.scope.scope_builder import parse_scope_lineage

from .table_semantics_demo import pack, packet_of, parse_corpus, write_json

SCHEMA = {
    "ods.t_a": ["k", "s", "x", "dt"],
    "ods.t_b": ["k", "s", "v", "dt"],
    "dw.t_out": ["k", "v", "c", "dt"],
}


def _profile(sql: str, schema: dict | None = None) -> dict:
    return build_semantic_profile(
        to_lineage_dict(parse_scope_lineage(sql, "comment_case", schema=schema or SCHEMA))
    )


def test_without_comments_keeps_the_sql_and_drops_only_the_comment():
    assert _without_comments("`t`.`dt` = '2026-01-01' /* and t.x <> 'y' */") == (
        "`t`.`dt` = '2026-01-01'"
    )
    assert _without_comments("a.k /* key */ = b.k") == "a.k = b.k"
    assert _without_comments("a.k = b.k /* */") == "a.k = b.k"
    # A comment marker inside a literal is text, not a comment.
    assert _without_comments("a.s = '/* not a comment */'") == "a.s = '/* not a comment */'"
    assert _without_comments("a.s = 'x  y'") == "a.s = 'x  y'"
    assert _without_comments(None) is None


def test_a_filter_rule_publishes_the_condition_and_keeps_its_comment_apart():
    profile = _profile(
        "INSERT OVERWRITE TABLE dw.t_out SELECT t.k, t.s, t.x, t.dt FROM ods.t_a t "
        "WHERE t.dt = '2026-01-01' /* and t.x <> 'y' */"
    )
    rule = next(item for item in profile["rules"] if item["kind"] == "filter")
    assert "/*" not in rule["expression"]
    assert rule["sql_comments"] == ["and t.x <> 'y'"]


def test_a_join_rule_and_its_sentence_carry_no_comment_text():
    profile = _profile(
        "INSERT OVERWRITE TABLE dw.t_out SELECT a.k, b.v, a.s, a.dt FROM ods.t_a a "
        "LEFT JOIN ods.t_b b ON a.k = b.k AND b.dt = '2026-01-01' /* and b.s <> 'x' */"
    )
    rule = next(item for item in profile["rules"] if item["kind"] == "join_condition")
    assert "/*" not in rule["expression"]
    assert rule["extra_conditions"]
    assert all("/*" not in item for item in rule["extra_conditions"])
    assert rule["sql_comments"]
    join = next(
        action
        for stage in profile["stages"]
        for action in stage["actions"]
        if action["type"] == "join"
    )
    assert "/*" not in join["text"] and "/*" not in join["expression"]
    markdown = render_semantic_markdown(profile)
    assert "/*" not in markdown
    assert "（注释：" in markdown


def test_an_empty_comment_leaves_neither_text_nor_a_comment_list():
    profile = _profile(
        "INSERT OVERWRITE TABLE dw.t_out SELECT a.k, b.v, a.s, a.dt FROM ods.t_a a "
        "JOIN ods.t_b b ON a.k = b.k /* */"
    )
    rule = next(item for item in profile["rules"] if item["kind"] == "join_condition")
    assert "/*" not in rule["expression"]
    assert "sql_comments" not in rule


def test_a_field_and_its_steps_publish_the_expression_without_the_comment():
    profile = _profile(
        "INSERT OVERWRITE TABLE dw.t_out SELECT t.k, t.x + 1 /* 加一 */ AS v, "
        "CASE WHEN t.s = 'A' /* 甲 */ THEN 'a' ELSE 'b' END AS c, t.dt FROM ods.t_a t"
    )
    assert "/*" not in json.dumps(
        [profile["fields"], profile["rules"], profile["stages"]], ensure_ascii=False
    )
    field = next(item for item in profile["fields"] if item["column"] == "v")
    assert field["sql_comments"] == ["加一"]
    case = next(item for item in profile["rules"] if item["kind"] == "case_branch")
    assert case["sql_comments"]


def test_a_merge_assignment_comment_moves_from_the_expression_to_sql_comments():
    schema = {"dw.ev_tgt": ["k", "v", "w"], "ods.ev_src": ["k", "v", "w"]}
    sql = """MERGE INTO dw.ev_tgt target
USING (SELECT k, v, w FROM ods.ev_src) source
ON target.k = source.k
WHEN MATCHED THEN UPDATE SET target.v = source.v / 1000 /* 备注 */, target.w = source.w
WHEN NOT MATCHED THEN INSERT *
"""
    profile = _profile(sql, schema)
    fields = [item for item in profile["fields"] if item["column"] == "v"]
    assert any("备注" in (item.get("sql_comments") or []) for item in fields)
    assert all("/*" not in str(item["expression"]) for item in fields)


TARGET = "demo_dwd.dwd_flow_df"


def _column(name: str, index: int, partition: int | None = None) -> dict:
    column = {"columnName": name, "columnType": "string", "columnComment": name,
              "columnIndex": index}
    if partition is not None:
        column["isPartition"] = partition
    return column


@pytest.fixture(scope="module")
def packet(tmp_path_factory) -> dict:
    work = tmp_path_factory.mktemp("comment_strip")
    corpus = work / "corpus"
    sql = (
        f"INSERT OVERWRITE TABLE {TARGET} PARTITION (dt = '2026-01-01')\n"
        "SELECT t.flow_no, t.status FROM demo_ods.ods_flow_df t\n"
        "WHERE t.dt = '2026-01-01' /* and t.status <> 'DELETE' */"
    )
    write_json(corpus / "tasks" / "dwd_flow_daily.json", {"meta": {
        "task_name": "dwd_flow_daily", "schedule_cycle": "day", "sql": sql,
    }})
    write_json(corpus / "schema_info.json", {"tables": [
        {"table_name": "demo_ods.ods_flow_df", "table_desc": "flow", "is_partition": "1",
         "schema": [_column("flow_no", 0), _column("status", 1), _column("dt", 2, 1)]},
        {"table_name": TARGET, "table_desc": "flow", "is_partition": "1",
         "schema": [_column("flow_no", 0), _column("status", 1), _column("dt", 2, 1)]},
    ]})
    lineage = parse_corpus(corpus, work / "lineage")
    assert pack(corpus, lineage, work / "packets") == 0
    return packet_of(work / "packets", TARGET)


def test_a_commented_partition_equality_is_read_as_an_equality(packet: dict):
    item = next(i for i in packet["inputs"] if i["table"] == "demo_ods.ods_flow_df")
    assert item["partition_read"] == "equality"
    assert item["full_snapshot"] is True
    assert all("/*" not in str(rule.get("expression")) for rule in packet["lineage"]["rules"])
