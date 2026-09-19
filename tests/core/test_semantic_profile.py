"""Behavioural tests for build_semantic_profile (semantic-json/1).

This module covers ``task`` / ``inputs`` / ``rules`` / ``fields`` / ``confidence``
(rules R1, R4, R5, R7, R8); ``output_shape`` and ``stages`` (R2, R3, R6) have their own
module, ``test_semantic_shape``.

The load-bearing test here is the anti-fabrication property test: every table and column
the profile prints must be findable in the source lineage document, including the
``table.column`` key strings ``output_shape`` publishes. A derived view that invents an
identifier is worse than one that omits it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.metadata.schema_metadata import load_schema
from scope_lineage.metadata.target_table_metadata import load_target_table_metadata
from scope_lineage.render.mapping_markdown import lineage_document_digest
from scope_lineage.render.semantic_profile import (
    DOC_FORMAT,
    FAN_OUT_PATHS,
    FINDING_KINDS,
    OUTPUT_SHAPES,
    STATEMENT_PROFILE_KEYS,
    build_semantic_profile,
)
from scope_lineage.scope.scope_builder import parse_scope_lineage

from .statement_document import build_statement_documents


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = REPO_ROOT / "examples"
FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN_CASES = tuple(
    sorted(path.parent for path in (FIXTURES / "lineage_contract").glob("*/case.json"))
)


def _demo_schema():
    """The demo catalog metadata, which carries the column comments R8 quotes."""
    return load_schema(str(EXAMPLES / "metadata" / "schema_info.json"))


def _demo_target_metadata():
    return load_target_table_metadata(str(EXAMPLES / "metadata" / "target_tables"))


def _example_sql(name: str) -> str:
    return (EXAMPLES / "sql" / name).read_text(encoding="utf-8")


def _document(sql: str, task_id: str = "case_task", schema=None, target_metadata=None) -> dict:
    return to_lineage_dict(
        parse_scope_lineage(sql, task_id, schema=schema, target_metadata=target_metadata)
    )


def _customer_profile_documents() -> tuple[dict, dict]:
    result = parse_scope_lineage(
        _example_sql("customer_profile_daily.sql"),
        "customer_profile_daily",
        schema=_demo_schema(),
        target_metadata=_demo_target_metadata(),
    )
    return build_statement_documents(result)


def _channel_document() -> dict:
    return _document(
        _example_sql("order_channel_metrics.sql"),
        "order_channel_metrics",
        schema=_demo_schema(),
    )


def _field(profile: dict, column: str) -> dict:
    return next(item for item in profile["fields"] if item["column"] == column)


def _input(profile: dict, table: str) -> dict:
    return next(item for item in profile["inputs"] if item["table"] == table)


# ---------------------------------------------------------------- entry contract


def test_rejects_unknown_schema_versions() -> None:
    document = _document("INSERT INTO mart.t SELECT id FROM ods.users")
    document["schema_version"] = "3.0"
    with pytest.raises(ValueError, match="3.0"):
        build_semantic_profile(document)


def test_statement_profile_has_the_declared_keys_in_order() -> None:
    lineage, _ = _customer_profile_documents()
    profile = build_semantic_profile(lineage)

    assert list(profile) == list(STATEMENT_PROFILE_KEYS)
    assert profile["doc_format"] == DOC_FORMAT == "semantic-json/1"
    assert profile["schema_version"] == lineage["schema_version"]
    assert profile["lineage_digest"] == lineage_document_digest(lineage)
    assert profile["statement_id"] == lineage["statement_id"]


def test_a_statement_document_without_statement_id_omits_the_key() -> None:
    lineage, _ = _customer_profile_documents()
    lineage.pop("statement_id")
    profile = build_semantic_profile(lineage)
    assert "statement_id" not in profile
    assert list(profile) == [
        key for key in STATEMENT_PROFILE_KEYS if key != "statement_id"
    ]


def test_output_shape_and_stages_are_populated() -> None:
    """Their content is asserted in test_semantic_shape; here only that they are real."""
    lineage, _ = _customer_profile_documents()
    profile = build_semantic_profile(lineage)
    assert profile["output_shape"]["shape"] in OUTPUT_SHAPES
    assert [item["scope_id"] for item in profile["stages"]] == [
        "cte:latest_status",
        "cte:order_summary",
        "ROOT",
    ]


def test_building_twice_is_byte_identical() -> None:
    lineage, diagnostics = _customer_profile_documents()
    first = json.dumps(
        build_semantic_profile(lineage, diagnostics), ensure_ascii=False, sort_keys=False
    )
    second = json.dumps(
        build_semantic_profile(lineage, diagnostics), ensure_ascii=False, sort_keys=False
    )
    assert first == second


# ---------------------------------------------------------------- task block (R1)


def test_task_block_reports_the_write_target_and_its_partition() -> None:
    lineage, _ = _customer_profile_documents()
    task = build_semantic_profile(lineage)["task"]

    assert task["task_name"] == "customer_profile_daily"
    assert task["target_table"] == "mart.customer_profile_snapshot"
    assert task["stmt_kind"] == "INSERT_OVERWRITE"
    assert task["partition"] == {
        "columns": ["dt"],
        "mode": "static",
        "spec": {"dt": "${bizdate}"},
    }
    assert task["target_metadata_source"] == "target_ddl"


def test_missing_table_comment_is_null_not_invented() -> None:
    """A schema with no table-level facts yields nulls, never a name read off the table id."""
    document = _document(
        "INSERT INTO mart.t SELECT id FROM ods.users", schema={"ods.users": ["id"]}
    )
    task = build_semantic_profile(document)["task"]
    assert task["target_table_comment"] is None
    assert task["target_table_domain"] is None
    assert task["target_table_project"] is None
    assert task["target_table_owner"] is None


def test_the_demo_metadata_table_facts_reach_the_task_block() -> None:
    """WI-2.5b: the target's own export states its domain and project, so the view says so."""
    lineage, _ = _customer_profile_documents()
    task = build_semantic_profile(lineage)["task"]
    assert task["target_table_comment"] == "Customer profile snapshot"
    assert task["target_table_domain"] == "Customer"
    assert task["target_table_project"] == "Customer profile demo"
    assert task["target_table_owner"] == "demo_owner"


