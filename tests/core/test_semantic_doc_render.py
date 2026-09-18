"""Behavioural tests for the semantic.md renderer (contract-derived view, semantic-md/1).

The load-bearing test here is the anti-fabrication property test at the bottom: every
``db.table`` / ``db.table.column`` identifier the rendered markdown puts inside a code
span must exist in the source lineage document. ``test_semantic_profile`` pins the same
property for the dict; a renderer that composes a plausible-looking id out of two real
halves would slip past that one and is caught here.

The golden baselines (``fixtures/{lineage,task_lineage}_contract/<case>/semantic.{json,md}``)
are re-recorded exactly the way mapping.md's are: build the profile from the case's
``lineage.json`` + ``diagnostics.json`` and write the two rendered artifacts back into the
case directory -- see ``_record_golden`` below, which the baseline test also uses as its
comparison, so the recording path and the asserted path cannot diverge.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.metadata.schema_metadata import load_schema
from scope_lineage.metadata.target_table_metadata import load_target_table_metadata
from scope_lineage.render.semantic_markdown import (
    DOC_FORMAT,
    SECTION_ORDER,
    render_semantic_markdown,
)
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.scope.scope_builder import parse_scope_lineage

from .statement_document import build_statement_documents


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = REPO_ROOT / "examples"
FIXTURES = Path(__file__).parent / "fixtures"

GOLDEN_GROUPS = ("lineage_contract", "task_lineage_contract")
GOLDEN_CASES = tuple(
    sorted(
        (path.parent for group in GOLDEN_GROUPS for path in (FIXTURES / group).glob("*/case.json")),
        key=lambda path: (path.parent.name, path.name),
    )
)

SECTION_TITLES = (
    "## 1. 任务概览",
    "## 2. 输出表形态与粒度",
    "## 3. 加工链路",
    "## 4. 规则清单",
    "## 5. 字段语义",
    "## 6. 可信度与边界",
    "## 7. 给 Agent 的说明",
)

FRONT_MATTER_KEYS = {
    "doc_format",
    "schema_version",
    "task_name",
    "target_table",
    "stmt_kind",
    "lineage_digest",
}


def _demo_schema():
    return load_schema(str(EXAMPLES / "metadata" / "schema_info.json"))


def _demo_target_metadata():
    return load_target_table_metadata(str(EXAMPLES / "metadata" / "target_tables"))


def _example_sql(name: str) -> str:
    return (EXAMPLES / "sql" / name).read_text(encoding="utf-8")


def _document(sql: str, task_id: str = "doc_case", schema=None, target_metadata=None) -> dict:
    return to_lineage_dict(
        parse_scope_lineage(sql, task_id, schema=schema, target_metadata=target_metadata)
    )


def _render(sql: str, *, schema=None, target_metadata=None, sections=None) -> str:
    document = _document(sql, schema=schema, target_metadata=target_metadata)
    return render_semantic_markdown(
        build_semantic_profile(document), sections=sections
    )


def _customer_profile_documents() -> tuple[dict, dict]:
    result = parse_scope_lineage(
        _example_sql("customer_profile_daily.sql"),
        "customer_profile_daily",
        schema=_demo_schema(),
        target_metadata=_demo_target_metadata(),
    )
    return build_statement_documents(result)


def _front_matter(rendered: str) -> dict:
    lines = rendered.splitlines()
    assert lines[0] == "---"
    block = {}
    for line in lines[1:]:
        if line == "---":
            return block
        key, _, value = line.partition(": ")
        block[key] = json.loads(value)
    raise AssertionError("front matter block is not closed")


# ------------------------------------------------------------------- front matter


def test_front_matter_keys_are_fixed_and_json_scalars() -> None:
    lineage, _ = _customer_profile_documents()
    block = _front_matter(render_semantic_markdown(build_semantic_profile(lineage)))

    assert set(block) == FRONT_MATTER_KEYS
    assert block["doc_format"] == DOC_FORMAT == "semantic-md/1"
    assert block["schema_version"] == "1.0"
    assert block["task_name"] == lineage["task_id"]
    assert block["target_table"] == lineage["target_table"]
    assert block["lineage_digest"] == build_semantic_profile(lineage)["lineage_digest"]


def test_the_document_carries_no_timestamp_and_renders_byte_identically() -> None:
    lineage, diagnostics = _customer_profile_documents()
    profile = build_semantic_profile(lineage, diagnostics)
    first = render_semantic_markdown(profile)
    second = render_semantic_markdown(build_semantic_profile(lineage, diagnostics))

    assert first == second
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:", first)


# ----------------------------------------------------------------------- sections


def test_all_seven_sections_render_in_fixed_order() -> None:
    lineage, diagnostics = _customer_profile_documents()
    rendered = render_semantic_markdown(build_semantic_profile(lineage, diagnostics))

    positions = [rendered.index(title) for title in SECTION_TITLES]
    assert positions == sorted(positions)
    assert len(SECTION_ORDER) == len(SECTION_TITLES)


def test_sections_filter_hides_sections_without_renumbering_them() -> None:
    lineage, _ = _customer_profile_documents()
    rendered = render_semantic_markdown(
        build_semantic_profile(lineage), sections=["shape", "agent"]
    )

    assert "## 2. 输出表形态与粒度" in rendered
    assert "## 7. 给 Agent 的说明" in rendered
    assert "## 1. 任务概览" not in rendered
    assert "## 5. 字段语义" not in rendered
    # the survivors keep their own numbers rather than becoming 1. and 2.
    assert "## 1. 输出表形态与粒度" not in rendered


def test_fields_table_switch_keeps_the_list_and_drops_the_per_field_sections() -> None:
    lineage, _ = _customer_profile_documents()
    profile = build_semantic_profile(lineage)

    full = render_semantic_markdown(profile, sections=["fields"])
    table_only = render_semantic_markdown(profile, sections=["fields_table"])

    assert "### 字段 mart.customer_profile_snapshot.customer_level" in full
    assert "### 字段 mart.customer_profile_snapshot.customer_level" not in table_only
    assert "### 完整字段清单" in table_only
    assert "| 1 | `mart.customer_profile_snapshot.customer_id` |" in table_only
    assert len(table_only) < len(full)


def test_an_unknown_section_name_is_rejected_by_name() -> None:
    lineage, _ = _customer_profile_documents()
    with pytest.raises(ValueError, match="graph"):
        render_semantic_markdown(build_semantic_profile(lineage), sections=["graph"])


def test_the_agent_section_states_the_three_fixed_lines() -> None:
    lineage, _ = _customer_profile_documents()
    rendered = render_semantic_markdown(build_semantic_profile(lineage))
    tail = rendered.split("## 7. 给 Agent 的说明", 1)[1]

    assert "事实骨架" in tail
    assert "skills/scope-lineage/references/semantic-profile-prompt.md" in tail
    assert "任何未标 `元数据事实` 的中文含义都不是业务定义" in tail
    assert len([line for line in tail.splitlines() if line.startswith("- ")]) == 3


# ------------------------------------------------------------------ stage folding

FOLDING_SQL_TEMPLATE = """
INSERT INTO mart.rollup
WITH {ctes}
SELECT {selects}
FROM ods.base b
{joins}
"""


def _many_same_shaped_scopes(count: int) -> tuple[str, dict]:
    """A SQL with ``count`` identically shaped aggregate CTEs plus ROOT."""
    ctes = ",\n".join(
        f"m{index} AS (SELECT id, SUM(v) AS s{index} FROM ods.src{index} GROUP BY id)"
        for index in range(count)
    )
    selects = ", ".join(["b.id", *[f"m{index}.s{index}" for index in range(count)]])
    joins = "\n".join(
        f"LEFT JOIN m{index} ON b.id = m{index}.id" for index in range(count)
    )
    schema = {"ods.base": ["id"], **{f"ods.src{index}": ["id", "v"] for index in range(count)}}
    return (
        FOLDING_SQL_TEMPLATE.format(ctes=ctes, selects=selects, joins=joins),
        schema,
    )


def test_more_than_twelve_same_shaped_stages_fold_into_one_table() -> None:
    sql, schema = _many_same_shaped_scopes(14)
    profile = build_semantic_profile(_document(sql, schema=schema))
    assert len(profile["stages"]) > 12, "premise: this document is past the fold threshold"

    rendered = render_semantic_markdown(profile, sections=["stages"])

    assert "以下 14 个阶段模式相同" in rendered
    # every folded scope id is listed in the table, none is silently dropped
    for index in range(14):
        assert f"| `cte:m{index}` |" in rendered
    # exactly one of them is expanded, as the group's representative
    expanded = [line for line in rendered.splitlines() if line.startswith("#### 阶段 ")]
    assert len(expanded) == 1
    assert "`cte:m0`" in expanded[0]
    assert "#### 阶段 2：" not in rendered


def test_root_is_always_expanded_even_in_a_folded_document() -> None:
    sql, schema = _many_same_shaped_scopes(14)
    rendered = render_semantic_markdown(
        build_semantic_profile(_document(sql, schema=schema)), sections=["stages"]
    )
    root_heading = [line for line in rendered.splitlines() if "（`ROOT`，角色" in line]
    assert len(root_heading) == 1
    assert root_heading[0].startswith("### 阶段 15：")


def test_twelve_or_fewer_stages_are_all_expanded() -> None:
    sql, schema = _many_same_shaped_scopes(8)
    profile = build_semantic_profile(_document(sql, schema=schema))
    assert len(profile["stages"]) <= 12

    rendered = render_semantic_markdown(profile, sections=["stages"])
    assert "模式相同" not in rendered
    headings = [line for line in rendered.splitlines() if line.startswith("### 阶段 ")]
    assert len(headings) == len(profile["stages"])


def test_a_folded_action_summary_is_truncated_not_wrapped() -> None:
    sql, schema = _many_same_shaped_scopes(14)
    rendered = render_semantic_markdown(
        build_semantic_profile(_document(sql, schema=schema)), sections=["stages"]
    )
    rows = [
        line
        for line in rendered.splitlines()
        if re.match(r"^\| \d+ \| `cte:m", line)
    ]
    assert rows
    for row in rows:
        # column 0 is the stage's topological number since WI-1g item E2.
        summary = row.split(" | ")[4]
        assert len(summary) <= 120


# ------------------------------------------------------------------ ⚠ annotations


def test_an_incomplete_trace_is_marked_and_never_claimed_complete() -> None:
    case_dir = FIXTURES / "lineage_contract" / "star_without_schema"
    lineage = json.loads((case_dir / "lineage.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((case_dir / "diagnostics.json").read_text(encoding="utf-8"))
    profile = build_semantic_profile(lineage, diagnostics)
    assert profile["confidence"]["trace_incomplete_fields"], "premise: this case is lossy"

    rendered = render_semantic_markdown(profile)
    assert "⚠ 追溯：不完整" in rendered
    assert "⚠ 追溯不完整字段：" in rendered


# Verbatim from tests/core/test_ambiguous_chain_consistency.py: a bare column, one
# derived source known to contain it, and one joined table whose schema is unknown.
AMBIGUOUS_SQL = """
INSERT OVERWRITE TABLE mart.session_summary
SELECT o.session_id AS session_id,
       CONCAT(begin_date, ' ', begin_time) AS session_start_time
