"""Behavioural tests for the Chinese restatement templates (R4) and the function glossary.

The templates are the only place where the semantic profile puts SQL into Chinese, so
they carry the whole "structural words only" promise: a template may name an operation
(聚合/去重/窗口/常量/合并) and echo an expression verbatim, and may never name a business
concept. Literals are echoed from ``raw_expression``-shaped input, never from
``display_expression`` (which lower-cases string literals).
"""

from __future__ import annotations

import pytest

from scope_lineage.render import semantic_text


# ------------------------------------------------------------------ the glossary


def test_glossary_is_an_explicit_enumerable_constant() -> None:
    assert isinstance(semantic_text.FUNCTION_GLOSSARY, dict)
    assert set(semantic_text.FUNCTION_GLOSSARY) == {
        "COALESCE",
        "NVL",
        "IFNULL",
        "CAST",
        "CONCAT",
        "CONCAT_WS",
        "DATE_ADD",
        "DATE_SUB",
        "DATE_FORMAT",
        "TO_DATE",
        "DATEDIFF",
        "DATE_TRUNC",
        "UPPER",
        "LOWER",
        "TRIM",
        "IF",
        "ROUND",
        "FLOOR",
        "CEIL",
        "SUM",
        "COUNT",
        "AVG",
        "MIN",
        "MAX",
        "REGEXP_REPLACE",
        "REGEXP_EXTRACT",
        "RLIKE",
        "LIKE",
        "GET_JSON_OBJECT",
        "FROM_JSON",
        "JSON_TUPLE",
        "EXPLODE",
        "POSEXPLODE",
        "SPLIT",
        "SUBSTRING",
        "SUBSTR",
        "LENGTH",
        "REPLACE",
        "UNIX_TIMESTAMP",
        "FROM_UNIXTIME",
        "CURRENT_TIMESTAMP",
        "CURRENT_DATE",
        "NULLIF",
        "NVL2",
        "ABS",
        "GREATEST",
        "LEAST",
    }


def test_every_glossary_entry_names_a_template_the_module_implements() -> None:
    for name, kind in semantic_text.FUNCTION_GLOSSARY.items():
        assert kind in semantic_text.TEMPLATE_KINDS, f"{name} -> unknown kind {kind}"


# ------------------------------------------------------- expression restatements


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("COALESCE(`base`.`customer_name`, 'UNKNOWN')", "空值回填为 'UNKNOWN'"),
        ("NVL(a, 0)", "空值回填为 0"),
        ("IFNULL(a, 0)", "空值回填为 0"),
        ("CAST(`t`.`amount` AS STRING)", "转换为 STRING"),
        ("CONCAT(a, '-', b)", "拼接"),
        ("CONCAT_WS('-', a, b)", "拼接"),
        ("UPPER(`t`.`code`)", "文本规整（UPPER）"),
        ("LOWER(`t`.`code`)", "文本规整（LOWER）"),
        ("TRIM(`t`.`code`)", "文本规整（TRIM）"),
        ("ROUND(`t`.`amount`, 2)", "取整（ROUND）"),
        ("FLOOR(`t`.`amount`)", "取整（FLOOR）"),
        ("CEIL(`t`.`amount`)", "取整（CEIL）"),
    ],
)
def test_function_templates(expression: str, expected: str) -> None:
    assert semantic_text.describe_function_expression(expression) == expected


def test_date_functions_keep_the_expression_verbatim() -> None:
    text = semantic_text.describe_function_expression("DATE_ADD('${bizdate}', -29)")
    assert text is not None
    assert text.startswith("日期运算：")
    assert "${bizdate}" in text


def test_if_renders_condition_then_else() -> None:
    text = semantic_text.describe_function_expression(
        "IF(`t`.`status` = 'PAID', `t`.`amount`, 0)"
    )
    assert text == "二值条件：status = 'PAID' 则 amount 否则 0"


def test_a_function_outside_the_glossary_is_not_restated() -> None:
    assert semantic_text.describe_function_expression("MY_UDF(`t`.`a`)") is None


def test_an_unparseable_expression_is_not_restated() -> None:
    assert semantic_text.describe_function_expression("SELECT FROM WHERE )(") is None


def test_string_literals_keep_their_case() -> None:
    """``display_expression`` lower-cases literals; the templates must not."""
    text = semantic_text.describe_case(
        "CASE WHEN a >= 10000 THEN 'HIGH' ELSE 'STANDARD' END"
    )
    assert text is not None
    assert "'HIGH'" in text and "'STANDARD'" in text
    assert "'high'" not in text