def test_a_statement_without_a_partition_clause_reports_an_empty_partition() -> None:
    document = _document(
        "INSERT INTO mart.t SELECT id FROM ods.users", schema={"ods.users": ["id"]}
    )
    task = build_semantic_profile(document)["task"]
    assert task["partition"] == {"columns": [], "mode": None, "spec": None}


def test_structural_summary_counts_come_from_the_contract_and_name_no_business_word() -> None:
    lineage, _ = _customer_profile_documents()
    summary = build_semantic_profile(lineage)["task"]["structural_summary"]

    assert "ods.customer_base" in summary
    assert "关联 2 个上游" in summary
    assert "1 个聚合" in summary and "1 个去重" in summary
    assert "过滤 1 处" in summary
    assert "CASE WHEN 派生 1 个字段" in summary
    assert "输出 8 列" in summary


def test_structural_summary_survives_a_document_without_a_scope_profile() -> None:
    document = _document("INSERT INTO mart.t SELECT id FROM ods.users")
    document["scope_profile"] = {}
    summary = build_semantic_profile(document)["task"]["structural_summary"]
    assert summary  # a sentence, not a crash
    assert "ROOT" in summary


# ---------------------------------------------------------------- inputs (R7, R8)


def test_inputs_are_sorted_and_carry_metadata_facts() -> None:
    lineage, _ = _customer_profile_documents()
    profile = build_semantic_profile(lineage)

    assert [item["table"] for item in profile["inputs"]] == [
        "dwd.order_detail",
        "ods.customer_base",
        "ods.customer_status_event",
    ]
    base = _input(profile, "ods.customer_base")
    assert base["metadata_complete"] is True
    assert base["table_column_count"] == 5
    assert base["read_by_scopes"] == ["ROOT"]
    assert base["comment"] == "Customer base"  # the demo schema's table-level name
    assert base["domain"] == "Customer"
    assert base["project"] == "Customer profile demo"
    assert base["owner"] == "demo_owner"
    assert base["layer"] == "ODS"


def test_input_roles_follow_r7() -> None:
    lineage, _ = _customer_profile_documents()
    profile = build_semantic_profile(lineage)

    assert _input(profile, "ods.customer_base")["role_in_task"] == "driving"
    assert _input(profile, "dwd.order_detail")["role_in_task"] == "aggregate_source"
    assert _input(profile, "ods.customer_status_event")["role_in_task"] == "dedup_source"


# WI-2.1c item 4. ROOT groups by a column of `subq:s`, whose own FROM item is `t_a`;
# `t_b` is only ever that scope's JOIN right side and `t_c` only ever ROOT's, so neither
# drives anything. Before this rule the whole statement had no driving table at all and
# the three inputs read as interchangeable lookups.
UPSTREAM_DRIVING_SQL = """
INSERT INTO mart.t
SELECT a.k AS k, MAX(c.v) AS mx
FROM (SELECT a.k AS k, b.x AS x FROM t_a a JOIN t_b b ON a.k = b.k) s
LEFT JOIN t_c c ON s.k = c.k
GROUP BY a.k
"""

UPSTREAM_DRIVING_SCHEMA = {"t_a": ["k"], "t_b": ["k", "x"], "t_c": ["k", "v"]}


def test_a_table_driving_a_scope_below_root_takes_the_driving_role() -> None:
    profile = build_semantic_profile(
        _document(UPSTREAM_DRIVING_SQL, schema=UPSTREAM_DRIVING_SCHEMA)
    )

    assert _input(profile, "t_a")["role_in_task"] == "driving"


@pytest.mark.parametrize("table", ["t_b", "t_c"])
def test_a_join_right_side_below_root_is_still_not_driving(table: str) -> None:
    """The same ``_scope_from_item`` rule ROOT is judged by: a right-only input is
    joined *to* the FROM item and never is one."""
    profile = build_semantic_profile(
        _document(UPSTREAM_DRIVING_SQL, schema=UPSTREAM_DRIVING_SCHEMA)
    )

    assert "driving" not in _input(profile, table)["roles"]


def test_a_merge_source_is_not_promoted_to_driving() -> None:
    """A MERGE writes through its WHEN branches; R2 answers ``unknown`` for its shape,
    so there is no driving path to sit on and ``merge_source`` stands alone."""
    lineage = json.loads(
        (FIXTURES / "lineage_contract" / "merge" / "lineage.json").read_text(
            encoding="utf-8"
        )
    )
    profile = build_semantic_profile(lineage)

    assert all("driving" not in item["roles"] for item in profile["inputs"])


def test_union_branch_tables_take_the_union_role() -> None:
    """WI-2.1c item 4: a branch table is also a driving one, and says both.

    Each output row arrives through exactly one branch, so the branch's own FROM item
    drives it -- the same reading ``_driving_inputs`` already applies when it descends a
    UNION. ``union_branch`` is kept beside it because which branch a row came from is a
    fact ``driving`` alone does not carry.
    """
    profile = build_semantic_profile(_channel_document())
    assert _input(profile, "ods.app_order")["roles"] == ["driving", "union_branch"]
    assert _input(profile, "ods.web_order")["role_in_task"] == "driving"
    assert "union_branch" in _input(profile, "ods.web_order")["roles"]


