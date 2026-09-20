"""P5b: the evidence the form advertises has to be evidence somebody can act on.

A review round over a large corpus closed 23 values out of 1972 askable ones. The form
was not short of rows -- it was short of *usable* rows, and every shortfall was a place
where the layer advertised evidence it did not have:

1. **an enumeration and a mention printed the same word.** ``0-未生效，1-生效`` defines
   the value; ``队列编码，99 表示无效`` merely contains it. Both arrived as ``comment``,
   so a reviewer had to re-read the comment to find out which one they were looking at.
   They are now ``comment_enum`` and ``comment_mention``, and a mention is trimmed to the
   clause around the value, because a hint is one phrase and not a paragraph;
2. **a code table inside brackets lost its first and last pair.** ``余额类别(Int-利息，…,
   IntFee-息费)`` is how a warehouse writes a code table when the comment also has to say
   what the column is, and the bracket glued the prose onto the first code and a stray
   `)` onto the last meaning;
3. **a switch the column's own comment defines was dropped as trivial.** ``Y``/``N`` is
   a switch *until somebody writes down which is which*, and then it is the one value in
   the form that can be closed by reading;
4. **a CASE label shared by many values read as a translation.** ``WHEN s IN ('AA','BB',
   'CC') THEN '进行中'`` says those three values fall in one bucket; it does not say what
   any one of them means, and publishing 进行中 as each value's candidate invites exactly
   that mistake;
5. **a value that is already Chinese prose was asked about.** Nobody can define 委外
   beyond writing 委外 again, so it is published in the dictionary and left out of the
   form.

Each section below carries its negative: the shape that must NOT take the new route.
"""

from __future__ import annotations

from scope_lineage.contract import to_lineage_dict
from scope_lineage.metadata.schema_metadata import SchemaMap
from scope_lineage.render.glossary import build_glossary
from scope_lineage.render.glossary_template import (
    build_overrides_template,
    render_overrides_template_markdown,
)
from scope_lineage.render.glossary_values import enumerated_meanings
from scope_lineage.scope.scope_builder import parse_scope_lineage


EVENT_TABLE = "ods.app_event"


def _document(sql: str, task_id: str = "evidence_quality", schema=None) -> dict:
    return to_lineage_dict(parse_scope_lineage(sql, task_id, schema=schema))


def _glossary(*documents) -> dict:
    return build_glossary(list(documents), artifact_root="corpus")


def _value(glossary: dict, column: str, value: str) -> dict:
    matches = [
        item
        for item in glossary["values"]
        if item["column"] == column and item["value"] == value
    ]
    assert matches, f"{column}={value} not in {[item['value'] for item in glossary['values']]}"
    return matches[0]


def _candidates(glossary: dict, column: str, value: str) -> list[dict]:
    return _value(glossary, column, value)["meaning_candidates"]


def _sources(glossary: dict, column: str, value: str) -> list[str]:
    return [str(item["source"]) for item in _candidates(glossary, column, value)]


def _form(glossary: dict) -> str:
    """The whole fill-in form, uncapped, as a reviewer reads it."""
    return render_overrides_template_markdown(
        build_overrides_template(glossary, top=0), glossary
    )


def _event_schema(comment: str | None, column: str) -> SchemaMap:
    return SchemaMap(
        {EVENT_TABLE: ["id", column]},
        column_details={
            EVENT_TABLE: [
                {"name": "id", "type": "bigint", "comment": None},
                {"name": column, "type": "string", "comment": comment},
            ]
        },
    )


def _in_list_glossary(comment: str | None, *values: str, column: str = "state") -> dict:
    """One statement pinning ``column`` to the given values, under one column comment."""
    listed = ", ".join(f"'{value}'" for value in values)
    return _glossary(
        _document(
            f"INSERT INTO mart.t SELECT e.id FROM {EVENT_TABLE} e "
            f"WHERE e.{column} IN ({listed})",
            schema=_event_schema(comment, column),
        )
    )


# ------------------------------------------- 1. an enumeration is not a mention