FROM (
  SELECT a.session_id, a.begin_date, a.begin_time
  FROM ods.session_events a
) o
LEFT JOIN ods.session_dim g ON o.session_id = g.session_id
"""


def test_an_ambiguous_bare_column_is_flagged_not_attributed() -> None:
    """The document must say the column's source is undecided, not pick one."""
    profile = build_semantic_profile(_document(AMBIGUOUS_SQL))
    assert profile["confidence"]["ambiguous_fields"], "premise: the columns are ambiguous"

    rendered = render_semantic_markdown(profile)
    assert "⚠ AMBIGUOUS 字段：" in rendered
    assert "裸列多源歧义" in rendered


def test_an_unprovable_grain_is_marked_rather_than_guessed() -> None:
    sql = (
        "INSERT INTO mart.t SELECT t1.id, b.v FROM "
        "(SELECT id, v FROM ods.left_side UNION ALL SELECT id, v FROM ods.other) t1 "
        "JOIN ods.right_side b ON t1.id = b.id"
    )
    schema = {
        "ods.left_side": ["id", "v"],
        "ods.other": ["id", "v"],
        "ods.right_side": ["id", "v"],
    }
    profile = build_semantic_profile(_document(sql, schema=schema))
    assert profile["output_shape"]["grain"]["basis"] == "unknown"

    rendered = render_semantic_markdown(profile, sections=["shape"])
    assert "⚠ 粒度：未能判定" in rendered
    # the line says which layer could not be crossed, so the reader knows why
    assert "含 UNION" in rendered


