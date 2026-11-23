"""One question: model turns and catalog tool calls until an answer, a stop or a cap.

A manual loop rather than the SDK's tool runner, for four reasons: every step is reported
to the page as it happens (an event per turn, tool call and result); a cancel or the wall
clock can stop a turn in flight, and the tool-call cap can refuse single calls while the
model still gets to answer; the fallback boundary rule decides which blocks are echoed and
which tool calls run; and the loop talks to the model through one small seam (``Model``),
so it is tested without the SDK or a network and the SDK is imported only by the class
that implements the seam (``anthropic_model``).

The seam takes ``{"system", "tools", "messages", "max_tokens"}`` and returns the turn as
plain data: ``{"content": [blocks as dicts], "stop_reason", "stop_details", "usage",
"model"}``. It raises ``Cancelled`` when ``should_stop()`` turned true mid-turn,
``InvalidToolInput`` when a streamed tool input was not JSON (the turn is asked again,
at most twice in a row), and ``ModelError`` for anything else the provider or the SDK
reports.

Each request's ``max_tokens`` is the per-turn limit, what is left of the question's output
cap, and the model's own ``max_tokens`` when it has one (privately hosted models often take
far fewer per request). A turn may say ``usage_estimated`` (an endpoint that reported no
usage); the turn event and the question's total then say so.

Stop reasons: ``tool_use`` runs the calls (in order, all results back in one user
message, a failed call as ``is_error``); ``end_turn`` is the answer; ``pause_turn`` sends
the turn back to be continued; ``max_tokens`` and ``refusal`` stop the question without
running that turn's calls (a cut-off input may still parse).

A follow-up question starts a fresh message list holding the previous question's brief
and the new question -- the walk's multi-turn rule (carry the brief, not the transcript),
which also keeps every replayed thinking block inside the conversation that produced it.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from .tools import ToolBox, placeholders_of

MIN_TURN_TOKENS = 1024
MAX_BRIEF_CHARS = 16_000
JSON_RETRIES = 2
USAGE_FIELDS = (
    "input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
)
# blocks of a declined attempt that may be echoed before the last fallback block
_ECHO_BEFORE_FALLBACK = {"text", "fallback"}


class Cancelled(Exception):
    """The turn was stopped because ``should_stop()`` became true."""


class InvalidToolInput(Exception):
    """A streamed tool input was not JSON; the turn holds no call to answer, so ask again."""


class ModelError(Exception):
    """The provider or the SDK refused or failed; ``kind`` is a short machine word."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind, self.message = kind, message


class Model(Protocol):
    name: str

    def turn(self, request: dict, should_stop: Callable[[], bool]) -> dict: ...


@dataclass(frozen=True)
class Limits:
    max_turns: int = 30
    max_tool_calls: int = 40
    max_output_tokens: int = 128_000
    max_seconds: float = 900.0
    max_tokens_per_turn: int = 64_000

    def as_dict(self) -> dict:
        return {
            "max_turns": self.max_turns, "max_tool_calls": self.max_tool_calls,
            "max_output_tokens": self.max_output_tokens, "max_seconds": self.max_seconds,
        }


@dataclass
class Run:
    """One question's run: the events the page polls, numbered from 1."""

    id: str
    question: str
    brief: str | None = None
    model_id: str | None = None
    model_label: str | None = None
    clock: Callable[[], float] = time.monotonic
    events: list = field(default_factory=list)
    status: str = "running"
    answer: dict | None = None

    def __post_init__(self) -> None:
        self.started = self.clock()
        self._changed = threading.Condition()
        self._cancel = threading.Event()

    def emit(self, kind: str, **data) -> dict:
        with self._changed:
            event = {"seq": len(self.events) + 1, "type": kind,
                     "t": round(self.clock() - self.started, 1), **data}
            self.events.append(event)
            self._changed.notify_all()
        return event

    def finish(self, status: str, **data) -> None:
        self.status = status
        self.emit("finished", status=status, model_id=self.model_id, **data)

    @property
    def done(self) -> bool:
        return self.status != "running"

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def wait_events(self, after: int, timeout: float) -> tuple[list, bool]:
        """The events after number ``after``, waiting up to ``timeout`` seconds for one."""
        with self._changed:
            if len(self.events) <= after and not self.done and timeout > 0:
                self._changed.wait_for(lambda: len(self.events) > after or self.done, timeout)
            return list(self.events[after:]), self.done


