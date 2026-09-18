"""WI-1f: statement-level diagnostics, field summaries, JOIN null semantics, findings.

Five themes, one module, because they answer one complaint from the profile-writing
agent: the skeleton dropped facts it already held. A warning recorded against a
statement never reached the statement's own confidence block; a field's meaning had to
be reassembled from four lines; a LEFT JOIN never said what happens when it misses; and
the governance signals the contract carries (mismatched partition literals, hardcoded
dates, metadata conflicts, positional target binding, missing table comments) were
nowhere in the document.

Everything asserted here is a *structural* fact: no test expects a business word.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.mapping_markdown import (
    render_mapping_markdown,
    render_warnings_markdown,
)
from scope_lineage.render import semantic_text
from scope_lineage.render.semantic_markdown import render_semantic_markdown
from scope_lineage.render.semantic_profile import (
    FINDING_KINDS,
    JOIN_NULL_SEMANTICS,
    build_semantic_profile,
)
from scope_lineage.scope.scope_builder import parse_scope_lineage


FIXTURES = Path(__file__).parent / "fixtures"


def _document(sql: str, task_id: str = "wi1f", schema=None) -> dict:
    return to_lineage_dict(parse_scope_lineage(sql, task_id, schema=schema))


def _field(profile: dict, column: str) -> dict:
    return next(item for item in profile["fields"] if item["column"] == column)


def _findings(profile: dict, kind: str) -> list[dict]:
    return [
        item
        for item in profile["confidence"]["findings"]
        if item["kind"] == kind
    ]


def _actions(profile: dict, scope_id: str, action_type: str) -> list[dict]:
    stage = next(item for item in profile["stages"] if item["scope_id"] == scope_id)
    return [item for item in stage["actions"] if item["type"] == action_type]


# ------------------------------------------------ 1. statement-level diagnostics


STATEMENT_ONLY_DIAGNOSTICS = {
    "schema_version": "2.0",
    "task_id": "wi1f",
    "analysis_status": {"status": "ok", "blocking_reasons": []},
    "warnings": [],
    "lineage_fact_gaps": [],
    "stats": {},
    "statement_diagnostics": {
        "stmt:001": {
            "warnings": [
                {"type": "magic_number", "scope": "ROOT", "msg": "constant 7 in ROOT"}
            ],
            "lineage_fact_gaps": [
                {"gap_id": "lineage_gap:0001", "gap_type": "expression_source_unresolved"}
            ],
            "stats": {},
        }
    },
}


def _statement_document() -> dict:
    document = _document(
        "INSERT INTO mart.t SELECT id FROM ods.users", schema={"ods.users": ["id"]}
    )
    document["statement_id"] = "stmt:001"
    return document


def test_a_statement_only_warning_reaches_that_statements_confidence() -> None:
    profile = build_semantic_profile(_statement_document(), STATEMENT_ONLY_DIAGNOSTICS)

    confidence = profile["confidence"]
    assert confidence["warning_counts"] == {"magic_number": 1}
    assert confidence["fact_gap_count"] == 1
    assert confidence["fact_gap_types"] == {"expression_source_unresolved": 1}


def test_section_six_no_longer_claims_there_are_no_warnings() -> None:
    rendered = render_semantic_markdown(
        build_semantic_profile(_statement_document(), STATEMENT_ONLY_DIAGNOSTICS),
        sections=["confidence"],
    )
    assert "解析警告：无" not in rendered
    assert "解析警告：1 条（magic_number 1" in rendered


def test_the_warning_line_points_at_the_command_that_writes_warnings_md() -> None:
    """WI-2.1c item 6: ``describe`` does not write warnings.md, so "同目录" was a
    promise about a file that is not there unless ``render`` was run too."""
    rendered = render_semantic_markdown(
        build_semantic_profile(_statement_document(), STATEMENT_ONLY_DIAGNOSTICS),
        sections=["confidence"],
    )

    assert "语义提示见 `scope-lineage render` 生成的 warnings.md" in rendered
    assert "同目录 warnings.md" not in rendered


def test_a_statement_without_warnings_names_no_file_at_all() -> None:
    clean = {**STATEMENT_ONLY_DIAGNOSTICS, "statement_diagnostics": {}}
    rendered = render_semantic_markdown(
        build_semantic_profile(_statement_document(), clean), sections=["confidence"]
    )

    assert "解析警告：无" in rendered
    assert "warnings.md" not in rendered


def test_the_top_level_and_statement_level_warnings_are_a_deduped_union() -> None:
    diagnostics = json.loads(json.dumps(STATEMENT_ONLY_DIAGNOSTICS))
    shared = {"type": "magic_number", "scope": "ROOT", "msg": "constant 7 in ROOT"}
    diagnostics["warnings"] = [
        shared,
        {"type": "duplicate_alias", "scope": "ROOT", "msg": "alias x twice"},
    ]
    confidence = build_semantic_profile(_statement_document(), diagnostics)["confidence"]

    assert confidence["warning_counts"] == {"duplicate_alias": 1, "magic_number": 1}


def test_a_document_without_a_statement_id_still_reads_the_top_level() -> None:
    document = _document(
        "INSERT INTO mart.t SELECT id FROM ods.users", schema={"ods.users": ["id"]}
    )
    document.pop("statement_id", None)
    confidence = build_semantic_profile(document, STATEMENT_ONLY_DIAGNOSTICS)[
        "confidence"
    ]
    assert confidence["warning_counts"] == {}


def test_the_task_wrapper_publishes_a_summary_warning_count() -> None:
    task_document = json.loads(
        (
            FIXTURES / "task_lineage_contract" / "merge_cte_source" / "lineage.json"
        ).read_text(encoding="utf-8")
    )
    diagnostics = json.loads(json.dumps(STATEMENT_ONLY_DIAGNOSTICS))
    diagnostics["warnings"] = [
        {"type": "duplicate_alias", "scope": "TASK", "msg": "alias x twice"}
    ]
    profile = build_semantic_profile(task_document, diagnostics)

    assert profile["warning_counts"] == {"duplicate_alias": 1, "magic_number": 1}
    assert build_semantic_profile(task_document)["warning_counts"] is None


def test_the_mapping_gap_section_reads_the_statements_own_diagnostics() -> None:
    rendered = render_mapping_markdown(
        _statement_document(), STATEMENT_ONLY_DIAGNOSTICS, sections=["gaps"]
    )
    assert "解析警告：无" not in rendered
    assert "解析警告：1 条（magic_number 1" in rendered
    assert "缺口：无" not in rendered
    assert "gap_type=expression_source_unresolved" in rendered


def test_warnings_md_covers_the_statement_level_warnings_of_a_task_document() -> None:
    task_document = json.loads(
        (
            FIXTURES / "task_lineage_contract" / "merge_cte_source" / "lineage.json"
        ).read_text(encoding="utf-8")
    )
    rendered = render_warnings_markdown(STATEMENT_ONLY_DIAGNOSTICS, task_document)

    assert rendered is not None
    assert "magic_number（1 条）" in rendered
    assert "stmt:001" in rendered


# ------------------------------------------------------- 2. one-sentence summary


SUMMARY_SQL = """
INSERT INTO mart.paid
WITH agg AS (
  SELECT customer_id,
         SUM(CASE WHEN pay_status = 'PAID' THEN pay_amount ELSE 0 END) AS paid
  FROM dwd.order_detail
  GROUP BY customer_id
)
SELECT customer_id, COALESCE(paid, 0) AS paid_amount FROM agg
"""

SUMMARY_SCHEMA = {"dwd.order_detail": ["customer_id", "pay_status", "pay_amount"]}


def test_a_derived_field_gets_one_readable_sentence() -> None:
    profile = build_semantic_profile(_document(SUMMARY_SQL, schema=SUMMARY_SCHEMA))
    summary = _field(profile, "paid_amount")["summary"]

    assert summary.startswith("（注释未知）：")
    assert "仅计 pay_status = 'PAID'" in summary
    assert "，再空值回填为 0" in summary
    assert "；来源 dwd.order_detail.pay_amount" in summary


def test_a_direct_field_says_where_it_is_taken_from() -> None:
    profile = build_semantic_profile(_document(SUMMARY_SQL, schema=SUMMARY_SCHEMA))
    summary = _field(profile, "customer_id")["summary"]

    assert "直接取自 dwd.order_detail.customer_id" in summary
    # the DIRECT sentence already names the source, so it is not repeated
    assert summary.count("dwd.order_detail.customer_id") == 1


def test_a_field_with_no_comment_and_no_chain_falls_back_to_its_expression() -> None:
    document = _document("INSERT INTO mart.t SELECT 1 AS flag", schema={})
    for field in document.get("field_mapping_chains") or []:
        field["ordered_steps"] = []
    summary = build_semantic_profile(document)["fields"][0]["summary"]

    assert summary.startswith("（注释未知）：")


def test_the_summary_never_uses_a_code_span() -> None:
    """The summary is free text, so it must not be punctuated as a catalog assertion.

    The document's anti-fabrication scanner checks identifiers *inside code spans*; a
    summary that wrapped ``dwd.order_detail.pay_amount`` in backticks would be read as
    one and flagged. The identifiers stay checkable in ``sources[]`` instead, which the
    property test below holds them to.
    """
    profile = build_semantic_profile(_document(SUMMARY_SQL, schema=SUMMARY_SCHEMA))
    for field in profile["fields"]:
        assert "`" not in field["summary"]


def test_section_five_leads_with_the_field_list_and_the_sentence() -> None:
    profile = build_semantic_profile(_document(SUMMARY_SQL, schema=SUMMARY_SCHEMA))
    rendered = render_semantic_markdown(profile, sections=["fields"])
    lines = rendered.splitlines()

    table_at = next(index for index, line in enumerate(lines) if "一句话语义" in line)
    first_field_at = next(
        index for index, line in enumerate(lines) if line.startswith("### 字段 ")
    )
    assert table_at < first_field_at
    body = lines[first_field_at + 1 :]
    assert body[1].startswith("- 语义：")


# ------------------------------------------------------- 3. JOIN null semantics


JOIN_SQL = """
INSERT INTO mart.enriched SELECT o.id, d.label
FROM ods.orders o
LEFT JOIN ods.dim d ON o.id = d.id
"""

JOIN_SCHEMA = {"ods.orders": ["id"], "ods.dim": ["id", "label"]}


def test_a_join_action_states_what_happens_when_it_misses() -> None:
    profile = build_semantic_profile(_document(JOIN_SQL, schema=JOIN_SCHEMA))
    action = _actions(profile, "ROOT", "join")[0]

    assert action["text"].endswith(JOIN_NULL_SEMANTICS["LEFT_OUTER"])


def test_a_join_rule_carries_the_same_sentence() -> None:
    profile = build_semantic_profile(_document(JOIN_SQL, schema=JOIN_SCHEMA))
    rule = next(item for item in profile["rules"] if item["kind"] == "join_condition")

    assert rule["null_semantics"] == JOIN_NULL_SEMANTICS["LEFT_OUTER"]


@pytest.mark.parametrize(
    "join_type", ["INNER", "LEFT_OUTER", "RIGHT_OUTER", "FULL_OUTER", "CROSS"]
)
def test_every_join_type_in_the_vocabulary_has_one_fixed_sentence(join_type) -> None:
    assert JOIN_NULL_SEMANTICS[join_type]


NULLABLE_SQL = """
INSERT INTO mart.enriched
WITH dim AS (SELECT id, label FROM ods.dim)
SELECT o.id, d.label
FROM ods.orders o
LEFT JOIN dim d ON o.id = d.id
"""


def test_a_field_reached_only_through_the_nullable_side_is_flagged() -> None:
    profile = build_semantic_profile(_document(NULLABLE_SQL, schema=JOIN_SCHEMA))

    assert _field(profile, "label")["nullable_by_join"] is True
    assert "（关联未命中时为空）" in _field(profile, "label")["summary"]
    assert "nullable_by_join" not in _field(profile, "id")


def test_an_inner_join_flags_nothing() -> None:
    sql = NULLABLE_SQL.replace("LEFT JOIN", "JOIN")
    profile = build_semantic_profile(_document(sql, schema=JOIN_SCHEMA))

    assert all("nullable_by_join" not in field for field in profile["fields"])


# ------------------------------------------------------------------ 4. findings


MISMATCH_SQL = """
INSERT INTO mart.joined SELECT a.id, b.amount
FROM ods.left_side a
JOIN ods.right_side b ON a.id = b.id
WHERE a.dt = '20260814' AND b.dt = '20260813'
"""

MISMATCH_SCHEMA = {
    "ods.left_side": ["id", "dt"],
    "ods.right_side": ["id", "amount", "dt"],
}


def test_mismatched_partition_literals_are_reported() -> None:
    profile = build_semantic_profile(_document(MISMATCH_SQL, schema=MISMATCH_SCHEMA))
    found = _findings(profile, "partition_literal_mismatch")

    assert len(found) == 1
    assert "'20260814'" in found[0]["text"] and "'20260813'" in found[0]["text"]
    assert found[0]["evidence"]


def test_matching_partition_literals_are_not_reported() -> None:
    sql = MISMATCH_SQL.replace("'20260813'", "'20260814'")
    profile = build_semantic_profile(_document(sql, schema=MISMATCH_SCHEMA))

    assert _findings(profile, "partition_literal_mismatch") == []


def test_a_hardcoded_date_literal_is_reported_and_a_parameter_is_not() -> None:
    profile = build_semantic_profile(_document(MISMATCH_SQL, schema=MISMATCH_SCHEMA))
    assert _findings(profile, "hardcoded_date_literal")

    parameterised = MISMATCH_SQL.replace("'20260814'", "${bizdate}").replace(
        "'20260813'", "${bizdate}"
    )
    profile = build_semantic_profile(_document(parameterised, schema=MISMATCH_SCHEMA))
    assert _findings(profile, "hardcoded_date_literal") == []


def test_a_computed_date_filter_is_an_expression_not_a_literal() -> None:
    sql = MISMATCH_SQL.replace("'20260814'", "date_sub(current_date(), 1)").replace(
        "'20260813'", "date_sub(current_date(), 1)"
    )
    profile = build_semantic_profile(_document(sql, schema=MISMATCH_SCHEMA))
    assert _findings(profile, "hardcoded_date_literal") == []


def test_metadata_conflicts_are_listed_per_table() -> None:
    diagnostics = json.loads(json.dumps(STATEMENT_ONLY_DIAGNOSTICS))
    diagnostics["metadata_coverage"] = {
        "metadata_conflicts": [
            {"table": "ods.users", "resolution": "kept_authoritative"},
        ]
    }
    profile = build_semantic_profile(_statement_document(), diagnostics)
    found = _findings(profile, "metadata_conflicts")

    assert len(found) == 1
    assert "ods.users" in found[0]["text"]
    assert "kept_authoritative" in found[0]["text"]


def test_the_target_binding_method_is_a_finding_and_a_section_six_line() -> None:
    case_dir = FIXTURES / "lineage_contract" / "target_ddl_binding"
    lineage = json.loads((case_dir / "lineage.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((case_dir / "diagnostics.json").read_text(encoding="utf-8"))
    profile = build_semantic_profile(lineage, diagnostics)

    found = _findings(profile, "target_binding")
    assert len(found) == 1
    assert "ddl_position" in found[0]["text"]

    rendered = render_semantic_markdown(profile, sections=["confidence"])
    assert "- 目标列绑定：" in rendered
    assert "ddl_position" in rendered


def test_an_absent_binding_reason_reaches_the_same_line() -> None:
    document = _document(
        "INSERT INTO mart.t SELECT id FROM ods.users", schema={"ods.users": ["id"]}
    )
    profile = build_semantic_profile(document)
    found = _findings(profile, "target_binding")

    assert len(found) == 1
    assert str(document["target_binding_absent_reason"]) in found[0]["text"]


def test_tables_without_a_table_comment_are_listed() -> None:
    profile = build_semantic_profile(_document(JOIN_SQL, schema=JOIN_SCHEMA))
    found = _findings(profile, "table_comment_missing")

    assert len(found) == 1
    assert "ods.orders" in found[0]["text"] and "ods.dim" in found[0]["text"]


def test_every_finding_uses_a_declared_kind_and_the_declared_shape() -> None:
    profile = build_semantic_profile(_document(MISMATCH_SQL, schema=MISMATCH_SCHEMA))
    for finding in profile["confidence"]["findings"]:
        assert finding["kind"] in FINDING_KINDS
        assert list(finding) == ["kind", "text", "evidence"]
        assert isinstance(finding["evidence"], list)


def test_section_six_renders_the_findings_and_says_so_when_there_are_none() -> None:
    profile = build_semantic_profile(_document(MISMATCH_SQL, schema=MISMATCH_SCHEMA))
    rendered = render_semantic_markdown(profile, sections=["confidence"])
    assert "#### 治理线索" in rendered
    assert "partition_literal_mismatch" in rendered

    empty = build_semantic_profile(
        _document("INSERT INTO mart.t SELECT 1 AS flag", schema={})
    )
    empty["confidence"]["findings"] = []
    rendered = render_semantic_markdown(empty, sections=["confidence"])
    assert "- 治理线索：无" in rendered


# ------------------------------------------------------------ 5. vocabulary


def test_a_date_difference_is_restated_as_one() -> None:
    sql = (
        "INSERT INTO mart.t SELECT DATEDIFF(end_dt, start_dt) AS days FROM ods.spans"
    )
    profile = build_semantic_profile(
        _document(sql, schema={"ods.spans": ["end_dt", "start_dt"]})
    )
    text = _field(profile, "days")["derivation"][-1]["text"]

    assert text == "日期差（天）：end_dt − start_dt"


TEMPORAL_SQL = """
INSERT INTO mart.t SELECT
  id,
  MAX(event_time) AS last_seen,
  MAX(amount) AS biggest,
  COUNT(DISTINCT session_id) AS sessions,
  COUNT(*) AS rows_seen
