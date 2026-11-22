"""``scope-lineage-service http|mcp ONTOLOGY [--semantics DIR] [--pending FILE]``.

The files named here are the only ones a server reads (and the pending file the only one
it writes); they are read once at start -- an unreadable one stops the server with the
``catalog`` command's sentence and exit code -- and again whenever they change.
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
    return parser


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

    if not _is_loopback(args.host):
        print(
            f"warning: binding {args.host}: the catalog and the pending file are reachable "
            "from other machines, with no authentication",
            file=sys.stderr,
        )
    httpd = make_server(
        state, args.host, args.port, max_body=args.max_body, allow_hosts=args.allow_host,
        quiet=args.quiet,
    )
    host, port = httpd.server_address[:2]
    print(f"Serving catalog answers on http://{host}:{port}/ (GET /api lists the endpoints)",
          file=sys.stderr, flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0
