"""The inputs a server was started with, read again whenever they change on disk.

A server answers from one ontology.json, an optional directory of table-semantics
documents and an optional pending file -- the paths given at start, and no others: no
request names a path. Before each answer the ontology file and the semantics directory
are checked with ``stat`` (size, modification time, inode; for the directory, the same
for every ``*.json`` under it, which is what ``catalog`` reads), and read again only when
something differs. So a ``catalog build`` or a new semantics document is answered from on
the next request without a restart, and an unchanged catalog costs a few ``stat`` calls.

A file that cannot be read after start (a build half way through writing it, say) makes
that request fail with the command's own sentence and exit code, and the next request
tries again; the server never answers from a copy it knows to be stale. The pending file
is read on each ``list`` and appended to under a lock, the way ``catalog pending`` does.

With an answers file (``--answers``, ``answers.py``) the page's answers and notes are
judged against the documents on disk and the answers in effect overlaid on them: the
state keeps both, the documents on disk (for the judgement and the export) and the
overlaid ones (for every answer). The answers file has its own signature, so a change to
it re-judges the records without reading the ontology or the semantics directory again.
Only the process started as the file's writer (``answers_writer``: ``http``) writes it --
the page's answers, and the deletion of records the disk has caught up with -- always
under the one lock ``inputs`` holds; any other process overlays it read-only.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from scope_lineage import cli_catalog_answers as answers
from scope_lineage.semantics.digests import document_digest
from scope_lineage.semantics.names import bare_table

from . import answers as records_file


@dataclass(frozen=True)
class AnswersView:
    """The answers file as the last judgement saw it."""

    status: str = "ok"  # or "unreadable"
    reason: str | None = None
    judgement: records_file.Judgement = field(default_factory=records_file.Judgement)
    unmatched: list = field(default_factory=list)  # Judged, not matched or not overlaid
    effective: list = field(default_factory=list)  # Judged answers and notes in effect
    overlaid: frozenset = frozenset()  # (table, question) of the answers overlaid
    problem: str | None = None  # why written-back records could not be deleted

    def live(self) -> list[dict]:
        """The records still standing: those the documents caught up with (written back,
        or a note on a question now answered) left out, even when deleting them failed."""
        gone = {id(item.record) for item in self.judgement.judged
                if item.state in (records_file.WRITTEN, records_file.VOID)}
        return [record for record in self.judgement.records if id(record) not in gone]

    def record(self, table: str, question: str) -> dict | None:
        return next((r for r in self.live() if (r["table"], r["question"]) == (table, question)),
                    None)


@dataclass(frozen=True)
class Inputs:
    document: dict
    semantics: dict | None
    # with an answers file: the documents as on disk, the page states the core marks, and
    # the judgement; without one ``semantics`` is the disk's and the rest None
    disk_semantics: dict | None = None
    page_states: dict | None = None
    answers: AnswersView | None = None

    @property
    def on_disk(self) -> dict | None:
        return self.semantics if self.answers is None else self.disk_semantics


def _file_signature(path: Path) -> tuple:
    try:
        stat = path.stat()
    except OSError:
        return ("missing",)
    return (stat.st_size, stat.st_mtime_ns, stat.st_ino)


def _directory_signature(root: Path) -> tuple:
    """``(relative path, size, mtime, inode)`` of every ``*.json`` below ``root``, in path
    order. Walked with ``os.scandir`` and plain strings: with thousands of documents this
    runs before every answer, and ``Path.rglob`` with ``relative_to`` cost several times
    as much."""
    if not root.is_dir():
        return ("missing",)
    found: list[tuple] = []
    pending = [("", str(root))]
    while pending:
        prefix, directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError:
            continue
        for entry in entries:
            name = prefix + entry.name
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                is_dir = False
            if is_dir:
                pending.append((name + "/", entry.path))
            if entry.name.endswith(".json"):
                try:
                    stat = entry.stat()
                except OSError:
                    found.append((name, "missing"))
                    continue
                found.append((name, stat.st_size, stat.st_mtime_ns, stat.st_ino))
    return tuple(sorted(found, key=lambda item: item[0].split("/")))


class CatalogState:
    """Answers' inputs; construction reads them once and raises ``CatalogAnswerError``."""

    def __init__(
        self,
        ontology: str,
        semantics: str | None = None,
        pending: str | None = None,
        *,
        answers: str | None = None,
        answers_writer: bool = False,
        today=None,
    ) -> None:
        self.ontology_path = Path(ontology)
        self.semantics_path = Path(semantics) if semantics else None
        self.pending_path = Path(pending) if pending else None
        self.answers_path = Path(answers) if answers else None
        self.answers_writer = bool(answers and answers_writer)
        self.today = today or (lambda: date.today().isoformat())
        self._lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._signature: tuple | None = None
        self._answers_signature: tuple | None = None
        self._base: Inputs | None = None
        self._inputs: Inputs | None = None
        self.inputs()

    def _current_signature(self) -> tuple:
        semantics = (
            _directory_signature(self.semantics_path) if self.semantics_path else None
        )
        return (_file_signature(self.ontology_path), semantics)

    def inputs(self) -> Inputs:
        """The documents as they are on disk now, with the page's answers in effect overlaid
        when there is an answers file; ``CatalogAnswerError`` when unreadable."""
        with self._lock:
            return self._refresh()

    def _refresh(self) -> Inputs:
        """``inputs`` with the lock held."""
        signature = self._current_signature()
        changed = self._base is None or signature != self._signature
        if changed:
            self._base = self._inputs = None
            document = answers.load_ontology(str(self.ontology_path))
            semantics = answers.load_semantics(
                str(self.semantics_path) if self.semantics_path else None
            )
            self._base = Inputs(document, semantics)
            self._signature = signature
        if self.answers_path is None:
            self._inputs = self._base
            return self._inputs
        answers_signature = _file_signature(self.answers_path)
        if changed or self._inputs is None or answers_signature != self._answers_signature:
            self._answers_signature = answers_signature
            self._inputs = self._judged(self._base)
        return self._inputs

    # ------------------------------------------------------------------ the page's answers

    def _judged(self, base: Inputs, records: list[dict] | None = None) -> Inputs:
        """``base`` with the answers file judged and its answers in effect overlaid;
        ``records`` are the file's when the caller has just written them (not read again).
        """
        disk = base.semantics
        if records is None:
            try:
                records = records_file.read_records(self.answers_path)
            except records_file.AnswersFileError as error:
                view = AnswersView(status="unreadable", reason=str(error))
                return Inputs(base.document, disk, disk, {}, view)
        judgement = records_file.judge_all(records, disk)
        problem = None
        caught_up = judgement.of(records_file.WRITTEN) + judgement.of(records_file.VOID)
        if caught_up and self.answers_writer:
            try:
                kept = self._delete([item.record for item in caught_up])
            except (OSError, records_file.AnswersFileError) as error:
                problem = (f"{len(caught_up)} record(s) the documents have caught up with "
                           f"could not be deleted: {error}")
            else:
                judgement = records_file.judge_all(kept, disk)
        effective = judgement.of(records_file.EFFECTIVE)
        answered = [item.record for item in effective if item.record["kind"] == records_file.ANSWER]
        overlaid, refused = answers.overlay_answers(
            disk, [records_file.confirmation(record) for record in answered]
        )
        refused_keys = {(bare_table(item.get("table")), str(item.get("target")).split(":", 1)[-1]):
                        item.get("reason") for item in refused}
        unmatched = judgement.of(records_file.UNMATCHED)
        states: dict = {}
        in_effect, written_false = [], set()
        for item in effective:
            key = (item.record["table"], item.record["question"])
            if key in refused_keys:
                unmatched.append(records_file.Judged(
                    item.record, records_file.UNMATCHED, records_file.NOT_APPLIED, item.now,
                    f"{records_file.REASON_TEXT[records_file.NOT_APPLIED]}：{refused_keys[key]}",
                ))
                continue
            in_effect.append(item)
            if item.record["kind"] == records_file.ANSWER:
                states[key] = {"written": False}
                written_false.add(key)
            else:
                states[key] = records_file.note_state(item.record)
        view = AnswersView(judgement=judgement, unmatched=unmatched, effective=in_effect,
                           overlaid=frozenset(written_false), problem=problem)
        return Inputs(base.document, overlaid if disk is not None else None, disk, states, view)

    def _delete(self, stale: list[dict]) -> list[dict]:
        """Delete ``stale`` from the answers file -- read again under the lock, and only
        records still exactly as judged -- and return the records left. The new file's
        signature is kept, so this write does not make the next request read it again."""
        current = records_file.read_records(self.answers_path)
        kept = [record for record in current if record not in stale]
        if len(kept) != len(current):
            records_file.write_records(self.answers_path, kept)
            self._answers_signature = _file_signature(self.answers_path)
        return kept

    def _require_answers(self) -> Inputs:
        """The inputs with the lock held, when answers can be written now."""
        if self.answers_path is None:
            raise AnswersNotConfigured()
        current = self._refresh()
        if current.answers.status != "ok":
            raise AnswersUnavailable(
                f"the answers file {current.answers.reason}; nothing is written until it is "
                "repaired or removed"
            )
        return current

    def _write(self, base: Inputs, records: list[dict]) -> None:
        try:
            records_file.write_records(self.answers_path, records)
        except OSError as error:
            raise AnswersUnavailable(f"the answers file cannot be written ({error})") from None
        self._answers_signature = _file_signature(self.answers_path)
        self._inputs = self._judged(base, records)

    def save_answer(self, request: dict) -> dict:
        """Store one answer or note (``request`` as ``POST /api/answers`` takes it, its texts
        already cleaned); the stored record. ``AnswerRefused`` (status, sentence) when the
        page saw something other than what is there now, or the request makes no change."""
        table, question = bare_table(request["table"]), request["question"]
        with self._lock:
            current = self._require_answers()
            asked_now = records_file.find_question(current.disk_semantics, table, question)
            if asked_now is None:
                raise AnswerRefused(404, "not_found",
                                    f"no table-semantics question {question} of {table}")
            disk = records_file.disk_answer(asked_now)
            existing = current.answers.record(table, question)
            seen = request["seen"]
            if records_file.folded(request["asked"]) != records_file.folded(asked_now.get("text")):
                raise AnswerRefused(409, "changed",
                                    "the question was rewritten since the page showed it")
            if seen.get("disk") != disk or seen.get("record") != existing:
                raise AnswerRefused(409, "changed", "the question's answer changed since the "
                                                    "page showed it; load it again")
            record = {"table": table, "question": question, "asked": request["asked"],
                      "base": disk, "kind": request["kind"]}
            text_key = "answer" if request["kind"] == records_file.ANSWER else "reason"
            record[text_key] = request[text_key]
            for key in ("choice", "to"):
                if request.get(key) is not None:
                    record[key] = request[key]
            record.update(source=dict(records_file.SOURCE), by=request["by"], date=self.today())
            if request["kind"] != records_file.ANSWER and disk is not None:
                raise AnswerRefused(400, "bad_input", "this question is answered in its document: "
                                                      "change the answer instead of noting it")
            # the same words to the same question on the same document: no change. The same
            # words to a question rewritten (a record not matched) are a new answer.
            same = existing is not None and records_file.content(record) == records_file.content(
                existing) and existing["base"] == disk and records_file.folded(
                existing["asked"]) == records_file.folded(record["asked"])
            if same or (
                disk is not None and request["kind"] == records_file.ANSWER
                and records_file.folded(records_file.sentence(record))
                == records_file.folded(disk["answer"])
            ):
                raise AnswerRefused(400, "bad_input", "the same as what is there now")
            records = [record if (r["table"], r["question"]) == (table, question) else r
                       for r in current.answers.live()]
            if existing is None:
                records.append(record)
            self._write(self._base, records)
            return record

    def withdraw_answer(self, table: str, question: str, seen) -> dict:
        """Delete one record, as the page saw it; the record deleted."""
        table = bare_table(table)
        with self._lock:
            current = self._require_answers()
            existing = current.answers.record(table, question)
            if existing is None:
                raise AnswerRefused(404, "not_found", f"no page answer to {question} of {table}")
            if seen != existing:
                raise AnswerRefused(409, "changed",
                                    "the answer changed since the page showed it; load it again")
            records = [r for r in current.answers.live() if r is not existing]
            self._write(self._base, records)
            return existing

    def export_answers(self) -> dict:
        """The ``semantic-confirmations/1`` file of the answers in effect."""
        current = self.inputs()
        if current.answers is None:
            raise AnswersNotConfigured()
        return records_file.export_document(
            [item.record for item in current.answers.effective
             if item.record["kind"] == records_file.ANSWER]
        )

    def answers_summary(self, current: Inputs) -> dict:
        """What the board says about the answers: their status, the ones not matched, and
        the digest of each document the export answers (to check before writing back)."""
        view = current.answers
        summary = {"status": view.status}
        if view.reason:
            summary["reason"] = view.reason
        exported = sorted({item.record["table"] for item in view.effective
                           if item.record["kind"] == records_file.ANSWER})
        summary.update(
            effective=len(view.effective),
            exported=sum(1 for item in view.effective
                         if item.record["kind"] == records_file.ANSWER),
            digests={table: document_digest(current.disk_semantics[table]) for table in exported},
            unmatched=[item.listing() for item in view.unmatched],
        )
        if view.problem:
            summary["problem"] = view.problem
        return summary

    # ------------------------------------------------------------------ answers

    def search(self, text: str, kinds=None, limit: int = 10) -> answers.CatalogAnswer:
        current = self.inputs()
        return answers.search(current.document, text, current.semantics, kinds=kinds, limit=limit)

    def query(self, kind: str, term: str) -> answers.CatalogAnswer:
        return answers.query(self.inputs().document, kind, term)

    def context(self, **request) -> answers.CatalogAnswer:
        answers.context_columns(
            **{key: value for key, value in request.items() if key != "brief"}
        )
        current = self.inputs()
        if current.page_states is not None:
            request["page_states"] = current.page_states
        return answers.context(current.document, current.semantics, **request)

    def check_sql(self, sql: str) -> answers.CatalogAnswer:
        return answers.check_sql(self.inputs().document, sql)

    def pending_list(self) -> answers.CatalogAnswer:
        path = self._require_pending()
        current = self.inputs()
        return answers.pending_list(str(path), current.document, current.semantics)

    def pending_add(self, **request) -> list[dict]:
        path = self._require_pending()
        with self._pending_lock:
            return answers.pending_add(str(path), **request)

    # ------------------------------------------------------------------ browsing

    def browse_index(self) -> answers.CatalogAnswer:
        current = self.inputs()
        return answers.browse_index(current.document, current.semantics)

    def browse_list(self, kind: str, **request) -> answers.CatalogAnswer:
        current = self.inputs()
        return answers.browse_list(current.document, kind, current.semantics, **request)

    def table_units(self, table: str) -> answers.CatalogAnswer:
        current = self.inputs()
        return answers.table_units(current.document, current.semantics, table)

    def neighbourhood(self, concept: str, **request) -> answers.CatalogAnswer:
        return answers.neighbourhood(self.inputs().document, concept, **request)

    def table_semantics(self, table: str) -> answers.CatalogAnswer:
        """One table's document whole (overlaid). With an answers file the answer gains,
        beside the document, ``unwritten`` (the ids of the questions answered on the page
        and not written back) and ``page`` (``{question id: note}``): the document itself
        never gains a key."""
        current = self.inputs()
        answer = answers.table_semantics(current.document, current.semantics, table)
        if current.answers is not None:
            key = bare_table(answer.result.get("table") or table)
            answer.result["unwritten"] = sorted(
                question for (name, question) in current.answers.overlaid if name == key
            )
            answer.result["page"] = {
                question: state for (name, question), state in sorted(current.page_states.items())
                if name == key and "kind" in state
            }
        return answer

    def questions(self, **request) -> answers.CatalogAnswer:
        """The board; the pending file joins it when one was given (absent yet: empty).

        With an answers file the page states are passed (so ``status`` takes
        ``set_aside``), each table-semantics item with a page record carries it
        (``record``, ``record_state`` -- ``effective`` or ``unmatched`` --, and ``disk``,
        what the document on disk holds for the question: the triple the page sends back as
        ``seen``), and the answer gains ``answers`` (``answers_summary``)."""
        current = self.inputs()
        text = None
        if self.pending_path is not None:
            text = (
                answers.read_pending_file(str(self.pending_path))
                if self.pending_path.is_file() else ""
            )
        if current.answers is None:
            return answers.questions(current.document, current.semantics, text, **request)
        answer = answers.questions(
            current.document, current.semantics, text, page_states=current.page_states, **request
        )
        view = current.answers
        states = {id(item.record): item for item in view.effective + view.unmatched}
        for item in answer.result.get("items") or []:
            if item.get("source") != "semantics":
                continue
            key = (bare_table(item.get("table")), str(item.get("id")))
            record = view.record(*key)
            if record is None:
                continue
            judged = states.get(id(record))
            item["record"] = record
            item["record_state"] = judged.state if judged else records_file.UNMATCHED
            item["disk"] = records_file.disk_answer(
                records_file.find_question(current.disk_semantics, *key)
            )
        answer.result["answers"] = self.answers_summary(current)
        return answer

    def public_text(self, text: str) -> str:
        """``text`` with every spelling of the three inputs' paths -- as given, absolute,
        resolved -- cut to the file or directory name, so a file under the semantics
        directory reads ``<dir name>/<file>``. The HTTP server passes every error message
        it sends through this; the core's messages, and the command line, keep full paths.
        """
        spellings: dict[str, str] = {}
        for path in (self.ontology_path, self.semantics_path, self.pending_path,
                     self.answers_path):
            if path is None:
                continue
            name = _name(path)
            for form in (str(path), os.path.abspath(path), str(path.resolve())):
                if form and form != name:
                    spellings[form] = name
        for form in sorted(spellings, key=len, reverse=True):
            text = text.replace(form, spellings[form])
        return text

    def _require_pending(self) -> Path:
        if self.pending_path is None:
            raise PendingNotConfigured()
        return self.pending_path

    # ------------------------------------------------------------------ health

    def health(self) -> dict:
        try:
            current = self.inputs()
        except answers.CatalogAnswerError as error:
            status, problem, current = "unavailable", error.message, None
        else:
            status, problem = "ok", None
        document = current.document if current else {}
        writes = [_name(path) for path in (self.pending_path,
                                           self.answers_path if self.answers_writer else None)
                  if path is not None]
        report = {
            "status": status,
            "writes": writes,
            "executes_sql": False,
            "ontology": {
                "path": _name(self.ontology_path),
                "doc_format": document.get("doc_format"),
                "catalog": (document.get("catalog") or {}).get("name"),
                "counts": document.get("counts"),
            },
            "semantics": {
                "path": _name(self.semantics_path) if self.semantics_path else None,
                "documents": len(current.semantics) if current and current.semantics else 0,
            },
            "pending": {
                "configured": self.pending_path is not None,
                "path": _name(self.pending_path) if self.pending_path else None,
                "exists": bool(self.pending_path and os.path.isfile(self.pending_path)),
            },
        }
        if self.answers_path is not None:
            report["answers"] = self._answers_health(current)
        if problem:
            report["problem"] = problem
        return report

    def _answers_health(self, current: Inputs | None) -> dict:
        view = current.answers if current else None
        health = {"path": _name(self.answers_path), "writer": self.answers_writer,
                  "status": view.status if view else "unknown"}
        if view is None:
            return health
        if view.reason:
            health["reason"] = view.reason
        health.update(records=len(view.live()), effective=len(view.effective),
                      unmatched=len(view.unmatched))
        if view.problem:
            health["problem"] = view.problem
        return health


def _name(path) -> str:
    """The last component of a path: ``/health`` names a file or directory, never where it
    lives, so a server reachable off loopback does not tell callers the operator's layout."""
    return os.path.basename(os.path.normpath(str(path)))


class AnswersNotConfigured(Exception):
    """An answers request to a server started without an answers file."""

    message = ("this server was started without an answers file (--answers); the page's "
               "questions are read-only")


class AnswersUnavailable(Exception):
    """The answers file cannot be read or written now."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AnswerRefused(Exception):
    """An answer the server does not store: ``status`` is the HTTP status."""

    def __init__(self, status: int, kind: str, message: str) -> None:
        super().__init__(message)
        self.status, self.kind, self.message = status, kind, message


class PendingNotConfigured(Exception):
    """A pending request to a server started without a pending file."""

    message = "this server was started without a pending file (--pending); nothing to list or add"
