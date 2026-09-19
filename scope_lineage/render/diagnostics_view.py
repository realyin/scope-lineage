"""Read one statement's diagnostics out of either diagnostics shape.

A 1.0 diagnostics document belongs to one statement and puts everything at the top
level. A 2.0 task document puts *script-scoped* facts at the top level -- the CTAS
repair, the quoted identifiers -- and everything a single statement produced under
``statement_diagnostics.<statement_id>``. Both are handed to the renderers as one
``diagnostics`` argument, so a renderer that reads only the top level silently reports
"no warnings" for a statement that has them (WI-1f).

Nothing here decides what a warning means; it only answers "which warnings / fact gaps
apply to this statement", as the union of the top-level list and that statement's own,
deduplicated by content so a document that repeats a warning in both places counts it
once.
"""

from __future__ import annotations

import json
from typing import Iterable, Sequence

from .sequences import unique_ordered


TOP_LEVEL = None


def _entries(diagnostics: dict | None, key: str) -> list[dict]:
    return [item for item in (diagnostics or {}).get(key) or [] if isinstance(item, dict)]


def _statement_entry(diagnostics: dict | None, statement_id: str | None) -> dict:
    if not statement_id:
        return {}
    entry = ((diagnostics or {}).get("statement_diagnostics") or {}).get(
        str(statement_id)
    )
    return entry if isinstance(entry, dict) else {}


def _content_key(item) -> str:
    """What makes two warnings one fact: their content, whatever order it is written in."""
    return json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)


def _dedupe(items: Iterable[dict]) -> list[dict]:
    """Order-preserving dedupe by content: the same warning in both places is one fact."""
    return unique_ordered(items, _content_key)


def warnings_for(diagnostics: dict | None, statement_id: str | None) -> list[dict]:
    """The warnings that apply to one statement: top-level ∪ that statement's own."""
    return _dedupe(
        [
            *_entries(diagnostics, "warnings"),
            *_entries(_statement_entry(diagnostics, statement_id), "warnings"),
        ]
    )


def fact_gaps_for(diagnostics: dict | None, statement_id: str | None) -> list[dict]:
    """The lineage fact gaps that apply to one statement, by the same union."""
    return _dedupe(
        [
            *_entries(diagnostics, "lineage_fact_gaps"),
            *_entries(
                _statement_entry(diagnostics, statement_id), "lineage_fact_gaps"
            ),
        ]
    )


def located_warnings(diagnostics: dict | None) -> list[tuple[str | None, dict]]:
    """Every warning in the document as ``(statement_id or None, warning)``.

    Used where the reader is looking at a whole task rather than at one statement: a
    task's warnings.md must show the statement-level ones too, and must say which
    statement each came from, because "@ ROOT" means a different ROOT per statement.
    """
    located: list[tuple[str | None, dict]] = [
        (TOP_LEVEL, warning) for warning in _entries(diagnostics, "warnings")
    ]
    statements = (diagnostics or {}).get("statement_diagnostics") or {}
    for statement_id in statements:
        entry = statements[statement_id]
        located.extend(
            (str(statement_id), warning)
            for warning in _entries(entry if isinstance(entry, dict) else {}, "warnings")
        )
    return _dedupe_located(located)


def _dedupe_located(items: Sequence[tuple[str | None, dict]]) -> list[tuple]:
    return unique_ordered(items, lambda pair: _content_key(list(pair)))


def all_warnings(diagnostics: dict | None) -> list[dict]:
    """Every warning in the document, wherever it is recorded, deduplicated."""
    return _dedupe(warning for _, warning in located_warnings(diagnostics))
