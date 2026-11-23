"""``scope-lineage-service http|mcp ONTOLOGY [--semantics DIR] [--pending FILE]``.

The files named here are the only ones a server reads (and the pending file the only one
it writes); they are read once at start -- an unreadable one stops the server with the
``catalog`` command's sentence and exit code -- and again whenever they change.

``http --ask`` adds the ask panel (a model on this server answers data questions through
the catalog tools; it costs money and sends catalog text to the model provider, so it is
never on by default and only on a loopback address); ``--ask-dev-fake-model`` is a
development aid that walks the same panel through scripted tool calls with no model.
"""

from __future__ import annotations

import argparse
import ipaddress
import sys

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
        if name == "http":
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
    return parser


def _ask_options(mode: argparse.ArgumentParser) -> None:
    from .ask.anthropic_model import DEFAULT_EFFORT, DEFAULT_MODEL, EFFORTS
    from .ask.loop import Limits

    limits = Limits()
    ask = mode.add_argument_group(
        "ask panel", "Answer data questions on the page with a model on this server. Off unless "
        "--ask is given: each question calls the model through the Anthropic API, costs money "
        "and sends the question and catalog text to the model provider. Credentials come from "
        "the server's environment (needs the [ask] extra). Loopback addresses only.")
    ask.add_argument("--ask", action="store_true", help="Enable the ask panel and its endpoints")
    ask.add_argument("--ask-model", default=DEFAULT_MODEL, help=f"Model id (default {DEFAULT_MODEL})")
    ask.add_argument("--ask-effort", choices=EFFORTS, default=DEFAULT_EFFORT,
                     help=f"output_config.effort (default {DEFAULT_EFFORT})")
    ask.add_argument("--ask-no-fallback", action="store_true",
                     help="Do not ask the API to retry a refused request on its fallback model")
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


def _ask_service(args, state: CatalogState):
    """The ask service the options ask for, and the sentence to print at start."""
    from .ask.anthropic_model import load_model
    from .ask.loop import Limits
    from .ask.service import AskService
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
    if args.ask_dev_fake_model:
        from .ask.fake_model import FakeModel

        model, reason = FakeModel(state), None
        notice = ("ask panel: DEVELOPMENT FAKE MODEL -- answers are scripted from real catalog "
                  "tool calls; no model is called and nothing leaves this machine")
    else:
        model, reason = load_model(args.ask_model, args.ask_effort, fallback=not args.ask_no_fallback)
        if reason:
            notice = f"ask panel: unavailable -- {reason}"
        else:
            notice = (
                f"ask panel: ON -- every question calls {args.ask_model} (effort {args.ask_effort}) "
                "through the Anthropic API with credentials from this environment "
                f"({model.source}). It costs money, and the question, the catalog text the tools "
                "return and the drafted SQL are sent to the model provider. No SQL is run."
            )
    service = AskService(
        tools, model, reason=reason, limits=limits,
        max_conversations=args.ask_max_conversations, max_idle_seconds=args.ask_idle_minutes * 60.0,
    )
    return service, notice


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        state = CatalogState(args.ontology, semantics=args.semantics, pending=args.pending)
    except CatalogAnswerError as error:
        print(error.message, file=sys.stderr)
        return error.exit_code
    if args.mode == "mcp":
        from .mcp_server import serve_stdio

        serve_stdio(state)
        return 0
    from .http_server import make_server

    asking = args.ask or args.ask_dev_fake_model
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
    httpd = make_server(
        state, args.host, args.port, max_body=args.max_body, allow_hosts=args.allow_host,
        quiet=args.quiet, ask=ask,
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
