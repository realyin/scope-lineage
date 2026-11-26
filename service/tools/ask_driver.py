"""Drive the ask panel of a running server turn by turn, as the page would: a developer tool.

For an evaluator -- a person, or an agent playing the asker -- running a multi-turn scenario
against ``scope-lineage-service http ... --ask`` (or ``--ask-dev-fake-model``). It talks to
the server's own endpoints only (``POST /api/ask``, ``GET /api/ask/events``, ``GET
/api/ask/conversation``, ``POST /api/ask/cancel``), standard library only, and is not part
of any installed package::

    python service/tools/ask_driver.py send "a question"                 # a new conversation
    python service/tools/ask_driver.py send --conversation ID "follow-up"
    echo "a long question" | python service/tools/ask_driver.py send -  # the question on stdin
    python service/tools/ask_driver.py show ID                          # the runs so far

``send`` waits until the run finishes and prints one JSON object: ``conversation``, ``run``,
``follow_up``, ``model``, ``status``, ``reason``, ``detail``, ``elapsed`` (the server's
seconds), ``answer``, ``sql``, ``brief``, ``brief_missing``, ``memory`` (topic, SQL version,
block status, the lines the guard added; null from a server without it) and ``usage``. Exit 0 when the
status is ``done``, 1 for any other end (``timeout`` when ``--timeout`` passed first: the run
is cancelled), 2 when the server refused the request (its error JSON on stderr). ``show``
prints the conversation with each run's outcome read from its events.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

DEFAULT_SERVER = "http://127.0.0.1:8765"
WAIT = 20


class ServerError(Exception):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body}")
        self.status, self.body = status, body


class Client:
    def __init__(self, server: str) -> None:
        self.server = server.rstrip("/")

    def _call(self, method: str, path: str, payload: dict | None = None, **params) -> dict:
        url = self.server + path + (f"?{urlencode(params)}" if params else "")
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=WAIT + 15) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise ServerError(error.code, error.read().decode("utf-8", "replace")) from None

    def ask(self, question: str, conversation: str | None, model: str | None) -> dict:
        payload = {"question": question}
        if conversation:
            payload["conversation"] = conversation
        if model:
            payload["model"] = model
        return self._call("POST", "/api/ask", payload)

    def events(self, conversation: str, run: str, after: int, wait: int) -> dict:
        return self._call("GET", "/api/ask/events", conversation=conversation, run=run,
                          after=after, wait=wait)

    def all_events(self, conversation: str, run: str, deadline: float | None = None) -> list | None:
        """Every event of the run once it is done; None when ``deadline`` passed first."""
        events, after = [], 0
        while True:
            left = WAIT if deadline is None else min(WAIT, int(deadline - time.monotonic()))
            if deadline is not None and left <= 0:
                return None
            page = self.events(conversation, run, after, max(0, left))
            events += page["events"]
            after = page["next"]
            if page["done"]:
                return events

    def conversation(self, conversation: str) -> dict:
        return self._call("GET", "/api/ask/conversation", conversation=conversation)

    def cancel(self, conversation: str) -> dict:
        return self._call("POST", "/api/ask/cancel", {"conversation": conversation})


def outcome(events: list) -> dict:
    """What a run ended with, read from its events."""
    answer = next((e for e in reversed(events) if e["type"] == "answer"), {})
    finished = next((e for e in reversed(events) if e["type"] == "finished"), {})
    return {
        "status": finished.get("status"), "reason": finished.get("reason"),
        "detail": finished.get("detail"), "elapsed": finished.get("t"),
        "answer": answer.get("text"), "sql": answer.get("sql"), "brief": answer.get("brief"),
        "brief_missing": answer.get("brief_missing"), "memory": answer.get("memory"),
        "usage": finished.get("usage"),
    }


def send(client: Client, args) -> int:
    question = sys.stdin.read() if args.question == "-" else args.question
    started = client.ask(question, args.conversation, args.model)
    conversation, run = started["conversation"], started["run"]
    deadline = None if args.timeout is None else time.monotonic() + args.timeout
    events = client.all_events(conversation, run, deadline)
    head = {"conversation": conversation, "run": run, "follow_up": started.get("follow_up"),
            "model": started.get("model")}
    if events is None:
        client.cancel(conversation)
        result = {**head, **outcome([]), "status": "timeout"}
    else:
        result = {**head, **outcome(events)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "done" else 1


def show(client: Client, args) -> int:
    held = client.conversation(args.conversation)
    runs = []
    for item in held["runs"]:
        page = client.events(args.conversation, item["run"], 0, 0)
        runs.append({**item, **outcome(page["events"]), "status": page["status"]})
    print(json.dumps({**held, "runs": runs}, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ask_driver.py", description=__doc__.split("\n")[0])
    parser.add_argument("--server", default=DEFAULT_SERVER,
                        help=f"The server's address (default {DEFAULT_SERVER})")
    commands = parser.add_subparsers(dest="command", required=True)
    asking = commands.add_parser("send", help="Ask a question and wait for the run to finish")
    asking.add_argument("question", help="The question's text, or - to read it from stdin")
    asking.add_argument("--conversation", help="Follow up in this conversation (default: a new one)")
    asking.add_argument("--model", help="A model id from GET /api/ask/status (default: the server's)")
    asking.add_argument("--timeout", type=float, default=None, metavar="SECONDS",
                        help="Stop waiting (and cancel the run) after this long")
    showing = commands.add_parser("show", help="Print a conversation's runs and their outcomes")
    showing.add_argument("conversation", help="The conversation id")
    args = parser.parse_args(argv)
    client = Client(args.server)
    try:
        return send(client, args) if args.command == "send" else show(client, args)
    except ServerError as error:
        print(error.body, file=sys.stderr)
        return 2
    except urllib.error.URLError as error:
        print(f"cannot reach {args.server}: {error.reason}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
