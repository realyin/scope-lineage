"""WI-2.12: the dictionary reaching the rule and term layers, not only the fields.

``fields[].value_domain`` hangs off an OUTPUT column, and a warehouse keeps most of its
business codes somewhere else entirely: in ``WHERE queue_code IN ('01','07')``, in a
JOIN's extra condition, in a CASE's *condition*. A corpus can confirm all seventeen of
them and a task's document still explain four, because nothing carried the answer to the
place the code is written.

Two consumers are added here and one is deliberately not:

- ``rules[].value_meanings`` -- every code a rule pins a column to, with the dictionary's
  reading of it, ``null`` while nobody has answered;
- ``term_meaning`` on an input's used column and on a target field that has NO comment of
  its own -- a term is what the corpus calls this column name, never a comment this table
  is missing;
- a ``meaning`` is never invented and never widened: a same-named column of another table
  does not lend one, and a scope-level name only speaks inside its own task.
"""

from __future__ import annotations

import json

from scope_lineage.contract import to_lineage_dict
from scope_lineage.metadata.schema_metadata import SchemaMap
from scope_lineage.render.glossary import apply_glossary, build_glossary
from scope_lineage.render.glossary_values import apply_rule_value_meanings
from scope_lineage.render.semantic_markdown import render_semantic_markdown
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.scope.scope_builder import parse_scope_lineage


APP_SQL = (
    "INSERT INTO mart.orders SELECT o.order_id, o.pay_status, "
    "CASE WHEN o.queue_code = '01' THEN 'MANUAL' ELSE 'AUTO' END AS queue_type "
    "FROM ods.app_order o LEFT JOIN dim.channel c "
    "ON o.channel_id = c.channel_id AND c.channel_kind = 'H5' "
    "WHERE o.pay_status IN ('PAID', 'REFUND') AND o.queue_code <> '99' "
    "AND o.memo LIKE '%X%'"
)

# The same column NAME on a different table. Its confirmed meaning must not travel.
WEB_SQL = (
    "INSERT INTO mart.web_orders SELECT w.order_id, w.queue_code "
    "FROM ods.web_order w WHERE w.queue_code = '01'"
)

_APP_COLUMNS = ("order_id", "pay_status", "queue_code", "channel_id", "memo")


def _details(names, comments=None) -> list[dict]:
    comments = comments or {}
    return [
        {"name": name, "type": "string", "comment": comments.get(name)}
        for name in names
    ]


def _schema() -> SchemaMap:
    return SchemaMap(
        {
            "ods.app_order": list(_APP_COLUMNS),
            "dim.channel": ["channel_id", "channel_kind"],
            "mart.orders": ["order_id", "pay_status", "queue_type"],
        },
        column_details={
            "ods.app_order": _details(_APP_COLUMNS),
            "dim.channel": _details(["channel_id", "channel_kind"]),
            # `order_id` is the field that already HAS a comment -- the one place a term
            # must stay out of.
            "mart.orders": _details(
                ["order_id", "pay_status", "queue_type"], {"order_id": "订单号"}
            ),
        },
    )


def _web_schema() -> SchemaMap:
    return SchemaMap(
        {"ods.web_order": ["order_id", "queue_code"]},
        column_details={"ods.web_order": _details(["order_id", "queue_code"])},
    )


def _document(sql: str = APP_SQL, task_id: str = "task_a") -> dict:
    schema = _web_schema() if "web_order" in sql else _schema()
    return to_lineage_dict(parse_scope_lineage(sql, task_id, schema=schema))


def _glossary(overrides=None, documents=None) -> dict:
    return build_glossary(
        documents or [_document()], artifact_root="corpus", overrides=overrides or {}
    )


def _profile(overrides=None, documents=None) -> dict:
    documents = documents or [_document()]
    return apply_glossary(
        build_semantic_profile(documents[0]), _glossary(overrides, documents)
    )


def _rule(profile: dict, expression_fragment: str) -> dict:
    return next(
        rule
        for rule in profile["rules"]
        if expression_fragment in str(rule.get("expression"))
    )


def _field(profile: dict, column: str) -> dict:
    return next(item for item in profile["fields"] if item["column"] == column)


# ------------------------------------------------- what a rule's codes now carry


def test_a_filter_rule_carries_the_confirmed_meaning_of_the_code_it_pins() -> None:
    profile = _profile({"values": {"ods.app_order.queue_code='99'": "无效队列"}})

    assert _rule(profile, "<> '99'")["value_meanings"] == [
        {
            "column_ref": "ods.app_order.queue_code",
            "value": "99",
            "sql_literal": "'99'",
            "meaning": {"text": "无效队列", "status": "confirmed"},
        }
    ]


def test_an_in_list_publishes_every_code_and_leaves_the_unanswered_one_null() -> None:
    """The count of open questions is the point: an unanswered code is not omitted."""
    profile = _profile({"values": {"pay_status='PAID'": "已支付"}})
    items = _rule(profile, "IN ('PAID', 'REFUND')")["value_meanings"]

    assert [(item["value"], item["meaning"]) for item in items] == [
        ("PAID", {"text": "已支付", "status": "confirmed"}),
        ("REFUND", None),
    ]