def test_a_pierced_grain_line_names_the_table_and_every_scope_it_was_read_through() -> None:
    sql = (
        "INSERT INTO mart.t SELECT t1.id, b.v FROM ("
        "  SELECT id FROM (SELECT id FROM ods.left_side WHERE id IS NOT NULL) inner1"
        "  WHERE id > 0"
        ") t1 LEFT JOIN ods.right_side b ON t1.id = b.id"
    )
    schema = {"ods.left_side": ["id"], "ods.right_side": ["id", "v"]}
    rendered = _render(sql, schema=schema, sections=["shape"])
    assert (
        "- 粒度：一行对应 `ods.left_side` 的一行（依据主表行，"
        "basis=driving_table_rows，经 `subq:t1` → `subq:inner1` 穿透）"
        "（结构推断；证据 subq:t1, subq:inner1, ods.left_side）"
    ) in rendered


def test_a_directly_read_driving_table_keeps_the_unpierced_grain_line() -> None:
    lineage, _ = _customer_profile_documents()
    rendered = render_semantic_markdown(build_semantic_profile(lineage), sections=["shape"])
    assert (
        "- 粒度：一行对应 `ods.customer_base` 的一行（依据主表行，"
        "basis=driving_table_rows）（结构推断；证据 ods.customer_base）"
    ) in rendered


# ------------------------------------------------------------ WI-1d rendering


def test_a_dynamic_partition_writes_the_columns_without_a_null_value() -> None:
    """The spec carries `null` for a dynamic column; ``dt = None`` would state a
    literal the statement never writes."""
    rendered = _render(
        "INSERT OVERWRITE TABLE mart.t PARTITION (dt, code) "
        "SELECT id, dt, code FROM ods.users",
        schema={"ods.users": ["id", "dt", "code"]},
        sections=["overview"],
    )
    assert "动态分区 dt、code" in rendered
    assert "None" not in rendered


def test_a_mixed_partition_writes_an_equals_only_for_the_column_that_has_one() -> None:
    rendered = _render(
        "INSERT OVERWRITE TABLE mart.t PARTITION (dt = '20260101', code) "
        "SELECT id, code FROM ods.users",
        schema={"ods.users": ["id", "dt", "code"]},
        sections=["overview"],
    )
    assert "分区 dt = `20260101`、code" in rendered


