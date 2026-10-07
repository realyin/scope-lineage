"""``semantic status``: where one table stands in a run, and which tables a step still needs.

A table moves through seven stages, each requiring the one before::

    no_packet -> packet -> drafted -> valid -> reviewed -> fixed -> rendered

- ``no_packet``: no ``packet.json`` for the table;
- ``packet``: a packet, no document;
- ``drafted``: a document that is ``invalid`` or ``packet_stale`` (flags below);
- ``valid``: the document meets its schema and fails no cross check (warnings allowed),
  and no review applies to it;
- ``reviewed``: a review with high or medium findings that the document still has to
  answer -- a review of this very document (its ``reviewed_doc_digest`` is the
  document's digest), or one whose fix changed the document without recording that it
  finished (``fix_unconfirmed``); or a review without front matter;
- ``fixed``: a review with no high or medium finding of this very document, or a fix
  record (``fixed_doc_digest``, written by ``semantic fixed``) for this very document;
- ``rendered``: fixed, and its page is not older than the document.

A valid document with a review is judged in this order, the first rule that holds wins
(``d`` the document's digest, ``dp`` its ``packet_digest``, which by now is the packet's):

0. the review read ``d``: ``reviewed`` with high or medium findings, else ``fixed``;
1. the review names its packet and it is not ``dp``: ``valid`` + ``review_packet_stale``;
2. the fix record is ``d``: ``fixed``, whatever the review found;
3. the review names no packet (written before the key existed): ``valid`` +
   ``review_stale`` -- a rewrite and a revision look the same without it, so it is
   reviewed again and never handed to a fix;
4. high or medium findings: ``reviewed`` + ``fix_unconfirmed``;
5. low findings only: ``valid`` + ``review_stale``.

Flags say what is wrong on the way: ``packet_stale`` (the document's ``packet_digest``
is not the packet's), ``invalid`` (a schema error, an unreadable file, or a failed cross
check other than the digest one), ``review_packet_stale`` (the review read another
packet: review the document again), ``review_stale`` (the document changed after the
review and nothing ties the change to it: review again), ``fix_unconfirmed`` (the
document changed after a review that asked for changes, with no fix record for this
version: fix again), ``review_unparsed`` (a review without complete front matter: it
counts as ``reviewed`` but no step takes it further) and ``render_stale`` (fixed, and its
page is older than the document). ``doc_misfiled`` only warns, at any stage: a document
file is named for another table than the one it holds (both tables are flagged: the one
named by the file looks unwritten), or two files hold the table (the first by path is
read).

The command line reads the files; this module is plain data in, plain data out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .digests import document_digest
from .review_notes import parse_review
from .validate import check_file

STATUS_FORMAT = "table-semantics-status/2"
NEXT_FORMAT = "table-semantics-next/1"
STAGES = ("no_packet", "packet", "drafted", "valid", "reviewed", "fixed", "rendered")
FLAGS = (
    "packet_stale", "invalid", "review_packet_stale", "review_stale", "fix_unconfirmed",
    "review_unparsed", "render_stale", "doc_misfiled",
)
STEPS = ("draft", "review", "fix", "render")

_MISSING = object()


@dataclass(frozen=True)
class TableFiles:
    """What a run holds for one table, read but not judged.

    ``document`` is the parsed JSON, or ``_MISSING`` with no file; ``unreadable`` says
    why a file that exists could not be parsed. ``review`` is the review's text;
    ``page_fresh`` is None without a page, else whether it is not older than the document.
    ``misfiled``: a document file of the run is named for another table than the one it
    holds, and this table is one of the two; or two files hold this table.
    """

    table: str
    packet: Optional[dict] = None
    document: object = _MISSING
    file: str = ""
    unreadable: Optional[str] = None
    review: Optional[str] = None
    page_fresh: Optional[bool] = None
    misfiled: bool = False

    @property
    def has_document(self) -> bool:
        return self.document is not _MISSING or self.unreadable is not None


def table_status(files: TableFiles) -> dict:
    """The status entry of one table; ``doc_misfiled`` warns whatever the stage."""
    entry = _staged(files)
    if files.misfiled:
        entry["flags"].append("doc_misfiled")
    return entry


def _staged(files: TableFiles) -> dict:
    packet, document = files.packet, files.document
    readable = files.document is not _MISSING and files.unreadable is None
    entry: dict = {
        "table": files.table,
        "stage": "no_packet",
        "flags": [],
        "packet_digest": packet.get("packet_digest") if packet else None,
        "doc_digest": document_digest(document) if readable else None,
        "doc_packet_digest": document.get("packet_digest") if isinstance(document, dict) else None,
        "schema_errors": 0,
        "failures": 0,
        "review": parse_review(files.review) if files.review is not None else None,
    }
    if packet is None:
        return entry
    if not files.has_document:
        return {**entry, "stage": "packet"}
    report = check_file(document if readable else None, packet, files.file,
                        unreadable=files.unreadable)
    failures = [item for item in report["failures"]
                if item["status"] == "fail" and item["check"] != "digest"]
    entry.update(schema_errors=len(report["schema_errors"]), failures=len(failures))
    if isinstance(entry["doc_packet_digest"], str) and entry["doc_packet_digest"] != entry[
        "packet_digest"
    ]:
        entry["flags"].append("packet_stale")
    if report["schema_errors"] or failures:
        entry["flags"].append("invalid")
    if entry["flags"]:
        return {**entry, "stage": "drafted"}
    return _reviewed(entry, files)


def _reviewed(entry: dict, files: TableFiles) -> dict:
    """The stage of a valid document: its review, then its page."""
    review = entry["review"]
    if files.review is None:
        return {**entry, "stage": "valid"}
    if review is None:
        return {**entry, "stage": "reviewed", "flags": ["review_unparsed"]}
    stage, flag = review_verdict(review, entry["doc_digest"], entry["doc_packet_digest"])
    if flag:
        entry["flags"].append(flag)
    if stage == "fixed" and files.page_fresh is not None:
        if files.page_fresh:
            stage = "rendered"
        else:
            entry["flags"].append("render_stale")
    return {**entry, "stage": stage}


def review_verdict(review: dict, doc_digest, doc_packet_digest) -> tuple[str, str | None]:
    """The stage and flag a parsed review gives a valid document (rules 0-5 above)."""
    serious = review["high"] + review["medium"]
    packet = review["reviewed_packet_digest"]
    if review["reviewed_doc_digest"] == doc_digest:
        return ("reviewed" if serious else "fixed"), None
    if packet is not None and packet != doc_packet_digest:
        return "valid", "review_packet_stale"
    if review["fixed_doc_digest"] == doc_digest:
        return "fixed", None
    if packet is None or not serious:
        return "valid", "review_stale"
    return "reviewed", "fix_unconfirmed"


def status_report(entries: list[dict], directories: dict) -> dict:
    """The ``--json`` document: every table's entry, the stage counts, the flagged tables."""
    return {
        "doc_format": STATUS_FORMAT,
        "directories": directories,
        "tables": entries,
        "summary": {
            "tables": len(entries),
            "stages": {stage: sum(1 for e in entries if e["stage"] == stage) for stage in STAGES},
            "flags": {
                flag: [e["table"] for e in entries if flag in e["flags"]] for flag in FLAGS
            },
        },
    }


