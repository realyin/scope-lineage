"""The answers a browsing page gives to table-semantics questions: the record file.

A server started with ``--answers FILE`` keeps the page's answers and notes in that file,
``question-answers/1``, and never in the semantics directory::

    {"doc_format": "question-answers/1",
     "answers": [{"table", "question", "asked", "base", "kind", "answer" | "reason",
                  "choice"?, "to"?, "source", "by", "date"}]}

One record per ``(table, question)``. ``kind`` is ``answer`` or one of the five page notes
(``PAGE_KINDS``: ``partial``, ``deferred``, ``redirect`` -- which names who to ask in
``to`` --, ``invalid``, ``not_applicable``); an answer carries ``answer``, a note
``reason``. ``choice`` (``yes`` / ``no``) is allowed on ``answer`` and ``partial``.
``asked`` is the question's text as the person saw it, ``base`` what the document on disk
held for the question then: ``null`` (open) or ``{answer, answered_by, answered_on}``.
``source`` is ``{"kind": "person"}``.

Each record is judged against the documents on disk (``judge``), in order, the first row
that holds deciding:

- the table or the question is gone -> not matched;
- the question's text differs from ``asked`` (NFKC and whitespace folded, the core's
  ``folded_text``) -> not matched;
- an answer the disk now holds exactly (text, who and date) -> written back; a note on a
  question the disk now answers -> void. Both are deleted by the one process that writes
  the file;
- an answer whose ``base`` is what the disk holds, a note on an open question -> in effect;
- anything else (an answer) -> not matched: the disk changed under it.

Only answers in effect are overlaid on the documents and exported as a
``semantic-confirmations/1`` file; notes are never written back. Each exported entry
carries ``asked``, and ``replace: true`` when its ``base`` is an answer, so ``semantic
confirm`` applies the same judgement on its side: a rewritten question is refused there
too, and an answer on disk is changed only where the person changed it. Nothing here
reads the semantics directory or writes outside the record file.

Structured answers
------------------

An answer may also carry a structured value (``target``, ``value``, ``slot_base``)::

    {"target": "summary.row", "value": {"unique": "yes" | "no", "grain_columns": [...]}}
    {"target": "column:<c>.meaning", "value": "<text>"}
    {"target": "column:<c>.code_values", "value": [{"value", "meaning"}, ...]}

``slot_base`` is the slot on disk when it was given (``slot_of``): the row's ``{unique,
grain_columns, grain_source}``, the column's meaning (or null), or ``{value: meaning or
null}`` of the code values submitted. ``answer`` is then optional, a note after the
generated sentence (``sentence``: 「否：按 (a, b) 不唯一」, 「列 c 的含义：…」, 「列 c 的码值：
1=…；2=…」). No ``choice``; only ``kind: answer``. The guards: 1--8 distinct grain
columns of the table; 1--50 distinct code values of 1--64 characters, never on an
identifier column; texts on one line; no row answer when the disk's grain is ``proven``
(the lineage proved it: say the disagreement in a sentence instead).

The judgement adds the slot to the rows above: written back needs the disk's answer to be
the generated sentence *and* the slot to hold the value (``slot_written``: the same
``unique`` and set of grain columns; the same meaning; each code value present, with the
meaning, not ``unconfirmed``); in effect needs the question *and* the slot to be as they
were (``slot_base``); a column gone is missing.

A structured record exports as its structured entries -- each code value one single-object
entry, never a list (a list replaces the column's codes) -- then the ``question:`` entry
that closes the question (``confirmations``). The structured entries carry no ``asked``:
``semantic confirm`` refuses it on a target that is not a question. ``overlay_records``
overlays a record's entries together: a record with any entry refused is taken out whole
and the rest overlaid again, until nothing is refused (at most ``MAX_OVERLAY_PASSES``);
a refusal is mapped back to its record by the entry's position, never by its target. Of two
records on one slot (two questions answering the row, or the same code value) the later is
not overlaid. ``semantic confirm`` keeps no such unity: replaying under
``--require-asked`` after a rewrite, the ``question:`` entry is unmatched and the
structured entry still applies. A code value changed from a meaning on disk cannot be
taken back by a replay (a single object only merges), so the export says to remove an old
entry for it (``export_notes``). A code value the SQL never writes (a constant column) is
not refused here or by ``semantic confirm`` -- neither has the packet --; validation fails
it as 「确认与 SQL 矛盾，交回 owner」.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from scope_lineage import cli_catalog_answers as core
from scope_lineage.render.catalog_context import PAGE_KINDS, ROW_SLOT
from scope_lineage.semantics.names import bare_table
from scope_lineage.semantics.names import folded_text as folded
from scope_lineage.semantics.observed import IDENTIFIER_CATEGORIES

ANSWERS_FORMAT = "question-answers/1"
CONFIRMATIONS_FORMAT = "semantic-confirmations/1"
ANSWER = "answer"
KINDS = (ANSWER, *PAGE_KINDS)
CHOICES = ("yes", "no")
CHOICE_KINDS = (ANSWER, "partial")
CHOICE_WORDS = {"yes": "是", "no": "否"}
SOURCE = {"kind": "person"}
MAX_TEXT = 1000  # characters of an answer or a reason, after normalising
MAX_NAME = 60  # characters of a name (who answers, who to ask)
BASE_KEYS = ("answer", "answered_by", "answered_on")
RECORD_KEYS = {
    "table", "question", "asked", "base", "kind", "answer", "reason", "choice", "to",
    "source", "by", "date", "target", "value", "slot_base",
}
ROW_TARGET = "summary.row"
UNIQUE_WORDS = {"yes": "是", "no": "否"}
ROW_FIELDS = ("unique", "grain_columns", "grain_source")
MAX_GRAIN_COLUMNS = 8
MAX_CODES = 50
MAX_CODE = 64  # characters of a code value
MAX_OVERLAY_PASSES = 8
_COLUMN_TARGET = re.compile(r"column:(?P<column>[^.\s]+)\.(?P<slot>meaning|code_values)")
PROVEN_REFUSED = "血缘已证明粒度，不接受页面的行粒度回答；用一句话说明分歧"
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
# Characters a text never carries: control and format characters, and line and paragraph
# separators. A line break could forge a line of the text context pack.
_REFUSED = frozenset({"Cc", "Cf", "Cs", "Co", "Zl", "Zp"})

# the states ``judge`` gives
EFFECTIVE, UNMATCHED, WRITTEN, VOID = "effective", "unmatched", "written", "void"
MISSING, REWRITTEN, CHANGED, NOT_APPLIED = "missing", "rewritten", "changed", "not_applied"
REASON_TEXT = {
    MISSING: "表或问题不存在",
    REWRITTEN: "问题已改写",
    CHANGED: "磁盘上的状态已变",
    NOT_APPLIED: "叠加不上",
}


class AnswersFileError(Exception):
    """The record file cannot be read, or is not ``question-answers/1``."""


class TextRefused(ValueError):
    """A text a person typed that the page may not store."""


# ------------------------------------------------------------------ texts


def clean_text(value, name: str, limit: int) -> str:
    """``value`` as typed, stripped of leading and trailing whitespace only -- never
    normalised, so full-width punctuation reaches the documents as it was written;
    ``TextRefused`` when it is not a string, blank, longer than ``limit`` characters, or
    carries a line break or a control character. NFKC is used only to compare texts
    (``folded``)."""
    if value is None:
        raise TextRefused(f"{name} is empty")
    if not isinstance(value, str):
        raise TextRefused(f"{name} takes a string")
    text = value.strip()
    if not text:
        raise TextRefused(f"{name} is empty")
    bad = next((char for char in text if unicodedata.category(char) in _REFUSED), None)
    if bad is not None:
        raise TextRefused(
            f"{name} carries a line break or a control character (U+{ord(bad):04X}); "
            "write it on one line"
        )
    if len(text) > limit:
        raise TextRefused(f"{name} is {len(text)} characters; at most {limit}")
    return text


def sentence(record: dict) -> str:
    """The answer as one sentence: ``是：…`` / ``否：…`` when a choice was made; for a
    structured answer the generated sentence, then ``；`` and the note when there is one."""
    if "target" in record:
        generated = structured_sentence(record["target"], record["value"])
        return f"{generated}；{record['answer']}" if record.get("answer") else generated
    text = record.get("answer") if record.get("kind") == ANSWER else record.get("reason")
    choice = record.get("choice")
    return f"{CHOICE_WORDS[choice]}：{text}" if choice in CHOICE_WORDS else str(text)


def structured_sentence(target: str, value) -> str:
    """The fixed sentence a structured value answers its question with."""
    if target == ROW_TARGET:
        columns = ", ".join(value["grain_columns"])
        said = "每行唯一" if value["unique"] == "yes" else "不唯一"
        return f"{UNIQUE_WORDS[value['unique']]}：按 ({columns}) {said}"
    match = _COLUMN_TARGET.fullmatch(target)
    if match["slot"] == "meaning":
        return f"列 {match['column']} 的含义：{value}"
    pairs = "；".join(f"{item['value']}={item['meaning']}" for item in value)
    return f"列 {match['column']} 的码值：{pairs}"


def content(record: dict | None) -> tuple | None:
    """What a record says, without who said it or when: two submissions saying the same
    are the same."""
    if record is None:
        return None
    said = (record.get("kind"), folded(record.get("answer")), folded(record.get("reason")),
            record.get("choice"), folded(record.get("to")))
    if "target" in record:
        said += (record["target"], json.dumps(record["value"], ensure_ascii=False, sort_keys=True))
    return said


# ------------------------------------------------------------------ structured values


def target_column(target) -> tuple[str, str] | None:
    """``(column, "meaning" | "code_values")`` of a column target; None otherwise."""
    match = _COLUMN_TARGET.fullmatch(str(target))
    return (match["column"], match["slot"]) if match else None


def value_problem(target, value) -> str | None:
    """Why ``value`` is not a structured value a page may give ``target`` (without the
    document: the columns are checked by ``document_problem``), or None."""
    if target == ROW_TARGET:
        if not isinstance(value, dict) or set(value) != {"unique", "grain_columns"}:
            return "a row value is {unique, grain_columns}"
        if value["unique"] not in UNIQUE_WORDS:
            return "unique is yes or no"
        columns = value["grain_columns"]
        if not isinstance(columns, list) or not 1 <= len(columns) <= MAX_GRAIN_COLUMNS:
            return f"grain_columns names 1 to {MAX_GRAIN_COLUMNS} columns"
        if not all(isinstance(c, str) and c and c == c.strip() for c in columns):
            return "grain_columns are column names"
        if len(set(columns)) != len(columns):
            return "grain_columns names a column twice"
        return None
    column = target_column(target)
    if column is None:
        return "target is summary.row, column:<c>.meaning or column:<c>.code_values"
    if column[1] == "meaning":
        return _text_problem(value, "value", MAX_TEXT)
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_CODES:
        return f"code values are a list of 1 to {MAX_CODES} {{value, meaning}}"
    seen = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"value", "meaning"}:
            return "each code value is {value, meaning}"
        problem = (_text_problem(item["value"], "a code value", MAX_CODE)
                   or _text_problem(item["meaning"], "a code value's meaning", MAX_TEXT))
        if problem:
            return problem
        if item["value"] in seen:
            return f"code value {item['value']!r} is given twice"
        seen.add(item["value"])
    return None


def _text_problem(value, name: str, limit: int) -> str | None:
    try:
        if clean_text(value, name, limit) != value:
            return f"{name} is not stripped (leading or trailing whitespace)"
    except TextRefused as error:
        return str(error)
    return None


def find_column(document: dict | None, column: str) -> dict | None:
    return next((c for c in (document or {}).get("columns") or [] if c.get("column") == column),
                None)


def document_problem(document: dict, target: str, value) -> str | None:
    """Why the table's document cannot take this structured answer, or None: a column it
    does not have, a code value on an identifier column, a row answer on a proven grain."""
    if target == ROW_TARGET:
        names = {c.get("column") for c in document.get("columns") or []}
        absent = [c for c in value["grain_columns"] if c not in names]
        if absent:
            return f"no column {', '.join(absent)} in {document.get('table')}"
        if ((document.get("summary") or {}).get("row") or {}).get("grain_source") == "proven":
            return PROVEN_REFUSED
        return None
    name, slot = target_column(target)
    column = find_column(document, name)
    if column is None:
        return f"no column {name} in {document.get('table')}"
    if slot == "code_values" and column.get("category") in IDENTIFIER_CATEGORIES:
        return f"{name} is an identifier column: its code values are not answered on the page"
    return None


def slot_of(document: dict | None, target: str, value):
    """The slot a structured answer writes, as ``document`` holds it now: the row's
    ``{unique, grain_columns, grain_source}``, the column's meaning (None without one), or
    ``{value: meaning or None}`` of the code values in ``value``. None when the column is
    gone."""
    if target == ROW_TARGET:
        row = ((document or {}).get("summary") or {}).get("row") or {}
        return {key: row.get(key) for key in ROW_FIELDS}
    name, slot = target_column(target)
    column = find_column(document, name)
    if column is None:
        return None
    if slot == "meaning":
        return column.get("meaning")
    codes = {code.get("value"): code for code in column.get("code_values") or []}
    return {item["value"]: (codes[item["value"]].get("meaning") if item["value"] in codes else None)
            for item in value}


def slot_written(document: dict | None, target: str, value) -> bool:
    """Whether the document holds the value as answered: the same ``unique`` and set of
    grain columns; the same meaning; each code value with the meaning, not unconfirmed."""
    if target == ROW_TARGET:
        row = ((document or {}).get("summary") or {}).get("row") or {}
        return (row.get("unique") == value["unique"]
                and set(row.get("grain_columns") or []) == set(value["grain_columns"]))
    name, slot = target_column(target)
    column = find_column(document, name)
    if column is None:
        return False
    if slot == "meaning":
        return folded(column.get("meaning")) == folded(value)
    codes = {code.get("value"): code for code in column.get("code_values") or []}
    return all(item["value"] in codes and not codes[item["value"]].get("unconfirmed")
               and folded(codes[item["value"]].get("meaning")) == folded(item["meaning"])
               for item in value)


def slot_names(record: dict) -> list[str]:
    """The page slots a structured record answers (``catalog_context.page_index``):
    ``row``, ``column:<c>.meaning``, ``column:<c>.code_values:<value>``; none without a
    target."""
    if "target" not in record:
        return []
    if record["target"] == ROW_TARGET:
        return [ROW_SLOT]
    if target_column(record["target"])[1] == "meaning":
        return [record["target"]]
    return [f"{record['target']}:{item['value']}" for item in record["value"]]


def _slot_base_problem(target: str, value, base) -> str | None:
    if target == ROW_TARGET:
        if not isinstance(base, dict) or set(base) != set(ROW_FIELDS):
            return "slot_base of a row answer is {unique, grain_columns, grain_source}"
        return None
    if target_column(target)[1] == "meaning":
        return None if base is None or isinstance(base, str) else (
            "slot_base of a meaning is the meaning on disk or null")
    if not isinstance(base, dict) or set(base) != {item["value"] for item in value} or not all(
        meaning is None or isinstance(meaning, str) for meaning in base.values()
    ):
        return "slot_base of code values is {value: meaning on disk or null} of the values given"
    return None


# ------------------------------------------------------------------ the file


def read_records(path: Path) -> list[dict]:
    """The records of the file; none when it does not exist yet. ``AnswersFileError``
    when it cannot be read or is not a legal ``question-answers/1`` document."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as error:
        raise AnswersFileError(f"cannot be read ({error})") from None
    try:
        document = json.loads(raw)
    except ValueError as error:
        raise AnswersFileError(f"not a JSON document ({error})") from None
    return check_document(document)


