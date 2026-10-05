"""What a column comment holds besides prose: markers, and references to other tables.

- ``comment_markers`` -- full-width bracketed markers such as ``【key:value】`` (an ASCII
  key, an optional value after a colon), split out as they are. What a marker means is
  the data owner's convention, never the tool's: the packet lists them and says so.
- ``comment_refs`` -- ``[db.table.col]`` / ``[db.table]`` / ``[table.col]`` references,
  each marked ``in_run`` (a task of the corpus reads or writes the table),
  ``metadata_only`` (only the metadata knows it) or ``unknown``. An unknown one may carry
  ``near``: tables of the run whose names, past their first layer prefix, extend one
  another -- a lead, not the same table.

The comment itself is never changed: check 3 still reads code values off it.
"""

from __future__ import annotations

import re
from typing import Callable, Iterable

_MARKER = re.compile(r"【([A-Za-z][A-Za-z0-9]*)(?:[:：]([^】]*))?】")
_REFERENCE = re.compile(r"\[([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+){1,2})\]")
_LAYER_PREFIX = re.compile(r"^[a-z]+_")

IN_RUN, METADATA_ONLY, UNKNOWN = "in_run", "metadata_only", "unknown"


def comment_markers(comment) -> list[dict]:
    """``[{key, value?}]`` for each marker of ``comment``, in order."""
    found = []
    for match in _MARKER.finditer(str(comment or "")):
        entry = {"key": match.group(1)}
        if match.group(2) is not None:
            entry["value"] = match.group(2)
        found.append(entry)
    return found


def marker_keys(columns: Iterable[tuple[str, dict]]) -> dict[str, dict]:
    """``key -> {count, example}`` over ``(table, column)`` pairs, sorted by key."""
    keys: dict[str, dict] = {}
    for table, column in columns:
        for marker in column.get("comment_markers") or []:
            entry = keys.setdefault(marker["key"], {"count": 0,
                                                    "example": f"{table}.{column['name']}"})
            entry["count"] += 1
    return {key: keys[key] for key in sorted(keys)}


class References:
    """Resolves comment references against the run's tables and the metadata."""

    def __init__(self, run_tables: Iterable[str], metadata: Callable[[str], dict | None]):
        self._run = sorted(set(run_tables))
        self._metadata = metadata

    def refs(self, comment) -> list[dict]:
        found = []
        for match in _REFERENCE.finditer(str(comment or "")):
            ref = match.group(1)
            entry = {"ref": ref, **self._resolve(ref)}
            if entry not in found:
                found.append(entry)
        return found

    def _resolve(self, ref: str) -> dict:
        parts = ref.split(".")
        # `db.table.col` names its table; `a.b` is `db.table` when such a table is known,
        # else `table.col`.
        candidates = [".".join(parts[:2])] if len(parts) == 3 else [ref]
        for table in candidates:
            status = self._status(table)
            if status:
                return {"status": status}
        if len(parts) == 2:
            named = [table for table in self._run if table.rsplit(".", 1)[-1] == parts[0]]
            if len(named) == 1:
                return {"status": IN_RUN}
        # The table's own name under either reading of a two-part reference.
        bare = [parts[1]] if len(parts) == 3 else [parts[1], parts[0]]
        near = [table for table in self._run
                if any(_near(name, table.rsplit(".", 1)[-1]) for name in bare)]
        return {"status": UNKNOWN, **({"near": near} if near else {})}

    def _status(self, table: str) -> str | None:
        if table in self._run:
            return IN_RUN
        return METADATA_ONLY if self._metadata(table) else None


def _near(name: str, other: str) -> bool:
    """Past the first layer prefix, one name is the other or the other plus ``_…``.

    Both names must have such a prefix: a bare word (a database name read as a table) is
    the prefix of half the warehouse.
    """
    name, other = name.lower(), other.lower()
    if not (_LAYER_PREFIX.match(name) and _LAYER_PREFIX.match(other)):
        return False
    left, right = _LAYER_PREFIX.sub("", name), _LAYER_PREFIX.sub("", other)
    if not left or not right:
        return False
    short, long = sorted((left, right), key=len)
    return long == short or long.startswith(short + "_")
