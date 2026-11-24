"""``semantic confirm``: a person's answers written back into table-semantics documents.

One confirmation names a table, a target and the answer. Four targets carry a person's
word:

- ``question:<id>`` -- the question becomes ``answered`` with the answer, who gave it and
  when;
- ``column:<c>.meaning`` -- the column's meaning is replaced;
- ``column:<c>.code_values`` -- a list replaces the column's code values, a single
  ``{value, meaning}`` is merged into them;
- ``summary.row`` -- an object is merged into the row statement (a string replaces its
  text). An object that sets ``grain_columns`` or ``unique`` but not ``grain_source`` turns
  an ``inferred`` or ``observed`` grain into ``declared``: the owner's word is no
  inference and outranks a query. A ``declared`` or ``proven`` grain is left as it is, and
  a ``grain_source`` the object sets is written as given -- except ``observed``: an object
  that sets it, or sets ``observed``, is unmatched (an observation has its own target).

Three more targets carry an observation, what a platform query found (the shapes and the
rules every value meets are :mod:`.observed`'s). An observation is no definition: it gains
no ``confirmed`` in any sources, and it never outranks a person or the lineage --
``proven`` > ``declared`` > ``observed`` > ``inferred``:

- ``summary.row.observed`` -- written to ``summary.row.observed``. Only an ``inferred`` or
  ``observed`` grain becomes ``observed`` with the observation's ``unique``; its grain
  columns are the columns the query counted, unless the observation says unique and the
  document's grain columns contain them (unique by fewer columns is unique by more), when
  the document's are kept. A ``declared`` or ``proven`` grain only gains the observation;
- ``column:<c>.observed_values`` -- written to the column's ``observed_values``, beside its
  code values and never into them. An identifier column takes counts only (values or
  ``absent`` -> unmatched), and ``observed_on`` must be one of its ``source_columns``;
- ``input:<db.table>`` -- one item of the top-level ``observed_inputs``, per input table
  (``bare_table``) and set of columns (case and order aside); a later one replaces it.

Whatever a confirmation changed gains ``confirmed`` in its sources, and the document logs
it under ``confirmed`` (once: the same target, person and date is not logged again). An
``input:`` record names the bare table and carries the observed ``columns``, so one input
table observed on two sets of columns is two records.
Applying the same confirmations again changes nothing, so a run replays them after every
write; onto a rewritten document they put the confirmed slots back. A confirmation that
matches nothing -- or whose answer would make the document illegal -- is returned in
``unmatched`` with the reason, never dropped, and leaves the document as it was.
``changed_by`` names, per table, the targets of the entries that changed its document, so
a caller can tell an answered question from a confirmed slot.

A ``question:<id>`` confirmation may carry ``asked``, the question's text as the person
saw it, so an id a rewrite gave to another question cannot take the answer:

- the question no longer reads as asked (``folded_text``) -> unmatched;
- the question already holds this very answer, by the same person on the same date ->
  ``skipped``: nothing changes and nothing is logged;
- the question holds another answer -> unmatched, unless the entry says ``replace: true``;
- otherwise it is applied as any confirmation.

A confirmation without ``asked`` is applied as it always was, whatever ``replace`` says --
unless the caller requires ``asked`` (``semantic confirm --require-asked``, every replay of a
run): then it is unmatched, since after a rewrite its id may name another question.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

from .names import bare_column, bare_table, folded_text
from .observed import (
    IDENTIFIER_CATEGORIES,
    INPUT,
    OBSERVED_ROW,
    OBSERVED_VALUES,
    USE_OBSERVED_TARGET,
    input_key,
    input_table,
    observation_problem,
)
from .schema import DOC_FORMAT, schema_errors

_COLUMN_TARGET = re.compile(
    r"column:(?P<column>[^.\s]+)\.(?P<slot>meaning|code_values|observed_values)")
CONFIRMED = "confirmed"
ASKED = "asked"
_SKIP = object()


@dataclass
class ConfirmResult:
    documents: dict
    applied: list = field(default_factory=list)
    unmatched: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    changed: set = field(default_factory=set)
    # table -> the target of each applied entry that changed its document, in order
    changed_by: dict = field(default_factory=dict)


NO_ASKED = ("no asked: a replay cannot tell which question this answers once a rewrite has "
            "renumbered the questions; add asked (the question's text as the person saw it)")


def apply_confirmations(documents: dict, confirmations: list,
                        require_asked: bool = False) -> ConfirmResult:
    """Apply ``confirmations`` in order to copies of ``documents`` (keyed ``db.table``).

    ``require_asked``: a ``question:`` entry without ``asked`` is unmatched (``NO_ASKED``)
    instead of applied -- the replay after a write, where question ids may have moved."""
    result = ConfirmResult({bare_table(t): copy.deepcopy(d) for t, d in documents.items()})
    original = copy.deepcopy(result.documents)
    for entry in confirmations:
        table = bare_table(entry.get("table"))
        document = result.documents.get(table)
        if document is None:
            result.unmatched.append(_miss(entry, "unknown table: no table-semantics document for it"))
            continue
        if (require_asked and ASKED not in entry
                and str(entry.get("target")).startswith("question:")):
            result.unmatched.append(_miss(entry, NO_ASKED))
            continue
        if ASKED in entry:
            verdict = _check_asked(document, entry)
            if verdict is _SKIP:
                result.skipped.append(_miss(entry, "the question already holds this answer"))
                continue
            if verdict is not None:
                result.unmatched.append(_miss(entry, verdict))
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
            result.changed_by.setdefault(table, []).append(str(entry.get("target")))
        result.documents[table] = candidate
        result.applied.append(entry)
    # Changed is judged on the end state: a replay whose entries undo each other's steps
    # (a list, then a merge into it) leaves the document as it was and rewrites nothing.
    result.changed = {table for table, document in result.documents.items()
                      if document != original[table]}
    return result


def _miss(entry: dict, reason: str) -> dict:
    return {"table": entry.get("table"), "target": entry.get("target"), "reason": reason}


def _check_asked(document: dict, entry: dict):
    """Where an entry carrying ``asked`` stands: ``_SKIP``, the reason it cannot be
    applied, or None to apply it."""
    target = str(entry.get("target"))
    if not target.startswith("question:"):
        return "asked names a question's text, but the target is not a question"
    question_id = target.split(":", 1)[1]
    question = next((q for q in document["summary"]["questions"] if q["id"] == question_id), None)
    if question is None:
        return None  # reported as an unknown question
    if folded_text(question.get("text")) != folded_text(entry[ASKED]):
        return "question was rewritten: it no longer reads as asked"
    if question.get("status") != "answered":
        return None
    if (question.get("answer"), question.get("answered_by"), question.get("answered_on")) == (
        entry.get("value"), entry.get("by"), entry.get("date")
    ):
        return _SKIP
    if entry.get("replace") is True:
        return None
    return "question already answered differently (pass replace: true to change it)"


def _apply_one(document: dict, entry: dict) -> str | None:
    """Apply one confirmation in place; the reason it cannot be applied, or None."""
    target, value = str(entry.get("target")), entry.get("value")
    if target.startswith("question:"):
        return _answer(document, target.split(":", 1)[1], entry)
    if target == "summary.row":
        return _confirm_row(document["summary"]["row"], value)
    if target == OBSERVED_ROW:
        return observation_problem(OBSERVED_ROW, value) or _observe_row(
            document["summary"]["row"], value)
    if target.startswith(INPUT):
        return observation_problem(INPUT, value) or _observe_input(
            document, input_table(target), value)
    match = _COLUMN_TARGET.fullmatch(target)
    if match is None:
        return f"unknown target {target!r}"
    column = next((c for c in document["columns"] if c["column"] == match["column"]), None)
    if column is None:
        return f"unknown column {match['column']!r} in this table"
    if match["slot"] == "meaning":
        return _confirm_meaning(column, value)
    if match["slot"] == "observed_values":
        return observation_problem(OBSERVED_VALUES, value) or _observe_values(column, value)
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
        if "observed" in value or value.get("grain_source") == "observed":
            return USE_OBSERVED_TARGET
        row.update(value)
        if (("grain_columns" in value or "unique" in value) and "grain_source" not in value
                and row.get("grain_source") in ("inferred", "observed")):
            row["grain_source"] = "declared"
    else:
        return "value must be the row text or an object of row fields"
    _mark(row)
    return None


def _observe_row(row: dict, value: dict) -> None:
    row["observed"] = copy.deepcopy(value)
    if row.get("grain_source") not in ("inferred", "observed"):
        return  # a person's word or the lineage outranks a query
    counted = value["grain_columns"]
    if not (value["unique"] == "yes" and set(row.get("grain_columns") or []) >= set(counted)):
        row["grain_columns"] = list(counted)
    row.update(grain_source="observed", unique=value["unique"])


def _observe_values(column: dict, value: dict) -> str | None:
    if column.get("category") in IDENTIFIER_CATEGORIES and (value.get("values") or value.get("absent")):
        return (f"{column['column']} is an identifier column: an observation of it gives counts "
                "only, no values")
    observed_on = value.get("observed_on")
    sources = {bare_column(source) for source in column.get("source_columns") or []}
    if observed_on is not None and bare_column(observed_on) not in sources:
        return f"observed_on {observed_on} is not a source column of {column['column']}"
    column["observed_values"] = copy.deepcopy(value)
    return None


def _observe_input(document: dict, table: str, value: dict) -> None:
    item = {"table": table, **copy.deepcopy(value)}
    items = document.setdefault("observed_inputs", [])
    key = input_key(table, value["columns"])
    for index, current in enumerate(items):
        if input_key(current["table"], current["columns"]) == key:
            items[index] = item
            return
    items.append(item)


def _log(document: dict, entry: dict) -> None:
    record = {"target": entry.get("target"), "by": entry.get("by"), "date": entry.get("date")}
    target = str(entry.get("target"))
    if target.startswith(INPUT):
        # One input table may be observed on two sets of columns: each is its own record.
        table, columns = input_key(input_table(target), entry["value"]["columns"])
        record.update(target=f"{INPUT}{table}", columns=list(columns))
    log = document.setdefault("confirmed", [])
    if record not in log:
        log.append(record)