def test_a_join_only_table_is_enrichment_not_driving() -> None:
    sql = (
        "INSERT INTO mart.t SELECT b.id, d.name FROM ods.base b "
        "LEFT JOIN ods.dim d ON b.id = d.id"
    )
    profile = build_semantic_profile(
        _document(sql, schema={"ods.base": ["id"], "ods.dim": ["id", "name"]})
    )
    assert _input(profile, "ods.base")["role_in_task"] == "driving"
    assert _input(profile, "ods.dim")["role_in_task"] == "enrich"


def test_a_table_joined_through_a_filter_subquery_is_still_enrichment() -> None:
    """The join key pair is already pierced to the physical field; the role follows it."""
    sql = (
        "INSERT INTO mart.t SELECT b.id, d.name FROM ods.base b "
        "LEFT JOIN (SELECT id, name FROM ods.dim WHERE dt = '20260101') d ON b.id = d.id"
    )
    profile = build_semantic_profile(
        _document(sql, schema={"ods.base": ["id"], "ods.dim": ["id", "name", "dt"]})
    )
    assert _input(profile, "ods.dim")["role_in_task"] == "enrich"


def test_a_self_join_keeps_the_table_driving() -> None:
    sql = (
        "INSERT INTO mart.node_edges SELECT a.id, b.id AS parent_id "
        "FROM ods.nodes AS a JOIN ods.nodes AS b ON a.parent_id = b.id"
    )
    profile = build_semantic_profile(
        _document(sql, schema={"ods.nodes": ["id", "parent_id"]})
    )
    assert _input(profile, "ods.nodes")["role_in_task"] == "driving"


def test_a_rowset_only_table_is_labelled_rowset_only() -> None:
    sql = "INSERT INTO mart.t SELECT COUNT(*) AS n FROM ods.events"
    profile = build_semantic_profile(_document(sql, schema={"ods.events": ["id"]}))
    item = _input(profile, "ods.events")
    # ROOT aggregates over it, so `aggregate_source` outranks `rowset_only` (R7 order);
    # both facts are kept, and no column is invented for a table no column was read from.
    assert item["roles"] == ["aggregate_source", "rowset_only"]
    assert item["role_in_task"] == "aggregate_source"
    assert item["used_columns"] == []


def test_a_merge_source_table_gets_the_merge_source_role() -> None:
    """A MERGE's USING relation is ROOT itself, so no projection role would fire."""
    lineage = json.loads(
        (FIXTURES / "lineage_contract" / "merge" / "lineage.json").read_text(
            encoding="utf-8"
        )
    )
    profile = build_semantic_profile(lineage)
    assert [item["role_in_task"] for item in profile["inputs"]] == ["merge_source"]


def test_a_table_joined_by_an_unresolvable_condition_is_still_enrichment() -> None:
    """`COALESCE(a, b) = c` yields no key pair, but the pierced condition proves the read."""
    sql = (
        "INSERT INTO mart.t SELECT b.id, d.name FROM ods.base b "
        "LEFT JOIN (SELECT id, name FROM ods.dim) d "
        "ON COALESCE(b.parent_id, b.id) = d.id"
    )
    profile = build_semantic_profile(
        _document(
            sql,
            schema={"ods.base": ["id", "parent_id"], "ods.dim": ["id", "name"]},
        )
    )
    assert _input(profile, "ods.dim")["role_in_task"] == "enrich"
    assert all(item["role_in_task"] for item in profile["inputs"])


def test_every_example_input_table_gets_a_role() -> None:
    """The WI-1a review found two role-less tables; neither may come back."""
    for name in ("customer_profile_daily.sql", "customer_profile_merge.sql"):
        document = _document(_example_sql(name), "roles", schema=_demo_schema())
        profile = build_semantic_profile(document)
        assert all(item["role_in_task"] for item in profile["inputs"]), name


def test_used_column_usages_come_from_the_logic_blocks() -> None:
    lineage, _ = _customer_profile_documents()
    profile = build_semantic_profile(lineage)
    event = _input(profile, "ods.customer_status_event")
    usages = {column["name"]: column["usages"] for column in event["used_columns"]}

    assert usages["dt"] == ["filter", "partition_filter"]
    assert usages["customer_id"] == ["join_key", "window_partition"]
    assert usages["event_time"] == ["window_order"]

    order = _input(profile, "dwd.order_detail")
    order_usages = {column["name"]: column["usages"] for column in order["used_columns"]}
    assert order_usages["customer_id"] == ["join_key", "group_by"]
    assert "output" in order_usages["pay_amount"]


def test_used_columns_carry_the_metadata_comment_verbatim() -> None:
    lineage, _ = _customer_profile_documents()
    profile = build_semantic_profile(lineage)
    column = next(
        item
        for item in _input(profile, "dwd.order_detail")["used_columns"]
        if item["name"] == "pay_amount"
    )
    assert column["type"] == "decimal(18,2)"
    assert column["comment"] == "Paid amount"


def test_a_bare_parse_reports_null_comments_rather_than_guesses() -> None:
    document = _document(_example_sql("customer_profile_daily.sql"), "bare")
    profile = build_semantic_profile(document)

    for item in profile["inputs"]:
        assert item["comment"] is None
        assert item["metadata_complete"] is False
        for column in item["used_columns"]:
            assert column["comment"] is None
            assert column["type"] is None
    for field in profile["fields"]:
        assert field["target_comment"] is None
        assert field["tag"] == "SQL事实"


# ---------------------------------------------------------------- rules


def test_rule_ids_are_stable_and_sequential() -> None:
    lineage, _ = _customer_profile_documents()
    rules = build_semantic_profile(lineage)["rules"]

    assert [rule["rule_id"] for rule in rules] == [
        f"rule:{index:03d}" for index in range(1, len(rules) + 1)
    ]
    assert rules == build_semantic_profile(lineage)["rules"]
    # Topological scope order: the CTEs come before ROOT.
    scopes = [rule["scope_id"] for rule in rules]
    assert scopes.index("cte:latest_status") < scopes.index("ROOT")


