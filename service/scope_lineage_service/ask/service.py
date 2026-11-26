"""Conversations and runs for the ask endpoints, in server memory (and on disk with a store).

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

Memory (``memory.py``): every question's message starts with today's date (``now``, read
for each question; ``--ask-today`` fixes it for tests) and the conversation's state card,
which replaces the previous question's brief. The finished answer updates the card (only
when the run ends ``done``), and the guard's and the budget's lines are added to the answer
shown. Each question is a numbered turn; the model has a ``recall`` tool bound to this
conversation that returns an earlier turn from the record. With ``store`` (``--ask-store
DIR``, a ``store.Store``) the record is written to disk after every change, so a
conversation dropped from memory or lost in a restart is read back when its id is next used
(a question running at the restart is ``interrupted`` and never touches the card). Without
it the record lives in memory, as conversations always did. At most ``MAX_TURNS`` questions
a conversation.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from scope_lineage.cli_catalog_answers import CatalogAnswerError

from . import memory
from .loop import Limits, Model, Run, run_question
from .models import ModelEntry, ModelSet
from .store import MAX_TURNS, Store
from .tools import ConversationTools, ToolBox
from .walk import system_blocks

LOG = logging.getLogger(__name__)

# Long enough for a pasted SQL to review or fix; a longer paste is refused (400) and the
# page asks for it in parts.
MAX_QUESTION_CHARS = 20_000
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
    # the full record: one dict a question (see store.py), and the state card's state
    turns: list = field(default_factory=list)
    state: dict = field(default_factory=memory.new_state)
    started_at: str | None = None
    read_only: bool = False

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
        now: Callable[[], datetime] | None = None,
        card_budget: int = memory.DEFAULT_CARD_BUDGET,
        store: Store | None = None,
    ) -> None:
        self.tools = tools
        self.models = models if models is not None else ModelSet.single(model, reason)
        self.limits = limits
        self.max_conversations = max_conversations
        self.max_idle_seconds = max_idle_seconds
        self.clock = clock
        self.trace = trace
        self.now = now or (lambda: datetime.now().astimezone())
        self.card_budget = card_budget
        self.store = store
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
            "max_question_chars": MAX_QUESTION_CHARS,
            "limits": self.limits.as_dict(),
            "conversations": {
                "max": self.max_conversations, "max_idle_seconds": self.max_idle_seconds,
                "kept_in_memory": self.store is None, "stored": self.store is not None,
                "max_turns": MAX_TURNS, "card_budget": self.card_budget,
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
            raise AskError(400, "bad_input", f"question is longer than {MAX_QUESTION_CHARS} characters; "
                           "send it in parts (请分段贴)")
        with self._lock:
            if conversation_id is None:
                self._expire()
                conversation = self._new_conversation()
            else:
                conversation = self._get(conversation_id)
            if conversation.read_only:
                raise AskError(409, "read_only", "this conversation's record has an older format: "
                                                 "it can be read, not continued; start a new one")
            if conversation.running is not None:
                raise AskError(409, "busy", "a question is still running in this conversation; "
                                            "wait for it or cancel it")
            if len(conversation.turns) >= MAX_TURNS:
                raise AskError(409, "conversation_full", f"this conversation has {MAX_TURNS} questions, "
                                                         "the most one keeps; start a new one")
            number = len(conversation.turns) + 1
            now = self.now()
            catalog = memory.catalog_version(self.tools.state.ontology_path)
            card = memory.render_card(conversation.state, turn=number, catalog=catalog)
            run = Run(secrets.token_urlsafe(12), question, conversation.brief,
                      model_id=entry.id, model_label=entry.label, clock=self.clock,
                      prelude=memory.today_line(now) + "\n" + card)
            if self.trace is not None:
                run.observer = self.trace.observer(conversation.id, run)
            record = {"turn": number, "run": run.id, "status": "running", "question": question,
                      "model": entry.id, "today": now.date().isoformat(), "started": now.isoformat(),
                      "card_chars": len(card)}
            run.on_answer = self._memory_hook(conversation, run, record, catalog, len(card))
            conversation.turns.append(record)
            conversation.runs.append(run)
            del conversation.runs[:-MAX_RUNS_KEPT]
            conversation.used = self.clock()
            self._save(conversation)
        tools = ConversationTools(self.tools, self._recall_for(conversation))
        thread = threading.Thread(target=self._answer, args=(conversation, run, entry, tools, record),
                                  daemon=True, name=f"ask-{run.id}")
        thread.start()
        return conversation, run

    def _answer(self, conversation: Conversation, run: Run, entry: ModelEntry,
                tools: ConversationTools, record: dict) -> None:
        try:
            run_question(run, entry.model, tools, self.system, self.limits)
        except Exception as error:  # noqa: BLE001 -- a bug must still end the run for the page
            if not run.done:
                run.finish("error", reason="internal", detail=f"{type(error).__name__}: {error}",
                           usage=None)
        with self._lock:
            conversation.used = self.clock()
            if run.answer is not None:
                conversation.brief = run.answer["brief"]
            self._finish_record(conversation, run, record)
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
                "turns": [_turn_summary(item) for item in conversation.turns],
                "memory": memory.view(conversation.state),
                "read_only": conversation.read_only,
                "stored": self.store is not None,
            }

    # ------------------------------------------------------------------ memory

    def _check(self, sql: str) -> tuple:
        try:
            return self.tools.state.check_sql(sql).result, None
        except CatalogAnswerError as error:
            return None, error.message
        except Exception as error:  # noqa: BLE001 -- a refused check is a card line, not a crash
            return None, f"{type(error).__name__}: {error}"

    def _memory_hook(self, conversation: Conversation, run: Run, record: dict, catalog: str,
                     card_chars: int):
        """What the loop calls with the finished answer: the card's next state (kept on the
        run, committed only when the run ends ``done``) and what the answer shows."""
        number = record["turn"]

        def hook(text: str, segments: list) -> dict:
            with self._lock:
                messages = {item["turn"]: item["question"] for item in conversation.turns}
                state = conversation.state
            outcome = memory.apply_turn(state, turn=number, question=record["question"], answer=text,
                                        segments=segments, user_messages=messages, check=self._check,
                                        catalog=catalog)
            state, archived, card_next = memory.compact(outcome["state"], turn=number + 1,
                                                        budget=self.card_budget)
            notices = list(outcome["guard"])
            if outcome["statements_over"]:
                notices.append(outcome["statements_over"])
            archived_line = memory.archive_notice(state, archived)
            if archived_line:
                notices.append(archived_line)
            if state.get("missing_streak", 0) >= 2:
                notices.append(f"（连续 {state['missing_streak']} 轮没有交回可用的增量块：这个模型可能不适合"
                               "多轮对话，状态卡里由模型给的字段停在更早的版本。）")
            outcome.update(state=state, archived=archived, card_next=card_next)
            event = {
                "turn": number, "topic": outcome["topic"], "topic_name": outcome["topic_name"],
                "version": outcome["version"], "new_version": outcome["new_version"],
                "block": outcome["block_status"], "problems": outcome["problems"],
                "sql_missing": outcome["sql_missing"],
                "segments": [{k: v for k, v in item.items() if k != "sql"} for item in outcome["segments"]],
                "notices": notices, "guard": outcome["guard"], "archived": archived,
                "gaps": [{k: gap[k] for k in ("missing", "column", "proposed", "turn")}
                         for gap in outcome["gaps"]],
                "view": memory.view(state),
            }
            run.note("memory", turn=number, block=outcome["block_status"], problems=outcome["problems"],
                     sql_missing=outcome["sql_missing"], card_chars=card_chars,
                     card_chars_next=len(card_next), archived=archived, guard=outcome["guard"],
                     statements_over=bool(outcome["statements_over"]), notices=notices)
            return {"sql": outcome["sql"], "check": outcome["check"], "check_error": outcome["check_error"],
                    "notices": notices, "event": event, "outcome": outcome}

        return hook

    def _recall_for(self, conversation: Conversation):
        """``recall`` bound to this conversation: the model passes turn, topic, version only."""
        def recall(turn: int | None = None, topic: int | None = None, version: int | None = None):
            with self._lock:
                turns = list(conversation.turns)
            return memory.recall(turns, turn=turn, topic=topic, version=version)
        return recall

    # ------------------------------------------------------------------ the record

    def _finish_record(self, conversation: Conversation, run: Run, record: dict) -> None:
        """With the lock held: the turn's record once its run ended; the card moves only on done."""
        record["status"] = run.status
        record["finished"] = self.now().isoformat()
        record["tools"] = [{"name": e.get("name"), "input": e.get("input")}
                           for e in run.events if e.get("type") == "tool_call"]
        if run.status == "done" and run.answer is not None:
            record["answer"] = run.answer["text"]
            outcome = (run.memory or {}).get("outcome")
            if outcome is not None:
                conversation.state = outcome["state"]
                record.update(segments=outcome["segments"], block=outcome["block"],
                              block_status=outcome["block_status"], problems=outcome["problems"],
                              topic=outcome["topic"], version=outcome["version"],
                              card_after=outcome["card_next"], notices=(run.memory or {}).get("notices"))
            else:
                record.update(segments=[{"index": i, "sql": sql, "role": None, "version": None, "topic": None}
                                        for i, sql in enumerate(memory.sql_segments(run.answer["text"]), 1)],
                              block_status="unread")
        self._save(conversation)

    def _document(self, conversation: Conversation) -> dict:
        return {"conversation": conversation.id, "created": conversation.started_at,
                "updated": self.now().isoformat(), "state": conversation.state,
                "turns": conversation.turns}

    def _save(self, conversation: Conversation) -> None:
        if self.store is not None and not conversation.read_only:
            self.store.save(self._document(conversation))

    # ------------------------------------------------------------------ the conversations

    def _new_conversation(self) -> Conversation:
        self._make_room()
        now = self.clock()
        conversation = Conversation(secrets.token_urlsafe(24), now, now,
                                    started_at=self.now().isoformat())
        self._conversations[conversation.id] = conversation
        return conversation

    def _make_room(self) -> None:
        if len(self._conversations) >= self.max_conversations:
            idle = [c for c in self._conversations.values() if c.running is None]
            if not idle:
                raise AskError(503, "too_many_conversations",
                               "every conversation this server keeps is answering a question")
            oldest = min(idle, key=lambda c: c.used)
            del self._conversations[oldest.id]

    def _get(self, conversation_id: str) -> Conversation:
        self._expire()
        conversation = self._conversations.get(conversation_id or "")
        if conversation is None and self.store is not None:
            conversation = self._load(conversation_id or "")
        if conversation is None:
            where = ("it is not in the store either" if self.store is not None
                     else "conversations live in server memory only, unless the server has --ask-store")
            raise AskError(404, "conversation_gone",
                           f"no such conversation: it expired, or the server restarted ({where})")
        return conversation

    def _load(self, conversation_id: str) -> Conversation | None:
        document = self.store.load(conversation_id)
        if document is None:
            return None
        self._make_room()
        now = self.clock()
        state = memory.new_state()
        if isinstance(document.get("state"), dict):
            state.update(document["state"])
        turns = [item for item in document.get("turns") or [] if isinstance(item, dict)]
        conversation = Conversation(conversation_id, now, now, turns=turns[-MAX_TURNS:], state=state,
                                    started_at=document.get("created"),
                                    read_only=bool(document.get("read_only")))
        self._conversations[conversation.id] = conversation
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


def _turn_summary(record: dict) -> dict:
    """A turn as the page lists it (a conversation read back from the store has no runs)."""
    return {"turn": record.get("turn"), "question": record.get("question"), "status": record.get("status"),
            "topic": record.get("topic"), "version": record.get("version"), "answer": record.get("answer"),
            "notices": record.get("notices") or []}
