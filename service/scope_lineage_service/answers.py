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
- the question's text differs from ``asked`` (NFKC and whitespace folded) -> not matched;
- an answer the disk now holds exactly (text, who and date) -> written back; a note on a
  question the disk now answers -> void. Both are deleted by the one process that writes
  the file;
- an answer whose ``base`` is what the disk holds, a note on an open question -> in effect;
- anything else (an answer) -> not matched: the disk changed under it.

Only answers in effect are overlaid on the documents and exported as a
``semantic-confirmations/1`` file; notes are never written back. Nothing here reads the
semantics directory or writes outside the record file.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from scope_lineage.render.catalog_context import PAGE_KINDS
from scope_lineage.semantics.names import bare_table

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
    "source", "by", "date",
}
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


def folded(text) -> str:
    """NFKC with whitespace folded: what two question texts, or a new answer and the one
    already there, are compared by. Never stored."""
    return " ".join(unicodedata.normalize("NFKC", str(text or "")).split())


def sentence(record: dict) -> str:
    """The answer as one sentence: ``是：…`` / ``否：…`` when a choice was made."""
    text = record.get("answer") if record.get("kind") == ANSWER else record.get("reason")
    choice = record.get("choice")
    return f"{CHOICE_WORDS[choice]}：{text}" if choice in CHOICE_WORDS else str(text)


def content(record: dict | None) -> tuple | None:
    """What a record says, without who said it or when: two submissions saying the same
    are the same."""
    if record is None:
        return None
    return (record.get("kind"), folded(record.get("answer")), folded(record.get("reason")),
            record.get("choice"), folded(record.get("to")))


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
    checks = [(text_key, MAX_TEXT), ("by", MAX_NAME)]
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
    if question is None:
        return Judged(record, UNMATCHED, MISSING, now)
    if folded(question.get("text")) != folded(record["asked"]):
        return Judged(record, UNMATCHED, REWRITTEN, now)
    disk = disk_answer(question)
    if record["kind"] != ANSWER:
        return Judged(record, VOID if disk else EFFECTIVE, None, now)
    if disk and disk == {"answer": sentence(record), "answered_by": record["by"],
                         "answered_on": record["date"]}:
        return Judged(record, WRITTEN, None, now)
    if disk == record["base"]:
        return Judged(record, EFFECTIVE, None, now)
    return Judged(record, UNMATCHED, CHANGED, now)


def confirmation(record: dict) -> dict:
    """The ``semantic-confirmations/1`` entry of an answer record."""
    return {"table": record["table"], "target": f"question:{record['question']}",
            "value": sentence(record), "by": record["by"], "date": record["date"]}


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
            "confirmations": [confirmation(record) for record in records]}