# ------------------------------------------------------------------ CASE / branches


def test_case_branches_are_split_into_when_then_pairs() -> None:
    branches, otherwise = semantic_text.split_case_branches(
        "CASE WHEN COALESCE(`s`.`amt`, 0) >= 10000 THEN 'HIGH' "
        "WHEN COALESCE(`s`.`amt`, 0) >= 1000 THEN 'MEDIUM' ELSE 'STANDARD' END"
    )
    assert branches == [
        {"when": "COALESCE(amt, 0) >= 10000", "then": "'HIGH'"},
        {"when": "COALESCE(amt, 0) >= 1000", "then": "'MEDIUM'"},
    ]
    assert otherwise == "'STANDARD'"


def test_split_case_branches_returns_none_when_it_cannot_parse_a_case() -> None:
    assert semantic_text.split_case_branches("`t`.`a` + 1") is None
    assert semantic_text.split_case_branches("CASE WHEN )(") is None


def test_case_template_lists_branches_with_an_arrow() -> None:
    text = semantic_text.describe_case(
        "CASE WHEN a >= 10000 THEN 'HIGH' WHEN a >= 1000 THEN 'MEDIUM' ELSE 'STANDARD' END"
    )
    assert text == "a >= 10000 → 'HIGH'；a >= 1000 → 'MEDIUM'；否则 'STANDARD'"


def test_case_template_folds_more_than_six_branches() -> None:
    branches = " ".join(f"WHEN a = {index} THEN '{index}'" for index in range(7))
    text = semantic_text.describe_case(f"CASE {branches} END")
    assert text is not None
    assert text.startswith("7 个分支，前 3 个：")
    assert "a = 2 → '2'" in text
    assert "a = 3 → '3'" not in text


def test_if_is_also_a_case_shape() -> None:
    branches, otherwise = semantic_text.split_case_branches("IF(a = 1, 'Y', 'N')")
    assert branches == [{"when": "a = 1", "then": "'Y'"}]
    assert otherwise == "'N'"


# ------------------------------------------------------------------ step templates


def test_aggregate_template_names_the_group_by_keys() -> None:
    text = semantic_text.describe_aggregate(
        "MAX(`order_detail`.`paid_at`)", ["customer_id"]
    )
    # WI-1f: no declared type is handed in, so MAX reads as the scalar maximum.
    assert text == "按 customer_id 聚合：MAX(paid_at)（最大值）"


def test_aggregate_template_without_group_by_says_so() -> None:
    assert semantic_text.describe_aggregate("COUNT(*)", []) == "全表聚合：COUNT(*)（行数）"


def test_aggregate_template_keeps_distinct() -> None:
    text = semantic_text.describe_aggregate(
        "COUNT(DISTINCT `order_detail`.`order_id`)", ["customer_id"]
    )
    assert text == "按 customer_id 聚合：COUNT(DISTINCT order_id)（去重计数 order_id）"


def test_aggregate_over_a_case_states_the_counted_condition() -> None:
    text = semantic_text.describe_aggregate(
        "SUM(CASE WHEN `order_detail`.`pay_status` = 'PAID' "
        "THEN `order_detail`.`pay_amount` ELSE 0 END)",
        ["customer_id"],
    )
    assert text == (
        "按 customer_id 聚合：SUM(pay_amount)，仅计 pay_status = 'PAID'，否则计 0"
    )


def test_window_template_states_partition_order_and_function() -> None:
    text = semantic_text.describe_window(
        "ROW_NUMBER() OVER (PARTITION BY `e`.`customer_id` ORDER BY `e`.`event_time` DESC)"
    )
    assert text == "窗口函数 ROW_NUMBER()；按 customer_id 分组；按 event_time DESC 排序"


def test_window_template_without_partition_omits_the_clause() -> None:
    text = semantic_text.describe_window("RANK() OVER (ORDER BY `e`.`dt` ASC)")
    assert text == "窗口函数 RANK()；按 dt ASC 排序"


def test_constant_template() -> None:
    assert semantic_text.describe_constant("'APP'") == "常量 'APP'"


def test_union_template_counts_the_branches() -> None:
    text = semantic_text.describe_union(
        ["union:n:b01.order_channel", "union:n:b02.order_channel"]
    )
    assert text == "合并 2 个分支（来自 union:n:b01.order_channel、union:n:b02.order_channel）"


