"""A column comment's code table that ends in a long constant-style code.

``角色；a1-甲,b2-乙,LONG_CODE_X外部`` lists three codes, and the shape reading used to see
two: a code was at most eight characters, and a code glued to its meaning with no joiner
was never split. Both are read now, under narrow rules:

- a code longer than eight characters is believed only in constant style -- upper case,
  digits and underscores, at most 32 characters (``flag_type=on时`` is a condition, not
  a code);
- a glued token is split only right after a joined pair, only for such a long constant
  code, and only when the meaning carries no ASCII letter or digit (``id关联`` after
  ``0-无效`` is a word, and ``Y是N否`` is two pairs this reading does not attempt).

Every fixture is synthetic.
"""

from __future__ import annotations

import pytest

from scope_lineage.render.glossary_values import enumerated_meanings


def test_a_long_constant_code_with_a_joiner_is_read():
    assert enumerated_meanings("角色；a1-甲,b2-乙,LONG_CODE_X-外部") == {
        "a1": "甲",
        "b2": "乙",
        "long_code_x": "外部",
    }


def test_a_long_constant_code_glued_to_its_meaning_is_read():
    assert enumerated_meanings("角色；a1-甲,b2-乙,LONG_CODE_X外部") == {
        "a1": "甲",
        "b2": "乙",
        "long_code_x": "外部",
    }


def test_a_long_code_without_an_underscore_is_read_too():
    assert enumerated_meanings("角色；a1-甲,b2-乙,LONGCODEXY-外部")["longcodexy"] == "外部"


@pytest.mark.parametrize(
    "comment",
    [
        "说明，flag_type=on时有值",
        "appCode编码",
        "渠道；CRM渠道类标签",
    ],
)
def test_prose_is_still_not_a_code_table(comment):
    assert enumerated_meanings(comment) == {}


@pytest.mark.parametrize(
    ("comment", "listed"),
    [
        ("角色；a1-甲,b2-乙,lower_long_name-说明", {"a1", "b2"}),
        ("角色；a1-甲,b2-乙,Y是N否", {"a1", "b2"}),
        ("状态；1-有效,0-无效 id关联", {"1", "0"}),
        ("类型；A-甲,B-乙 remark备注", {"a", "b"}),
        ("级别；L1-低,L2-高 na不适用", {"l1", "l2"}),
        ("标记；Y-是,N-否 default默认值", {"y", "n"}),
        # 33 characters: one past the bound, with and without a joiner.
        ("角色；a1-甲,b2-乙,A_" + "B" * 31 + "-超长", {"a1", "b2"}),
        ("角色；a1-甲,b2-乙,A_" + "B" * 31 + "超长", {"a1", "b2"}),
    ],
)
def test_nothing_else_is_read_as_a_code(comment, listed):
    assert set(enumerated_meanings(comment)) == listed


def test_a_glued_token_not_after_a_joined_pair_is_not_split():
    assert "long_code_x" not in enumerated_meanings("角色 LONG_CODE_X外部，a1-甲，b2-乙")
