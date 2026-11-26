"""``--ask-store DIR``: every conversation's full record on disk, so it survives a restart.

Off unless the option names a directory; there is no default place (the record holds the
asker's words, pasted SQL and pasted results, and the catalog directory is often in a
repository or on a shared drive). The directory is created with mode 0700; each conversation
is one file, ``DIR/<conversation id>.json``, mode 0600, rewritten whole after every change
through a temporary file and ``os.replace`` (a crash leaves the old or the new file, never half).

The file (``schema: "ask-store/1"``) holds ``conversation``, ``created``, ``updated``, the
state card's state (``memory.py``) and ``turns``: per question its number, ``status``,
``question``, ``answer`` (the text shown, guard lines included), ``segments`` (every SQL block
with its role and the version code gave the current one), ``block`` (the parsed increment
block), ``block_status``, ``topic``, ``card_after`` (the card the next question carries),
``tools`` (each call's name and arguments, never the result text), ``model``, ``started`` and
``finished``. At most ``MAX_TURNS`` questions a conversation.

A file of another schema version is read but never written: the conversation can be shown
and recalled, not continued. A question still ``running`` when the file is read (the server
stopped mid-answer) is marked ``interrupted``; it never updated the card.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
from pathlib import Path

LOG = logging.getLogger(__name__)
SCHEMA = "ask-store/1"
MAX_TURNS = 200
_SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


class Store:
    """The conversation files under ``directory`` (created, mode 0700, when missing)."""

    def __init__(self, directory: str | os.PathLike) -> None:
        self.directory = Path(directory)
        if not self.directory.exists():
            self.directory.mkdir(parents=True, mode=0o700)
            os.chmod(self.directory, 0o700)
        elif not self.directory.is_dir():
            raise NotADirectoryError(f"{directory} is not a directory")
        self._lock = threading.Lock()

    def path(self, conversation_id: str) -> Path | None:
        if not _SAFE_ID.fullmatch(conversation_id or ""):
            return None
        return self.directory / f"{conversation_id}.json"

    def save(self, document: dict) -> None:
        """Write one conversation's document whole (atomic); a failure is logged, not raised."""
        path = self.path(document.get("conversation", ""))
        if path is None:
            LOG.warning("ask store: not a conversation id, nothing written")
            return
        data = json.dumps({**document, "schema": SCHEMA}, ensure_ascii=False, indent=1).encode("utf-8")
        try:
            with self._lock:
                fd, temporary = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=self.directory)
                try:
                    os.fchmod(fd, 0o600)
                    view = memoryview(data)
                    while view:
                        view = view[os.write(fd, view):]
                    os.fsync(fd)
                finally:
                    os.close(fd)
                try:
                    os.replace(temporary, path)
                except BaseException:
                    os.unlink(temporary)
                    raise
        except OSError as error:
            LOG.warning("ask store: could not write %s: %s", path.name, error)

    def load(self, conversation_id: str) -> dict | None:
        """The conversation's document, or None when there is no such file (or it is
        unreadable, which is logged). ``read_only`` is true for another schema version;
        a ``running`` question is marked ``interrupted`` (and written back when writable)."""
        path = self.path(conversation_id)
        if path is None or not path.is_file():
            return None
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            LOG.warning("ask store: could not read %s: %s", path.name, error)
            return None
        if not isinstance(document, dict) or document.get("conversation") != conversation_id:
            LOG.warning("ask store: %s is not this conversation's record", path.name)
            return None
        read_only = document.get("schema") != SCHEMA
        changed = False
        for turn in document.get("turns") or []:
            if isinstance(turn, dict) and turn.get("status") == "running":
                turn["status"] = "interrupted"
                changed = True
        document["read_only"] = read_only
        if changed and not read_only:
            self.save({key: value for key, value in document.items() if key != "read_only"})
        return document
