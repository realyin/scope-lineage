"""``semantic confirm``: a person's answers written back into table-semantics documents.

One confirmation names a table, a target and the answer. Four targets exist:

- ``question:<id>`` -- the question becomes ``answered`` with the answer, who gave it and
  when;
- ``column:<c>.meaning`` -- the column's meaning is replaced;
- ``column:<c>.code_values`` -- a list replaces the column's code values, a single
  ``{value, meaning}`` is merged into them;
- ``summary.row`` -- an object is merged into the row statement (a string replaces its
  text).

Whatever a confirmation changed gains ``confirmed`` in its sources, and the document logs
it under ``confirmed``. A confirmation that matches nothing -- or whose answer would make
the document illegal -- is returned in ``unmatched`` with the reason, never dropped, and
leaves the document as it was.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

from .names import bare_table
from .schema import DOC_FORMAT, schema_errors

_COLUMN_TARGET = re.compile(r"column:(?P<column>[^.\s]+)\.(?P<slot>meaning|code_values)")
CONFIRMED = "confirmed"


@dataclass
class ConfirmResult:
    documents: dict
    applied: list = field(default_factory=list)
    unmatched: list = field(default_factory=list)
    changed: set = field(default_factory=set)


def apply_confirmations(documents: dict, confirmations: list) -> ConfirmResult:
    """Apply ``confirmations`` in order to copies of ``documents`` (keyed ``db.table``)."""
    result = ConfirmResult({bare_table(t): copy.deepcopy(d) for t, d in documents.items()})
    for entry in confirmations:
        table = bare_table(entry.get("table"))
        document = result.documents.get(table)
        if document is None:
            result.unmatched.append(_miss(entry, "unknown table: no table-semantics document for it"))
            continue
        candidate = copy.deepcopy(document)
        reason = _apply_one(candidate, entry)
        if reason is None:
            errors = schema_errors(candidate, DOC_FORMAT)
            if errors:
                reason = f"value does not fit table-semantics/1 ({errors[0]['at']}: {errors[0]['message']})"
        if reason is not None:
            result.unmatched.append(_miss(entry, reason))
            continue
        _log(candidate, entry)
        if candidate != document:
            result.changed.add(table)
        result.documents[table] = candidate
        result.applied.append(entry)
    return result


def _miss(entry: dict, reason: str) -> dict:
    return {"table": entry.get("table"), "target": entry.get("target"), "reason": reason}


def _apply_one(document: dict, entry: dict) -> str | None:
    """Apply one confirmation in place; the reason it cannot be applied, or None."""
    target, value = str(entry.get("target")), entry.get("value")
    if target.startswith("question:"):
        return _answer(document, target.split(":", 1)[1], entry)
    if target == "summary.row":
        return _confirm_row(document["summary"]["row"], value)
    match = _COLUMN_TARGET.fullmatch(target)
    if match is None:
        return f"unknown target {target!r}"
    column = next((c for c in document["columns"] if c["column"] == match["column"]), None)
    if column is None:
        return f"unknown column {match['column']!r} in this table"
    if match["slot"] == "meaning":
        return _confirm_meaning(column, value)
    return _confirm_code_values(column, value)


def _mark(item: dict) -> None:
    sources = item.setdefault("sources", [])
    if CONFIRMED not in sources:
        sources.append(CONFIRMED)


def _answer(document: dict, question_id: str, entry: dict) -> str | None:
    questions = document["summary"]["questions"]
    question = next((q for q in questions if q["id"] == question_id), None)
    if question is None:
        return f"unknown question {question_id!r} in this table"
    if not isinstance(entry.get("value"), str) or not entry["value"].strip():
        return "value must be the answer text"
    question.update(status="answered", answer=entry["value"], answered_by=entry.get("by"),
                    answered_on=entry.get("date"))
    return None


def _confirm_meaning(column: dict, value) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return "value must be the meaning text"
    column["meaning"] = value
    _mark(column)
    return None


def _confirm_code_values(column: dict, value) -> str | None:
    items = value if isinstance(value, list) else [value] if isinstance(value, dict) else None
    if not items or not all(_is_code(item) for item in items):
        return "value must be a list of {value, meaning} (or one such object)"
    current = {code["value"]: code for code in column.get("code_values") or []}
    confirmed = []
    for item in items:
        code = copy.deepcopy(current.get(item["value"], {"sources": []}))
        code.update(value=item["value"], meaning=item["meaning"], unconfirmed=False)
        _mark(code)
        confirmed.append(code)
    if isinstance(value, list):
        column["code_values"] = confirmed
    else:
        current[confirmed[0]["value"]] = confirmed[0]
        column["code_values"] = list(current.values())
    return None


def _is_code(item) -> bool:
    return (isinstance(item, dict) and isinstance(item.get("value"), str)
            and isinstance(item.get("meaning"), str) and bool(item["meaning"].strip()))


def _confirm_row(row: dict, value) -> str | None:
    if isinstance(value, str) and value.strip():
        row["text"] = value
    elif isinstance(value, dict) and value:
        row.update(value)
    else:
        return "value must be the row text or an object of row fields"
    _mark(row)
    return None


def _log(document: dict, entry: dict) -> None:
    record = {"target": entry.get("target"), "by": entry.get("by"), "date": entry.get("date")}
    log = document.setdefault("confirmed", [])
    if record not in log:
        log.append(record)