def question_text(question: str, brief: str | None) -> str:
    if not brief:
        return f"问题：{question}"
    return f"上一题的简报：\n```text\n{brief}\n```\n\n问题：{question}"


def echo_content(content: list) -> list:
    """The assistant content to send back: before the last ``fallback`` block only its text
    and fallback blocks (the declined attempt's thinking and calls are left out, the boundary
    stays where it was); everything after it as it came."""
    boundary = _last_fallback(content)
    if boundary < 0:
        return list(content)
    return [b for b in content[:boundary] if b.get("type") in _ECHO_BEFORE_FALLBACK] + content[boundary:]


def _last_fallback(content: list) -> int:
    for index in range(len(content) - 1, -1, -1):
        if content[index].get("type") == "fallback":
            return index
    return -1


def _text_of(content: list) -> str:
    return "".join(block.get("text", "") for block in content if block.get("type") == "text")


def _model_name(value) -> str | None:
    return value.get("model") if isinstance(value, dict) else value


_SQL_BLOCK = re.compile(r"```sql[^\n]*\n(.*?)```", re.IGNORECASE | re.DOTALL)
_TEXT_BLOCK = re.compile(r"```text[^\n]*\n(.*?)```", re.DOTALL)


def final_sql(answer: str) -> str | None:
    found = _SQL_BLOCK.search(answer)
    return found.group(1).strip() if found else None


def final_brief(answer: str) -> str | None:
    briefs = [block.strip() for block in _TEXT_BLOCK.findall(answer)
              if block.strip().startswith("问题")]
    return briefs[-1][:MAX_BRIEF_CHARS] if briefs else None