def test_filter_rules_are_one_per_conjunct_and_carry_the_partition_verdict() -> None:
    lineage, _ = _customer_profile_documents()
    rules = build_semantic_profile(lineage)["rules"]
    filters = [rule for rule in rules if rule["kind"] == "filter"]

    assert len(filters) == 3
    partition_filter = next(
        rule for rule in filters if rule["scope_id"] == "cte:latest_status"
    )
    assert partition_filter["is_partition_filter"] is True
    assert partition_filter["expression"] == "`customer_status_event`.`dt` = '${bizdate}'"
    assert partition_filter["fields"] == [
        {
            "table": "ods.customer_status_event",
            "column": "dt",
            "comment": "Partition date",
        }
    ]
    assert partition_filter["evidence"] == "logic:cte:latest_status:filter:001"
    assert partition_filter["tag"] == "SQL事实"


def test_having_predicates_get_their_own_rule_kind() -> None:
    sql = (
        "INSERT INTO mart.t SELECT customer_id, SUM(amount) AS total FROM ods.orders "
        "GROUP BY customer_id HAVING SUM(amount) > 100"
    )
    profile = build_semantic_profile(
        _document(sql, schema={"ods.orders": ["customer_id", "amount"]})
    )
    kinds = {rule["kind"] for rule in profile["rules"]}
    assert "having" in kinds


def test_join_rules_carry_the_pierced_key_pairs_and_extra_conditions() -> None:
    lineage, _ = _customer_profile_documents()
    rules = build_semantic_profile(lineage)["rules"]
    join = next(
        rule
        for rule in rules
        if rule["kind"] == "join_condition"
        and rule["evidence"] == "logic:ROOT:join:001"
    )

    assert join["join_type"] == "LEFT_OUTER"
    assert join["left_input"] == "ods.customer_base"
    assert join["right_input"] == "cte:latest_status"
    # WI-1g item A2: the key as the ON clause writes it. The pierced cross product is
    # published beside it, never instead of it -- over a UNION it invents key pairs.
    assert join["key_pairs"] == [{"left": "base.customer_id", "right": "status.customer_id"}]
    assert join["physical_key_pairs"] == [
        {
            "left": "ods.customer_base.customer_id",
            "right": "ods.customer_status_event.customer_id",
        }
    ]
    assert join["extra_conditions"] == ["`status`.`row_num` = 1"]
    # (table, column) deduped and restricted to the key-pair endpoints: `customer_id`
    # appears once per side because the two sides are different tables.
    assert join["fields"] == [
        {
            "table": "ods.customer_base",
            "column": "customer_id",
            "comment": "Synthetic customer identifier",
        },
        {
            "table": "ods.customer_status_event",
            "column": "customer_id",
            "comment": "Synthetic customer identifier",
        },
    ]


def test_generated_column_conditions_are_not_published_as_join_key_fields() -> None:
    """`status.row_num = 1` pierces to the window's own inputs; they are not join keys."""
    lineage, _ = _customer_profile_documents()
    join = next(
        rule
        for rule in build_semantic_profile(lineage)["rules"]
        if rule["evidence"] == "logic:ROOT:join:001"
    )
    assert "event_time" not in {item["column"] for item in join["fields"]}
    assert join["extra_condition_fields"] == [
        {
            "table": "ods.customer_status_event",
            "column": "event_time",
            "comment": "Status event timestamp",
            "via_generated_column": True,
        }
    ]


def test_case_rules_split_branches_from_the_raw_expression_not_the_display_form() -> None:
    lineage, _ = _customer_profile_documents()
    rules = build_semantic_profile(lineage)["rules"]
    case_rule = next(rule for rule in rules if rule["kind"] == "case_branch")

    assert case_rule["branches"] == [
        {"when": "COALESCE(paid_amount_30d, 0) >= 10000", "then": "'HIGH'"},
        {"when": "COALESCE(paid_amount_30d, 0) >= 1000", "then": "'MEDIUM'"},
    ]
    assert case_rule["else"] == "'STANDARD'"
    # display_expression would have lower-cased the labels
    assert "'high'" not in json.dumps(case_rule, ensure_ascii=False)
    # the CASE reads a CTE column, so there is no physical field to claim
    assert case_rule["fields"] == []
    assert case_rule["scope_fields"] == [
        {"scope": "cte:order_summary", "column": "paid_amount_30d"}
    ]


def test_an_unparseable_case_keeps_the_expression_and_nulls_the_branches() -> None:
    lineage, _ = _customer_profile_documents()
    block = next(
        item
        for item in lineage["scopes"]["ROOT"]["logic_blocks"]
        if item["logic_type"] == "case_when"
    )
    block["raw_expression"] = "CASE WHEN )( THEN"
    case_rule = next(
        rule
        for rule in build_semantic_profile(lineage)["rules"]
        if rule["kind"] == "case_branch"
    )
    assert case_rule["branches"] is None
    assert case_rule["expression"] == "CASE WHEN )( THEN"


# ---------------------------------------------------------------- fields (R4, R5)


def test_fields_follow_the_target_column_order() -> None:
    lineage, _ = _customer_profile_documents()
    profile = build_semantic_profile(lineage)
    assert [item["column"] for item in profile["fields"]] == [
        "customer_id",
        "customer_name",
        "country_code",
        "customer_level",
        "customer_status",
        "order_count_30d",
        "paid_amount_30d",
        "last_paid_at",
    ]