def check_document(document) -> list[dict]:
    if not isinstance(document, dict) or document.get("doc_format") != ANSWERS_FORMAT:
        raise AnswersFileError(f"not a {ANSWERS_FORMAT} document")
    if set(document) != {"doc_format", "answers"} or not isinstance(document["answers"], list):
        raise AnswersFileError('the document is {"doc_format", "answers": [...]}')
    seen = set()
    for number, record in enumerate(document["answers"], 1):
        problem = record_problem(record)
        if problem:
            raise AnswersFileError(f"answers[{number}]: {problem}")
        key = (record["table"], record["question"])
        if key in seen:
            raise AnswersFileError(
                f"answers[{number}]: a second record for {record['table']} {record['question']}"
            )
        seen.add(key)
    return document["answers"]


def record_problem(record) -> str | None:
    """Why ``record`` is not a legal record, or None."""
    if not isinstance(record, dict):
        return "not an object"
    unknown = sorted(set(record) - RECORD_KEYS)
    if unknown:
        return f"unknown key(s): {', '.join(unknown)}"
    for name in ("table", "question", "asked"):
        if not isinstance(record.get(name), str) or not record[name]:
            return f"{name} must be a non-empty string"
    if record["table"] != bare_table(record["table"]):
        return f"table must be written db.table in lower case, not {record['table']!r}"
    kind = record.get("kind")
    if kind not in KINDS:
        return f"kind must be one of {', '.join(KINDS)}"
    text_key, other = ("answer", "reason") if kind == ANSWER else ("reason", "answer")
    if other in record:
        return f"a {kind} record has {text_key}, not {other}"
    structured = "target" in record
    if not structured and ("value" in record or "slot_base" in record):
        return "value and slot_base come with a target"
    if structured:
        problem = _structured_problem(record)
        if problem:
            return problem
    checks = [("by", MAX_NAME)] if structured and "answer" not in record else [
        (text_key, MAX_TEXT), ("by", MAX_NAME)]
    if kind == "redirect":
        checks.append(("to", MAX_NAME))
    elif "to" in record:
        return "only a redirect names who to ask (to)"
    for name, limit in checks:
        try:
            if clean_text(record.get(name), name, limit) != record.get(name):
                return f"{name} is not stripped (leading or trailing whitespace)"
        except TextRefused as error:
            return str(error)
    if "choice" in record and (kind not in CHOICE_KINDS or record["choice"] not in CHOICES):
        return f"choice is yes or no, on {' or '.join(CHOICE_KINDS)} only"
    if record.get("source") != SOURCE:
        return f"source must be {json.dumps(SOURCE)}"
    if not isinstance(record.get("date"), str) or not _DATE.fullmatch(record["date"]):
        return "date must be YYYY-MM-DD"
    base = record.get("base", ...)
    if base is ...:
        return "base is required (null when the question was open)"
    if base is not None:
        if kind != ANSWER:
            return "a note is left on an open question: its base is null"
        if not isinstance(base, dict) or set(base) != set(BASE_KEYS) or not isinstance(
            base.get("answer"), str
        ) or not all(base[key] is None or isinstance(base[key], str) for key in BASE_KEYS):
            return "base is null or {answer, answered_by, answered_on}"
    return None