def test_direct_projection_template() -> None:
    assert (
        semantic_text.describe_direct_projection(["cte:s.last_paid_at"])
        == "直接投影自 cte:s.last_paid_at"
    )
    assert semantic_text.describe_direct_projection([]) == "直接投影"


# ------------------------------------------------------------------ the dispatcher


def test_describe_step_dispatches_on_step_type() -> None:
    assert semantic_text.describe_step(
        "aggregate", "MAX(`t`.`paid_at`)", group_by_keys=["customer_id"]
    ) == "按 customer_id 聚合：MAX(paid_at)（最大值）"
    assert semantic_text.describe_step("constant", "'APP'") == "常量 'APP'"
    assert semantic_text.describe_step(
        "case_when", "CASE WHEN a = 1 THEN 'Y' ELSE 'N' END"
    ) == "a = 1 → 'Y'；否则 'N'"
    assert semantic_text.describe_step(
        "direct_projection", "`s`.`x`", input_fields=["cte:s.x"]
    ) == "直接投影自 cte:s.x"


def test_describe_step_returns_none_for_an_expression_outside_the_glossary() -> None:
    assert semantic_text.describe_step("expression", "MY_UDF(`t`.`a`)") is None


def test_udf_is_always_marked_black_box() -> None:
    assert semantic_text.describe_step(
        "expression", "MY_UDF(`t`.`a`)", has_udf=True
    ) == semantic_text.UDF_MARKER
    text = semantic_text.describe_step(
        "aggregate", "MAX(`t`.`paid_at`)", group_by_keys=["k"], has_udf=True
    )
    assert text is not None and text.endswith("；" + semantic_text.UDF_MARKER)


def test_describe_step_is_deterministic() -> None:
    args = ("aggregate", "SUM(CASE WHEN a = 'X' THEN b ELSE 0 END)")
    assert semantic_text.describe_step(*args, group_by_keys=["k"]) == (
        semantic_text.describe_step(*args, group_by_keys=["k"])
    )


def test_constant_label_case_is_recognised_only_when_every_branch_is_literal() -> None:
    assert semantic_text.is_constant_label_case(
        "CASE WHEN a >= 1 THEN 'HIGH' ELSE 'STANDARD' END"
    )
    assert semantic_text.is_constant_label_case("IF(a = 1, 'Y', 'N')")
    assert not semantic_text.is_constant_label_case(
        "CASE WHEN a >= 1 THEN b ELSE 'STANDARD' END"
    )
    assert not semantic_text.is_constant_label_case("`t`.`a` + 1")
    assert not semantic_text.is_constant_label_case("CASE WHEN )( THEN")


# --------------------------------------------------- WI-1d glossary additions


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("REGEXP_REPLACE(`t`.`a`, '[0-9]+', '')", "正则替换"),
        ("REGEXP_EXTRACT(`t`.`a`, '([0-9]+)', 1)", "正则提取"),
        ("`t`.`a` RLIKE '^ABC'", "正则匹配"),
        ("GET_JSON_OBJECT(`t`.`a`, '$.b')", "JSON 解析（GET_JSON_OBJECT）"),
        ("FROM_JSON(`t`.`a`, 'map<string,string>')", "JSON 解析（FROM_JSON）"),
        ("JSON_TUPLE(`t`.`a`, 'b')", "JSON 解析（JSON_TUPLE）"),
        ("EXPLODE(`t`.`a`)", "拆分/展开（EXPLODE）"),
        ("POSEXPLODE(`t`.`a`)", "拆分/展开（POSEXPLODE）"),
        ("SPLIT(`t`.`a`, ',')", "拆分/展开（SPLIT）"),
        ("SUBSTRING(`t`.`a`, 1, 3)", "文本规整（SUBSTRING）"),
        ("SUBSTR(`t`.`a`, 1, 3)", "文本规整（SUBSTRING）"),
        ("LENGTH(`t`.`a`)", "文本规整（LENGTH）"),
        ("REPLACE(`t`.`a`, 'x', 'y')", "文本规整（REPLACE）"),
        ("NULLIF(`t`.`a`, 0)", "空值处理（NULLIF）"),
        ("NVL2(`t`.`a`, 1, 2)", "空值处理（NVL2）"),
        ("ABS(`t`.`a`)", "数值函数（ABS）"),
        ("GREATEST(`t`.`a`, `t`.`b`)", "数值函数（GREATEST）"),
        ("LEAST(`t`.`a`, `t`.`b`)", "数值函数（LEAST）"),
    ],
)
def test_wi_1d_function_templates(expression: str, expected: str) -> None:
    assert semantic_text.describe_function_expression(expression) == expected


