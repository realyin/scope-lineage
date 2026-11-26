"""``--ask-trace DIR``: a read-only record of every question run, one JSON line at a time.

Off unless the option names a directory (there is no default place: the record holds the
asker's words and the answers, and the catalog directory is often in a repository or on a
shared drive). Each conversation appends to ``DIR/<conversation id>.jsonl`` (mode 0600),
one ``os.write`` per line on a file opened for appending, so a crash leaves whole lines.

The record is built from the run's own events (``Run.emit``) and two notes the events do
not carry (``Run.note``: the message list sent before each model turn, and the size of each
tool result's text). Three kinds of line, each with ``schema: "ask-trace/1"``, ``kind``,
``at`` (UTC), ``conversation`` and ``run``:

- ``turn``: ``turn``, ``model_id`` (the server's id), ``model`` (what the provider said),
  ``elapsed`` (seconds of that request), ``stop_reason``, ``usage`` (the four token counts)
  and ``usage_estimated``, ``request_chars`` (characters of the message list sent, as JSON),
  ``largest_tool_result_chars`` and ``tool_results`` (the tool_result blocks in that list).
- ``tool``: ``turn``, ``id``, ``name``, ``input`` (the arguments), ``ok``, ``result_chars``
  -- never the result's text, which is catalog text.
- ``run`` (when it finishes): ``model_id``, ``question``, ``follow_up``, ``status``,
  ``reason``, ``error_kind`` and ``error_message`` (the first 300 characters; errors only),
  ``answer`` (its text, or null), ``has_sql``, ``has_brief``, ``brief_missing``, ``elapsed``,
  ``turns``, ``tool_calls``, ``usage`` and ``usage_estimated``.

No key, header, system prompt or tool result text is written. Writing never raises into
the run: a failure is logged as a warning and the question goes on.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from .loop import USAGE_FIELDS, Run

LOG = logging.getLogger(__name__)
SCHEMA = "ask-trace/1"
MAX_ERROR_CHARS = 300
_SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


class Tracer:
    """Appends the trace lines of every run under ``directory`` (created if missing)."""

    def __init__(self, directory: str | os.PathLike) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock = threading.Lock()

    def observer(self, conversation_id: str, run: Run) -> RunTrace:
        return RunTrace(self, conversation_id, run)

    def write(self, conversation_id: str, record: dict) -> None:
        if not _SAFE_ID.fullmatch(conversation_id):
            LOG.warning("ask trace: not a conversation id, nothing written")
            return
        try:
            line = (json.dumps(record, ensure_ascii=False, default=str) + "\n").encode("utf-8")
            path = self.directory / f"{conversation_id}.jsonl"
            with self._lock:
                fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
                try:
                    view = memoryview(line)
                    while view:
                        view = view[os.write(fd, view):]
                finally:
                    os.close(fd)
        except Exception as error:  # noqa: BLE001 -- recording never stops the run
            LOG.warning("ask trace: could not write a line: %s", error)


def _tool_results(messages: list) -> list:
    return [block for message in messages if isinstance(message.get("content"), list)
            for block in message["content"]
            if isinstance(block, dict) and block.get("type") == "tool_result"]


def _chars(content) -> int:
    return len(content) if isinstance(content, str) else len(json.dumps(content, ensure_ascii=False))


class RunTrace:
    """One run's observer (``Run.observer``): turns events and notes into trace lines."""

    def __init__(self, tracer: Tracer, conversation_id: str, run: Run) -> None:
        self.tracer, self.conversation_id, self.run = tracer, conversation_id, run
        self.request: dict = {}
        self.turn = self.turns = self.tool_calls = 0
        self.calls: dict = {}
        self.outputs: dict = {}
        self.question: dict = {}
        self.answer: dict | None = None

    def __call__(self, item: dict) -> None:
        handler = getattr(self, "_on_" + str(item.get("type")), None)
        if handler is not None:
            handler(item)

    def _write(self, kind: str, **data) -> None:
        self.tracer.write(self.conversation_id, {
            "schema": SCHEMA, "kind": kind,
            "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "conversation": self.conversation_id, "run": self.run.id, **data,
        })

    # ------------------------------------------------------------------ notes and events

    def _on_started(self, event: dict) -> None:
        self.question = {"question": event.get("question"), "follow_up": event.get("follow_up")}

    def _on_request(self, note: dict) -> None:
        messages = note.get("messages") or []
        results = _tool_results(messages)
        self.request = {
            "started": self.run.clock(),
            "request_chars": len(json.dumps(messages, ensure_ascii=False, default=str)),
            "largest_tool_result_chars": max((_chars(b.get("content", "")) for b in results), default=0),
            "tool_results": len(results),
        }

    def _on_turn(self, event: dict) -> None:
        self.turn = event.get("turn") or self.turn
        self.turns += 1
        request = self.request
        started = request.get("started")
        self._write(
            "turn", turn=self.turn, model_id=self.run.model_id, model=event.get("model"),
            elapsed=None if started is None else round(self.run.clock() - started, 3),
            stop_reason=event.get("stop_reason"), usage=event.get("usage"),
            usage_estimated=bool(event.get("usage_estimated")),
            request_chars=request.get("request_chars"),
            largest_tool_result_chars=request.get("largest_tool_result_chars"),
            tool_results=request.get("tool_results"),
        )
        self.request = {}

    def _on_tool_call(self, event: dict) -> None:
        self.calls[event.get("id")] = event

    def _on_tool_output(self, note: dict) -> None:
        self.outputs[note.get("id")] = note.get("chars")

    def _on_tool_result(self, event: dict) -> None:
        call = self.calls.pop(event.get("id"), {})
        self.tool_calls += 1
        self._write("tool", turn=self.turn, id=event.get("id"), name=event.get("name"),
                    input=call.get("input"), ok=bool(event.get("ok")),
                    result_chars=self.outputs.pop(event.get("id"), None))

    def _on_answer(self, event: dict) -> None:
        self.answer = event

    def _on_finished(self, event: dict) -> None:
        status = event.get("status")
        usage = event.get("usage") or {}
        answer = self.answer or {}
        error = status == "error"
        detail = event.get("detail")
        self._write(
            "run", model_id=self.run.model_id, **self.question, status=status,
            reason=event.get("reason"), error_kind=event.get("reason") if error else None,
            error_message=str(detail)[:MAX_ERROR_CHARS] if error and detail is not None else None,
            answer=answer.get("text"), has_sql=bool(answer.get("sql")),
            has_brief=bool(answer) and not answer.get("brief_missing"),
            brief_missing=answer.get("brief_missing"),
            elapsed=round(self.run.clock() - self.run.started, 3),
            turns=usage.get("turns", self.turns), tool_calls=usage.get("tool_calls", self.tool_calls),
            usage={name: usage.get(name, 0) for name in USAGE_FIELDS},
            usage_estimated=bool(usage.get("estimated")),
        )