def test_a_case_condition_code_reaches_the_case_rule() -> None:
    """The branch LABELS stay a field's value domain; the condition is the rule's."""
    profile = _profile({"values": {"ods.app_order.queue_code='01'": "人工队列"}})
    items = _rule(profile, "CASE WHEN")["value_meanings"]

    assert [item["value"] for item in items] == ["01"]
    assert items[0]["meaning"]["text"] == "人工队列"


def test_a_joins_extra_condition_carries_a_meaning_and_its_key_pair_does_not() -> None:
    profile = _profile({"values": {"channel_kind='H5'": "H5 渠道"}})
    items = _rule(profile, "channel_id` = ")["value_meanings"]

    # `channel_id = channel_id` compares two columns: neither side is a code.
    assert [(item["value"], item["meaning"]["text"]) for item in items] == [
        ("H5", "H5 渠道")
    ]


def test_a_match_shape_is_not_a_rule_value() -> None:
    """WI-2.4b: ``LIKE '%X%'`` names a shape, and a shape has no business definition."""
    profile = _profile({"values": {"memo='%X%'": "备注模式"}})

    assert "value_meanings" not in _rule(profile, "LIKE")


def test_a_candidate_meaning_is_published_as_a_candidate() -> None:
    """A comment that happens to spell the code out is a lead, not a confirmation."""
    document = to_lineage_dict(
        parse_scope_lineage(
            APP_SQL,
            "task_a",
            schema=SchemaMap(
                {
                    "ods.app_order": list(_APP_COLUMNS),
                    "dim.channel": ["channel_id", "channel_kind"],
                },
                column_details={
                    "ods.app_order": _details(
                        _APP_COLUMNS, {"queue_code": "队列编码，99 表示无效"}
                    ),
                    "dim.channel": _details(["channel_id", "channel_kind"]),
                },
            ),
        )
    )
    profile = apply_glossary(
        build_semantic_profile(document), _glossary(documents=[document])
    )

    assert _rule(profile, "<> '99'")["value_meanings"][0]["meaning"] == {
        # P5b: a mention is trimmed to the clause around the value.
        "text": "99 表示无效",
        "status": "candidate",
    }


# --------------------------------------------------------- what must NOT travel


def test_a_code_confirmed_on_a_same_named_column_of_another_table_stays_there() -> None:
    documents = [_document(), _document(WEB_SQL, "task_b")]
    profile = _profile(
        {"values": {"ods.web_order.queue_code='01'": "网页队列"}}, documents
    )

    # P5: this task's own CASE offers `MANUAL` as a candidate for `'01'`. What must not
    # travel is the answer somebody confirmed about the OTHER table's column.
    meaning = _rule(profile, "CASE WHEN")["value_meanings"][0]["meaning"]
    assert meaning == {"text": "MANUAL", "status": "candidate"}


def test_a_scope_level_name_speaks_only_inside_the_task_that_observed_it() -> None:
    """``cte.flag`` is a name inside one statement, not a column of the warehouse."""
    rule = {
        "kind": "filter",
        "scope_id": "cte",
        "expression": "flag = 'HIT'",
        "fields": [],
        "scope_fields": [{"scope": "cte", "column": "flag"}],
    }
    entry = {
        "column_ref": "cte.flag",
        "logical": True,
        "column": "flag",
        "value": "HIT",
        "kind": "literal",
        "observations": [{"task": "task_b", "context": "case_then"}],
        "meaning": {"text": "命中", "source": "override"},
    }

    elsewhere = dict(rule)
    apply_rule_value_meanings([elsewhere], [entry], "task_a")
    here = dict(rule)
    apply_rule_value_meanings([here], [entry], "task_b")

    assert "value_meanings" not in elsewhere
    assert here["value_meanings"][0]["meaning"] == {"text": "命中", "status": "confirmed"}


def test_without_a_glossary_no_rule_carries_the_key_and_the_markdown_is_unchanged() -> None:
    plain = build_semantic_profile(_document())
    rendered = render_semantic_markdown(plain)

    applied = apply_glossary(build_semantic_profile(_document()), None)

    assert all("value_meanings" not in rule for rule in plain["rules"])
    assert render_semantic_markdown(applied) == rendered
    assert "取值含义" not in rendered
    assert "（取值：" not in rendered


# ------------------------------------------------------------------- A2 coverage


def test_the_coverage_block_counts_the_two_halves_and_dedupes_the_union() -> None:
    """``pay_status`` is pinned by the WHERE and carried out under the same name."""
    profile = _profile(
        {
            "values": {
                "pay_status='PAID'": "已支付",
                "ods.app_order.queue_code='01'": "人工队列",
            }
        }
    )
    coverage = profile["confidence"]["metadata_coverage"]["glossary"]

    assert coverage["field_values_confirmed"] == 1
    assert coverage["rule_values_confirmed"] == 2
    # 'PAID' is one business question however many places write it.
    assert coverage["confirmed"] == 2
    assert coverage["values_total"] < (
        coverage["field_values_total"] + coverage["rule_values_total"]
    )
    assert profile["confidence"]["confirmations"]["rule_values_confirmed"] == 2
    assert profile["confidence"]["confirmations"]["values_confirmed"] == 1