def test_a_proven_key_set_is_stated_as_a_fact_not_as_a_candidate() -> None:
    rendered = _render(
        "INSERT INTO mart.t SELECT customer_id, SUM(amount) AS s "
        "FROM ods.orders GROUP BY customer_id",
        schema={"ods.orders": ["customer_id", "amount"]},
        sections=["shape"],
    )
    assert (
        "- 键：目标表列 `customer_id`——由 GROUP BY 键保证输出内唯一"
        "（key_confidence=proven）（结构推断）"
    ) in rendered
    assert "仅为候选" not in rendered


def test_a_proven_key_set_under_a_partition_says_the_uniqueness_is_per_partition() -> None:
    rendered = _render(
        "INSERT OVERWRITE TABLE mart.t PARTITION (dt = '20260101') "
        "SELECT customer_id, SUM(amount) AS s FROM ods.orders GROUP BY customer_id",
        schema={"ods.orders": ["customer_id", "amount"]},
        sections=["shape"],
    )
    assert "由 GROUP BY 键保证输出内唯一（分区内）（key_confidence=proven）" in rendered


def test_a_candidate_key_set_keeps_the_candidate_wording() -> None:
    rendered = _render(
        "INSERT INTO mart.t WITH agg AS (SELECT id, SUM(v) AS s FROM ods.right_side "
        "GROUP BY id) SELECT a.id, agg.s FROM ods.left_side a "
        "LEFT JOIN agg ON a.id = agg.id",
        schema={"ods.left_side": ["id"], "ods.right_side": ["id", "v"]},
        sections=["shape"],
    )
    assert "- 候选键：目标表列 `id`——仅为候选，输入中无主键声明" in rendered
    assert "key_confidence=candidate" in rendered


# ------------------------------------------------------------ WI-1e rendering


_WIDE_SCHEMA = {
    "ods.orders": [
        "customer_id",
        "amount",
        "dt",
        "region",
        "city",
        "kind",
        "product_type",
    ]
}


def test_the_grain_line_names_logical_keys_and_inlines_a_short_source_list() -> None:
    rendered = _render(
        "INSERT INTO mart.t SELECT customer_id, product_type, SUM(amount) AS s "
        "FROM ods.orders GROUP BY customer_id, product_type",
        schema=_WIDE_SCHEMA,
        sections=["shape"],
    )
    assert (
        "- 粒度：一行对应一组 `ROOT.customer_id`、`ROOT.product_type`"
        "（物理来源：`ods.orders.customer_id`、`ods.orders.product_type`）"
    ) in rendered


def test_a_long_physical_source_list_defers_to_the_json_instead_of_inlining() -> None:
    """Five physical columns behind three keys: the line stays readable, the JSON keeps
    the detail."""
    rendered = _render(
        "INSERT INTO mart.t SELECT "
        "  CASE WHEN kind = 'a' THEN CONCAT(region, city) ELSE dt END AS bucket, "
        "  customer_id, product_type, SUM(amount) AS total "
        "FROM ods.orders GROUP BY "
        "  CASE WHEN kind = 'a' THEN CONCAT(region, city) ELSE dt END, "
        "  customer_id, product_type",
        schema=_WIDE_SCHEMA,
        sections=["shape"],
    )
    assert "`ROOT.bucket`、`ROOT.customer_id`、`ROOT.product_type`" in rendered
    assert "物理来源 6 列见 semantic.json grain.keys[].physical_sources" in rendered
    assert "物理来源：" not in rendered
    assert "- 键：目标表列 `bucket`、`customer_id`、`product_type`" in rendered


def test_a_key_the_target_never_receives_is_rendered_as_a_warning() -> None:
    rendered = _render(
        "INSERT INTO mart.t WITH agg AS ("
        "  SELECT customer_id, region, SUM(amount) AS total "
        "  FROM ods.orders GROUP BY customer_id, region"
        ") SELECT customer_id, total FROM agg",
        schema=_WIDE_SCHEMA,
        sections=["shape"],
    )
    assert (
        "- ⚠ 键：GROUP BY 键 `cte:agg.region` 未输出到目标表；"
        "目标表列 `customer_id` 不能唯一标识一行（key_confidence=proven_unexposed）"
    ) in rendered


def test_a_fan_out_risk_outside_root_names_the_scope_it_sits_in() -> None:
    rendered = _render(
        "INSERT INTO mart.t WITH joined AS ("
        "  SELECT a.id AS id, b.v AS v FROM ods.left_side a "
        "  LEFT JOIN ods.right_side b ON a.id = b.id"
        ") SELECT id, v FROM joined",
        schema={"ods.left_side": ["id"], "ods.right_side": ["id", "v"]},
        sections=["shape"],
    )
    assert "`cte:joined` 中的 LEFT_OUTER JOIN" in rendered


