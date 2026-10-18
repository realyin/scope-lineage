"""A comment's code table written as ``<code><label>`` tokens with no joiner (G2).

``是否有效 1是 0否``, ``是否删除(1是 0否)`` and ``1是0否`` list two codes each; the shape
reading wanted a joiner (``1-是``) or a space (``1 是``) and saw none. A glued reading now
takes over when nothing else is read: at least two pairs, each a short code -- digits, or
one to three upper-case letters / digits -- straight against a label with no ASCII letter
or digit; digit codes may follow each other with no separator (``1是0否``). A sentence
with one number, a word glued to a lower-case name (``id关联``), and a list whose
labels run into a conjunction (``3天或7天``) are not code tables.

Every fixture is synthetic.
"""

from __future__ import annotations

import pytest

from scope_lineage.render.glossary_values import enumerated_meanings


@pytest.mark.parametrize(
    ("comment", "expected"),
    [
        ("是否有效 1是 0否", {"1": "是", "0": "否"}),
        ("是否删除(1是 0否)", {"1": "是", "0": "否"}),
        ("1是0否", {"1": "是", "0": "否"}),
        ("标记|Y是 N否", {"y": "是", "n": "否"}),
        ("类型：1甲类，2乙类，3丙类", {"1": "甲类", "2": "乙类", "3": "丙类"}),
    ],
)
def test_glued_code_label_tokens_are_read(comment, expected):
    assert enumerated_meanings(comment) == expected


@pytest.mark.parametrize(
    "comment",
    [
        "保留3天",
        "第1期 应还金额",
        "最近 30天 内的记录",
        "保留期 3天或7天",
        "关联 id关联 code编码",
        "1是",
        "重复 1是 1否",
    ],
)
def test_prose_with_numbers_is_no_code_table(comment):
    assert enumerated_meanings(comment) == {}


def test_a_joined_reading_still_wins():
    assert enumerated_meanings("状态 0-未生效,1-生效") == {"0": "未生效", "1": "生效"}
