"""WI-2.2 part B: how the semantic view consumes comments and task metadata.

The rule the whole module defends: **a comment is a quotation, not a fact this view
derived.** It is copied verbatim, it carries its own evidence label (``SQL注释``), it
never goes inside a code span, and it never changes a structural verdict. The metric
card's ``refresh`` slot is the one place where task metadata fills a slot that used to be
``null`` -- and it stays ``null`` when nothing supplied a cadence.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scope_lineage import parse_task_lineage
from scope_lineage.contract import to_lineage_dict
from scope_lineage.contract.task_lineage import to_task_lineage_dict
from scope_lineage.render.semantic_markdown import (
    HEADER_COMMENTS_TITLE,
    TAG_SQL_COMMENT,
    render_semantic_markdown,
)
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.render.semantic_text import (
    COMMENT_KIND_COMMENTED_OUT_SQL,
    COMMENT_KIND_NOTE,
    comment_kind,
)
from scope_lineage.scope.scope_builder import parse_scope_lineage


FIXTURES = Path(__file__).parent / "fixtures"
COMMENTED_TASK = FIXTURES / "task_lineage_contract" / "commented_task"
COMMENTED_STATEMENT = FIXTURES / "lineage_contract" / "commented_insert"

METRIC_SQL = """-- 头注释一
INSERT OVERWRITE TABLE mart.metric_target
SELECT
    s.customer_id AS customer_id,
    SUM(s.amount) AS total_amount -- 金额合计（元）