def test_regex_and_like_wildcards_survive_inside_a_code_span() -> None:
    """``%`` and ``_`` are markdown-inert, but only inside a span; the fence must hold.

    ``_`` is the one a reader worries about: outside a span, ``a_b_c`` italicises. The
    pattern is published verbatim in a code span inside a pipe-escaped table cell, so
    nothing in it can be eaten -- this pins that, and that the cell is still one cell.
    """
    rendered = _render(
        "INSERT INTO mart.t SELECT id FROM ods.users WHERE name LIKE '%A_B%' "
        "AND name RLIKE '^[0-9]|x_y$'",
        schema={"ods.users": ["id", "name"]},
        sections=["rules"],
    )
    spans = [span for _, span in _CODE_SPAN.findall(rendered)]
    assert any("'%A_B%'" in span for span in spans)
    assert any("x_y$" in span for span in spans)
    # the regex's own pipe cannot open a new table column
    rules = [row for row in rendered.splitlines() if row.startswith("| rule:")]
    assert rules and all(row.count(" | ") == 7 for row in rules)


def test_a_fan_out_risk_is_marked_and_a_proven_join_is_not() -> None:
    lineage, _ = _customer_profile_documents()
    safe = render_semantic_markdown(build_semantic_profile(lineage), sections=["shape"])
    assert "⚠ 有放大风险" not in safe
    assert "安全（safe）" in safe

    sql = (
        "INSERT INTO mart.t SELECT a.id, b.v FROM ods.left_side a "
        "LEFT JOIN ods.right_side b ON a.id = b.id"
    )
    schema = {"ods.left_side": ["id"], "ods.right_side": ["id", "v"]}
    risky = _render(sql, schema=schema, sections=["shape"])
    assert "⚠ 未知（unknown）" in risky


def test_a_missing_diagnostics_document_is_stated_not_silently_zeroed() -> None:
    lineage, _ = _customer_profile_documents()
    rendered = render_semantic_markdown(
        build_semantic_profile(lineage), sections=["confidence"]
    )
    assert "⚠ 无 diagnostics 文档" in rendered
    assert "事实缺口：0 条" not in rendered


# --------------------------------------------------------------- naming conventions


def test_a_directory_target_is_named_as_a_directory_not_as_a_table() -> None:
    case_dir = FIXTURES / "lineage_contract" / "directory_target"
    lineage = json.loads((case_dir / "lineage.json").read_text(encoding="utf-8"))
    rendered = render_semantic_markdown(build_semantic_profile(lineage))

    assert "# 任务语义描述 （写入目录 /warehouse/export/daily）" in rendered
    assert "directory:/warehouse/export/daily." not in rendered
    assert "### 字段 user_id（写入目录 /warehouse/export/daily）" in rendered
    # the path target never becomes a `<table>.<column>` heading
    assert "### 字段 directory:" not in rendered


# Verbatim from tests/core/test_anonymous_projection_coverage.py: an anonymous
# projection over more than one field cannot recover a target column name.
ANONYMOUS_SQL = """
INSERT OVERWRITE TABLE mart.notify_payload
SELECT o.contract_no AS contract_no,
       CONCAT('{"code":"', o.contract_no, '","cust":"', o.customer_no, '"}')
FROM (SELECT a.contract_no, a.customer_no FROM ods.enqueue_list a) o
"""


def test_an_unbound_projection_keeps_its_placeholder_heading() -> None:
    profile = build_semantic_profile(_document(ANONYMOUS_SQL))
    headings = [
        line
        for line in render_semantic_markdown(profile).splitlines()
        if line.startswith("### 字段 ")
    ]
    assert any("未绑定目标列）" in heading for heading in headings)
    # no heading fabricates `<target>.<generated name>`
    assert not any(
        heading.startswith("### 字段 mart.notify_payload._col") for heading in headings
    )


def test_a_missing_comment_is_written_as_unknown_never_invented() -> None:
    rendered = _render(
        "INSERT INTO mart.t SELECT id FROM ods.users", schema={"ods.users": ["id"]}
    )
    assert "- 目标注释：注释未知（元数据事实）" in rendered
    assert "（表注释：注释未知）" in rendered


def test_a_comment_that_exists_is_quoted_verbatim() -> None:
    lineage, _ = _customer_profile_documents()
    rendered = render_semantic_markdown(build_semantic_profile(lineage))
    assert "- 目标注释：Derived customer level（元数据事实）" in rendered


# -------------------------------------------------------------------- task document


def test_a_task_document_renders_one_section_per_statement() -> None:
    task_doc = json.loads(
        (
            FIXTURES / "task_lineage_contract" / "merge_cte_source" / "lineage.json"
        ).read_text(encoding="utf-8")
    )
    rendered = render_semantic_markdown(build_semantic_profile(task_doc))

    assert rendered.startswith("# 任务语义描述：golden_merge_cte_source")
    assert "共 1 条写入语句；最终产出表：`mart.event_target`" in rendered
    assert "\n## stmt:001\n" in rendered
    # each statement section holds a complete statement document
    assert rendered.count('doc_format: "semantic-md/1"') == 1
    assert "## 5. 字段语义" in rendered
    assert rendered.endswith("\n")