@pytest.mark.parametrize(
    "expression",
    [
        "UNIX_TIMESTAMP(`t`.`ts`)",
        "FROM_UNIXTIME(`t`.`ts`)",
        "CURRENT_TIMESTAMP()",
        "CURRENT_DATE",
    ],
)
def test_the_unix_and_current_time_functions_join_the_date_family(expression: str) -> None:
    text = semantic_text.describe_function_expression(expression)
    assert text is not None and text.startswith("日期运算：")


def test_like_is_matched_as_a_pattern_and_keeps_its_wildcards() -> None:
    """LIKE parses to a predicate, not a function, so the glossary needs it by name.
    The wildcards are part of the fact and must survive verbatim."""
    text = semantic_text.describe_function_expression("`t`.`code` LIKE '%A_B%'")
    assert text == "模式匹配：code LIKE '%A_B%'"


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("`t`.`a` + `t`.`b`", "算术运算：a + b"),
        ("`t`.`a` * `t`.`b` / 100", "算术运算：a * b / 100"),
        ("COALESCE(`t`.`a`, 0) + COALESCE(`t`.`b`, 0)", "算术运算：COALESCE(a, 0) + COALESCE(b, 0)"),
        ("(`t`.`a` - `t`.`b`) AS diff", "算术运算：a - b"),
    ],
)
def test_arithmetic_is_restated_with_the_expression_minus_its_alias(
    expression: str, expected: str
) -> None:
    assert semantic_text.describe_function_expression(expression) == expected


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("`t`.`a` + /* 2026 rewrite */ `t`.`b`", "算术运算：a + b"),
        ("`t`.`a` + `t`.`b` -- keep in sync", "算术运算：a + b"),
        ("CAST(/* widened */ `t`.`a` AS STRING)", "转换为 STRING"),
    ],
)
def test_a_sql_comment_is_dropped_from_the_restatement(
    expression: str, expected: str
) -> None:
    """The comment is a note to the next engineer, not part of the computation. It
    survives in the profile's verbatim ``expression`` key, not in the sentence."""
    assert semantic_text.describe_function_expression(expression) == expected


def test_a_comment_inside_a_case_is_dropped_from_the_branch_list() -> None:
    text = semantic_text.describe_case(
        "CASE WHEN /* legacy */ a = 1 THEN 'HIGH' ELSE 'LOW' END"
    )
    assert text == "a = 1 → 'HIGH'；否则 'LOW'"


def test_an_unknown_function_is_still_not_restated_after_the_additions() -> None:
    """The additions widen the vocabulary; they must not add a catch-all sentence."""
    assert semantic_text.describe_function_expression("SOME_TEAM_UDF(`t`.`a`)") is None
    assert semantic_text.describe_function_expression("`t`.`a` IS NOT NULL") is None


# ------------------------------------------------- WI-1g: nested calls, keys, sources


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("MAX(DATEDIFF(a, b))", "MAX(DATEDIFF(a, b))（最大值；日期差（天）：a − b）"),
        ("SUM(COALESCE(a, 0))", "SUM(COALESCE(a, 0))（空值回填为 0）"),
        # a bare column is already visible in the call text; a second gloss adds nothing
        ("MAX(a)", "MAX(a)（最大值）"),
        # arithmetic restates itself, so it is deliberately left unglossed
        ("SUM(a - b)", "SUM(a - b)"),
        ("MIN(my_udf(a))", "MIN(MY_UDF(a))（最小值）"),
    ],
)
def test_an_aggregate_gloss_restates_its_argument_when_that_says_something(
    expression: str, expected: str
) -> None:
    assert semantic_text.describe_aggregate_call(expression) == expected


def test_a_window_over_a_nested_call_restates_the_inner_call() -> None:
    text = semantic_text.describe_window(
        "SUM(DATEDIFF(a, b)) OVER (PARTITION BY id)"
    )
    assert text is not None
    assert text.startswith("窗口函数 SUM(DATEDIFF(a, b))（日期差（天）：a − b）")