def test_a_field_carries_its_target_comment_type_and_tag() -> None:
    lineage, _ = _customer_profile_documents()
    field = _field(build_semantic_profile(lineage), "customer_level")

    assert field["target_comment"] == "Derived customer level"
    assert field["type"] == "string"
    assert field["tag"] == "SQL事实+元数据事实"
    assert field["column_label"] == "mart.customer_profile_snapshot.customer_level"
    assert field["trace_complete"] is True
    assert field["ambiguous"] is False
    assert field["mapping_chain_id"] == "mc:004"


def test_field_sources_carry_the_source_column_comment() -> None:
    lineage, _ = _customer_profile_documents()
    field = _field(build_semantic_profile(lineage), "customer_level")
    assert field["sources"] == [
        {
            "table": "dwd.order_detail",
            "column": "pay_amount",
            "comment": "Paid amount",
            "transform": "AGGREGATE",
        },
        {
            "table": "dwd.order_detail",
            "column": "pay_status",
            "comment": "Payment status",
            "transform": "AGGREGATE",
        },
    ]


def test_derivation_restates_every_ordered_step() -> None:
    lineage, _ = _customer_profile_documents()
    field = _field(build_semantic_profile(lineage), "customer_level")

    assert [step["step_no"] for step in field["derivation"]] == [1, 2]
    first, second = field["derivation"]
    assert first["scope_id"] == "cte:order_summary"
    assert first["step_type"] == "aggregate"
    assert first["grain"] == "changed"
    assert first["text"] == (
        "按 customer_id 聚合：SUM(pay_amount)，仅计 pay_status = 'PAID'，否则计 0"
    )
    assert first["expression"] == (
        "SUM(CASE WHEN `order_detail`.`pay_status` = 'PAID' "
        "THEN `order_detail`.`pay_amount` ELSE 0 END)"
    )
    assert second["step_type"] == "case_when"
    assert "'HIGH'" in second["text"]


def test_a_step_outside_the_glossary_keeps_the_expression_and_nulls_the_text() -> None:
    sql = "INSERT INTO mart.t SELECT MY_UDF(a.name) AS v FROM ods.users a"
    profile = build_semantic_profile(_document(sql, schema={"ods.users": ["name"]}))
    step = _field(profile, "v")["derivation"][0]
    assert step["text"] is None
    assert step["expression"] == "MY_UDF(`a`.`name`)"


@pytest.mark.parametrize(
    "column,role",
    [
        ("customer_id", "candidate_key"),
        ("customer_name", "derived"),
        ("customer_level", "conditional_label"),
        ("order_count_30d", "measure"),
        ("paid_amount_30d", "measure"),
        ("last_paid_at", "event_time"),
    ],
)
def test_structural_roles_follow_r5(column: str, role: str) -> None:
    lineage, _ = _customer_profile_documents()
    assert _field(build_semantic_profile(lineage), column)["structural_role"] == role


def test_a_constant_union_field_is_a_constant() -> None:
    profile = build_semantic_profile(_channel_document())
    field = _field(profile, "order_channel")
    assert field["structural_role"] == "constant"
    assert field["generated_sources"] == [
        {"source_type": "CONSTANT", "value": "'APP'", "transform": "CONSTANT"},
        {"source_type": "CONSTANT", "value": "'WEB'", "transform": "CONSTANT"},
    ]
    assert field["sources"] == []
    texts = [step["text"] for step in field["derivation"]]
    assert "常量 'APP'" in texts
    assert any(text and text.startswith("合并 2 个分支") for text in texts)


def test_structural_role_looks_past_a_direct_final_step() -> None:
    """A field whose last step is DIRECT can still be an aggregate underneath."""
    sql = (
        "INSERT INTO mart.caps "
        "WITH capped AS ("
        "  SELECT account_id, MAX(CASE WHEN cap_type = '2' THEN cap_value END) AS bonus_cap"
        "  FROM ods.usage_cap GROUP BY account_id"
        ") "
        "SELECT c.account_id, c.bonus_cap FROM capped c"
    )
    profile = build_semantic_profile(
        _document(sql, schema={"ods.usage_cap": ["account_id", "cap_type", "cap_value"]})
    )
    field = _field(profile, "bonus_cap")
    assert field["transform"] == "DIRECT"
    assert field["structural_role"] == "measure"


CAPPED_SCHEMA = {"ods.usage_cap": ["account_id", "cap_type", "cap_value"]}

LABELLED = (
    "INSERT INTO mart.caps "
    "WITH b AS ("
    "  SELECT account_id, cap_value,"
    "         CASE WHEN cap_value >= 100 THEN 'HIGH' ELSE 'LOW' END AS band"
    "  FROM ods.usage_cap"
    ") "
    "SELECT b.account_id, b.band,"
    "       CASE WHEN b.cap_value > 0 THEN 0 ELSE b.cap_value END AS gap "
    "FROM b"
)

# The same cap, one layer further down, so the label's CASE and the cap's CASE end up in
# one ordered chain: the window reads `band`, which drags that step into `gap`'s steps.
CAPPED_BEHIND_A_LABEL = (
    "INSERT INTO mart.caps "
    "WITH b AS ("
    "  SELECT account_id, cap_value,"
    "         CASE WHEN cap_value >= 100 THEN 'HIGH' ELSE 'LOW' END AS band"
    "  FROM ods.usage_cap"
    "), r AS ("
    "  SELECT account_id, band, SUM(cap_value) OVER (PARTITION BY band) AS band_total"
    "  FROM b"
    ") "
    "SELECT r.account_id,"
    "       CASE WHEN r.band_total > 0 THEN 0 ELSE r.band_total END AS gap "
    "FROM r"
)


def test_a_case_with_a_constant_in_every_branch_is_the_conditional_label() -> None:
    profile = build_semantic_profile(_document(LABELLED, schema=CAPPED_SCHEMA))
    roles = {item["column"]: item["structural_role"] for item in profile["fields"]}

    assert roles["band"] == "conditional_label"
    assert roles["gap"] == "derived"


