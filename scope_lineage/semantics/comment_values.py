"""What a column comment says a value means (check 12).

Two spellings are read. Pairs -- ``0-申请 1-成功``, ``0：未推送，1：已推送``, ``1:是,0:否``,
``I是分期，R非分期`` -- give a value and its meaning. A list -- ``正常、锁定、删除`` -- gives
labels only; it documents a value when the value *is* one of the labels, which the check
confirms against the SQL.
"""

from __future__ import annotations

import re

_STOP = r"\s,，;；、:：=()（）/|"
_PAIR = re.compile(
    rf"(?<![A-Za-z0-9_])([A-Za-z0-9_]{{1,10}})\s*(?:->|→|[-:：=])\s*([^{_STOP}]{{1,20}})"
)
# ``0未推送`` / ``R非分期``: a short code written straight against its Chinese label.
_GLUED = re.compile(
    rf"(?<![A-Za-z0-9_])(\d{{1,4}}|[A-Z]{{1,3}})([一-鿿][^{_STOP}0-9A-Za-z]{{0,19}})"
)
_LIST_SPLIT = re.compile(r"[、，,/|；;\s]+")
_LABEL = re.compile(r"^[一-鿿A-Za-z]{1,8}$")
# ``A或B或C`` lists values; the word between two of them is not a meaning.
_CONJUNCTIONS = frozenset({"或", "或者", "和", "与", "及", "至", "到"})


def value_labels(comment) -> dict[str, str]:
    """``{value: meaning}`` for every pair the comment spells out, first spelling wins."""
    text = str(comment or "")
    found: dict[str, str] = {}
    for pattern in (_PAIR, _GLUED):
        for value, label in pattern.findall(text):
            if label not in _CONJUNCTIONS:
                found.setdefault(value, label)
    return found


def listed_labels(comment) -> set[str]:
    """The labels of a ``、``-separated list after the comment's ``名称：`` prefix."""
    text = re.split(r"[:：]", str(comment or ""), maxsplit=1)[-1]
    if not re.search(r"[、，,/|]", text):
        return set()
    return {item for item in _LIST_SPLIT.split(text) if _LABEL.match(item)}
