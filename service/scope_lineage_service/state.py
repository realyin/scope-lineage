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

A structured answer (the row's grain, a column's meaning, code values) overlays its slot
and its question together (``answers.overlay_records``): the page states then also mark
the slot (``(table, slot)``: ``{"written": False}``), the table's semantics answer lists it
in ``unwritten_slots``, and the board's summary carries ``export_notes`` when the export
must say something beside the file (a changed code value). Without structured records
every output is what it was.

With a probes file (``--probes``, ``probes.py``) the board's semantics items carry their
queries (``probes``), a pasted result is drafted (``probe_draft``, nothing written) and a
person's confirmation stored under the answers file's ``observations`` key
(``confirm_observation``): the pasted text is parsed again and the draft compared with the
one the page showed (409 when it differs), and the entry must apply to the document on disk
as ``semantic confirm`` would apply it. Observations in effect are listed in the table's
``unwritten_slots`` (by target) and exported with their ``evidence``; the documents are never
overlaid with them. Without observations, and without ``--probes``, every output is what it
was.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from scope_lineage import cli_catalog_answers as answers
from scope_lineage.cli_catalog_answers import CatalogAnswerError
from scope_lineage.semantics import probe_results
from scope_lineage.semantics.confirm import apply_confirmations
from scope_lineage.semantics.digests import document_digest
from scope_lineage.semantics.names import bare_table

from . import answers as records_file
from . import probes as probes_file