@pytest.mark.parametrize(
    "pair,expected",
    [
        ({"left": "a.segment", "right": "d.segment"}, "segment"),
        ({"left": "a.customer_id", "right": "d.id"}, "a.customer_id = d.id"),
        ({"left": "", "right": ""}, " = "),
    ],
)
def test_a_join_key_pair_drops_the_qualifiers_only_when_both_sides_agree(
    pair: dict, expected: str
) -> None:
    assert semantic_text.join_key_text(pair) == expected


@pytest.mark.parametrize(
    "expression,expected",
    [
        # every one of these is a Spark builtin the core function catalog does not list
        ("HOUR(dt)", False),
        ("RANK() OVER (PARTITION BY id ORDER BY a)", False),
        ("LAG(a, 1) OVER (PARTITION BY id ORDER BY d)", False),
        ("YEAR(d)", False),
        ("my_udf(a)", True),
        ("COALESCE(my_udf(a), 0)", True),
        # unparseable is not "no UDF": the caller keeps the contract's own verdict
        ("SELECT FROM WHERE ((", None),
        (None, None),
    ],
)
def test_the_builtin_whitelist_is_sqlglots_own_grammar(expression, expected) -> None:
    assert semantic_text.has_unknown_function(expression) is expected


@pytest.mark.parametrize(
    "item,expected",
    [
        ({"source_type": "CONSTANT", "value": "'F_00'"}, "常量 'F_00'"),
        ({"source_type": "SYSTEM", "value": "current_date()"}, "系统值 current_date()"),
        ({"source_type": "OTHER", "value": "x"}, "x"),
        ("already a string", "already a string"),
    ],
)
def test_a_generated_source_is_named_not_repr_ed(item, expected: str) -> None:
    assert semantic_text.generated_source_text(item) == expected


def test_a_branch_grouped_summary_numbers_the_branches_and_merges_after_them() -> None:
    summary = semantic_text.describe_field_summary(
        target_comment="渠道编码",
        step_texts=["文本规整（UPPER）"],
        direct_notes=[],
        source_notes=["ods.a.code（无）"],
        expression=None,
        branch_steps=[
            {"index": 1, "label": "ods.a", "texts": ["正则替换"]},
            {"index": 2, "label": "ods.b", "texts": ["正则提取"]},
        ],
    )
    assert summary == (
        "渠道编码：分支 1（来自 ods.a）：正则替换；分支 2（来自 ods.b）：正则提取；"
        "合并后 文本规整（UPPER）；来源 ods.a.code（无）"
    )


def test_branch_groups_past_the_limit_are_counted_not_listed() -> None:
    summary = semantic_text.describe_field_summary(
        target_comment=None,
        step_texts=[],
        direct_notes=[],
        source_notes=[],
        expression=None,
        branch_steps=[
            {"index": index, "label": f"ods.s{index}", "texts": ["正则替换"]}
            for index in range(1, 7)
        ],
    )
    assert "（共 6 个分支，完整链路见 derivation）" in summary
    assert "分支 4" not in summary


# ------------------------------------------------ WI-2.1c item 1: date-difference units


@pytest.mark.parametrize(
    "expression,unit",
    [
        ("DATEDIFF(end_dt, start_dt)", "天"),
        ("MONTHS_BETWEEN(end_dt, start_dt)", "月"),
        ("UNIX_TIMESTAMP(end_ts) - UNIX_TIMESTAMP(start_ts)", "秒"),
        ("MAX(DATEDIFF(end_dt, start_dt))", "天"),
        ("AVG(MONTHS_BETWEEN(end_dt, start_dt))", "月"),
        ("SUM(UNIX_TIMESTAMP(end_ts) - UNIX_TIMESTAMP(start_ts))", "秒"),
        ("(DATEDIFF(end_dt, start_dt))", "天"),
    ],
)
def test_a_date_difference_states_its_own_unit(expression: str, unit: str) -> None:
    assert semantic_text.date_difference_unit(expression) == unit


@pytest.mark.parametrize(
    "expression",
    [
        # A date built *from* an interval is a date, not an interval.
        "DATE_ADD(start_dt, DATEDIFF(end_dt, start_dt))",
        # Only the difference of two epoch readings is seconds; minus a number is not.
        "UNIX_TIMESTAMP(end_ts) - 1",
        "UNIX_TIMESTAMP(end_ts)",
        "SUM(amount)",
        "COUNT(1)",
        # An aggregate outside the transparent set says nothing about the unit.
        "COUNT(DATEDIFF(end_dt, start_dt))",
        None,
        "not sql (((",
    ],
)
def test_anything_else_earns_no_difference_unit(expression) -> None:
    assert semantic_text.date_difference_unit(expression) is None