class _Question:
    """The state of one run_question call."""

    def __init__(self, run: Run, model: Model, tools: ToolBox, system: list, limits: Limits):
        self.run, self.model, self.tools, self.system, self.limits = run, model, tools, system, limits
        self.definitions = tools.definitions()
        self.messages: list = [{"role": "user", "content": [
            {"type": "text", "text": question_text(run.question, run.brief)}]}]
        self.usage = dict.fromkeys(USAGE_FIELDS, 0)
        self.estimated = False
        self.turns = self.tool_calls = self.json_retries = self.strikes = 0
        self.deadline = run.started + limits.max_seconds

    def expired(self) -> bool:
        return self.run.clock() > self.deadline

    def should_stop(self) -> bool:
        return self.run.cancelled or self.expired()

    def totals(self) -> dict:
        totals = {**self.usage, "turns": self.turns, "tool_calls": self.tool_calls}
        if self.estimated:
            totals["estimated"] = True
        return totals

    def stop(self, status: str, reason: str | None = None, detail=None) -> None:
        self.run.finish(status, reason=reason, detail=detail, usage=self.totals())

    def interrupted(self) -> bool:
        if self.run.cancelled:
            self.stop("cancelled")
            return True
        if self.expired():
            self.stop("cap_reached", "seconds")
            return True
        return False

    # ------------------------------------------------------------------ steps

    def next_turn(self) -> dict | None:
        """One model turn, or None when the question has stopped."""
        if self.interrupted():
            return None
        if self.turns >= self.limits.max_turns:
            self.stop("cap_reached", "turns")
            return None
        remaining = self.limits.max_output_tokens - self.usage["output_tokens"]
        if remaining < MIN_TURN_TOKENS:
            self.stop("cap_reached", "output_tokens")
            return None
        cap = min(self.limits.max_tokens_per_turn, remaining)
        per_model = getattr(self.model, "max_tokens", None)
        if isinstance(per_model, int) and per_model > 0:
            cap = min(cap, per_model)  # private models often take far fewer per request
        request = {
            "system": self.system, "tools": self.definitions, "messages": self.messages,
            "max_tokens": cap,
        }
        try:
            result = self.model.turn(request, self.should_stop)
        except Cancelled:
            if not self.interrupted():
                self.stop("cancelled")
            return None
        except InvalidToolInput as error:
            self.json_retries += 1
            if self.json_retries > JSON_RETRIES:
                self.stop("error", "invalid_tool_input", str(error))
                return None
            self.run.emit("retry", reason="invalid_tool_input")
            return self.next_turn()
        except ModelError as error:
            self.stop("error", error.kind, error.message)
            return None
        self.json_retries = 0
        self.turns += 1
        if result.get("usage_estimated"):
            self.estimated = True
        usage = result.get("usage") or {}
        for name in USAGE_FIELDS:
            self.usage[name] += int(usage.get(name) or 0)
        return result

    def report_turn(self, result: dict) -> None:
        content = result["content"]
        for block in content:
            if block.get("type") == "fallback":
                self.run.emit("fallback", **{"from": _model_name(block.get("from")),
                                             "to": _model_name(block.get("to"))})
        extra = {"usage_estimated": True} if result.get("usage_estimated") else {}
        self.run.emit(
            "turn", turn=self.turns, stop_reason=result.get("stop_reason"),
            model=result.get("model"), text=_text_of(content),
            usage={name: int((result.get("usage") or {}).get(name) or 0) for name in USAGE_FIELDS},
            **extra,
        )

    def run_tools(self, calls: list) -> list:
        results, refused = [], False
        for block in calls:
            if self.run.cancelled:
                break
            self.run.emit("tool_call", id=block["id"], name=block["name"], input=block.get("input"))
            if self.tool_calls >= self.limits.max_tool_calls:
                refused = True
                message = (f"本题的工具调用已到上限（{self.limits.max_tool_calls} 次），这次没有执行；"
                           "用已有的材料作答。")
                self.run.emit("tool_result", id=block["id"], name=block["name"], ok=False,
                              exit_code=None, data={}, error=message)
                results.append({"type": "tool_result", "tool_use_id": block["id"],
                                "content": message, "is_error": True})
                continue
            self.tool_calls += 1
            outcome = self.tools.call(block["name"], block.get("input"))
            self.run.emit("tool_result", id=block["id"], name=block["name"], ok=outcome.ok,
                          exit_code=outcome.exit_code, data=outcome.data,
                          error=None if outcome.ok else outcome.text)
            item = {"type": "tool_result", "tool_use_id": block["id"], "content": outcome.text}
            if not outcome.ok:
                item["is_error"] = True
            results.append(item)
        self.strikes = self.strikes + 1 if refused else 0
        return results

    def answer(self, text: str) -> None:
        sql = final_sql(text)
        brief = final_brief(text)
        missing = brief is None
        if missing:
            brief = (f"问题：{self.run.question}\n结论：（模型没有交回简报；下面是答案的开头）\n"
                     + text[:4000])
        placeholders, problem = [], None
        if sql:
            try:
                placeholders = placeholders_of(self.tools.state.check_sql(sql).result)
            except Exception as error:  # noqa: BLE001 -- any refusal only hides the list
                problem = str(getattr(error, "message", error))
        self.run.answer = {"text": text, "sql": sql, "brief": brief}
        self.run.emit("answer", text=text, sql=sql, brief=brief, brief_missing=missing,
                      placeholders=placeholders, placeholder_check_error=problem)


def run_question(run: Run, model: Model, tools: ToolBox, system: list, limits: Limits) -> None:
    """Answer ``run.question``; every step is an event on ``run``, the last one ``finished``."""
    job = _Question(run, model, tools, system, limits)
    run.emit("started", question=run.question, follow_up=bool(run.brief),
             model=getattr(model, "name", None), model_id=run.model_id,
             model_label=run.model_label, limits=limits.as_dict())
    while True:
        result = job.next_turn()
        if result is None:
            return
        job.report_turn(result)
        content = result["content"]
        stop = result.get("stop_reason")
        if stop == "refusal":
            job.stop("refused", "refusal", result.get("stop_details"))
            return
        if stop == "max_tokens":
            job.stop("max_tokens", "max_tokens", _text_of(content))
            return
        if stop == "pause_turn":
            job.messages.append({"role": "assistant", "content": echo_content(content)})
            continue
        boundary = _last_fallback(content)
        calls = [b for b in content[boundary + 1:] if b.get("type") == "tool_use"]
        if not calls:
            job.answer(_text_of(content))
            job.stop("done")
            return
        job.messages.append({"role": "assistant", "content": echo_content(content)})
        results = job.run_tools(calls)
        if run.cancelled:
            job.stop("cancelled")
            return
        job.messages.append({"role": "user", "content": results})
        if job.strikes >= 2:
            job.stop("cap_reached", "tool_calls")
            return