FROM ods.events GROUP BY id
"""


def _temporal_profile() -> dict:
    document = _document(TEMPORAL_SQL, schema={})
    metadata = document["related_metadata"]["input_tables"].setdefault(
        "ods.events", {"column_details": []}
    )
    metadata["column_details"] = [
        {"name": "id", "type": "string"},
        {"name": "event_time", "type": "timestamp"},
        {"name": "amount", "type": "decimal(18,2)"},
        {"name": "session_id", "type": "string"},
    ]
    return build_semantic_profile(document)


def test_max_over_a_timestamp_is_the_latest_time_and_otherwise_the_maximum() -> None:
    text = _actions(_temporal_profile(), "ROOT", "aggregate")[0]["text"]

    assert "MAX(event_time)（最晚时间）" in text
    assert "MAX(amount)（最大值）" in text


def test_count_distinct_and_count_star_are_named() -> None:
    text = _actions(_temporal_profile(), "ROOT", "aggregate")[0]["text"]

    assert "COUNT(DISTINCT session_id)（去重计数 session_id）" in text
    assert "COUNT(*)（行数）" in text


# --------------------------------------------- summary anti-fabrication property


_QUALIFIED = re.compile(r"[A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)+")

# WI-2.2. A summary may end in the author's own comment, quoted. That tail is the one
# part of the sentence this view did not compose, so it is cut off before the scan: a
# comment reading "口径同 legacy.old_table" names a table nobody promised exists, and
# flagging it would be flagging the SQL's author, not a fabrication by this document.
# The claim the property defends is unchanged -- everything this view *derives* names
# only identifiers the contract carries.
COMMENTED_SUMMARY_SQL = """
INSERT INTO mart.t SELECT
  u.user_id AS user_id, -- 口径同 legacy.retired_table.retired_col
  u.user_name AS user_name