def test_the_difference_unit_is_read_at_the_function_tier_but_after_a_comment() -> None:
    assert semantic_text.unit_hint([None], "MAX", expressions=["MAX(DATEDIFF(a, b))"]) == (
        "天",
        "function",
    )
    # A person wrote a unit down; that still wins over the call's own reading.
    assert semantic_text.unit_hint(
        ["间隔天数"], "MAX", expressions=["MAX(DATEDIFF(a, b))"]
    ) == ("天数", "comment")
    assert semantic_text.unit_hint([None], "SUM", expressions=["SUM(amount)"]) == (
        None,
        None,
    )


def test_every_published_unit_hint_is_in_the_declared_vocabulary() -> None:
    assert semantic_text.date_difference_unit("DATEDIFF(a, b)") in semantic_text.UNIT_HINTS
    for hint in ("天", "月", "秒"):
        assert hint in semantic_text.UNIT_HINTS


# ------------------------------------------- WI-2.1c item 2: run-time / random calls


@pytest.mark.parametrize(
    "expression,found",
    [
        ("CURRENT_TIMESTAMP", ["CURRENT_TIMESTAMP"]),
        ("current_date", ["CURRENT_DATE"]),
        ("NOW()", ["NOW"]),
        # sqlglot rewrites the no-argument form to UNIX_TIMESTAMP(CURRENT_TIMESTAMP()),
        # so the canonical name is what the rule matches.
        ("UNIX_TIMESTAMP()", ["CURRENT_TIMESTAMP"]),
        ("RAND()", ["RAND"]),
        ("UUID()", ["UUID"]),
        ("DATEDIFF(CURRENT_DATE, order_dt)", ["CURRENT_DATE"]),
    ],
)
def test_a_run_time_call_is_named(expression: str, found: list) -> None:
    assert semantic_text.nondeterministic_functions(expression) == found


@pytest.mark.parametrize(
    "expression",
    ["UNIX_TIMESTAMP(order_ts)", "DATEDIFF(end_dt, start_dt)", "dt = '20260814'", None],
)
def test_a_deterministic_expression_names_nothing(expression) -> None:
    assert semantic_text.nondeterministic_functions(expression) == []


def test_an_unparseable_expression_is_not_reported_as_nondeterministic() -> None:
    """"Cannot tell" is not "contains one" -- this feeds a finding that names fields."""
    assert semantic_text.nondeterministic_functions("not sql (((") == []


# --------------------------------------- WI-2.1c item 3: the gap between two literals


def test_two_day_literals_are_measured_in_whole_days() -> None:
    assert semantic_text.predicate_literal_days_between(
        "dt = '20260814'", "dt = '20260801'"
    ) == 13
    assert semantic_text.predicate_literal_days_between(
        "dt = '2026-08-14'", "dt = '20260814'"
    ) == 0


@pytest.mark.parametrize(
    "left,right",
    [
        # Not written as a plain day.
        ("dt = 'X1'", "dt = '20260814'"),
        # Not an equality against a literal.
        ("dt >= '20260814'", "dt = '20260801'"),
        ("dt = ${bizdate}", "dt = '20260801'"),
        (None, "dt = '20260801'"),
    ],
)
def test_an_unmeasurable_pair_answers_none_rather_than_a_number(left, right) -> None:
    assert semantic_text.predicate_literal_days_between(left, right) is None


# ---------------------------------------------- WI-2.1d: four judgements, four probes


def test_a_constant_label_case_survives_its_alias_and_its_signed_literals() -> None:
    """The wrapper an expression arrives in is not part of what it computes."""
    assert semantic_text.is_constant_label_case(
        "CASE WHEN a >= 1 THEN 'HIGH' ELSE 'STANDARD' END AS band"
    )
    assert semantic_text.is_constant_label_case("(CASE WHEN a >= 1 THEN 1 ELSE -1 END)")
    assert semantic_text.is_constant_label_case("CASE WHEN a >= 1 THEN 1 ELSE NULL END")


