"""How lineage hops compose, and when two sources are one -- for every level alike.

The statement-level end-to-end trace, the task-level rows and the session fold each
compose hops and deduplicate sources. They used to do it three ways, and F6 was the fold
disagreeing with the trace: a temp view in the middle turned ``v * 2`` into ``DIRECT``
and merged two different constants into one. The rules live here once:

- a path carries the **strongest** transform it crosses (``dominant_transform``);
- two sources are one only when their whole content is equal (``source_identity``) --
  ``(table, column, source_kind)`` is not an identity: every constant shares it, and one
  column reached by two paths is two participations, which the contract keeps apart;
- a list of sources keeps the first of each, in order (``dedupe_sources``).
"""

from __future__ import annotations

import json
from typing import Iterable, Mapping

_TRANSFORM_PRIORITY: dict[str, int] = {
    "CONSTANT": 0,
    "DIRECT": 1,
    "EXPAND_ALL": 2,
    "UNION": 3,
    "EXPRESSION": 4,
    "CONDITIONAL": 5,
    "WINDOW": 6,
    "AGGREGATE": 7,
}


def dominant_transform(left: str, right: str) -> str:
    """The transform a path of two hops carries: the stronger of the two.

    ``DIRECT`` then ``EXPRESSION`` is ``EXPRESSION`` whichever hop applied it.
    """
    if _TRANSFORM_PRIORITY.get(left, 0) >= _TRANSFORM_PRIORITY.get(right, 0):
        return left
    return right


def source_identity(source: Mapping) -> str:
    """A source's whole content, canonically: the only thing that makes two sources one."""
    return json.dumps(source, sort_keys=True, ensure_ascii=False, default=str)


def compose_hop(hop: Mapping, leaf: dict) -> dict:
    """``leaf`` as read through ``hop``: the path's transform is the stronger of the two.

    A hop with no transform of its own (a row condition, a bare reference) passes the
    leaf through unchanged.
    """
    if not hop.get("transform") or not leaf.get("transform"):
        return leaf
    composed = dominant_transform(str(hop["transform"]), str(leaf["transform"]))
    return leaf if composed == leaf["transform"] else {**leaf, "transform": composed}


def dedupe_sources(items: Iterable[Mapping]) -> list[dict]:
    """The first of each source by identity, in order, each as a fresh dict."""
    result: list[dict] = []
    seen: set[str] = set()
    for item in items:
        key = source_identity(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(item))
    return result