def test_a_comment_that_enumerates_the_value_is_published_as_an_enumeration() -> None:
    glossary = _in_list_glossary("AA-已受理，BB-已完成", "AA", "BB")

    assert _candidates(glossary, "state", "AA") == [
        {
            "text": "已受理",
            "source": "comment_enum",
            "evidence": f"column:{EVENT_TABLE}.state",
        }
    ]


def test_a_comment_that_only_mentions_the_value_is_published_as_a_mention() -> None:
    """The negative of the route above: prose about a code does not define it."""
    glossary = _in_list_glossary("事件状态，AA 之后才会有下游动作，由上游每日刷新", "AA", "BB")

    assert _candidates(glossary, "state", "AA") == [
        {
            "text": "AA 之后才会有下游动作",
            "source": "comment_mention",
            "evidence": f"column:{EVENT_TABLE}.state",
        }
    ]


def test_a_mention_is_trimmed_to_the_clause_around_the_value() -> None:
    """A whole paragraph in a table cell is not a hint anybody reads."""
    clause = "事件状态说明" * 6 + "AA 表示已受理"
    glossary = _in_list_glossary(f"由上游每日刷新，{clause}，其余取值见上游文档", "AA", "BB")

    text = _candidates(glossary, "state", "AA")[0]["text"]
    assert len(text) == 40
    assert text.endswith("AA 表示已受理")
    assert text.startswith("…")
    assert "由上游每日刷新" not in text
    assert "其余取值见上游文档" not in text


def test_an_inline_sql_comment_is_trimmed_to_its_clause_too() -> None:
    document = _document(
        f"INSERT INTO mart.t SELECT e.id FROM {EVENT_TABLE} e\n"
        "WHERE e.state = 'AA' -- 每日跑批，AA 是已受理状态，其余分支另有任务\n"
    )
    candidates = _candidates(_glossary(document), "state", "AA")

    assert [(item["source"], item["text"]) for item in candidates] == [
        ("comment_mention", "AA 是已受理状态")
    ]


def test_a_comment_that_neither_enumerates_nor_mentions_offers_nothing() -> None:
    assert _candidates(_in_list_glossary("事件状态，由上游每日刷新", "AA", "BB"), "state", "AA") == []


def test_the_form_tells_an_enumeration_from_a_mention() -> None:
    enumerated = _in_list_glossary("AA-已受理，BB-已完成", "AA", "BB")
    mentioned = _in_list_glossary("事件状态，AA 之后才会有下游动作，由上游每日刷新", "AA", "BB")

    assert "| 已受理 | comment_enum |" in _form(enumerated)
    assert "| AA 之后才会有下游动作 | comment_mention |" in _form(mentioned)


# --------------------------------------------- 2. a code table inside brackets


def test_a_half_width_bracket_keeps_the_first_and_the_last_pair() -> None:
    assert enumerated_meanings(
        "余额类别(Int-利息，Fee-费用，Pint-罚息，Cint-利罚，IntFee-息费)"
    ) == {
        "int": "利息",
        "fee": "费用",
        "pint": "罚息",
        "cint": "利罚",
        "intfee": "息费",
    }


def test_a_full_width_bracket_is_read_the_same_way() -> None:
    assert enumerated_meanings("类型（1：A；2：B）") == {"1": "A", "2": "B"}


def test_prose_before_the_bracket_does_not_swallow_the_first_pair() -> None:
    assert enumerated_meanings("客户在本机构的账户余额类别（Int-利息，Fee-费用）") == {
        "int": "利息",
        "fee": "费用",
    }


def test_a_slash_list_read_out_by_a_verb_is_not_a_code_table() -> None:
    """The negative: `A/B/C 分别表示 x/y/z` pairs nothing with anything."""
    assert enumerated_meanings("A/B/C 分别表示 x/y/z") == {}


def test_a_bracketed_code_table_reaches_the_dictionary_as_an_enumeration() -> None:
    glossary = _in_list_glossary("余额类别(Int-利息，IntFee-息费)", "Int", "IntFee")

    assert _candidates(glossary, "state", "Int")[0]["text"] == "利息"
    assert _candidates(glossary, "state", "IntFee")[0]["text"] == "息费"