def render_status_text(report: dict) -> str:
    """One line of stage counts, one line per table (stage, flags), one line per flag."""
    summary = report["summary"]
    counts = ", ".join(f"{stage} {count}" for stage, count in summary["stages"].items())
    lines = [f"Status of {summary['tables']} table(s): {counts}"]
    width = max((len(entry["table"]) for entry in report["tables"]), default=0)
    lines += [
        f"  {entry['table']:<{width}}  {' '.join([entry['stage'], *entry['flags']])}"
        for entry in report["tables"]
    ]
    lines += [
        f"  {flag}: {', '.join(tables)}" for flag, tables in summary["flags"].items() if tables
    ]
    return "\n".join(lines) + "\n"


def needs_step(entry: dict, step: str) -> bool:
    """Whether ``step`` is the next thing to do for this table.

    ``draft`` writes or rewrites a document (``packet`` and ``drafted``: no document, a
    stale one, an invalid one); ``review`` reviews a ``valid`` one; ``fix`` revises a
    ``reviewed`` one whose review has front matter; ``render`` renders a ``fixed`` one.
    """
    stage = entry["stage"]
    if step == "draft":
        return stage in ("packet", "drafted")
    if step == "review":
        return stage == "valid"
    if step == "fix":
        return stage == "reviewed" and "review_unparsed" not in entry["flags"]
    return stage == "fixed"


def next_batches(entries: list[dict], step: str, size: int) -> dict:
    """The tables ``step`` still needs, in name order, ``size`` to a batch."""
    tables = sorted(entry["table"] for entry in entries if needs_step(entry, step))
    return {
        "doc_format": NEXT_FORMAT,
        "step": step,
        "batches": [tables[i:i + size] for i in range(0, len(tables), size)],
    }