def _structured_problem(record: dict) -> str | None:
    if record.get("kind") != ANSWER:
        return "only an answer carries a target"
    if "choice" in record:
        return "a structured answer has no choice (its value says it)"
    if "value" not in record or "slot_base" not in record:
        return "a structured answer has value and slot_base"
    problem = value_problem(record["target"], record["value"])
    if problem:
        return problem
    problem = _slot_base_problem(record["target"], record["value"], record["slot_base"])
    if problem:
        return problem
    if len(sentence(record)) > MAX_TEXT:
        return f"the answer's sentence is longer than {MAX_TEXT} characters"
    return None


def write_records(path: Path, records: list[dict]) -> None:
    """Replace the file with ``records``: a temporary file beside it, then a rename, so a
    reader sees the old file or the new one, never half of one. ``OSError`` when it cannot
    be written."""
    text = json.dumps({"doc_format": ANSWERS_FORMAT, "answers": records},
                      ensure_ascii=False, indent=2) + "\n"
    directory = path.parent if str(path.parent) else Path(".")
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


# ------------------------------------------------------------------ judgement


def disk_answer(question: dict | None) -> dict | None:
    """``{answer, answered_by, answered_on}`` of an answered question, None when open."""
    if not question or question.get("status") != "answered":
        return None
    return {key: question.get(key) for key in BASE_KEYS}