FROM ods.users u
"""

COMMENTED_SUMMARY_SCHEMA = {"ods.users": ["user_id", "user_name"]}

SUMMARY_PROPERTY_CASES = (
    (SUMMARY_SQL, SUMMARY_SCHEMA),
    (JOIN_SQL, JOIN_SCHEMA),
    (NULLABLE_SQL, JOIN_SCHEMA),
    (MISMATCH_SQL, MISMATCH_SCHEMA),
    (COMMENTED_SUMMARY_SQL, COMMENTED_SUMMARY_SCHEMA),
)


def _derived_part(summary: str) -> str:
    """The summary with any quoted SQL comment removed -- see the note above."""
    return summary.split(semantic_text.SQL_COMMENT_PREFIX)[0]


def _known_identifiers(document: dict) -> tuple[set[str], set[str]]:
    tables = set(document.get("source_tables") or [])
    if document.get("target_table"):
        tables.add(str(document["target_table"]))
    metadata = document.get("related_metadata") or {}
    tables |= set(metadata.get("input_tables") or {})
    tables |= set(metadata.get("output_tables") or {})
    columns: set[str] = set()
    for group in ("input_tables", "output_tables"):
        for item in (metadata.get(group) or {}).values():
            columns |= {str(detail.get("name")) for detail in item.get("column_details") or []}
    for entry in document.get("end_to_end_lineage") or []:
        columns.add(str(entry.get("column")))
        for source in entry.get("physical_sources") or []:
            tables.add(str(source.get("table")))
            columns.add(str(source.get("column")))
    for scope in (document.get("scopes") or {}).values():
        columns |= {str(output.get("name")) for output in scope.get("outputs") or []}
    return tables, columns


@pytest.mark.parametrize(
    "sql,schema", SUMMARY_PROPERTY_CASES, ids=lambda item: str(item)[:30]
)
def test_a_summary_never_invents_a_table_or_a_column(sql: str, schema: dict) -> None:
    """Every qualified identifier a summary prints must exist in the source document."""
    document = _document(sql, schema=schema)
    tables, columns = _known_identifiers(document)
    owners = tables | set(document.get("scopes") or {})
    checked = 0
    for field in build_semantic_profile(document)["fields"]:
        for token in _QUALIFIED.findall(_derived_part(field["summary"])):
            if token in owners or token in columns:
                continue
            owner, _, column = token.rpartition(".")
            checked += 1
            assert owner in owners, f"summary invented the owner {owner!r} ({token!r})"
            assert column in columns, f"summary invented the column {column!r} ({token!r})"
    assert checked, "premise: the summaries print qualified identifiers"


def test_a_comment_naming_an_unknown_table_is_quoted_not_flagged() -> None:
    """The premise of the exclusion above: the comment really does reach the summary,
    and it really does name something the contract has never heard of."""
    document = _document(COMMENTED_SUMMARY_SQL, schema=COMMENTED_SUMMARY_SCHEMA)
    summary = _field(build_semantic_profile(document), "user_id")["summary"]
    assert summary.endswith("；注释：口径同 legacy.retired_table.retired_col")
    assert "legacy.retired_table" not in _derived_part(summary)


# ------------------------------- WI-1g C: positional binding with disagreeing names


_ALIAS_CASE = FIXTURES / "lineage_contract" / "target_ddl_binding"


def _alias_document() -> dict:
    return json.loads((_ALIAS_CASE / "lineage.json").read_text(encoding="utf-8"))


def test_a_positional_write_whose_aliases_disagree_with_the_ddl_is_a_finding() -> None:
    """Core has always counted these (`target_field_binding.corrected_column_count`).

    The skeleton only said "按 DDL 位置绑定", so nobody learned that the values landed in
    columns the SQL never named. It is either wrong data or stale metadata; the finding
    says which two readings are open and what to do, and decides neither.
    """
    document = _alias_document()
    assert document["target_field_binding"]["method"] == "ddl_position"
    found = _findings(build_semantic_profile(document), "alias_position_mismatch")

    assert len(found) == 1
    assert found[0]["text"] == (
        "按位置写入且 2/2 个投影的 SQL 别名与 DDL 同位置列名不同"
        "（如 目标 account_id ← 别名 wrong_key、目标 balance ← 别名 wrong_balance）"
        "——生产数据写错列或元数据列序过期，需 DESC 表核对"
    )


def test_the_alias_finding_cites_the_mapping_chain_of_every_mismatched_field() -> None:
    profile = build_semantic_profile(_alias_document())
    found = _findings(profile, "alias_position_mismatch")[0]
    chains = {
        field["mapping_chain_id"]
        for field in profile["fields"]
        if field["column"] in ("account_id", "balance")
    }
    assert set(found["evidence"]) == chains


def test_a_positional_write_whose_aliases_agree_is_not_a_finding() -> None:
    document = _alias_document()
    for entry in document["end_to_end_lineage"]:
        entry["parsed_column"] = entry["column"]
    assert _findings(build_semantic_profile(document), "alias_position_mismatch") == []


def test_an_alias_mismatch_under_a_non_positional_binding_is_not_a_finding() -> None:
    """Only a *positional* write can silently put a value in the wrong column."""
    document = _alias_document()
    document["target_field_binding"]["method"] = "insert_column_list"
    assert _findings(build_semantic_profile(document), "alias_position_mismatch") == []


def test_the_alias_finding_reaches_section_six_with_both_evidence_classes() -> None:
    rendered = render_semantic_markdown(
        build_semantic_profile(_alias_document()), sections=["confidence"]
    )
    assert "⚠ alias_position_mismatch：按位置写入且 2/2 个投影" in rendered
    assert "SQL事实+元数据事实" in rendered


def test_the_alias_finding_leads_the_governance_list() -> None:
    """A suspected production incident is not read if it sits under "缺少表注释"."""
    kinds = [item["kind"] for item in build_semantic_profile(_alias_document())["confidence"]["findings"]]
    assert kinds[0] == "alias_position_mismatch"
    assert FINDING_KINDS[0] == "alias_position_mismatch"


# ------------------------------------------- WI-1g D1: UNION branches in the summary


_BRANCH_SCHEMA = {"ods.a": ["id", "code"], "ods.b": ["id", "code2"]}

_BRANCH_SQL = (
    "INSERT INTO mart.t WITH u AS ("
    "SELECT id, regexp_replace(code, 'x', 'y') AS code FROM ods.a "
    "UNION ALL SELECT id, regexp_extract(code2, 'p', 1) AS code FROM ods.b) "
    "SELECT id, UPPER(code) AS code FROM u"
)


def test_a_union_field_summary_groups_the_branches_instead_of_chaining_them() -> None:
    """The branches are alternatives: "正则替换，再正则提取" claimed both ran, in order."""
    profile = build_semantic_profile(_document(_BRANCH_SQL, schema=_BRANCH_SCHEMA))
    summary = _field(profile, "code")["summary"]

    assert "分支 1（来自 ods.a）：正则替换" in summary
    assert "分支 2（来自 ods.b）：正则提取" in summary
    assert "合并后 文本规整（UPPER）" in summary
    assert "，再正则提取" not in summary


def test_a_field_with_no_branch_processing_keeps_the_direct_reading() -> None:
    profile = build_semantic_profile(_document(_BRANCH_SQL, schema=_BRANCH_SCHEMA))
    assert _field(profile, "id")["summary"].startswith("（注释未知）：直接取自 ods.a.id")


def test_more_branches_than_the_limit_are_counted_rather_than_listed() -> None:
    branches = " UNION ALL ".join(
        f"SELECT id, regexp_replace(code, 'x{index}', 'y') AS code FROM ods.s{index}"
        for index in range(1, 9)
    )
    schema = {f"ods.s{index}": ["id", "code"] for index in range(1, 9)}
    profile = build_semantic_profile(
        _document(f"INSERT INTO mart.t WITH u AS ({branches}) SELECT id, code FROM u", schema=schema)
    )
    summary = _field(profile, "code")["summary"]
    assert "分支 3（来自 ods.s3）" in summary
    assert "（共 8 个分支，完整链路见 derivation）" in summary


# --------------------------------------- WI-1g D3: nested calls are restated as well


def test_an_aggregate_over_a_nested_call_restates_the_inner_call_too() -> None:
    """`MAX(DATEDIFF(a, b))（最大值）` said nothing about what is being maximised."""
    sql = (
        "INSERT INTO mart.t SELECT id, MAX(DATEDIFF(end_dt, start_dt)) AS gap "
        "FROM ods.spans GROUP BY id"
    )
    profile = build_semantic_profile(
        _document(sql, schema={"ods.spans": ["id", "end_dt", "start_dt"]})
    )
    text = _actions(profile, "ROOT", "aggregate")[0]["text"]

    assert text == (
        "按 id 分组聚合：MAX(DATEDIFF(end_dt, start_dt))"
        "（最大值；日期差（天）：end_dt − start_dt）"
    )


def test_an_aggregate_over_a_plain_column_gains_no_second_gloss() -> None:
    text = _actions(_temporal_profile(), "ROOT", "aggregate")[0]["text"]
    assert "MAX(amount)（最大值）" in text


# --------------------------------- WI-1g E4: generated sources are words, not reprs


def test_a_constant_source_is_named_rather_than_printed_as_a_dict() -> None:
    profile = build_semantic_profile(
        _document("INSERT INTO mart.t SELECT id, 'F_00' AS flag FROM ods.a", schema={"ods.a": ["id"]})
    )
    field = _field(profile, "flag")

    assert "常量 'F_00'" in field["summary"]
    assert "source_type" not in field["summary"]
    # the JSON keeps the structure it was given
    assert field["generated_sources"][0]["value"] == "'F_00'"


def test_the_markdown_source_line_names_the_constant_too() -> None:
    rendered = render_semantic_markdown(
        build_semantic_profile(
            _document(
                "INSERT INTO mart.t SELECT id, 'F_00' AS flag FROM ods.a",
                schema={"ods.a": ["id"]},
            )
        ),
        sections=["fields"],
    )
    assert "生成来源 常量 'F_00'" in rendered
    assert "'source_type'" not in rendered


# -------------------------------- WI-2.1c item 2: run-time and random calls (findings)


NONDETERMINISTIC_SQL = """
INSERT INTO mart.snapshot
SELECT k,
       CURRENT_TIMESTAMP() AS loaded_at,
       SUM(DATEDIFF(CURRENT_DATE, start_dt)) AS age_days,
       MAX(amount) AS peak