def test_a_task_document_with_no_write_statement_still_ends_cleanly() -> None:
    task_doc = json.loads(
        (FIXTURES / "task_lineage_contract" / "delete_all" / "lineage.json").read_text(
            encoding="utf-8"
        )
    )
    rendered = render_semantic_markdown(build_semantic_profile(task_doc))
    assert "共 0 条写入语句" in rendered
    assert rendered.endswith("\n")


# ------------------------------------------------- anti-fabrication property test

# A code span may hold a whole SQL expression, where identifiers are backtick-quoted
# (`t`.`c`) and therefore never match this. What matches is the document's own bare
# `db.table` / `db.table.column` ids -- exactly the ones a renderer could compose.
_IDENTIFIER = re.compile(
    r"(?<![`\w.$:])([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){1,2})(?![`\w.(])"
)

# The document names its own sibling artifacts; those are file names, not catalog ids.
_ARTIFACT_FILE_SUFFIXES = (".json", ".md")
_CODE_SPAN = re.compile(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.DOTALL)


def _known_tables(document: dict) -> set[str]:
    tables = set(document.get("source_tables") or [])
    if document.get("target_table"):
        tables.add(str(document["target_table"]))
    metadata = document.get("related_metadata") or {}
    tables |= set(metadata.get("input_tables") or {})
    tables |= set(metadata.get("output_tables") or {})
    for entry in document.get("end_to_end_lineage") or []:
        for source in entry.get("physical_sources") or []:
            if source.get("table"):
                tables.add(str(source["table"]))
    return tables


def _known_columns(document: dict) -> set[str]:
    columns: set[str] = set()
    metadata = document.get("related_metadata") or {}
    for group in ("input_tables", "output_tables"):
        for item in (metadata.get(group) or {}).values():
            for detail in item.get("column_details") or []:
                columns.add(str(detail.get("name")))
    for entry in document.get("end_to_end_lineage") or []:
        columns.add(str(entry.get("column")))
        for source in entry.get("physical_sources") or []:
            columns.add(str(source.get("column")))
    for scope in (document.get("scopes") or {}).values():
        for output in scope.get("outputs") or []:
            columns.add(str(output.get("name")))
        for block in scope.get("logic_blocks") or []:
            for field in block.get("fields") or []:
                columns.add(str(field.get("column")))
    return columns


def _assert_no_fabricated_identifiers(rendered: str, document: dict) -> None:
    tables = _known_tables(document)
    owners = tables | set(document.get("scopes") or {})
    columns = _known_columns(document)
    checked = 0
    for _, span in _CODE_SPAN.findall(rendered):
        for token in _IDENTIFIER.findall(span):
            checked += 1
            if token in owners or token in columns:
                continue
            if token.endswith(_ARTIFACT_FILE_SUFFIXES):
                continue
            owner, _, column = token.rpartition(".")
            assert owner in owners, f"code span invented the owner {owner!r} ({token!r})"
            assert column in columns, f"code span invented the column {column!r} ({token!r})"
    assert checked or not tables, "premise: the document prints qualified identifiers"


ANTI_FABRICATION_CASES = (
    ("customer_profile_daily.sql", True),
    ("order_channel_metrics.sql", True),
    ("customer_profile_daily.sql", False),
    ("select_star_with_schema.sql", False),
)


@pytest.mark.parametrize(
    "sql_name,with_schema", ANTI_FABRICATION_CASES, ids=lambda item: str(item)[:40]
)
def test_the_document_never_invents_a_table_or_column(sql_name: str, with_schema) -> None:
    document = _document(
        _example_sql(sql_name),
        "anti_fabrication",
        schema=_demo_schema() if with_schema else None,
    )
    _assert_no_fabricated_identifiers(
        render_semantic_markdown(build_semantic_profile(document)), document
    )


