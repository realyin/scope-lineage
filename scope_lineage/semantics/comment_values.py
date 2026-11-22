"""What a column comment says a value means (check 12).

Two spellings are read. Pairs -- ``0-申请 1-成功``, ``0：未推送，1：已推送``, ``1:是,0:否``,
``I是分期，R非分期`` -- give a value and its meaning. A list -- ``正常、锁定、删除`` -- gives
labels only; it documents a value when the value *is* one of the labels, which the check
confirms against the SQL.
"""

from __future__ import annotations

import re

from ..render import glossary_values

_STOP = r"\s,，;；、:：=()（）/|"
_PAIR = re.compile(
    rf"(?<![A-Za-z0-9_])([A-Za-z0-9_]{{1,10}})\s*(?:->|→|[-:：=])\s*([^{_STOP}]{{1,20}})"
)
# ``0未推送`` / ``R非分期``: a short code written straight against its Chinese label.
_GLUED = re.compile(
    rf"(?<![A-Za-z0-9_])(\d{{1,4}}|[A-Z]{{1,3}})([一-鿿][^{_STOP}0-9A-Za-z]{{0,19}})"
)
# ``A或B或C`` lists values; the word between two of them is not a meaning.
_CONJUNCTIONS = frozenset({"或", "或者", "和", "与", "及", "至", "到"})
# A label that opens with a unit or a counter says how much, not what: ``近30天``,
# ``满100元``, ``2024年``, ``3个月``.
_QUANTITY_HEADS = ("天", "元", "年", "月", "日", "个", "次", "%")


def value_labels(comment) -> dict[str, str]:
    """``{value: meaning}`` for every pair the comment spells out, first spelling wins.

    A joined pair (``0-申请``) counts on its own. Glued pairs (``0未推送``) count only
    together and only when they hold as a code list by the glossary's rule
    (:func:`~scope_lineage.render.glossary_values.glued_pairs_hold`: two or more, one code
    width, distinct labels) and no label opens with a unit -- one glued hit is far more
    often an amount in a sentence (``近30天活跃标志``) than a code.
    """
    text = str(comment or "")
    found: dict[str, str] = {}
    for value, label in _PAIR.findall(text):
        if label not in _CONJUNCTIONS:
            found.setdefault(value, label)
    glued = [(value, label) for value, label in _GLUED.findall(text)
             if label not in _CONJUNCTIONS]
    if glued_codes(glued):
        for value, label in glued:
            found.setdefault(value, label)
    return found


def glued_codes(pairs: list[tuple[str, str]]) -> bool:
    """Whether glued ``(code, label)`` pairs are a code list rather than quantities."""
    return glossary_values.glued_pairs_hold(pairs) and not any(
        label.startswith(_QUANTITY_HEADS) for _code, label in pairs
    )


def listed_labels(comment) -> set[str]:
    """The labels of a ``、``-separated list after the comment's ``名称：`` prefix."""
    return set(glossary_values.listed_labels(comment))