def test_a_label_earlier_in_the_chain_does_not_name_a_later_fields_role() -> None:
    """WI-2.1d item 3: a cap is a number, however many label CASEs share its chain.

    ``gap`` and ``band`` travel one ordered chain because the two threads are interleaved
    there, and asking "does *any* step carry a constant CASE" let ``band``'s label set
    name ``gap``'s role. The step that produces this field's value is its last
    conditional one; everything before it fed something else.
    """
    profile = build_semantic_profile(
        _document(CAPPED_BEHIND_A_LABEL, schema=CAPPED_SCHEMA)
    )
    roles = {item["column"]: item["structural_role"] for item in profile["fields"]}

    assert roles["gap"] == "measure"


def test_an_ambiguous_field_is_flagged_and_stays_incomplete() -> None:
    sql = """
    INSERT OVERWRITE TABLE mart.session_summary
    SELECT o.session_id AS session_id,
           CONCAT(begin_date, ' ', begin_time) AS session_start_time
    FROM (SELECT a.session_id, a.begin_date, a.begin_time FROM ods.session_events a) o
    LEFT JOIN ods.session_dim g ON o.session_id = g.session_id
    """
    profile = build_semantic_profile(_document(sql))
    field = _field(profile, "session_start_time")

    assert field["ambiguous"] is True
    assert field["trace_complete"] is False
    assert field["trace_incomplete_reasons"] == ["ambiguous_unqualified"]
    assert profile["confidence"]["ambiguous_fields"] == ["session_start_time"]
    assert profile["confidence"]["trace_incomplete_fields"] == ["session_start_time"]


def test_an_unbound_projection_is_named_without_fabricating_a_target_column() -> None:
    sql = "INSERT OVERWRITE DIRECTORY '/warehouse/export/daily' SELECT id FROM ods.users"
    profile = build_semantic_profile(_document(sql, schema={"ods.users": ["id"]}))
    field = profile["fields"][0]
    assert not field["column_label"].startswith("directory:")
    assert "写入目录 /warehouse/export/daily" in field["column_label"]


# ---------------------------------------------------------------- confidence


def test_confidence_reports_metadata_coverage_and_diagnostics_facts() -> None:
    lineage, diagnostics = _customer_profile_documents()
    confidence = build_semantic_profile(lineage, diagnostics)["confidence"]

    assert confidence["metadata_coverage"] == {
        "input_tables_complete": 3,
        "input_tables_total": 3,
        "target_comments_available": True,
        "target_metadata_source": "target_ddl",
        # WI-2.2: counted where the author wrote them -- two header lines, one alias
        # comment on `paid_amount_30d`, and one on the first JOIN's condition.
        "sql_comment_counts": {"header": 2, "output": 1, "logic": 1},
        # WI-2.4: the value dictionary's reach over this task's fields. No corpus
        # glossary was supplied, so nothing is confirmed and nothing is a candidate.
        # WI-2.12: the rule half is zero without a dictionary to read the codes this
        # task's conditions pin, so the field half is the whole of the total.
        "glossary": {
            "values_total": 3,
            "confirmed": 0,
            "candidate": 0,
            "rule_values_total": 0,
            "rule_values_confirmed": 0,
            "field_values_total": 3,
            "field_values_confirmed": 0,
            # WI-9 legacy b: all three are quoted labels a CASE writes, so all three
            # are codes somebody can be asked to name.
            "enumerable_total": 3,
            "enumerable_confirmed": 0,
        },
    }
    assert confidence["diagnostics_available"] is True
    assert confidence["fact_gap_count"] == 0
    assert confidence["fact_gap_types"] == {}
    assert confidence["trace_incomplete_fields"] == []
    # WI-1g item E7: counted by path pattern, not listed once per array index.
    assert confidence["inferred_items"] == {
        "fields[].structural_role": 8,
        "output_shape.shape": 1,
        "output_shape.grain": 1,
        "output_shape.candidate_keys": 1,
        "output_shape.unexposed_keys": 1,
        "output_shape.key_confidence": 1,
        "output_shape.fan_out_risks[]": 2,
        "stages[].actions[].intent": 1,
    }


def test_without_a_diagnostics_document_the_gap_facts_are_null_not_zero() -> None:
    lineage, _ = _customer_profile_documents()
    confidence = build_semantic_profile(lineage)["confidence"]

    assert confidence["diagnostics_available"] is False
    assert confidence["fact_gap_count"] is None
    assert confidence["fact_gap_types"] is None
    assert confidence["warning_counts"] is None