@dataclass(frozen=True)
class AnswersView:
    """The answers file as the last judgement saw it."""

    status: str = "ok"  # or "unreadable"
    reason: str | None = None
    judgement: records_file.Judgement = field(default_factory=records_file.Judgement)
    unmatched: list = field(default_factory=list)  # Judged, not matched or not overlaid
    effective: list = field(default_factory=list)  # Judged answers and notes in effect
    overlaid: frozenset = frozenset()  # (table, question) of the answers overlaid
    slots: frozenset = frozenset()  # (table, slot) of the structured answers overlaid
    problem: str | None = None  # why written-back records could not be deleted
    # the observation records, judged: every one, those in effect, those not matched
    observations: list = field(default_factory=list)
    observations_effective: list = field(default_factory=list)  # Judged
    observations_unmatched: list = field(default_factory=list)  # Judged

    def live_observations(self) -> list[dict]:
        """The observation records still standing (those written back left out)."""
        kept = {id(item.record) for item in self.observations_effective + self.observations_unmatched}
        return [record for record in self.observations if id(record) in kept]

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
        probes: str | None = None,
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
        try:
            self.probes = probes_file.ProbesFile(probes) if probes else None
        except probes_file.ProbesError as error:
            raise CatalogAnswerError(2, f"{probes}: {error.message}") from None
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

    def _judged(self, base: Inputs, records: list[dict] | None = None,
                observations: list[dict] | None = None) -> Inputs:
        """``base`` with the answers file judged and its answers in effect overlaid;
        ``records`` and ``observations`` are the file's when the caller has just written
        them (not read again).
        """
        disk = base.semantics
        if records is None:
            try:
                records, observations = records_file.read_file(self.answers_path)
            except records_file.AnswersFileError as error:
                view = AnswersView(status="unreadable", reason=str(error))
                return Inputs(base.document, disk, disk, {}, view)
        observations = list(observations or [])
        judgement = records_file.judge_all(records, disk)
        observed = [records_file.judge_observation(record, disk) for record in observations]
        problem = None
        caught_up = judgement.of(records_file.WRITTEN) + judgement.of(records_file.VOID)
        seen_written = [item.record for item in observed if item.state == records_file.WRITTEN]
        if (caught_up or seen_written) and self.answers_writer:
            try:
                kept, observations = self._delete([item.record for item in caught_up],
                                                  seen_written)
            except (OSError, records_file.AnswersFileError) as error:
                problem = (f"{len(caught_up) + len(seen_written)} record(s) the documents have "
                           f"caught up with could not be deleted: {error}")
            else:
                judgement = records_file.judge_all(kept, disk)
                observed = [records_file.judge_observation(record, disk) for record in observations]
        effective = judgement.of(records_file.EFFECTIVE)
        answered = [item.record for item in effective if item.record["kind"] == records_file.ANSWER]
        # a record's entries stand or fall together; refusals come back per record
        overlaid, refused = records_file.overlay_records(disk, answered)
        unmatched = judgement.of(records_file.UNMATCHED)
        states: dict = {}
        in_effect, written_false, slots = [], set(), set()
        for item in effective:
            key = (item.record["table"], item.record["question"])
            if id(item.record) in refused:
                unmatched.append(records_file.Judged(
                    item.record, records_file.UNMATCHED, records_file.NOT_APPLIED, item.now,
                    f"{records_file.REASON_TEXT[records_file.NOT_APPLIED]}：{refused[id(item.record)]}",
                ))
                continue
            in_effect.append(item)
            if item.record["kind"] == records_file.ANSWER:
                states[key] = {"written": False}
                written_false.add(key)
                for slot in records_file.slot_names(item.record):
                    states[(item.record["table"], slot)] = {"written": False}
                    slots.add((item.record["table"], slot))
            else:
                states[key] = records_file.note_state(item.record)
        observations_effective = [item for item in observed if item.state == records_file.EFFECTIVE]
        # an observation is not overlaid: its slot is only listed as not written back
        slots.update((item.record["table"], item.record["target"]) for item in observations_effective)
        view = AnswersView(judgement=judgement, unmatched=unmatched, effective=in_effect,
                           overlaid=frozenset(written_false), slots=frozenset(slots),
                           problem=problem, observations=observations,
                           observations_effective=observations_effective,
                           observations_unmatched=[item for item in observed
                                                   if item.state == records_file.UNMATCHED])
        return Inputs(base.document, overlaid if disk is not None else None, disk, states, view)

    def _delete(self, stale: list[dict], stale_observations: list[dict] = ()) -> tuple[list, list]:
        """Delete ``stale`` records and ``stale_observations`` from the answers file -- read
        again under the lock, and only records still exactly as judged -- and return the
        records and observations left. The new file's signature is kept, so this write does
        not make the next request read it again."""
        current, observed = records_file.read_file(self.answers_path)
        kept = [record for record in current if record not in stale]
        seen = [record for record in observed if record not in stale_observations]
        if len(kept) != len(current) or len(seen) != len(observed):
            records_file.write_records(self.answers_path, kept, seen)
            self._answers_signature = _file_signature(self.answers_path)
        return kept, seen

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

    def _write(self, base: Inputs, records: list[dict],
               observations: list[dict] | None = None) -> None:
        """Replace the answers file; ``observations`` None keeps the ones standing."""
        if observations is None:
            observations = self._inputs.answers.live_observations()
        try:
            records_file.write_records(self.answers_path, records, observations)
        except OSError as error:
            raise AnswersUnavailable(f"the answers file cannot be written ({error})") from None
        self._answers_signature = _file_signature(self.answers_path)
        self._inputs = self._judged(base, records, observations)

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
            target = request.get("target")
            if target is not None:
                slot_base = self._structured_check(current, table, question, request)
            record = {"table": table, "question": question, "asked": request["asked"],
                      "base": disk, "kind": request["kind"]}
            if target is not None:
                record.update(target=target, value=request["value"], slot_base=slot_base)
            text_key = "answer" if request["kind"] == records_file.ANSWER else "reason"
            if request.get(text_key) is not None:
                record[text_key] = request[text_key]
            for key in ("choice", "to"):
                if request.get(key) is not None:
                    record[key] = request[key]
            source = dict(records_file.SOURCE)
            if request.get("probe_result") is not None:
                source = self._query_source(table, question, request)
            record.update(source=source, by=request["by"], date=self.today())
            problem = records_file.record_problem(record) if (
                target is not None or source != records_file.SOURCE) else None
            if problem:
                raise AnswerRefused(400, "bad_input", problem)
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
                and (target is None or records_file.slot_written(
                    current.disk_semantics.get(table), target, record["value"]))
            ):
                raise AnswerRefused(400, "bad_input", "the same as what is there now")
            records = [record if (r["table"], r["question"]) == (table, question) else r
                       for r in current.answers.live()]
            if existing is None:
                records.append(record)
            self._write(self._base, records)
            return record

    def _structured_check(self, current: Inputs, table: str, question: str, request: dict):
        """The disk's slot for a structured answer (its ``slot_base``), after the guards: the
        table must have what it names (400), the page must have seen the slot as it is
        overlaid now (409), and no other question's page answer may hold the slot (400)."""
        target, value = request["target"], request["value"]
        document = current.disk_semantics.get(table)
        problem = records_file.document_problem(document, target, value)
        if problem:
            raise AnswerRefused(400, "bad_input", problem)
        if request["seen"].get("slot") != records_file.slot_of(
                current.semantics.get(table), target, value):
            raise AnswerRefused(409, "changed", "what the page showed of the answered slot "
                                                "changed since; load it again")
        mine = set(records_file.slot_names({"target": target, "value": value}))
        for other in current.answers.live():
            if other["table"] != table or other["question"] == question:
                continue
            if mine & set(records_file.slot_names(other)):
                raise AnswerRefused(400, "bad_input", (
                    f"question {other['question']} already has a page answer on this slot; "
                    "withdraw it there first, or answer it in a sentence"))
        return records_file.slot_of(document, target, value)

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

    # ------------------------------------------------------------------ platform results

    def _require_probes(self) -> probes_file.ProbesFile:
        if self.probes is None:
            raise ProbesNotConfigured()
        return self.probes

    def _probe(self, probe) -> dict:
        try:
            item = self._require_probes().item(probe)
        except probes_file.ProbesError as error:
            raise AnswersUnavailable(error.message) from None
        if item is None:
            raise AnswerRefused(404, "not_found", f"no probe {probe} in the probes file")
        return item

    def probes_for(self, table: str, question: str | None = None) -> dict:
        """The probes of one table (one question), as the board shows them."""
        probes = self._require_probes()
        try:
            document, sha256 = probes.current()
            items = probes.items_for(table, question)
        except probes_file.ProbesError as error:
            raise AnswersUnavailable(error.message) from None
        disk = self.inputs().on_disk
        return {"table": bare_table(table), "sha256": sha256,
                "placeholders": document.get("placeholders") or {},
                "items": [probes_file.shown(item, (records_file.find_question(
                    disk, item["table"], item["question"]) or {}).get("text")) for item in items]}

    def probe_draft(self, probe: str, pasted: str, by: str = "-", date: str = "1970-01-01") -> dict:
        """What a pasted result gives -- ``draft`` (``{target, value, evidence}``) for an item
        that lands, ``evidence`` (the reference) for one that does not, or ``refused`` with
        the reason -- and ``pasted_sha256``. Nothing is written."""
        item = self._probe(probe)
        try:
            _, sha256 = self.probes.current()
        except probes_file.ProbesError as error:
            raise AnswersUnavailable(error.message) from None
        out = {"probe": probe, "table": bare_table(item["table"]), "question": item["question"],
               "lands": item.get("lands"), "pasted_sha256": probes_file.pasted_sha256(pasted)}
        try:
            result = probe_results.read_result(pasted)
        except probe_results.ResultRefused as error:
            return {**out, "refused": str(error)}
        if item.get("lands"):
            entry, reason = probe_results.draft_observation(item, result, sha256, by, date)
            if entry is None:
                return {**out, "refused": reason}
            return {**out, "draft": {key: entry[key] for key in ("target", "value", "evidence")}}
        reference, reason = probe_results.evidence_reference(item, result, sha256)
        return {**out, "refused": reason} if reference is None else {**out, "evidence": reference}

    def _query_source(self, table: str, question: str, request: dict) -> dict:
        """The ``source`` of a sentence answer backed by a query's pasted result."""
        pasted = request["probe_result"]
        item = self._probe(pasted["probe"])
        if (bare_table(item["table"]), item["question"]) != (table, question):
            raise AnswerRefused(400, "bad_input", f"probe {item['id']} is not about {question} "
                                                  f"of {table}")
        if item.get("lands"):
            raise AnswerRefused(400, "bad_input", (
                f"probe {item['id']} lands in {item['lands']}: confirm its result as an "
                "observation instead of backing a sentence with it"))
        drafted = self.probe_draft(pasted["probe"], pasted["pasted"])
        if "evidence" not in drafted:
            raise AnswerRefused(400, "bad_input", f"the pasted result: {drafted['refused']}")
        return {"kind": records_file.QUERY, **drafted["evidence"]}

    def confirm_observation(self, request: dict) -> dict:
        """Store one observation a person confirmed (``request``: probe, pasted, by, seen);
        the record stored. The pasted text is parsed again: 409 when the draft is not the
        one the page showed (``seen``), 400 when it gives none or the document on disk
        would refuse the entry."""
        with self._lock:
            current = self._require_answers()
            item = self._probe(request["probe"])
            if not item.get("lands"):
                raise AnswerRefused(400, "bad_input", f"probe {item['id']} lands nothing: back a "
                                                      "sentence answer with its result instead")
            drafted = self.probe_draft(request["probe"], request["pasted"], request["by"],
                                       self.today())
            if "draft" not in drafted:
                raise AnswerRefused(400, "bad_input", f"no draft: {drafted['refused']}")
            shown = {**drafted["draft"], "pasted_sha256": drafted["pasted_sha256"]}
            if request["seen"] != shown:
                raise AnswerRefused(409, "changed", "the draft is not the one the page showed (the "
                                                    "pasted text or the probes file changed); "
                                                    "preview it again")
            table, question = drafted["table"], drafted["question"]
            asked_now = records_file.find_question(current.disk_semantics, table, question)
            if asked_now is None:
                raise AnswerRefused(404, "not_found",
                                    f"no table-semantics question {question} of {table}")
            if records_file.folded(asked_now.get("text")) != records_file.folded(item["asked"]):
                raise AnswerRefused(400, "bad_input", (
                    f"{question} was rewritten after the query was written: the query may not "
                    "answer it any more; write the probes again"))
            entry = {"table": table, "target": drafted["draft"]["target"],
                     "value": drafted["draft"]["value"], "by": request["by"], "date": self.today()}
            applied = apply_confirmations({table: current.disk_semantics[table]}, [entry])
            if applied.unmatched:
                raise AnswerRefused(400, "bad_input", applied.unmatched[0]["reason"])
            record = {"probe": item["id"], "table": table, "question": question,
                      "asked": item["asked"], "target": entry["target"], "value": entry["value"],
                      "evidence": drafted["draft"]["evidence"],
                      "pasted_sha256": drafted["pasted_sha256"], "by": request["by"],
                      "date": self.today()}
            problem = records_file.observation_record_problem(record)
            if problem:
                raise AnswerRefused(400, "bad_input", problem)
            key = records_file.observation_key(record)
            observations = current.answers.live_observations()
            held = next((r for r in observations if records_file.observation_key(r) == key), None)
            if held is not None and (held["value"], held["evidence"]) == (
                    record["value"], record["evidence"]):
                raise AnswerRefused(400, "bad_input", "the same as what is there now")
            if records_file.observation_slot(current.disk_semantics[table], record) == record["value"]:
                raise AnswerRefused(400, "bad_input", "the document already holds this observation")
            observations = [r for r in observations if r is not held] + [record]
            self._write(self._base, current.answers.live(), observations)
            return record

    def withdraw_observation(self, seen) -> dict:
        """Delete one observation record, as the page saw it; the record deleted."""
        with self._lock:
            current = self._require_answers()
            observations = current.answers.live_observations()
            if not isinstance(seen, dict) or observation_key_or_none(seen) is None:
                raise AnswerRefused(404, "not_found", "no such observation")
            held = next((r for r in observations
                         if records_file.observation_key(r) == observation_key_or_none(seen)), None)
            if held is None:
                raise AnswerRefused(404, "not_found", "no such observation")
            if held != seen:
                raise AnswerRefused(409, "changed",
                                    "the observation changed since the page showed it; load it again")
            self._write(self._base, current.answers.live(),
                        [r for r in observations if r is not held])
            return held

    def export_answers(self) -> dict:
        """The ``semantic-confirmations/1`` file of the answers and observations in effect."""
        current = self.inputs()
        if current.answers is None:
            raise AnswersNotConfigured()
        return records_file.export_document(
            [item.record for item in current.answers.effective
             if item.record["kind"] == records_file.ANSWER],
            [item.record for item in current.answers.observations_effective],
        )

    def answers_summary(self, current: Inputs) -> dict:
        """What the board says about the answers: their status, the ones not matched, and
        the digest of each document the export answers (to check before writing back)."""
        view = current.answers
        summary = {"status": view.status}
        if view.reason:
            summary["reason"] = view.reason
        exported = sorted({item.record["table"] for item in view.effective
                           if item.record["kind"] == records_file.ANSWER}
                          | {item.record["table"] for item in view.observations_effective})
        summary.update(
            effective=len(view.effective),
            exported=sum(1 for item in view.effective
                         if item.record["kind"] == records_file.ANSWER),
            digests={table: document_digest(current.disk_semantics[table]) for table in exported},
            unmatched=[item.listing() for item in view.unmatched],
        )
        notes = records_file.export_notes([item.record for item in view.effective
                                           if item.record["kind"] == records_file.ANSWER])
        if notes:
            summary["export_notes"] = notes
        if view.observations_effective or view.observations_unmatched:
            summary["observations"] = {
                "effective": len(view.observations_effective),
                "records": [item.record for item in view.observations_effective],
                "unmatched": [item.listing() for item in view.observations_unmatched],
            }
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

    def pending_add_unless_recorded(self, **request) -> tuple[list[dict], dict | None]:
        """``(lines, None)`` after appending as ``pending_add`` does, or ``([], item)``
        without writing when ``request["missing"]`` names something the pending file
        already holds (``item`` as ``catalog pending list`` groups it). The check and the
        append happen under one lock, so two clicks cannot both write. A request by
        ``sql`` is appended as ``pending_add`` appends it."""
        path = self._require_pending()
        with self._pending_lock:
            missing = request.get("missing")
            if isinstance(missing, str) and missing.strip():
                item = answers.pending_recorded(str(path), missing)
                if item is not None:
                    return [], item
            return answers.pending_add(str(path), **request), None

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
            slots = sorted(slot for (name, slot) in current.answers.slots if name == key)
            if slots:
                answer.result["unwritten_slots"] = slots
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
            answer = answers.questions(current.document, current.semantics, text, **request)
            self._mark_probes(answer, current)
            return answer
        answer = answers.questions(
            current.document, current.semantics, text, page_states=current.page_states, **request
        )
        self._mark_probes(answer, current)
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

    def _mark_probes(self, answer: answers.CatalogAnswer, current: Inputs) -> None:
        """With a probes file, each semantics item of the board gains ``probes``: the
        queries written for its question (an empty list when none). A probes file that
        cannot be read now leaves the board as it is."""
        if self.probes is None:
            return
        try:
            self.probes.current()
        except probes_file.ProbesError:
            return
        for item in answer.result.get("items") or []:
            if item.get("source") != "semantics":
                continue
            question = records_file.find_question(current.on_disk, item.get("table"),
                                                  str(item.get("id")))
            item["probes"] = [probes_file.shown(probe, (question or {}).get("text"))
                              for probe in self.probes.items_for(item["table"], str(item["id"]))]

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
        if self.probes is not None:
            try:
                document, sha256 = self.probes.current()
                report["probes"] = {"path": _name(self.probes.path), "status": "ok",
                                    "items": len(document["items"]), "sha256": sha256}
            except probes_file.ProbesError as error:
                report["probes"] = {"path": _name(self.probes.path), "status": "unreadable",
                                    "reason": error.message}
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


class ProbesNotConfigured(Exception):
    """A probes request to a server started without a probes file."""

    message = ("this server was started without a probes file (--probes); the board shows no "
               "platform queries and takes no pasted results")


def observation_key_or_none(record) -> tuple | None:
    """The slot an observation record (as a page sent it back) holds, or None."""
    try:
        return records_file.observation_key(record)
    except (KeyError, TypeError, AttributeError):
        return None


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