@pytest.mark.parametrize(
    "expression",
    [
        # WI-2.1d item 3: a cap returns a column from one branch, so it labels nothing.
        "CASE WHEN `t`.`x` > 0 THEN 0 ELSE `t`.`x` END",
        "IF(`t`.`x` > 0, 0, `t`.`x`)",
        "CASE WHEN `t`.`x` > 0 THEN 0 ELSE `t`.`x` * 2 END",
    ],
)
def test_a_case_with_a_non_constant_branch_is_not_a_label_set(expression: str) -> None:
    assert not semantic_text.is_constant_label_case(expression)


def test_an_aggregate_inside_a_scalar_call_is_still_the_aggregate() -> None:
    assert semantic_text.aggregate_call_parts(
        "DATE_FORMAT(MAX(`t`.`seen_at`), 'yyyy-MM-dd')"
    ) == ("MAX", "seen_at")
    assert semantic_text.aggregate_call_parts(
        "ROUND(SUM(`t`.`amount`) / 100, 2)"
    ) == ("SUM", "amount")


def test_a_windowed_aggregate_is_not_an_aggregate_call() -> None:
    """A window keeps every row, so it never sets the grain a metric card reports."""
    assert semantic_text.outer_aggregate_call(
        "SUM(`t`.`amount`) OVER (PARTITION BY `t`.`k`)"
    ) is None
    assert semantic_text.aggregate_call_parts(
        "SUM(`t`.`amount`) OVER (PARTITION BY `t`.`k`)"
    ) == (None, None)


def test_the_scalar_coat_around_an_aggregate_is_restated_once() -> None:
    assert semantic_text.describe_aggregate_wrapper(
        "DATE_FORMAT(MAX(`t`.`seen_at`), 'yyyy-MM-dd')"
    ) == "外层 DATE_FORMAT(…, 'yyyy-MM-dd')"
    assert semantic_text.describe_aggregate_wrapper("MAX(`t`.`seen_at`)") is None
    assert semantic_text.describe_aggregate_wrapper("`t`.`seen_at`") is None


def test_a_default_is_read_from_a_top_level_case_with_a_constant_else() -> None:
    assert semantic_text.constant_case_default(
        "CASE WHEN `t`.`paid` > 0 THEN `t`.`paid` ELSE 0 END"
    ) == "0"
    assert semantic_text.constant_case_default("IF(`t`.`paid` > 0, `t`.`paid`, 0)") == "0"


@pytest.mark.parametrize(
    "expression",
    [
        # The ELSE is a column, so nothing is being filled in -- the value is passed on.
        "CASE WHEN `t`.`a` LIKE 'X%' THEN 'X' ELSE `t`.`a` END",
        "CASE WHEN `t`.`a` LIKE 'X%' THEN 'X' ELSE SUBSTRING(`t`.`a`, 1, 3) END",
        # Nested inside another call: that CASE is an argument, not this field's tail.
        "REGEXP_REPLACE(CASE WHEN `t`.`a` LIKE 'X%' THEN 'X' ELSE 'Y' END, '_', '')",
        "CASE WHEN `t`.`a` LIKE 'X%' THEN 'X' END",
    ],
)
def test_an_unprovable_case_default_answers_none(expression: str) -> None:
    assert semantic_text.constant_case_default(expression) is None


def test_a_coalesce_default_is_its_last_argument() -> None:
    assert semantic_text.coalesce_default("COALESCE(`t`.`a`, `t`.`b`, 0)") == "0"
    assert semantic_text.coalesce_default("NVL(`t`.`a`, '19700101')") == "'19700101'"
    assert semantic_text.coalesce_default("`t`.`a` + 1") is None
    # A fill inside an argument is still a fill of the value this expression computes.
    assert semantic_text.coalesce_default("MAX(DATEDIFF('20260814', NVL(`t`.`a`, 0)))") == "0"


def test_a_top_level_coalesce_is_the_only_one_a_step_proves() -> None:
    """A step whose value *is* the COALESCE fills the column that step produces."""
    assert semantic_text.top_level_coalesce_default("COALESCE(`t`.`a`, 0)") == "0"
    assert semantic_text.top_level_coalesce_default("(NVL(`t`.`a`, 0))") == "0"
    assert semantic_text.top_level_coalesce_default("COALESCE(`t`.`a`, 0) / `t`.`n`") is None
    assert semantic_text.top_level_coalesce_default(
        "CASE WHEN COALESCE(`t`.`a`, 0) <= 1 THEN 'X' ELSE 'Y' END"
    ) is None
