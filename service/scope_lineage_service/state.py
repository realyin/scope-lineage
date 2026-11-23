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
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path

from scope_lineage import cli_catalog_answers as answers


@dataclass(frozen=True)
class Inputs:
    document: dict
    semantics: dict | None


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
        self, ontology: str, semantics: str | None = None, pending: str | None = None
    ) -> None:
        self.ontology_path = Path(ontology)
        self.semantics_path = Path(semantics) if semantics else None
        self.pending_path = Path(pending) if pending else None
        self._lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._signature: tuple | None = None
        self._inputs: Inputs | None = None
        self.inputs()

    def _current_signature(self) -> tuple:
        semantics = (
            _directory_signature(self.semantics_path) if self.semantics_path else None
        )
        return (_file_signature(self.ontology_path), semantics)

    def inputs(self) -> Inputs:
        """The documents as they are on disk now; ``CatalogAnswerError`` when unreadable."""
        with self._lock:
            signature = self._current_signature()
            if self._inputs is None or signature != self._signature:
                self._inputs = None
                document = answers.load_ontology(str(self.ontology_path))
                semantics = answers.load_semantics(
                    str(self.semantics_path) if self.semantics_path else None
                )
                self._inputs = Inputs(document, semantics)
                self._signature = signature
            return self._inputs

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
        current = self.inputs()
        return answers.table_semantics(current.document, current.semantics, table)

    def questions(self, **request) -> answers.CatalogAnswer:
        """The board; the pending file joins it when one was given (absent yet: empty)."""
        current = self.inputs()
        text = None
        if self.pending_path is not None:
            text = (
                answers.read_pending_file(str(self.pending_path))
                if self.pending_path.is_file() else ""
            )
        return answers.questions(current.document, current.semantics, text, **request)

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
        report = {
            "status": status,
            "read_only": True,
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
        if problem:
            report["problem"] = problem
        return report


def _name(path) -> str:
    """The last component of a path: ``/health`` names a file or directory, never where it
    lives, so a server reachable off loopback does not tell callers the operator's layout."""
    return os.path.basename(os.path.normpath(str(path)))


class PendingNotConfigured(Exception):
    """A pending request to a server started without a pending file."""

    message = "this server was started without a pending file (--pending); nothing to list or add"