def find_question(semantics: dict | None, table: str, question: str) -> dict | None:
    document = (semantics or {}).get(bare_table(table))
    if not document:
        return None
    return next(
        (item for item in (document.get("summary") or {}).get("questions") or []
         if str(item.get("id")) == str(question)),
        None,
    )


def now_of(question: dict | None) -> dict | None:
    """What the disk holds for a question now, as the board shows it."""
    if question is None:
        return None
    return {"text": question.get("text"), "status": question.get("status"),
            **(disk_answer(question) or {key: None for key in BASE_KEYS})}


@dataclass
class Judged:
    record: dict
    state: str
    reason: str | None = None
    now: dict | None = None
    message: str | None = None

    def listing(self) -> dict:
        """The not-matched entry the board and the export list."""
        return {"table": self.record["table"], "question": self.record["question"],
                "record": self.record, "reason": self.reason,
                "message": self.message or REASON_TEXT.get(self.reason, self.reason),
                "now": self.now}


def judge(record: dict, semantics: dict | None) -> Judged:
    """Where ``record`` stands against the documents on disk (the module's rows)."""
    question = find_question(semantics, record["table"], record["question"])
    now = now_of(question)
    structured = "target" in record
    document = (semantics or {}).get(bare_table(record["table"])) if structured else None
    if structured and question is not None:
        now["slot"] = slot_of(document, record["target"], record["value"])
    if question is None or (structured and record["target"] != ROW_TARGET
                            and find_column(document, target_column(record["target"])[0]) is None):
        return Judged(record, UNMATCHED, MISSING, now)
    if folded(question.get("text")) != folded(record["asked"]):
        return Judged(record, UNMATCHED, REWRITTEN, now)
    disk = disk_answer(question)
    if record["kind"] != ANSWER:
        return Judged(record, VOID if disk else EFFECTIVE, None, now)
    if disk and disk == {"answer": sentence(record), "answered_by": record["by"],
                         "answered_on": record["date"]} and (
            not structured or slot_written(document, record["target"], record["value"])):
        return Judged(record, WRITTEN, None, now)
    if disk == record["base"] and (not structured or now["slot"] == record["slot_base"]):
        return Judged(record, EFFECTIVE, None, now)
    return Judged(record, UNMATCHED, CHANGED, now)