FROM ods.spans
WHERE dt = CURRENT_DATE AND status = 'OK'
GROUP BY k
"""

DETERMINISTIC_SQL = """
INSERT INTO mart.snapshot
SELECT k,
       UNIX_TIMESTAMP(start_ts) AS loaded_at,
       SUM(DATEDIFF(end_dt, start_dt)) AS age_days,
       MAX(amount) AS peak
FROM ods.spans
WHERE dt = '20260814' AND status = 'OK'
GROUP BY k
"""

NONDETERMINISTIC_SCHEMA = {
    "ods.spans": ["k", "start_dt", "end_dt", "start_ts", "amount", "status", "dt"]
}


def _nondeterministic(sql: str) -> list[dict]:
    profile = build_semantic_profile(_document(sql, schema=NONDETERMINISTIC_SCHEMA))
    return _findings(profile, "nondeterministic_function")


def test_a_run_time_call_becomes_one_finding_naming_the_fields_and_rules() -> None:
    """One finding, not one per call: the reader's question is "does re-running this
    reproduce the day", and the answer is a single yes or no with a list attached."""
    findings = _nondeterministic(NONDETERMINISTIC_SQL)

    assert len(findings) == 1
    text = findings[0]["text"]
    assert text.startswith("依赖作业运行时刻或随机值而非数据日期，补跑历史会得到不同结果：")
    assert "字段 loaded_at" in text
    assert "字段 age_days" in text
    # The deterministic measure in the same statement is not dragged in.
    assert "字段 peak" not in text
    # `dt = CURRENT_DATE` is one of the statement's own filter conjuncts.
    assert "规则 rule:" in text


