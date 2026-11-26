"""Conversations and runs for the ask endpoints, in server memory only.

A conversation is keyed by an unguessable id (``secrets.token_urlsafe``) and holds its
questions' runs and the brief the next question carries. It lives in this process: a
restart loses it, and so does a conversation idle longer than the age limit, or the
least recently used idle one when the count limit is reached. One question runs at a
time per conversation, on its own thread; a cancel stops it at the next model event or
before the next tool call. The page polls a run's events (``events``), waiting on the
run for the next one, so it sees each step as it happens.

The service holds a set of models (``models.ModelSet``): one from ``--ask-model``, or the
list from ``--ask-models``. A question names the model by id (none: the default); a
follow-up may name another one. A model whose provider refuses its credentials is taken
out of the set for the rest of the process; the others keep answering.

With ``trace`` (``--ask-trace DIR``, a ``trace.Tracer``) every run is recorded as it goes,
read-only: the run, its events and its answer are the same with or without it.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from .loop import Limits, Model, Run, run_question
from .models import ModelEntry, ModelSet
from .tools import ToolBox
from .walk import system_blocks

MAX_QUESTION_CHARS = 4000
MAX_RUNS_KEPT = 20
MAX_WAIT = 25.0


class AskError(Exception):
    """A request the ask service refuses: ``status`` and ``kind`` for the HTTP answer."""

    def __init__(self, status: int, kind: str, message: str) -> None:
        super().__init__(message)
        self.status, self.kind, self.message = status, kind, message


@dataclass
class Conversation:
    id: str
    created: float
    used: float
    brief: str | None = None
    runs: list = field(default_factory=list)

    @property
    def running(self) -> Run | None:
        return next((run for run in self.runs if not run.done), None)


class AskService:
    """Asking over one catalog with one model (``model``, None when it cannot work and
    ``reason`` says why) or several (``models``). When no model can answer, the browse page
    and every other endpoint keep working."""

    def __init__(
        self,
        tools: ToolBox,
        model: Model | None = None,
        *,
        reason: str | None = None,
        models: ModelSet | None = None,
        limits: Limits = Limits(),
        max_conversations: int = 20,
        max_idle_seconds: float = 3600.0,
        clock: Callable[[], float] = time.monotonic,
        trace=None,
    ) -> None:
        self.tools = tools
        self.models = models if models is not None else ModelSet.single(model, reason)
        self.limits = limits
        self.max_conversations = max_conversations
        self.max_idle_seconds = max_idle_seconds
        self.clock = clock
        self.trace = trace
        self.system = system_blocks(tools.pending)
        self._lock = threading.Lock()
        self._conversations: dict[str, Conversation] = {}

    # ------------------------------------------------------------------ status

    @property
    def model(self) -> Model | None:
        """The default model (what a question without a model id gets)."""
        return self.models.default.model

    @property
    def reason(self) -> str | None:
        return self.models.reason

    def status(self) -> dict:
        model = self.model
        return {
            "available": self.models.available,
            "reason": self.models.reason,
            "fake": self.models.fake,
            # the default model, as before several models could be listed
            "model": getattr(model, "name", None),
            "effort": getattr(model, "effort", None),
            "fallback": getattr(model, "fallback", None),
            "default": self.models.default_id,
            "models": self.models.public(),
            "pending": self.tools.pending,
            "executes_sql": False,
            "limits": self.limits.as_dict(),
            "conversations": {
                "max": self.max_conversations, "max_idle_seconds": self.max_idle_seconds,
                "kept_in_memory": True,
            },
        }

    # ------------------------------------------------------------------ asking

    def ask(self, question: str, conversation_id: str | None = None,
            model_id: str | None = None) -> tuple[Conversation, Run]:
        if not self.models.available:
            raise AskError(503, "ask_unavailable", self.models.reason or "asking is not available")
        try:
            entry = self.models.resolve(model_id)
        except LookupError:
            raise AskError(400, "unknown_model", f"no model {model_id!r} on this server; "
                                                 "GET /api/ask/status lists them") from None
        except ValueError as unavailable:
            raise AskError(409, "model_unavailable",
                           f"model {model_id!r} cannot answer now: {unavailable}") from None
        question = question.strip()
        if not question:
            raise AskError(400, "bad_input", "question is empty")
        if len(question) > MAX_QUESTION_CHARS:
            raise AskError(400, "bad_input", f"question is longer than {MAX_QUESTION_CHARS} characters")
        with self._lock:
            if conversation_id is None:
                self._expire()
                conversation = self._new_conversation()
            else:
                conversation = self._get(conversation_id)
            if conversation.running is not None:
                raise AskError(409, "busy", "a question is still running in this conversation; "
                                            "wait for it or cancel it")
            run = Run(secrets.token_urlsafe(12), question, conversation.brief,
                      model_id=entry.id, model_label=entry.label, clock=self.clock)
            if self.trace is not None:
                run.observer = self.trace.observer(conversation.id, run)
            conversation.runs.append(run)
            del conversation.runs[:-MAX_RUNS_KEPT]
            conversation.used = self.clock()
        thread = threading.Thread(target=self._answer, args=(conversation, run, entry), daemon=True,
                                  name=f"ask-{run.id}")
        thread.start()
        return conversation, run

    def _answer(self, conversation: Conversation, run: Run, entry: ModelEntry) -> None:
        try:
            run_question(run, entry.model, self.tools, self.system, self.limits)
        except Exception as error:  # noqa: BLE001 -- a bug must still end the run for the page
            if not run.done:
                run.finish("error", reason="internal", detail=f"{type(error).__name__}: {error}",
                           usage=None)
        with self._lock:
            conversation.used = self.clock()
            if run.answer is not None:
                conversation.brief = run.answer["brief"]
        last = run.events[-1] if run.events else {}
        if last.get("reason") == "credentials":
            self.models.mark_unavailable(
                entry.id, f"the model provider refused the credentials: {last.get('detail')}")

    def events(self, conversation_id: str, run_id: str, after: int, wait: float) -> dict:
        with self._lock:
            run = self._run(conversation_id, run_id)
        events, done = run.wait_events(max(0, after), min(max(0.0, wait), MAX_WAIT))
        return {"run": run.id, "status": run.status, "done": done, "events": events,
                "next": after + len(events)}

    def cancel(self, conversation_id: str) -> dict:
        with self._lock:
            conversation = self._get(conversation_id)
            run = conversation.running
        if run is None:
            return {"conversation": conversation_id, "cancelled": None}
        run.cancel()
        return {"conversation": conversation_id, "cancelled": run.id}

    def conversation(self, conversation_id: str) -> dict:
        with self._lock:
            conversation = self._get(conversation_id)
            return {
                "conversation": conversation.id,
                "brief": conversation.brief,
                "runs": [{"run": run.id, "question": run.question, "status": run.status,
                          "follow_up": bool(run.brief), "model": run.model_id,
                          "model_label": run.model_label} for run in conversation.runs],
            }

    # ------------------------------------------------------------------ the store

    def _new_conversation(self) -> Conversation:
        if len(self._conversations) >= self.max_conversations:
            idle = [c for c in self._conversations.values() if c.running is None]
            if not idle:
                raise AskError(503, "too_many_conversations",
                               "every conversation this server keeps is answering a question")
            oldest = min(idle, key=lambda c: c.used)
            del self._conversations[oldest.id]
        now = self.clock()
        conversation = Conversation(secrets.token_urlsafe(24), now, now)
        self._conversations[conversation.id] = conversation
        return conversation

    def _get(self, conversation_id: str) -> Conversation:
        self._expire()
        conversation = self._conversations.get(conversation_id or "")
        if conversation is None:
            raise AskError(404, "conversation_gone",
                           "no such conversation: it expired, or the server restarted "
                           "(conversations live in server memory only)")
        return conversation

    def _run(self, conversation_id: str, run_id: str) -> Run:
        conversation = self._get(conversation_id)
        run = next((run for run in conversation.runs if run.id == run_id), None)
        if run is None:
            raise AskError(404, "run_gone", "no such run in this conversation")
        return run

    def _expire(self) -> None:
        now = self.clock()
        for conversation in list(self._conversations.values()):
            if conversation.running is None and now - conversation.used > self.max_idle_seconds:
                del self._conversations[conversation.id]
