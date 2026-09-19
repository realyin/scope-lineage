"""The reviewed metadata patch (``metadata-patch/1``): a human answer, written back.

WI-2.6. ``describe`` publishes a 待确认清单 and ``glossary.overrides.json`` takes the
answers that are about *values* and *terms*. The other two kinds of answer -- "this
column means X" and "this table holds Y" -- belong to the warehouse's metadata, and the
warehouse is somebody else's system: a team that cannot write to the catalog today would
otherwise have nowhere to put the answer, and the next profile would ask the same
question again.

A patch is that somewhere. It is a local file, the same vocabulary a rich JSON metadata
export uses, and it never touches the source metadata:

.. code-block:: json

    {"doc_format": "metadata-patch/1",
     "tables": {"db.table": {"table_name_cn": "订单明细", "table_desc": "…",
                             "confirmed_by": "owner", "date": "2026-09-19"}},
     "columns": {"db.table.col": {"comment": "…",
                                  "confirmed_by": "owner", "date": "2026-09-19"}}}

Two entry points consume it, and they must agree:

- ``parse --metadata-patch`` patches each statement document on its way to disk;
- ``describe --metadata-patch`` patches an already written ``lineage.json`` in memory
  before deriving the view, so a corpus does not have to be re-parsed to see an answer
  land -- and the artifact on disk is never rewritten.

Both paths call :func:`apply_metadata_patch` on the same statement document, which is why
they produce one document rather than two that happen to look alike -- the patched
comments, their markers and the ``lineage_digest`` the derived view records all agree.
Deliberately *not* the ``SchemaMap``: patching the loader would reach only the run that
re-parses, and the two paths would answer differently for the same patch. The patch is
*additive and marked*: a patched column detail carries ``comment_source: "patch"`` and a
patched table carries ``table_metadata.patch_applied: true``, so a reader can always tell
a warehouse fact from an answer somebody wrote down. A key that matches nothing is
reported as ``unmatched`` rather than dropped -- for the same reason
``glossary.overrides.json`` reports one: a typo in a reviewed file is exactly the thing
the reviewer cannot see.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence

from .schema_metadata import (
    _blank_to_none,
    _normalize_table_detail,
    normalize_table_name,
)


DOC_FORMAT = "metadata-patch/1"

#: What a patched column detail and a patched table say about themselves.
COMMENT_SOURCE_PATCH = "patch"
COMMENT_SOURCE_METADATA = "metadata"
TABLE_PATCH_MARKER = "patch_applied"

_TASK_SCHEMA_VERSION = "2.0"


class MetadataPatchError(ValueError):
    """A patch file that cannot be read, or does not declare ``metadata-patch/1``."""


class MetadataPatch:
    """One or more reviewed patch files, normalized for lookup.

    ``tables`` is keyed by :func:`normalize_table_name` and holds the table-level facts in
    the same normalized vocabulary ``--schema`` produces. ``columns`` is keyed by
    ``(table key, lower-cased column)`` and holds only a comment: a patch answers "what
    does this mean", never "what type is it" -- a type is the warehouse's fact and an
    answer that disagreed with it would be a bug, not a correction.
    """

    def __init__(self) -> None:
        self.tables: dict[str, dict] = {}
        self.columns: dict[tuple, str] = {}
        self.sources: list[str] = []
        # Original spellings, so an unmatched report quotes the file rather than the
        # normalization of it. A reviewer looks for the line they wrote.
        self._table_keys: dict[str, str] = {}
        self._column_keys: dict[tuple, str] = {}
        self._matched: set = set()

    def __bool__(self) -> bool:
        return bool(self.tables or self.columns)

    def table_detail(self, table: str) -> dict:
        return self.tables.get(normalize_table_name(table)) or {}

    def column_comment(self, table: str, column: str) -> str | None:
        return self.columns.get((normalize_table_name(table), str(column).lower()))

    def mark_matched(self, key) -> None:
        self._matched.add(key)

    def unmatched(self) -> list[str]:
        """Every patch key no document answered to, in the spelling the file used."""
        missed = [
            spelling
            for key, spelling in {**self._table_keys, **self._column_keys}.items()
            if key not in self._matched
        ]
        return sorted(missed)


def load_metadata_patch(paths: Sequence[str] | None) -> MetadataPatch:
    """Read every ``--metadata-patch`` file into one patch, later files winning.

    Repeatable on purpose: one file per review round keeps who-answered-what readable,
    and the loader merges them the way a reader would -- the later answer replaces the
    earlier one for the same key, and keys nobody repeated all survive.
    """
    patch = MetadataPatch()
    for raw in paths or []:
        _merge_document(patch, _read_document(Path(raw)), str(raw))
    return patch


def _read_document(path: Path) -> Mapping:
    if not path.is_file():
        raise MetadataPatchError(f"--metadata-patch file does not exist: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise MetadataPatchError(f"{path}: not a readable JSON document ({error})")
    if not isinstance(document, Mapping):
        raise MetadataPatchError(f"{path}: a metadata patch must be a JSON object")
    declared = document.get("doc_format")
    if declared not in (None, DOC_FORMAT):
        raise MetadataPatchError(
            f"--metadata-patch expects a {DOC_FORMAT} document; {path} declares "
            f"{declared!r}"
        )
    for section in ("tables", "columns"):
        value = document.get(section)
        # A reviewer who writes the section as a list of keys ("the questions I
        # answered") rather than a mapping from key to answer has made a typo, and a
        # typo in a reviewed file is exactly what the reviewer cannot see. Said here,
        # where the file is still named, rather than as an AttributeError two calls on.
        if value is not None and not isinstance(value, Mapping):
            raise MetadataPatchError(
                f"{path}: \"{section}\" must be a JSON object mapping each key to its "
                f"answer, got {type(value).__name__}"
            )
    return document


def _merge_document(patch: MetadataPatch, document: Mapping, source: str) -> None:
    patch.sources.append(source)
    for name, detail in (document.get("tables") or {}).items():
        key = normalize_table_name(str(name))
        if not key or not isinstance(detail, Mapping):
            continue
        normalized = _normalize_table_detail(key, detail, include_table_name=False)
        if not normalized:
            continue
        patch.tables[key] = {**patch.tables.get(key, {}), **normalized}
        patch._table_keys[key] = str(name)
    for reference, detail in (document.get("columns") or {}).items():
        key = _column_key(str(reference))
        comment = _comment_of(detail)
        if key is None or comment is None:
            continue
        patch.columns[key] = comment
        patch._column_keys[key] = str(reference)


def _column_key(reference: str) -> tuple | None:
    """``db.table.column`` -> ``(table key, column)``; anything shorter is not a column."""
    parts = [part.strip().strip("`") for part in reference.split(".") if part.strip()]
    if len(parts) < 3:
        return None
    return (normalize_table_name(".".join(parts[:-1])), parts[-1].lower())


def _comment_of(detail) -> str | None:
    if isinstance(detail, Mapping):
        return _blank_to_none(detail.get("comment") or detail.get("column_comment"))
    return _blank_to_none(detail)


# --------------------------------------------------------------- document patching


def apply_metadata_patch(statement: Mapping, patch: MetadataPatch) -> dict:
    """Patch one statement document in place; return what was applied.

    The single place both the parse path and the describe path go through, so the two
    cannot drift: whatever this writes is what ``semantic.json`` reads, whichever command
    supplied the patch, down to the ``lineage_digest`` the view records.

    Two surfaces carry a comment and both are patched: ``related_metadata`` (what the
    tables and columns of this statement are) and the ``field_usage`` entries inside the
    scopes (what each scope read from a physical table). Only the first is counted --
    the second is the same answer seen from the other end, not a second answer.
    """
    counts = {"tables": 0, "columns": 0}
    if not patch or not isinstance(statement, Mapping):
        return counts
    for group in ("input_tables", "output_tables"):
        for name, item in ((statement.get("related_metadata") or {}).get(group) or {}).items():
            if not isinstance(item, dict):
                continue
            counts["columns"] += _patch_columns(item, str(name), patch)
            counts["tables"] += _patch_table(item, str(name), patch)
    for usage in _field_usages(statement):
        _patch_field_usage(usage, patch)
    return counts


def _patch_columns(item: dict, table: str, patch: MetadataPatch) -> int:
    applied = 0
    for detail in item.get("column_details") or []:
        applied += _patch_column_detail(detail, table, patch)
    return applied


def _patch_column_detail(detail, table: str, patch: MetadataPatch) -> int:
    if not isinstance(detail, dict):
        return 0
    name = str(detail.get("name"))
    comment = patch.column_comment(table, name)
    if comment is None:
        return 0
    detail["comment"] = comment
    detail["comment_source"] = COMMENT_SOURCE_PATCH
    patch.mark_matched((normalize_table_name(table), name.lower()))
    return 1


def _patch_table(item: dict, table: str, patch: MetadataPatch) -> int:
    detail = patch.table_detail(table)
    if not detail:
        return 0
    item["table_metadata"] = {
        **(item.get("table_metadata") or {}),
        **detail,
        TABLE_PATCH_MARKER: True,
    }
    patch.mark_matched(normalize_table_name(table))
    return 1


def _field_usages(statement: Mapping) -> Iterator[dict]:
    """Every ``field_usage`` entry, scope-level and logic-block-level alike."""
    for scope in (statement.get("scopes") or {}).values():
        if not isinstance(scope, Mapping):
            continue
        blocks = [scope, *(scope.get("logic_blocks") or [])]
        for block in blocks:
            for usage in (block or {}).get("field_usage") or []:
                if isinstance(usage, dict):
                    yield usage


def _patch_field_usage(usage: dict, patch: MetadataPatch) -> None:
    """The same comments, where a scope records what it read from a physical table."""
    if usage.get("source_type") != "physical_table":
        return
    table = str(usage.get("source_id") or "")
    for detail in usage.get("used_field_details") or []:
        _patch_column_detail(detail, table, patch)
    detail = patch.table_detail(table)
    if detail:
        usage["source_metadata"] = {
            **(usage.get("source_metadata") or {}),
            **detail,
            TABLE_PATCH_MARKER: True,
        }
        patch.mark_matched(normalize_table_name(table))


def statement_documents(document: Mapping) -> Iterator[Mapping]:
    """Every statement of a 1.0 statement document or a 2.0 task document."""
    if document.get("schema_version") == _TASK_SCHEMA_VERSION:
        for statement in (document.get("statement_lineage") or {}).values():
            if isinstance(statement, Mapping):
                yield statement
        return
    yield document


def apply_metadata_patch_to_document(document: Mapping, patch: MetadataPatch) -> dict:
    """Patch every statement of one lineage document; return the totals."""
    return apply_metadata_patch_to_statements(statement_documents(document), patch)


def apply_metadata_patch_to_statements(
    statements: Iterable[Mapping], patch: MetadataPatch
) -> dict:
    totals = {"tables": 0, "columns": 0}
    for statement in statements:
        applied = apply_metadata_patch(statement, patch)
        totals["tables"] += applied["tables"]
        totals["columns"] += applied["columns"]
    return totals