# ------------------------------------------------------------------ term meanings


def test_a_confirmed_term_reaches_a_field_that_has_no_target_comment() -> None:
    profile = _profile({"terms": {"queue_type": "队列类型", "order_id": "订单标识"}})

    assert _field(profile, "queue_type")["term_meaning"] == {
        "text": "队列类型",
        "status": "confirmed",
    }
    # `order_id` HAS a comment: a term never overwrites or impersonates one.
    assert "term_meaning" not in _field(profile, "order_id")


def test_a_terms_key_sits_behind_the_comment_it_stands_in_for() -> None:
    """Key order is part of ``semantic-json/1``; a reader diffs these files."""
    profile = _profile({"terms": {"queue_type": "队列类型", "queue_code": "队列编码"}})
    keys = list(_field(profile, "queue_type"))
    column = next(
        item
        for entry in profile["inputs"]
        for item in entry["used_columns"]
        if item["name"] == "queue_code"
    )

    assert keys.index("target_comment") < keys.index("term_meaning")
    assert keys.index("term_meaning") < keys.index("type")
    assert list(column).index("term_meaning") < list(column).index("usages")


def test_an_input_column_carries_its_term_beside_its_own_comment() -> None:
    profile = _profile({"terms": {"queue_code": "队列编码"}})
    columns = {
        item["name"]: item
        for entry in profile["inputs"]
        for item in entry["used_columns"]
    }

    assert columns["queue_code"]["term_meaning"]["text"] == "队列编码"
    assert "term_meaning" not in columns["pay_status"]


# --------------------------------------------------------------------- markdown


def test_the_rule_table_gains_a_value_column_only_when_the_dictionary_speaks() -> None:
    answered = render_semantic_markdown(
        _profile({"values": {"ods.app_order.queue_code='99'": "无效队列"}})
    )
    # A corpus with no comment and no CASE label: the dictionary has nothing to say
    # about `'01'`, so the column is not there at all.
    silent = render_semantic_markdown(_profile(documents=[_document(WEB_SQL, "task_b")]))

    assert "| 规则 | 类型 | 阶段 | 条件 | 取值含义 |" in answered
    assert "'99'＝无效队列" in answered
    assert "取值含义" not in silent


def test_a_candidate_is_marked_in_the_rule_table_and_a_confirmed_one_is_not() -> None:
    profile = _profile({"values": {"pay_status='PAID'": "已支付"}})
    profile["rules"][1]["value_meanings"][1]["meaning"] = {
        "text": "退款",
        "status": "candidate",
    }
    rendered = render_semantic_markdown(profile)

    assert "'PAID'＝已支付" in rendered
    assert "'REFUND'＝? 退款" in rendered


def test_a_restated_filter_ends_with_the_codes_it_pins() -> None:
    rendered = render_semantic_markdown(
        _profile({"values": {"pay_status='PAID'": "已支付"}})
    )

    assert "（取值：'PAID'＝已支付）" in rendered


def test_a_restatement_with_more_than_three_codes_points_at_the_rule_table() -> None:
    sql = (
        "INSERT INTO mart.orders SELECT o.order_id, o.pay_status, o.queue_code "
        "AS queue_type FROM ods.app_order o "
        "WHERE o.queue_code IN ('01', '02', '03', '04')"
    )
    document = to_lineage_dict(parse_scope_lineage(sql, "task_a", schema=_schema()))
    overrides = {
        "values": {f"ods.app_order.queue_code='{code}'": f"队列{code}"
                   for code in ("01", "02", "03", "04")}
    }
    profile = apply_glossary(
        build_semantic_profile(document),
        build_glossary([document], artifact_root="corpus", overrides=overrides),
    )

    rendered = render_semantic_markdown(profile)

    assert "（取值：'01'＝队列01；'02'＝队列02；'03'＝队列03；等 4 个，见规则表）" in rendered


def test_the_field_section_states_a_term_on_its_own_line() -> None:
    rendered = render_semantic_markdown(_profile({"terms": {"queue_type": "队列类型"}}))

    assert "- 术语：队列类型（人工确认）（元数据事实）" in rendered
    # The missing comment is still reported as missing: the term did not fill it.
    assert "- 目标注释：注释未知" in rendered
    assert "| 队列类型 ✓ |" in rendered


def test_the_field_list_has_no_term_column_when_no_term_was_confirmed() -> None:
    assert "术语" not in render_semantic_markdown(_profile())


# ------------------------------------------------------------------- round trip


def test_the_profile_stays_json_serialisable_with_both_new_keys() -> None:
    profile = _profile(
        {
            "values": {"ods.app_order.queue_code='01'": "人工队列"},
            "terms": {"queue_type": "队列类型"},
        }
    )

    assert json.loads(json.dumps(profile, ensure_ascii=False))["rules"]