def test_a_statement_without_one_reports_no_such_finding() -> None:
    assert _nondeterministic(DETERMINISTIC_SQL) == []


def test_a_bare_unix_timestamp_call_counts_and_a_column_argument_does_not() -> None:
    """sqlglot rewrites ``UNIX_TIMESTAMP()`` to carry a ``CURRENT_TIMESTAMP()``; the
    one-argument form reads a column and reproduces exactly."""
    bare = _nondeterministic(
        "INSERT INTO mart.t SELECT k, UNIX_TIMESTAMP() AS ts FROM ods.spans"
    )
    column = _nondeterministic(
        "INSERT INTO mart.t SELECT k, UNIX_TIMESTAMP(start_ts) AS ts FROM ods.spans"
    )

    assert len(bare) == 1
    assert column == []


def test_the_finding_kind_is_declared_and_rendered_in_section_six() -> None:
    assert "nondeterministic_function" in FINDING_KINDS
    profile = build_semantic_profile(
        _document(NONDETERMINISTIC_SQL, schema=NONDETERMINISTIC_SCHEMA)
    )
    rendered = render_semantic_markdown(profile, sections=["confidence"])

    assert "nondeterministic_function" in rendered
    assert "补跑历史会得到不同结果" in rendered


def test_the_finding_cites_the_chains_and_the_rule_blocks_it_read() -> None:
    profile = build_semantic_profile(
        _document(NONDETERMINISTIC_SQL, schema=NONDETERMINISTIC_SCHEMA)
    )
    finding = _findings(profile, "nondeterministic_function")[0]
    chain = _field(profile, "age_days")["mapping_chain_id"]

    assert chain in finding["evidence"]
    assert any(item.startswith("logic:") for item in finding["evidence"])