FROM ods.channel_event s
WHERE s.status = 'ACTIVE' -- 仅生效状态
GROUP BY s.customer_id
"""

METRIC_SCHEMA = {"ods.channel_event": ["customer_id", "amount", "status"]}


def _statement_profile(sql: str = METRIC_SQL, schema=METRIC_SCHEMA) -> dict:
    return build_semantic_profile(
        to_lineage_dict(parse_scope_lineage(sql, "wi22b", schema=schema))
    )


def _task_profile(task_meta=None) -> dict:
    result = parse_task_lineage(
        METRIC_SQL, task_name="wi22b", schema=METRIC_SCHEMA, task_meta=task_meta
    )
    return build_semantic_profile(to_task_lineage_dict(result))["statements"][0]


def _field(profile: dict, column: str) -> dict:
    return next(item for item in profile["fields"] if item["column"] == column)


def _golden(case_dir: Path) -> dict:
    lineage = json.loads((case_dir / "lineage.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((case_dir / "diagnostics.json").read_text(encoding="utf-8"))
    return build_semantic_profile(lineage, diagnostics)


# ------------------------------------------------------------ 1. task block


def test_the_task_block_carries_the_header_comments_in_order() -> None:
    profile = _golden(COMMENTED_STATEMENT)
    assert profile["task"]["header_comments"] == [
        "任务：客户渠道汇总（合成示例）",
        "口径：仅统计生效状态的客户",
        # the address in the third header line is masked at parse time; the sentence
        # around it reaches the derived view unchanged
        "口径问题联系 <email>（合成地址）",
    ]


def test_a_statement_document_has_no_task_meta_and_says_so_with_null() -> None:
    assert _statement_profile()["task"]["meta"] is None


def test_a_task_document_hands_its_meta_to_every_statement_profile() -> None:
    profile = _golden(COMMENTED_TASK)["statements"][0]
    assert profile["task"]["meta"]["owner"] == "demo_owner"
    assert profile["task"]["meta"]["schedule_cycle"] == "DAY"


# ------------------------------------------------------------ 2. fields[].sql_comments


def test_a_commented_output_reaches_its_field() -> None:
    assert _field(_statement_profile(), "total_amount")["sql_comments"] == [
        "金额合计（元）"
    ]


def test_an_uncommented_field_omits_the_key() -> None:
    assert "sql_comments" not in _field(_statement_profile(), "customer_id")


def test_a_comment_written_upstream_travels_down_the_chain() -> None:
    """The note belongs to the value, not to the scope it was finally projected in."""
    sql = (
        "INSERT OVERWRITE TABLE mart.t\n"
        "WITH staged AS (\n"
        "  SELECT s.customer_id AS customer_id, -- 客户号（上游注释）\n"
        "         s.amount AS amount\n"
        "  FROM ods.channel_event s\n"
        ")\n"
        "SELECT staged.customer_id, staged.amount FROM staged"
    )
    profile = _statement_profile(sql)
    assert _field(profile, "customer_id")["sql_comments"] == ["客户号（上游注释）"]


def test_the_summary_quotes_only_the_alias_comment_and_labels_it() -> None:
    summary = _field(_statement_profile(), "total_amount")["summary"]
    assert summary.endswith("；注释：金额合计（元）")


def test_a_field_without_a_comment_gets_no_suffix() -> None:
    assert "；注释：" not in _field(_statement_profile(), "customer_id")["summary"]


# ------------------------------------------------ 3. rules[] and stages[].actions[]


def test_a_filter_rule_carries_the_comment_written_on_it() -> None:
    rule = next(
        item for item in _statement_profile()["rules"] if item["kind"] == "filter"
    )
    assert rule["sql_comments"] == ["仅生效状态"]


def test_an_uncommented_rule_omits_the_key() -> None:
    profile = _golden(COMMENTED_STATEMENT)
    case_rule = next(
        item for item in profile["rules"] if item["kind"] == "case_branch"
    )
    assert "sql_comments" not in case_rule


def test_the_matching_stage_action_carries_the_same_comment() -> None:
    stage = next(
        item for item in _statement_profile()["stages"] if item["scope_id"] == "ROOT"
    )
    action = next(item for item in stage["actions"] if item["type"] == "filter")
    assert action["sql_comments"] == ["仅生效状态"]


def test_a_join_action_and_its_rule_agree() -> None:
    profile = _golden(COMMENTED_STATEMENT)
    rule = next(
        item for item in profile["rules"] if item["kind"] == "join_condition"
    )
    stage = next(item for item in profile["stages"] if item["scope_id"] == "ROOT")
    action = next(item for item in stage["actions"] if item["type"] == "join")
    assert rule["sql_comments"] == action["sql_comments"] == ["按渠道编码补充维度"]


# ------------------------------------------------------------ 4. metric refresh


def test_the_refresh_slot_stays_null_without_task_metadata() -> None:
    assert _field(_statement_profile(), "total_amount")["metric_spec"]["refresh"] is None


def test_the_refresh_slot_is_filled_from_the_task_schedule() -> None:
    profile = _task_profile({"schedule_cycle": "DAY", "schedule": "0 20 3 * * ?"})
    assert _field(profile, "total_amount")["metric_spec"]["refresh"] == {
        "cycle": "DAY",
        "cron": "0 20 3 * * ?",
        "source": "task_meta",
    }


def test_metadata_without_a_cadence_leaves_the_slot_null() -> None:
    profile = _task_profile({"owner": "demo_owner"})
    assert _field(profile, "total_amount")["metric_spec"]["refresh"] is None


def test_the_markdown_reads_the_cycle_and_names_the_cron() -> None:
    rendered = render_semantic_markdown(
        _task_profile({"schedule_cycle": "DAY", "schedule": "0 20 3 * * ?"})
    )
    assert "- 更新频率：每日（cron `0 20 3 * * ?`）" in rendered


def test_an_unlisted_cycle_name_is_printed_as_the_exporter_wrote_it() -> None:
    rendered = render_semantic_markdown(_task_profile({"schedule_cycle": "FORTNIGHT"}))
    assert "- 更新频率：FORTNIGHT" in rendered


# ------------------------------------------------------------ 5. comment counts


def test_the_comment_counts_are_reported_by_where_they_were_written() -> None:
    coverage = _golden(COMMENTED_STATEMENT)["confidence"]["metadata_coverage"]
    assert coverage["sql_comment_counts"] == {"header": 3, "output": 3, "logic": 2}


def test_a_statement_without_comments_counts_zero_rather_than_omitting_the_key() -> None:
    profile = _statement_profile("INSERT INTO mart.t SELECT 1 AS id")
    assert profile["confidence"]["metadata_coverage"]["sql_comment_counts"] == {
        "header": 0,
        "output": 0,
        "logic": 0,
    }


# ------------------------------------------------------------ 6. the markdown


def test_section_one_quotes_the_header_block_as_a_blockquote() -> None:
    rendered = render_semantic_markdown(_golden(COMMENTED_STATEMENT))
    assert f"{HEADER_COMMENTS_TITLE}（{TAG_SQL_COMMENT}）：" in rendered
    assert "> 任务：客户渠道汇总（合成示例）" in rendered
    assert "> 口径：仅统计生效状态的客户" in rendered


def test_a_document_without_header_comments_prints_no_such_block() -> None:
    rendered = render_semantic_markdown(
        _statement_profile("INSERT INTO mart.t SELECT 1 AS id")
    )
    assert HEADER_COMMENTS_TITLE not in rendered


def test_section_one_prints_the_task_metadata_line_only_when_there_is_one() -> None:
    with_meta = render_semantic_markdown(_golden(COMMENTED_TASK)["statements"][0])
    assert "- 任务元信息：项目 demo_project；负责人 demo_owner；调度周期 DAY" in with_meta
    assert "- 任务元信息：" not in render_semantic_markdown(_statement_profile())


def test_the_rules_table_has_its_own_comment_column() -> None:
    rendered = render_semantic_markdown(_golden(COMMENTED_STATEMENT))
    header = next(
        line for line in rendered.splitlines() if line.startswith("| 规则 |")
    )
    assert header.endswith("| 涉及字段（注释） | SQL注释 | 分区过滤 | 证据 |")
    row = next(line for line in rendered.splitlines() if line.startswith("| rule:"))
    assert row.count(" | ") == header.count(" | ")


def test_an_uncommented_rule_row_writes_an_em_dash() -> None:
    rendered = render_semantic_markdown(_golden(COMMENTED_STATEMENT))
    rows = [line for line in rendered.splitlines() if line.startswith("| rule:")]
    assert any(" | — | " in row for row in rows)


def test_a_field_subsection_carries_its_own_comment_line() -> None:
    rendered = render_semantic_markdown(_golden(COMMENTED_STATEMENT))
    assert f"- 注释：金额合计（元）（{TAG_SQL_COMMENT}）" in rendered


def test_a_stage_action_line_ends_with_its_comment() -> None:
    rendered = render_semantic_markdown(_golden(COMMENTED_STATEMENT))
    line = next(
        item
        for item in rendered.splitlines()
        if item.strip().startswith("- 过滤：")
    )
    assert line.endswith("（SQL事实；证据 logic:ROOT:filter:001）")
    assert f"（注释：仅生效状态；{TAG_SQL_COMMENT}）" in line


# ------------------------------------------- 7. comments stay out of the SQL grammar


_CODE_SPAN = re.compile(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.DOTALL)


@pytest.mark.parametrize("case_dir", [COMMENTED_STATEMENT, COMMENTED_TASK])
def test_no_rendered_comment_is_put_inside_a_code_span(case_dir: Path) -> None:
    """A code span in this document means verbatim SQL, which the anti-fabrication scan
    reads as identifiers. Free text there would be scanned as one."""
    profile = _golden(case_dir)
    if "statements" in profile:
        profile = profile["statements"][0]
    rendered = render_semantic_markdown(profile)
    comments = {
        *(profile["task"]["header_comments"]),
        *(
            comment
            for field in profile["fields"]
            for comment in field.get("sql_comments") or []
        ),
        *(
            comment
            for rule in profile["rules"]
            for comment in rule.get("sql_comments") or []
        ),
    }
    assert comments, "premise: these cases carry comments"
    spans = [span for _, span in _CODE_SPAN.findall(rendered)]
    for comment in comments:
        # A comment may appear inside a span only because the *contract expression* it
        # was written into carries it inline; nothing this renderer composes puts it
        # there on its own, so the check is that no span is the bare comment.
        assert not any(span.strip() == comment for span in spans), comment


def test_a_comment_naming_a_table_does_not_change_what_the_summary_claims() -> None:
    """A comment is the author's text. It must not be read as a source this view proved."""
    sql = (
        "INSERT OVERWRITE TABLE mart.t\n"
        "SELECT s.customer_id AS customer_id -- 口径同 nowhere.no_such_table.no_such_col\n"
        "FROM ods.channel_event s"
    )
    profile = _statement_profile(sql)
    field = _field(profile, "customer_id")
    assert "nowhere.no_such_table.no_such_col" in field["summary"]
    assert [source["table"] for source in field["sources"]] == ["ods.channel_event"]


