"""The ``question-probes/1`` file a server shows on the questions board (``--probes``).

Read-only: the server never writes it and never runs a query. It is read at start (a file
that cannot be read, or is not ``question-probes/1``, stops the start) and again whenever
its size, modification time or inode change, so the sha256 a draft cites is always that
of the file as it is now. A pasted result is turned into a draft or an evidence reference
by the core (``scope_lineage.semantics.probe_results``); this module only finds the item
and says what the board shows of it.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from scope_lineage.semantics.names import bare_table
from scope_lineage.semantics.names import folded_text as folded
from scope_lineage.semantics.schema import PROBES_FORMAT, schema_errors

MAX_PASTE = 64 * 1024  # characters of a pasted result
# what the board shows of an item: enough to run the query and read its result
SHOWN = ("id", "part", "ask", "class", "shape", "sql", "engine", "partitions", "full_scan",
         "filter", "lands", "how_to_read", "note")


class ProbesError(Exception):
    """The probes file cannot be read, or is not ``question-probes/1``."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ProbesFile:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._signature: tuple | None = None
        self._document: dict = {}
        self._sha256 = ""
        self.current()

    def current(self) -> tuple[dict, str]:
        """``(document, sha256 of its bytes)``, read again when the file changed."""
        with self._lock:
            try:
                stat = self.path.stat()
            except OSError as error:
                raise ProbesError(f"the probes file cannot be read ({error})") from None
            signature = (stat.st_size, stat.st_mtime_ns, stat.st_ino)
            if signature != self._signature:
                self._document, self._sha256 = _read(self.path)
                self._signature = signature
            return self._document, self._sha256

    def item(self, probe: str) -> dict | None:
        document, _ = self.current()
        return next((item for item in document["items"] if item["id"] == probe), None)

    def items_for(self, table: str, question: str | None = None) -> list[dict]:
        document, _ = self.current()
        table = bare_table(table)
        return [item for item in document["items"] if bare_table(item["table"]) == table
                and (question is None or item["question"] == question)]


def _read(path: Path) -> tuple[dict, str]:
    try:
        raw = path.read_bytes()
        document = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise ProbesError(f"the probes file cannot be read ({error})") from None
    errors = schema_errors(document, PROBES_FORMAT)
    if errors:
        raise ProbesError(f"the probes file is not {PROBES_FORMAT} ({errors[0]['at']}: "
                          f"{errors[0]['message']})")
    return document, hashlib.sha256(raw).hexdigest()


def shown(item: dict, question_text: str | None) -> dict:
    """What the board shows of an item, and ``stale`` when its question no longer reads as
    the item asked it (the query may be out of date)."""
    out = {key: item[key] for key in SHOWN if key in item}
    out["stale"] = question_text is None or folded(question_text) != folded(item["asked"])
    return out


def pasted_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