def test_fact_gaps_and_warnings_are_counted_by_type() -> None:
    case_dir = FIXTURES / "lineage_contract" / "fact_gap"
    lineage = json.loads((case_dir / "lineage.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((case_dir / "diagnostics.json").read_text(encoding="utf-8"))

    confidence = build_semantic_profile(lineage, diagnostics)["confidence"]
    assert confidence["fact_gap_count"] == 1
    assert confidence["fact_gap_types"] == {"expression_source_unresolved": 1}
    assert confidence["warning_counts"] == {"ambiguous_unqualified": 1}


def test_target_comments_unavailable_is_reported_as_such() -> None:
    document = _document(
        _example_sql("customer_profile_daily.sql"), "bare", schema=_demo_schema()
    )
    coverage = build_semantic_profile(document)["confidence"]["metadata_coverage"]
    assert coverage["target_comments_available"] is False
    assert coverage["target_metadata_source"] is None


# ---------------------------------------------------------------- task document 2.0


def test_a_task_document_becomes_one_profile_per_statement() -> None:
    task_doc = json.loads(
        (
            FIXTURES / "task_lineage_contract" / "merge_cte_source" / "lineage.json"
        ).read_text(encoding="utf-8")
    )
    profile = build_semantic_profile(task_doc)

    assert profile["doc_format"] == DOC_FORMAT
    assert profile["artifact_kind"] == "task_semantic"
    assert profile["task_id"] == task_doc["task_id"]
    assert profile["lineage_digest"] == lineage_document_digest(task_doc)
    assert profile["produced_tables"] == ["mart.event_target"]
    assert [item["statement_id"] for item in profile["statements"]] == ["stmt:001"]
    assert profile["statements"][0] == build_semantic_profile(
        task_doc["statement_lineage"]["stmt:001"]
    )


def test_task_statements_follow_statement_sequence_order() -> None:
    task_doc = json.loads(
        (
            FIXTURES / "task_lineage_contract" / "merge_cte_source" / "lineage.json"
        ).read_text(encoding="utf-8")
    )
    entry = task_doc["statement_lineage"]["stmt:001"]
    task_doc["statement_lineage"] = {"stmt:999": entry, "stmt:001": entry}

    profile = build_semantic_profile(task_doc)
    # stmt:001 is the one statement_sequence points at; the orphan follows it.
    assert [item["statement_id"] for item in profile["statements"]] == [
        "stmt:001",
        "stmt:001",
    ]
    assert len(profile["statements"]) == 2


def test_session_scoped_and_directory_targets_are_not_produced_tables() -> None:
    task_doc = json.loads(
        (
            FIXTURES / "task_lineage_contract" / "merge_cte_source" / "lineage.json"
        ).read_text(encoding="utf-8")
    )
    task_doc["final_table_states"] = {
        "mart.event_target": "state:mart.event_target:001",
        "tmp_view": "state:tmp_view:001",
        "directory:/warehouse/export": "state:dir:001",
    }
    task_doc["statement_sequence"] = [
        *task_doc["statement_sequence"],
        {
            "statement_id": "stmt:002",
            "statement_index": 1,
            "target_table": "tmp_view",
            "is_session_scoped_relation": True,
        },
    ]
    profile = build_semantic_profile(task_doc)
    assert profile["produced_tables"] == ["mart.event_target"]


# ---------------------------------------------------------------- golden corpus


@pytest.mark.parametrize("case_dir", GOLDEN_CASES, ids=lambda path: path.name)
def test_every_golden_document_builds(case_dir: Path) -> None:
    lineage = json.loads((case_dir / "lineage.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((case_dir / "diagnostics.json").read_text(encoding="utf-8"))

    profile = build_semantic_profile(lineage, diagnostics)

    assert profile["doc_format"] == DOC_FORMAT
    assert json.dumps(profile, ensure_ascii=False, sort_keys=False) == json.dumps(
        build_semantic_profile(lineage, diagnostics), ensure_ascii=False, sort_keys=False
    )


# ------------------------------------------------- anti-fabrication property test


def _known_tables(document: dict) -> set[str]:
    tables = set(document.get("source_tables") or [])
    target = document.get("target_table")
    if target:
        tables.add(str(target))
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
        if entry.get("parsed_column"):
            columns.add(str(entry["parsed_column"]))
        for source in entry.get("physical_sources") or []:
            columns.add(str(source.get("column")))
    for scope in (document.get("scopes") or {}).values():
        for output in scope.get("outputs") or []:
            columns.add(str(output.get("name")))
        for column in scope.get("columns") or []:
            columns.add(str(column.get("name")))
        for block in scope.get("logic_blocks") or []:
            for field in block.get("fields") or []:
                columns.add(str(field.get("column")))
    for chain in document.get("field_mapping_chains") or []:
        columns.add(str(chain.get("target_field")))
    return columns


def _walk(node, path: str = ""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield f"{path}.{key}", key, value
            yield from _walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{path}[{index}]")


# Lists of bare table ids that the shape and stage blocks publish. They carry
# identifiers without a `table` / `column` key, so the walk above would not see them.
_TABLE_LIST_KEYS = ("direct_source_tables", "upstream_physical_tables")

# The one place a `column` value is written qualified (`db.table.column`) rather than
# bare -- see the branch in `_assert_no_fabricated_identifiers` that reads it.
_QUALIFIED_COLUMN_PATH = "metric_spec.time_range"

# WI-2.1c: the keys that are published only in their true state.
_FLAG_ONLY_KEYS = ("mismatch", "time_dependent")


def _target_columns(document: dict) -> set[str]:
    """The columns the statement actually writes, per ``end_to_end_lineage``."""
    return {
        str(entry.get("column"))
        for entry in document.get("end_to_end_lineage") or []
        if entry.get("column")
    }


def _assert_no_fabricated_identifiers(profile: dict, document: dict) -> None:
    tables = _known_tables(document)
    columns = _known_columns(document)
    scopes = set(document.get("scopes") or {})
    written = _target_columns(document)
    for path, key, value in _walk(profile):
        if isinstance(value, list) and key in _TABLE_LIST_KEYS:
            for item in value:
                assert item in tables, f"{path}: table {item!r} is not in the source"
        # WI-1e: candidate keys are target column names, so they must be columns the
        # statement writes -- never a scope column that never reached the target.
        if isinstance(value, list) and key == "candidate_keys":
            for item in value:
                assert item in written, f"{path}: column {item!r} is not a target column"
        if key == "scope_id" and isinstance(value, str):
            assert value in scopes, f"{path}: scope {value!r} is not in the source"
        if not isinstance(value, str):
            continue
        if key == "table":
            assert value in tables, f"{path}: table {value!r} is not in the source document"
        if key == "column" and _QUALIFIED_COLUMN_PATH in path:
            # WI-2.1: a metric's time range names the column it bounds in the qualified
            # form, because a bare `dt` does not say which input was filtered. Both
            # halves are still checked against the document, one against the tables and
            # one against the columns -- the composition is exactly what could be faked.
            owner, _, bare = value.rpartition(".")
            assert bare in columns, f"{path}: column {bare!r} is not in the source document"
            assert not owner or owner in tables, f"{path}: table {owner!r} is not in the source"
        elif key == "column":
            assert value in columns, f"{path}: column {value!r} is not in the source document"
    # WI-1g item A2: a key pair is now written at scope level (``alias.column``). The
    # qualifier is whatever the ON clause wrote, which no catalog declares -- the column
    # half is the part that could be fabricated, and it is the part checked.
    for path, key, value in _walk(profile):
        if key not in ("key_pairs", "physical_key_pairs") or not isinstance(value, list):
            continue
        for pair in value:
            for side in ("left", "right"):
                name = str(pair.get(side) or "").rpartition(".")[2]
                assert name in columns, f"{path}: column {name!r} is not in the source"
    # WI-2.1c. The three signals added there publish four new keys, and none of them
    # may ever carry a free-form string: `path` is a two-word vocabulary, and the two
    # flags exist only in their true state -- a `false` would read as "checked and
    # clean", which is a claim the walk never made.
    for path, key, value in _walk(profile):
        if key == "path":
            assert value in FAN_OUT_PATHS, f"{path}: unknown path {value!r}"
        if key in _FLAG_ONLY_KEYS:
            assert value is True, f"{path}: {key} is published only when true"
        if key == "kind" and path.endswith(".kind") and "findings" in path:
            assert value in FINDING_KINDS, f"{path}: unknown finding kind {value!r}"
    # `via_scopes` names the scopes R3 pierced through, never tables: they are checked
    # against the document's scope ids rather than against `tables`, which is why the
    # list needs its own branch instead of being read as a list of owners.
    for path, key, value in _walk(profile):
        if key != "via_scopes" or not isinstance(value, list):
            continue
        for item in value:
            assert item in (document.get("scopes") or {}), (
                f"{path}: scope {item!r} is not in the source document"
            )


ANTI_FABRICATION_CASES = (
    ("customer_profile_daily.sql", True),
    ("order_channel_metrics.sql", True),
    ("customer_profile_daily.sql", False),
    ("select_star_with_schema.sql", False),
)


@pytest.mark.parametrize(
    "sql_name,with_schema", ANTI_FABRICATION_CASES, ids=lambda item: str(item)[:40]
)
def test_the_profile_never_invents_a_table_or_column(sql_name: str, with_schema) -> None:
    document = _document(
        _example_sql(sql_name),
        "anti_fabrication",
        schema=_demo_schema() if with_schema else None,
    )
    _assert_no_fabricated_identifiers(build_semantic_profile(document), document)


def test_pierced_via_scopes_are_scope_ids_and_never_tables() -> None:
    """The WI-1c/WI-1d key the walk above would otherwise never see with a value."""
    document = _document(
        "INSERT INTO mart.t SELECT t1.id, d.name FROM ("
        "  SELECT * FROM (SELECT * FROM ods.customer_base WHERE dt = '1') inner1 "
        "  WHERE customer_id IS NOT NULL"
        ") t1 "
        "LEFT JOIN ods.customer_status_event d ON t1.customer_id = d.customer_id",
        "via_scope_case",
        schema=_demo_schema(),
    )
    profile = build_semantic_profile(document)
    via = profile["output_shape"]["grain"]["via_scopes"]

    assert via == ["subq:t1", "subq:inner1"]
    for scope_id in via:
        assert scope_id in document["scopes"]
        assert scope_id not in (document["source_tables"] or [])
    _assert_no_fabricated_identifiers(profile, document)


@pytest.mark.parametrize("case_dir", GOLDEN_CASES, ids=lambda path: path.name)
def test_golden_profiles_never_invent_a_table_or_column(case_dir: Path) -> None:
    lineage = json.loads((case_dir / "lineage.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((case_dir / "diagnostics.json").read_text(encoding="utf-8"))
    _assert_no_fabricated_identifiers(
        build_semantic_profile(lineage, diagnostics), lineage
    )


# WI-2.1c: a statement that carries every key the three new signals add -- an argument
# path with its own JOIN and its own date, a date difference, and a run-time call -- so
# the property walk above is actually exercised on them rather than on their absence.
WI21C_SQL = """
INSERT INTO mart.t
SELECT a.k AS k,
       MAX(DATEDIFF(CURRENT_DATE, x.oper_dt)) AS gap_days,
       SUM(a.v) AS total
FROM ods.main a
LEFT JOIN (
  SELECT x.id AS id, x.oper_dt AS oper_dt
  FROM ods.oper x
  JOIN (SELECT id FROM ods.tag) g ON x.id = g.id
  WHERE x.dt = '20260813'
) x ON a.k = x.id
WHERE a.dt = '20260814'
GROUP BY a.k
"""

WI21C_SCHEMA = {
    "ods.main": ["k", "v", "dt"],
    "ods.oper": ["id", "oper_dt", "dt"],
    "ods.tag": ["id"],
}


def test_the_new_signals_publish_only_closed_vocabularies_and_true_flags() -> None:
    document = _document(WI21C_SQL, "wi21c_property", schema=WI21C_SCHEMA)
    profile = build_semantic_profile(document)
    spec = next(
        item["metric_spec"]
        for item in profile["fields"]
        if item["column"] == "gap_days"
    )

    # The keys really are present, so the walk below is asserting something.
    assert spec["time_dependent"] is True
    assert any(item.get("mismatch") for item in spec["time_range"])
    assert {item["path"] for item in profile["output_shape"]["fan_out_risks"]} == {
        "grain",
        "argument",
    }
    _assert_no_fabricated_identifiers(profile, document)
