"""Order-preserving sequence utilities for the render domain.

The same four lines had been written five times across ``render`` -- once per module that
needed to say "these items, in the order they were first seen, without repeats" -- and
the copies had quietly grown apart: one compared dicts by ``repr``, one by a JSON dump
with sorted keys, one dropped falsy entries, one scanned a list instead of a set. A
reader comparing two of them could not tell which differences were decisions.

One function, and the differences that *are* decisions become an argument: ``key`` says
what "the same item" means here. ``scope/sequences.py`` is the sibling of this module;
the two are deliberately not shared, because ``render`` may not depend on ``scope``.
"""

from __future__ import annotations

from typing import Callable, Iterable, TypeVar


T = TypeVar("T")


def unique_ordered(
    items: Iterable[T], key: Callable[[T], object] | None = None
) -> list[T]:
    """The items, first occurrence kept, later repeats dropped.

    ``key`` maps an item to what makes it the same item -- a JSON dump for a warning
    that must compare by content whatever its key order, a ``(column, value)`` pair for
    a comparison that may be written twice. Without it the item is its own key, so it
    must be hashable.
    """
    seen: set = set()
    ordered: list[T] = []
    for item in items:
        marker = key(item) if key is not None else item
        if marker in seen:
            continue
        seen.add(marker)
        ordered.append(item)
    return ordered