# --------------------------------- WI-2.8 D9: a comment that IS SQL is not a note

COMMENTED_OUT_SQL = """INSERT OVERWRITE TABLE mart.metric_target
SELECT
    s.customer_id AS customer_id, -- cast(null as string) as customer_id
    SUM(s.amount) AS total_amount -- 金额合计（元）
FROM ods.channel_event s
GROUP BY s.customer_id
"""


def _commented_fields() -> dict:
    document = to_lineage_dict(
        parse_scope_lineage(COMMENTED_OUT_SQL, "commented_out", schema=METRIC_SCHEMA)
    )
    profile = build_semantic_profile(document)
    return {item["column"]: item for item in profile["fields"]}


def test_a_commented_out_expression_is_kept_out_of_the_fields_comments() -> None:
    """It records what the code USED to do, never what the column means."""
    field = _commented_fields()["customer_id"]

    assert "sql_comments" not in field
    assert "cast(null as string)" not in field["summary"]


def test_a_prose_comment_beside_a_column_is_still_published() -> None:
    field = _commented_fields()["total_amount"]

    assert field["sql_comments"] == ["金额合计（元）"]
    assert "金额合计（元）" in field["summary"]


@pytest.mark.parametrize(
    "text",
    [
        "cast(null as string) as source_lead",
        "coalesce(a, b) AS fallback",
        "select 1 from dual",
        "sum(amount) as total",
    ],
)
def test_a_body_that_parses_into_sql_is_called_commented_out_code(text: str) -> None:
    assert comment_kind(text) == COMMENT_KIND_COMMENTED_OUT_SQL


@pytest.mark.parametrize(
    "text",
    [
        "金额合计（元）",
        "金额(元)",
        "仅生效状态",
        "这里 cast 过的字段",
        "user as defined by risk",
        "amount",
        "",
        "   ",
    ],
)
def test_anything_the_parser_cannot_prove_is_sql_stays_a_note(text: str) -> None:
    """The conservative side: a misread note loses an explanation, so it must not happen."""
    assert comment_kind(text) == COMMENT_KIND_NOTE