def confirmation(record: dict) -> dict:
    """The ``semantic-confirmations/1`` entry of an answer record: the question as it was
    asked, and ``replace`` when the person changed an answer already on disk."""
    entry = {"table": record["table"], "target": f"question:{record['question']}",
             "value": sentence(record), "by": record["by"], "date": record["date"],
             "asked": record["asked"]}
    if record["base"] is not None:
        entry["replace"] = True
    return entry


def confirmations(record: dict) -> list[dict]:
    """Every ``semantic-confirmations/1`` entry of an answer record: a structured record's
    entries first (each code value its own single-object entry, none carrying ``asked``),
    then the ``question:`` entry that closes the question."""
    if "target" not in record:
        return [confirmation(record)]
    values = record["value"] if target_column(record["target"]) and target_column(
        record["target"])[1] == "code_values" else [record["value"]]
    entries = [{"table": record["table"], "target": record["target"], "value": value,
                "by": record["by"], "date": record["date"]} for value in values]
    return entries + [confirmation(record)]


def overlay_records(semantics: dict | None, records: list[dict]) -> tuple[dict, dict]:
    """``(semantics with the records' answers overlaid, {id(record): why not overlaid})``.

    A record stands or falls whole: every entry of a record any entry of which the core
    refuses is taken out, and the rest overlaid again, until a pass refuses nothing (at
    most ``MAX_OVERLAY_PASSES``; past that nothing is overlaid). A refusal is mapped to its
    record by the entry's position (``overlay_answers(indexed=True)``): a structured target
    names a column, not its question. Of two structured records on one slot the later is
    not overlaid."""
    refused: dict[int, str] = {}
    held: dict[tuple[str, str], dict] = {}
    live = []
    for record in records:
        slots = [(record["table"], name) for name in slot_names(record)]
        holder = next((held[slot] for slot in slots if slot in held), None)
        if holder is not None:
            refused[id(record)] = (f"问题 {holder['question']} 的页面回答已答同一槽位"
                                   f"（{_slot_words(record)}）")
            continue
        held.update({slot: record for slot in slots})
        live.append(record)
    for _ in range(MAX_OVERLAY_PASSES):
        entries, owners = [], []
        for record in live:
            for entry in confirmations(record):
                entries.append(entry)
                owners.append(record)
        overlaid, unapplied = core.overlay_answers(semantics, entries, indexed=True)
        taken = False
        for item in unapplied:
            index = item.get("index")
            if isinstance(index, int) and 0 <= index < len(owners) and id(owners[index]) not in refused:
                refused[id(owners[index])] = item.get("reason")
                taken = True
        if not unapplied:
            return overlaid, refused
        live = [record for record in live if id(record) not in refused]
        if not taken:
            break
    for record in live:
        refused.setdefault(id(record), "叠加反复被拒，没有叠加")
    return dict(semantics or {}), refused