@pytest.mark.parametrize(
    "case_dir",
    [case for case in GOLDEN_CASES if case.parent.name == "lineage_contract"],
    ids=lambda path: path.name,
)
def test_golden_documents_never_invent_a_table_or_column(case_dir: Path) -> None:
    lineage = json.loads((case_dir / "lineage.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((case_dir / "diagnostics.json").read_text(encoding="utf-8"))
    _assert_no_fabricated_identifiers(
        render_semantic_markdown(build_semantic_profile(lineage, diagnostics)), lineage
    )


# ---------------------------------------------------------------- golden baseline


def _record_golden(case_dir: Path) -> tuple[str, str]:
    """The recording path and the asserted path, deliberately one function.

    To re-record: run this over every case directory and write the two returned strings
    to ``semantic.json`` / ``semantic.md`` beside the case's ``lineage.json``.
    """
    lineage = json.loads((case_dir / "lineage.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((case_dir / "diagnostics.json").read_text(encoding="utf-8"))
    profile = build_semantic_profile(lineage, diagnostics)
    return (
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
        render_semantic_markdown(profile),
    )


@pytest.mark.parametrize(
    "case_dir", GOLDEN_CASES, ids=lambda path: f"{path.parent.name}-{path.name}"
)
def test_semantic_artifacts_match_golden_bytes(case_dir: Path) -> None:
    first_json, first_md = _record_golden(case_dir)
    second_json, second_md = _record_golden(case_dir)

    assert first_json == (case_dir / "semantic.json").read_text(encoding="utf-8")
    assert first_md == (case_dir / "semantic.md").read_text(encoding="utf-8")
    assert second_json == first_json
    assert second_md == first_md


def test_the_baseline_covers_both_contract_shapes() -> None:
    groups = {case.parent.name for case in GOLDEN_CASES}
    assert groups == set(GOLDEN_GROUPS)
    assert len(GOLDEN_CASES) == 16


# ------------------------------------------------------------------ WI-1g markdown


def test_a_folded_group_carries_every_members_topological_number() -> None:
    """"阶段 2 等 3 个同模式阶段" left a reader who had just read 阶段 6 guessing."""
    sql, schema = _many_same_shaped_scopes(14)
    rendered = render_semantic_markdown(
        build_semantic_profile(_document(sql, schema=schema)), sections=["stages"]
    )
    heading = next(
        line for line in rendered.splitlines() if line.startswith("### 阶段 ") and "同模式" in line
    )
    assert heading == (
        "### 阶段 " + "、".join(str(index) for index in range(1, 15)) + " 等 14 个同模式阶段"
    )
    assert "| 阶段 | scope_id | 角色 | 直接输入 | 动作摘要 | 输出列数 |" in rendered
    assert "| 1 | `cte:m0` |" in rendered
    assert "| 6 | `cte:m13` |" in rendered
    assert "| 14 | `cte:m9` |" in rendered


_DERIVE_SCHEMA = {"ods.metrics": ["id", *[f"c{index}" for index in range(12)]]}


def _derive_sql(count: int) -> str:
    columns = ", ".join(f"c{index} - c0 AS d{index}" for index in range(1, count + 1))
    return f"INSERT INTO mart.t SELECT id, {columns} FROM ods.metrics"


def test_up_to_eight_derivations_are_listed_one_per_line() -> None:
    rendered = render_semantic_markdown(
        build_semantic_profile(_document(_derive_sql(8), schema=_DERIVE_SCHEMA)),
        sections=["stages"],
    )
    assert "派生 8 列" not in rendered
    for index in range(1, 9):
        assert f"- 表达式派生 `d{index}`：算术运算：" in rendered


def test_more_than_eight_derivations_are_counted_with_the_first_three_expanded() -> None:
    rendered = render_semantic_markdown(
        build_semantic_profile(_document(_derive_sql(11), schema=_DERIVE_SCHEMA)),
        sections=["stages"],
    )
    assert (
        "- 派生 11 列：`d1`、`d2`、`d3`…（前 3 条展开，"
        "完整清单见 semantic.json stages[].actions[]）"
    ) in rendered
    assert "- 表达式派生 `d3`：" in rendered
    assert "- 表达式派生 `d4`：" not in rendered


def test_the_json_never_folds_the_derivations_the_markdown_counts() -> None:
    profile = build_semantic_profile(_document(_derive_sql(11), schema=_DERIVE_SCHEMA))
    stage = next(item for item in profile["stages"] if item["scope_id"] == "ROOT")
    assert len([item for item in stage["actions"] if item["type"] == "derive"]) == 11


_PASSTHROUGH_SQL = (
    "INSERT INTO mart.t WITH a AS (SELECT id FROM ods.src), "
    "b AS (SELECT id FROM a), c AS (SELECT id FROM b) SELECT id FROM c"
)


def test_a_run_of_carrying_steps_folds_into_one_line_naming_every_scope() -> None:
    """Four "直接投影自 …" lines are one fact written four times."""
    rendered = render_semantic_markdown(
        build_semantic_profile(_document(_PASSTHROUGH_SQL, schema={"ods.src": ["id"]})),
        sections=["fields"],
    )
    assert (
        "- 第 1–4/4 步：直接透传（经 `cte:a` → `cte:b` → `cte:c` → `ROOT`）；粒度=preserved"
    ) in rendered
    assert "步骤 2/4 @" not in rendered


def test_a_real_union_step_is_not_folded_away() -> None:
    """A two-branch UNION changes the row set; a one-branch one is a reference."""
    sql = (
        "INSERT INTO mart.t WITH u AS (SELECT id FROM ods.a UNION ALL SELECT id FROM ods.b) "
        "SELECT id FROM u"
    )
    rendered = render_semantic_markdown(
        build_semantic_profile(
            _document(sql, schema={"ods.a": ["id"], "ods.b": ["id"]})
        ),
        sections=["fields"],
    )
    assert "合并 2 个分支" in rendered


def test_the_json_keeps_every_derivation_step_the_markdown_folds() -> None:
    profile = build_semantic_profile(_document(_PASSTHROUGH_SQL, schema={"ods.src": ["id"]}))
    assert len(profile["fields"][0]["derivation"]) == 4


_RULE_FAMILY_SCHEMA = {"ods.hours": ["id", "h", "h1", "h2"]}


def _rule_family_sql(count: int) -> str:
    """``count`` filters that differ only in one numeric literal."""
    return (
        "INSERT INTO mart.t SELECT id FROM ods.hours WHERE "
        + " AND ".join(f"h <> {value}" for value in range(9, 9 + count))
    )


def _rule_rows(rendered: str) -> list[str]:
    return [line for line in rendered.splitlines() if line.startswith("| rule:")]


def test_three_or_more_rules_differing_only_in_a_number_fold_into_one_row() -> None:
    rendered = render_semantic_markdown(
        build_semantic_profile(_document(_rule_family_sql(12), schema=_RULE_FAMILY_SCHEMA)),
        sections=["rules"],
    )
    rows = _rule_rows(rendered)

    assert len(rows) == 1
    assert rows[0].startswith("| rule:001–012（12 条） |")
    assert "（N 取 9…20（12 个）） |" in rows[0]
    assert "其中 1 组同构规则已折叠（semantic.json 不折叠）" in rendered


def test_two_rules_of_a_shape_stay_two_rows() -> None:
    rendered = render_semantic_markdown(
        build_semantic_profile(_document(_rule_family_sql(2), schema=_RULE_FAMILY_SCHEMA)),
        sections=["rules"],
    )
    assert len(_rule_rows(rendered)) == 2
    assert "同构规则已折叠" not in rendered


def test_rules_that_differ_in_more_than_a_number_are_not_folded() -> None:
    sql = (
        "INSERT INTO mart.t SELECT id FROM ods.hours "
        "WHERE h = 9 AND h1 <> 10 AND h2 > 11"
    )
    rendered = render_semantic_markdown(
        build_semantic_profile(_document(sql, schema=_RULE_FAMILY_SCHEMA)),
        sections=["rules"],
    )
    assert len(_rule_rows(rendered)) == 3


def test_the_json_keeps_every_rule_the_markdown_folds() -> None:
    profile = build_semantic_profile(
        _document(_rule_family_sql(12), schema=_RULE_FAMILY_SCHEMA)
    )
    assert len(profile["rules"]) == 12


def test_a_family_whose_members_vary_in_several_numbers_defers_to_the_json() -> None:
    """``h1 <> 10`` carries two digit runs; guessing which one is "N" would be a lie."""
    sql = (
        "INSERT INTO mart.t SELECT id FROM ods.hours "
        "WHERE h1 <> 10 AND h2 <> 20 AND h1 <> 30"
    )
    rendered = render_semantic_markdown(
        build_semantic_profile(_document(sql, schema=_RULE_FAMILY_SCHEMA)),
        sections=["rules"],
    )
    row = _rule_rows(rendered)[0]
    assert "（各条取值见 semantic.json rules[]）" in row


def test_a_redundant_source_boundary_line_is_dropped() -> None:
    """A stage whose boundary is exactly its own direct inputs restates them."""
    rendered = render_semantic_markdown(
        build_semantic_profile(_document(_PASSTHROUGH_SQL, schema={"ods.src": ["id"]})),
        sections=["stages"],
    )
    # `cte:a` reads ods.src directly: boundary == direct inputs, so the line goes; the
    # stages above it all resolve to the same one table, so theirs go too.
    assert "- 上游物理表（来源边界）：" not in rendered


def test_a_boundary_that_differs_from_the_direct_inputs_is_still_printed() -> None:
    sql = (
        "INSERT INTO mart.t WITH a AS (SELECT id FROM ods.src) "
        "SELECT a.id, o.v FROM a JOIN ods.other o ON a.id = o.id"
    )
    rendered = render_semantic_markdown(
        build_semantic_profile(
            _document(sql, schema={"ods.src": ["id"], "ods.other": ["id", "v"]})
        ),
        sections=["stages"],
    )
    assert "- 上游物理表（来源边界）：`ods.other`、`ods.src`" in rendered


def test_the_inference_inventory_reads_the_counted_form() -> None:
    lineage, _ = _customer_profile_documents()
    profile = build_semantic_profile(lineage)
    rendered = render_semantic_markdown(profile, sections=["confidence"])

    assert isinstance(profile["confidence"]["inferred_items"], dict)
    assert "本文档的结构推断项：16 项（按 semantic.json 路径：fields[].structural_role 8、" in rendered


def test_a_run_of_union_branch_steps_is_listed_not_arrowed() -> None:
    """Each row takes one branch; "b01 → b02" would state a sequence that never runs."""
    sql = (
        "INSERT INTO mart.t WITH u AS (SELECT id FROM ods.a UNION ALL SELECT id FROM ods.b) "
        "SELECT id FROM u"
    )
    profile = build_semantic_profile(
        _document(sql, schema={"ods.a": ["id"], "ods.b": ["id"]})
    )
    rendered = render_semantic_markdown(profile, sections=["fields"])

    assert "各分支直接透传（经 `union:u:b01`、`union:u:b02`）" in rendered
    assert "`union:u:b01` → `union:u:b02`" not in rendered
    # the branch each step belongs to is a published fact, not a decoded scope id
    assert profile["fields"][0]["derivation"][0]["branch"] == {
        "index": 1,
        "label": "ods.a",
    }
