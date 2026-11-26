"""``scope-lineage-service http|mcp ONTOLOGY [--semantics DIR] [--pending FILE] [--answers FILE]``.

The files named here are the only ones a server reads (and the pending file -- with
``http``, the answers file too -- the only ones it writes); they are read once at start --
an unreadable one stops the server with the ``catalog`` command's sentence and exit code --
and again whenever they change.

``--answers FILE`` keeps the browsing page's answers to table-semantics questions
(``answers.py``). ``http`` is the file's one writer; ``mcp`` overlays it read-only. On an
address other machines reach the page's answers are refused unless
``--answers-allow-remote`` is given. ``scope-lineage-service answers export ANSWERS
--semantics DIR --out FILE`` writes the answers in effect as a ``semantic-confirmations/1``
file for ``scope-lineage semantic confirm``, without a server and without writing ANSWERS.

``http --ask`` adds the ask panel (a model on this server answers data questions through
the catalog tools; it costs money and sends catalog text to the model provider, so it is
never on by default and only on a loopback address). ``--ask-model`` names the one model;
``--ask-models FILE`` lists several (the page lets the asker pick one per question; see
``ask/models.py`` for the file). ``--ask-dev-fake-model`` is a development aid that walks
the same panel through scripted tool calls with no model. ``--ask-trace DIR`` records every
question run as JSON lines under DIR (``ask/trace.py``); off unless given.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import sys
from pathlib import Path

from scope_lineage.cli_catalog_answers import CatalogAnswerError

from . import __version__
from .state import CatalogState


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scope-lineage-service",
        description="Read-only HTTP and MCP servers for the scope-lineage catalog answers",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    modes = parser.add_subparsers(dest="mode", required=True)
    for name, text in (
        ("http", "Serve JSON endpoints over HTTP (127.0.0.1 by default)"),
        ("mcp", "Serve MCP tools over stdio"),
    ):
        mode = modes.add_parser(name, help=text)
        mode.add_argument("ontology", help="An ontology.json written by `scope-lineage catalog build`")
        mode.add_argument("--semantics", help="A directory of table-semantics documents")
        mode.add_argument(
            "--pending",
            help="A catalog-pending/1 file: enables pending list and add (the only file written)",
        )
        mode.add_argument(
            "--answers", metavar="FILE",
            help=("A question-answers/1 file of the browsing page's answers to table-semantics "
                  "questions, overlaid on the documents; http writes it (created on the first "
                  "answer), mcp only reads it. Keep it outside the semantics directory")
            if name == "http" else
            "A question-answers/1 file an http server writes: its answers are overlaid, read-only",
        )
        if name == "http":
            mode.add_argument(
                "--answers-allow-remote", action="store_true",
                help="Take the page's answers even when other machines can reach this server "
                     "(a non-loopback --host, or --allow-host): anyone who reaches the port can "
                     "answer under any name, and the text reaches models and MCP")
            mode.add_argument(
                "--probes", metavar="FILE",
                help="A question-probes/1 file (read-only): the questions board shows each "
                     "question's platform queries and takes pasted results as draft "
                     "observations a person confirms into the --answers file")
            mode.add_argument("--host", default="127.0.0.1",
                              help="IPv4 address to bind (default 127.0.0.1, this machine only)")
            mode.add_argument("--port", type=int, default=8765,
                              help="Port (default 8765; 0 picks a free one)")
            mode.add_argument("--max-body", type=int, default=1024 * 1024,
                              help="Largest POST body in bytes (default 1 MiB)")
            mode.add_argument(
                "--allow-host", action="append", default=[], metavar="NAME",
                help="Another Host/Origin name to accept besides this machine (repeatable)",
            )
            mode.add_argument("--quiet", action="store_true", help="Do not log each request")
            _ask_options(mode)
    answers = modes.add_parser("answers", help="Work with a --answers file without a server")
    actions = answers.add_subparsers(dest="action", required=True)
    export = actions.add_parser(
        "export",
        help="Write the answers in effect as a semantic-confirmations/1 file "
             "(for scope-lineage semantic confirm); exit 1 when a record did not match",
    )
    export.add_argument("answers", help="The question-answers/1 file a server keeps")
    export.add_argument("--semantics", required=True,
                        help="The directory of table-semantics documents the answers are for")
    export.add_argument("--out", required=True, help="Where to write the confirmations file")
    return parser


def _export(args) -> int:
    """``answers export``: the answers in effect, judged against the documents on disk now.
    The reason of each record not matched, a note for each code value whose meaning on disk
    the page changed (``answers.export_notes``) and the digest of each table answered go to
    stderr; exit 1 when a record did not match (the others are still written)."""
    from scope_lineage import cli_catalog_answers as core
    from scope_lineage.semantics.digests import document_digest

    from . import answers as records_file

    try:
        semantics = core.load_semantics(args.semantics)
    except CatalogAnswerError as error:
        print(error.message, file=sys.stderr)
        return error.exit_code
    try:
        records, observations = records_file.read_file(Path(args.answers))
    except records_file.AnswersFileError as error:
        print(f"{args.answers}: {error}", file=sys.stderr)
        return 2
    judgement = records_file.judge_all(records, semantics)
    observed = [records_file.judge_observation(record, semantics) for record in observations]
    seen = [item.record for item in observed if item.state == records_file.EFFECTIVE]
    effective = [item.record for item in judgement.of(records_file.EFFECTIVE)
                 if item.record["kind"] == records_file.ANSWER]
    _, refused = records_file.overlay_records(semantics, effective)
    unmatched = [item for item in judgement.of(records_file.UNMATCHED)
                 if item.record["kind"] == records_file.ANSWER]
    kept = []
    for record in effective:
        reason = refused.get(id(record))
        if reason is None:
            kept.append(record)
        else:
            unmatched.append(records_file.Judged(
                record, records_file.UNMATCHED, records_file.NOT_APPLIED, None,
                f"{records_file.REASON_TEXT[records_file.NOT_APPLIED]}：{reason}"))
    out = Path(args.out)
    unmatched += [item for item in observed if item.state == records_file.UNMATCHED]
    out.write_text(json.dumps(records_file.export_document(kept, seen), ensure_ascii=False,
                              indent=2) + "\n", encoding="utf-8")
    observed_words = f", {len(seen)} observation(s)" if observations else ""
    print(f"Exported {len(kept)} answer(s){observed_words} to {out} "
          f"(not matched={len(unmatched)})", file=sys.stderr)
    for item in unmatched:
        entry = item.listing()
        now = entry["now"]
        held = "不存在" if now is None else (
            f"问题「{now['text']}」，" + (f"回答「{now['answer']}」（{now['answered_by'] or '—'}，"
                                      f"{now['answered_on'] or '—'}）" if now["answer"] else "待确认"))
        print(f"  not matched: {entry['table']} {entry['question']}: {entry['message']}；"
              f"磁盘上现在：{held}", file=sys.stderr)
    for note in records_file.export_notes(kept):
        print(f"  note: {note}", file=sys.stderr)
    for table in sorted({record["table"] for record in kept + seen}):
        print(f"  {table}  document_digest {document_digest(semantics[table])}", file=sys.stderr)
    return 1 if unmatched else 0


def _ask_options(mode: argparse.ArgumentParser) -> None:
    from .ask.anthropic_model import DEFAULT_EFFORT, DEFAULT_MODEL, EFFORTS
    from .ask.loop import Limits

    limits = Limits()
    ask = mode.add_argument_group(
        "ask panel", "Answer data questions on the page with a model on this server. Off unless "
        "--ask is given: each question calls the model (the Anthropic API, or the endpoints a "
        "--ask-models file names), costs money and sends the question and catalog text to the "
        "model provider. Credentials come from the server's environment (needs the [ask] "
        "extra; [ask-openai] for OpenAI-compatible endpoints). Loopback addresses only.")
    ask.add_argument("--ask", action="store_true", help="Enable the ask panel and its endpoints")
    ask.add_argument("--ask-model", default=None,
                     help=f"The one model's id (default {DEFAULT_MODEL})")
    ask.add_argument("--ask-effort", choices=EFFORTS, default=None,
                     help=f"output_config.effort (default {DEFAULT_EFFORT})")
    ask.add_argument("--ask-no-fallback", action="store_true",
                     help="Do not ask the API to retry a refused request on its fallback model")
    ask.add_argument(
        "--ask-models", metavar="FILE",
        help="A JSON file listing several models (Anthropic or OpenAI-compatible endpoints) the "
             "asker picks from per question; replaces --ask-model, --ask-effort and "
             "--ask-no-fallback. Keys come from environment variables it names, never the file")
    ask.add_argument("--ask-max-turns", type=int, default=limits.max_turns, metavar="N",
                     help=f"Model requests per question (default {limits.max_turns})")
    ask.add_argument("--ask-max-tool-calls", type=int, default=limits.max_tool_calls, metavar="N",
                     help=f"Tool calls per question (default {limits.max_tool_calls})")
    ask.add_argument("--ask-max-output-tokens", type=int, default=limits.max_output_tokens,
                     metavar="N", help=f"Output tokens per question (default {limits.max_output_tokens})")
    ask.add_argument("--ask-max-seconds", type=int, default=int(limits.max_seconds), metavar="N",
                     help=f"Wall time per question (default {int(limits.max_seconds)})")
    ask.add_argument("--ask-max-conversations", type=int, default=20, metavar="N",
                     help="Conversations kept in memory (default 20)")
    ask.add_argument("--ask-idle-minutes", type=int, default=60, metavar="N",
                     help="An idle conversation is dropped after this long (default 60)")
    ask.add_argument(
        "--ask-dev-fake-model", action="store_true",
        help="DEVELOPMENT AID: answer from a scripted sequence of real tool calls, no model and "
             "no network (implies --ask; the page says so on every answer)")
    ask.add_argument(
        "--ask-trace", metavar="DIR",
        help="Append a JSON-lines record of every question run to DIR/<conversation id>.jsonl "
             "(created if missing; files mode 0600): per model turn the time, tokens and how much "
             "was sent, per tool call its name, arguments and result size, per run the outcome, "
             "the question and the answer text. Never the catalog text the tools return. Off "
             "unless given; no default place")


def _ask_service(args, state: CatalogState):
    """The ask service the options ask for, and the sentence to print at start."""
    from .ask.loop import Limits
    from .ask.tools import ToolBox

    values = [args.ask_max_turns, args.ask_max_tool_calls, args.ask_max_output_tokens,
              args.ask_max_seconds, args.ask_max_conversations, args.ask_idle_minutes]
    if min(values) < 1:
        raise CatalogAnswerError(2, "the --ask-max-* and --ask-idle-minutes options take integers >= 1")
    limits = Limits(max_turns=args.ask_max_turns, max_tool_calls=args.ask_max_tool_calls,
                    max_output_tokens=args.ask_max_output_tokens,
                    max_seconds=float(args.ask_max_seconds),
                    max_tokens_per_turn=min(Limits().max_tokens_per_turn, args.ask_max_output_tokens))
    tools = ToolBox(state, max_sql=args.max_body)
    options = dict(limits=limits, max_conversations=args.ask_max_conversations,
                   max_idle_seconds=args.ask_idle_minutes * 60.0)
    service, notice = _ask_service_for(args, state, tools, options)
    if args.ask_trace:
        from .ask.trace import Tracer

        try:
            service.trace = Tracer(args.ask_trace)
        except OSError as error:
            raise CatalogAnswerError(2, f"--ask-trace {args.ask_trace}: {error.strerror or error}") from None
        notice += (f"\nask trace: every question run is appended to {args.ask_trace}/<conversation "
                   "id>.jsonl, with the question and the answer text (not the catalog text)")
    return service, notice


def _ask_service_for(args, state: CatalogState, tools, options: dict):
    """``_ask_service`` from the limits on: the models the options name."""
    from .ask.anthropic_model import DEFAULT_EFFORT, DEFAULT_MODEL, load_model
    from .ask.service import AskService

    if args.ask_models:
        models, notice = _models(args, state)
        return AskService(tools, models=models, **options), notice
    if args.ask_dev_fake_model:
        from .ask.fake_model import FakeModel

        model, reason = FakeModel(state), None
        notice = ("ask panel: DEVELOPMENT FAKE MODEL -- answers are scripted from real catalog "
                  "tool calls; no model is called and nothing leaves this machine")
    else:
        name, effort = args.ask_model or DEFAULT_MODEL, args.ask_effort or DEFAULT_EFFORT
        model, reason = load_model(name, effort, fallback=not args.ask_no_fallback)
        if reason:
            notice = f"ask panel: unavailable -- {reason}"
        else:
            notice = (
                f"ask panel: ON -- every question calls {name} (effort {effort}) "
                "through the Anthropic API with credentials from this environment "
                f"({model.source}). It costs money, and the question, the catalog text the tools "
                "return and the drafted SQL are sent to the model provider. No SQL is run."
            )
    return AskService(tools, model, reason=reason, **options), notice


def _models(args, state: CatalogState):
    """The models of the --ask-models file, loaded (or all played by the fake model)."""
    from .ask.models import ModelEntry, ModelSet, ModelsFileError, load_entries, read_models_file

    given = [name for name, value in (("--ask-model", args.ask_model), ("--ask-effort", args.ask_effort),
                                      ("--ask-no-fallback", args.ask_no_fallback)) if value]
    if given:
        raise CatalogAnswerError(2, f"--ask-models replaces {', '.join(given)}: set the model, "
                                    "effort and fallback of each model in the file")
    try:
        specs = read_models_file(args.ask_models)
    except ModelsFileError as error:
        raise CatalogAnswerError(2, error.message) from None
    if args.ask_dev_fake_model:
        from .ask.fake_model import NAME, FakeModel

        models = ModelSet([ModelEntry(spec.id, spec.label, spec.provider,
                                      FakeModel(state, name=f"{NAME}:{spec.id}"), None, spec.default,
                                      spec) for spec in specs])
        return models, (f"ask panel: DEVELOPMENT FAKE MODEL -- the {len(specs)} models of "
                        f"{args.ask_models} are all played by scripted catalog tool calls; no model "
                        "is called and nothing leaves this machine")
    models = load_entries(specs)
    lines = [_model_line(entry) for entry in models.entries]
    if not models.available:
        return models, "\n".join([f"ask panel: unavailable -- no model in {args.ask_models} can "
                                   "answer:", *lines])
    head = (f"ask panel: ON -- {len(specs)} models; each question goes to the one the asker picks "
            f"(default {models.default_id}). It costs money, and the question, the catalog text "
            "the tools return and the drafted SQL are sent to that model's endpoint. No SQL is run.")
    return models, "\n".join([head, *lines])


def _model_line(entry) -> str:
    spec = entry.spec
    if spec.provider == "anthropic":
        where = f"the Messages API at {spec.base_url}" if spec.base_url else "the Anthropic API"
        off = [name for name in ("fallback", "prompt_cache", "eager_input_streaming",
                                 "adaptive_thinking") if not getattr(spec, name)]
        if spec.effort is None:
            off.append("effort")
        extra = f"; switched off: {', '.join(off)}" if off else ""
    else:
        from .ask.openai_model import DEFAULT_MAX_TOKENS

        where = f"the chat-completions API at {spec.base_url}"
        extra = f"; at most {spec.max_tokens or DEFAULT_MAX_TOKENS} output tokens per request"
    if spec.api_key_env:
        key = f"key from ${spec.api_key_env}"
    elif spec.provider == "anthropic":
        key = f"credentials from {getattr(entry.model, 'source', None) or 'the SDK'}"
    else:
        key = "no key"
    state = "available" if entry.available else f"unavailable -- {entry.reason}"
    return f"  - {spec.id} ({spec.provider}, {spec.model}) -> {where}, {key}{extra}: {state}"


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


ANSWERS_REMOTE_WARNING = (
    "warning: --answers-allow-remote: this server takes the page's answers from other "
    "machines, with no authentication -- any program that can reach the port can answer under "
    "any name, and the answers' text enters the model's context (the ask panel) and the MCP "
    "output"
)


def _answers_notice(args) -> str | None:
    """What to print at start about the page's answers on an address others reach."""
    from .http_server import _reachable_from_elsewhere

    if not args.answers or not _reachable_from_elsewhere(args.host, args.allow_host):
        return None
    if args.answers_allow_remote:
        return ANSWERS_REMOTE_WARNING
    return ("answers: other machines can reach this server, so the page's answers are refused "
            "(read-only cards); --answers-allow-remote takes them anyway")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.mode == "answers":
        return _export(args)
    try:
        state = CatalogState(args.ontology, semantics=args.semantics, pending=args.pending,
                             answers=args.answers, answers_writer=args.mode == "http",
                             probes=getattr(args, "probes", None))
    except CatalogAnswerError as error:
        print(error.message, file=sys.stderr)
        return error.exit_code
    if args.mode == "mcp":
        from .mcp_server import serve_stdio

        serve_stdio(state)
        return 0
    from .http_server import make_server

    asking = args.ask or args.ask_dev_fake_model
    if args.ask_models and not asking:
        print("--ask-models lists the models of the ask panel: add --ask to enable it",
              file=sys.stderr)
        return 2
    if args.ask_trace and not asking:
        print("--ask-trace records the ask panel's questions: add --ask to enable it",
              file=sys.stderr)
        return 2
    if asking and not _is_loopback(args.host):
        print(f"--ask serves this machine only: it spends money on every question and the "
              f"server has no authentication; bind a loopback address, not {args.host}",
              file=sys.stderr)
        return 2
    if not _is_loopback(args.host):
        print(
            f"warning: binding {args.host}: the catalog and the pending file are reachable "
            "from other machines, with no authentication",
            file=sys.stderr,
        )
    ask, notice = None, None
    if asking:
        try:
            ask, notice = _ask_service(args, state)
        except CatalogAnswerError as error:
            print(error.message, file=sys.stderr)
            return error.exit_code
    answers_notice = _answers_notice(args)
    if answers_notice:
        print(answers_notice, file=sys.stderr)
    httpd = make_server(
        state, args.host, args.port, max_body=args.max_body, allow_hosts=args.allow_host,
        quiet=args.quiet, ask=ask, answers_allow_remote=args.answers_allow_remote,
    )
    host, port = httpd.server_address[:2]
    print(f"Serving catalog answers on http://{host}:{port}/ (open it in a browser to browse "
          "the catalog; GET /api lists the endpoints)", file=sys.stderr, flush=True)
    if notice:
        print(notice, file=sys.stderr, flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0
