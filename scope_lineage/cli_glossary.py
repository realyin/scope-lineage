"""The ``scope-lineage glossary`` subcommand: parser and runner.

Kept out of ``cli.py`` for the same reason ``cli_tables`` is: ``glossary``'s unit of work
is the *corpus*, not the document. It reads every ``lineage.json`` under one root, builds
one semantic profile per task, and publishes what the tasks together say about each
column name -- the comments the warehouse carries for it and the constants the SQL
compares it against. The shared walk (``cli._discover_lineage_documents`` /
``cli._load_contract_documents``) is imported inside the runner so this module can be
imported from ``cli`` without a cycle.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .render.glossary import build_glossary, render_glossary_markdown


def add_glossary_parser(subcommands) -> None:
    glossary_cmd = subcommands.add_parser(
        "glossary",
        help=(
            "Aggregate a corpus of Core artifacts into one term / value dictionary: "
            "glossary.json and glossary.md"
        ),
    )
    glossary_cmd.add_argument(
        "--lineage",
        required=True,
        help="One lineage.json file, or a directory searched recursively for lineage.json",
    )
    glossary_cmd.add_argument(
        "--out",
        required=True,
        help="Directory for glossary.json and glossary.md",
    )
    glossary_cmd.add_argument(
        "--overrides",
        help=(
            "A reviewed glossary.overrides.json: confirmed meanings for column names "
            "and for column='VALUE' pairs. Keys that match nothing are reported under "
            "overrides_applied.unmatched rather than dropped"
        ),
    )
    glossary_cmd.add_argument(
        "--format",
        default="json,md",
        help="Comma-separated output formats: json, md (default: json,md)",
    )


def formats(value: str | None) -> set[str]:
    return {name.strip() for name in (value or "json,md").split(",") if name.strip()}


def load_overrides(path: str | None):
    """The reviewed overrides document, or the exit code when it cannot be read."""
    if not path:
        return None
    source = Path(path)
    if not source.is_file():
        print(f"--overrides file does not exist: {source}", file=sys.stderr)
        return 2
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except ValueError as error:
        print(f"{source}: not valid JSON ({error})", file=sys.stderr)
        return 2
    if not isinstance(document, dict):
        print(f"{source}: overrides must be a JSON object", file=sys.stderr)
        return 2
    return document


def run_glossary(args: argparse.Namespace) -> int:
    from .cli import _discover_lineage_documents, _load_contract_documents

    overrides = load_overrides(getattr(args, "overrides", None))
    if isinstance(overrides, int):
        return overrides
    found = _discover_lineage_documents(args.lineage)
    if isinstance(found, int):
        return found
    loaded = _load_contract_documents(*found, args.out, "glossary builder")
    if isinstance(loaded, int):
        return loaded
    documents, skipped_unknown_version, missing_diagnostics = loaded

    try:
        glossary = build_glossary(
            [item.document for item in documents],
            artifact_root=str(Path(args.lineage)),
            overrides=overrides,
        )
    except ValueError as error:
        print(f"{args.lineage}: {error}", file=sys.stderr)
        return 1
    _write(Path(args.out), glossary, formats(args.format))

    applied = glossary["overrides_applied"]
    print(
        f"Collected {len(glossary['terms'])} term(s) and {len(glossary['values'])} "
        f"value observation(s) from {glossary['corpus']['task_count']} task(s) "
        f"(overrides terms={applied['terms']}, values={applied['values']}, "
        f"unmatched={len(applied['unmatched'])}, "
        f"skipped_unknown_version={skipped_unknown_version}, "
        f"missing_diagnostics={missing_diagnostics})"
    )
    return 0


def _write(out_dir: Path, glossary: dict, selected: set) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    if "json" in selected:
        (out_dir / "glossary.json").write_text(
            json.dumps(glossary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if "md" in selected:
        (out_dir / "glossary.md").write_text(
            render_glossary_markdown(glossary), encoding="utf-8"
        )