def _slot_words(record: dict) -> str:
    if record["target"] == ROW_TARGET:
        return "行粒度"
    name, slot = target_column(record["target"])
    return f"列 {name} 的含义" if slot == "meaning" else f"列 {name} 的码值"


def export_notes(records: list[dict]) -> list[str]:
    """What the export must say beside the file: a code value whose meaning on disk the
    page changed cannot be taken back by a replay -- a single ``{value, meaning}`` entry
    only merges, and an old entry for the value, wherever it sorts, says the old meaning
    again -- so the old entry must be removed from the confirmations."""
    notes = []
    for record in records:
        column = target_column(record.get("target"))
        if not column or column[1] != "code_values":
            continue
        for item in record["value"]:
            old = record["slot_base"].get(item["value"])
            if old is not None and folded(old) != folded(item["meaning"]):
                notes.append(
                    f"{record['table']} {record['question']}：列 {column[0]} 的码值 "
                    f"{item['value']!r} 由「{old}」改为「{item['meaning']}」。重放只合并、不撤回："
                    "写回前先从 confirmations/ 里删掉确认旧含义的条目（若有），再放入新导出的文件"
                )
    return notes


def note_state(record: dict) -> dict:
    """The page state a note gives the core (``catalog_context.page_index``)."""
    state = {"kind": record["kind"], "reason": record["reason"], "by": record["by"],
             "date": record["date"]}
    for key in ("choice", "to"):
        if key in record:
            state[key] = record[key]
    return state


@dataclass
class Judgement:
    """Every record of the file, judged; the overlay is computed from ``effective``."""

    records: list[dict] = field(default_factory=list)
    judged: list[Judged] = field(default_factory=list)

    def of(self, state: str) -> list[Judged]:
        return [item for item in self.judged if item.state == state]


def judge_all(records: list[dict], semantics: dict | None) -> Judgement:
    return Judgement(list(records), [judge(record, semantics) for record in records])


def export_document(records: list[dict]) -> dict:
    return {"doc_format": CONFIRMATIONS_FORMAT,
            "confirmations": [entry for record in records for entry in confirmations(record)]}