# ------------------------------------- 3. a switch the comment defines is askable


def test_a_switch_the_column_comment_enumerates_is_asked_about() -> None:
    glossary = _in_list_glossary("Y-是，N-否", "Y", "N", column="vip")
    template = build_overrides_template(glossary, top=0)

    assert set(template["values"]) == {f"{EVENT_TABLE}.vip=Y", f"{EVENT_TABLE}.vip=N"}
    assert "| 是 | comment_enum |" in render_overrides_template_markdown(template, glossary)


def test_a_bare_number_the_column_comment_enumerates_is_asked_about() -> None:
    glossary = _in_list_glossary("0-未生效，1-生效", "0", "1", column="eff")

    assert set(build_overrides_template(glossary, top=0)["values"]) == {
        f"{EVENT_TABLE}.eff=0",
        f"{EVENT_TABLE}.eff=1",
    }


def test_a_switch_no_comment_defines_stays_excluded() -> None:
    """The negative: without the code table, `Y` still answers a question nobody asks."""
    glossary = _in_list_glossary("是否有效标记", "Y", "N", column="vip")
    template = build_overrides_template(glossary, top=0)

    assert template["values"] == {}
    assert template["generated"]["excluded_values"] == 2


# ------------------------------------------------------- 4. the CASE-label fan-out


_TICKET_SCHEMA = SchemaMap(
    {"ods.ticket": ["id", "state"]},
    column_details={
        "ods.ticket": [
            {"name": "id", "type": "bigint", "comment": None},
            {"name": "state", "type": "string", "comment": None},
        ]
    },
)


def _case_glossary(label_sql: str) -> dict:
    return _glossary(
        _document(
            f"INSERT INTO mart.t SELECT t.id, {label_sql} AS state_name FROM ods.ticket t",
            schema=_TICKET_SCHEMA,
        )
    )


def test_a_label_only_one_value_carries_is_a_translation() -> None:
    glossary = _case_glossary(
        "CASE WHEN t.state = 'AA' THEN '已受理' WHEN t.state = 'BB' THEN '已完成' ELSE '未知' END"
    )
    candidate = _candidates(glossary, "state", "AA")[0]

    assert candidate["text"] == "已受理"
    assert candidate["fan_out"] == 1
    assert "| 已受理 | case_label |" in _form(glossary)


def test_a_label_several_values_share_is_published_as_a_bucket() -> None:
    """The negative: one label over three values is a category, not a meaning."""
    glossary = _case_glossary(
        "CASE WHEN t.state IN ('AA', 'BB', 'CC') THEN '进行中' ELSE '未知' END"
    )
    candidate = _candidates(glossary, "state", "AA")[0]

    assert candidate["text"] == "分类桶：进行中（同桶 3 个值）"
    assert candidate["fan_out"] == 3
    assert "case_label(桶 3)" in _form(glossary)


# ------------------------------------------- 5. a value that describes itself


def test_a_chinese_prose_value_is_published_but_never_asked_about() -> None:
    glossary = _in_list_glossary(None, "委外", "触达成功", column="channel")
    template = build_overrides_template(glossary, top=0)

    assert {item["value"] for item in glossary["values"]} == {"委外", "触达成功"}
    assert template["values"] == {}
    assert template["generated"]["excluded_values"] == 2
    assert "个开关/数字/日期/中文自述型取值" in render_overrides_template_markdown(
        template, glossary
    )


def test_a_value_that_mixes_code_and_digits_stays_askable() -> None:
    """The negative: `SF_S1_1_1` describes nothing, whoever reads it."""
    glossary = _in_list_glossary(None, "SF_S1_1_1", "A1", column="channel")

    assert set(build_overrides_template(glossary, top=0)["values"]) == {
        f"{EVENT_TABLE}.channel=SF_S1_1_1",
        f"{EVENT_TABLE}.channel=A1",
    }
