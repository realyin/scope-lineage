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

from .corpus_cache import add_incremental_arguments, open_cache
from .render.glossary import build_glossary, render_glossary_markdown
from .render.glossary_template import (
    TEMPLATE_TOP_DEFAULT,
    build_overrides_template,
    render_overrides_template_markdown,
)


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
        help=(
            "Directory for glossary.json and glossary.md. Required, including with "
            "--template: the form is ranked from the dictionary written here"
        ),
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
        "--template",
        help=(
            "Also write a fill-in glossary.overrides.template.md at this path, plus the "
            "same-named .json: the corpus's most-used unexplained values, with an empty "
            "meaning each. Fill it in and pass the .json back as --overrides. Needs "
            "--out as well -- the form is a ranking OF the dictionary, not a "
            "replacement for it"
        ),
    )
    glossary_cmd.add_argument(
        "--template-top",
        type=int,
        default=TEMPLATE_TOP_DEFAULT,
        help=(
            "How many values the --template form asks about; 0 asks about every "
            f"askable value (default: {TEMPLATE_TOP_DEFAULT})"
        ),
    )
    glossary_cmd.add_argument(
        "--format",
        default="json,md",
        help="Comma-separated output formats: json, md (default: json,md)",
    )
    add_incremental_arguments(glossary_cmd)


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

    if not getattr(args, "out", None):
        print(
            "--out is required: glossary writes glossary.json and glossary.md there, "
            "and --template ranks its form from that dictionary",
            file=sys.stderr,
        )
        return 2
    overrides = load_overrides(getattr(args, "overrides", None))
    if isinstance(overrides, int):
        return overrides
    found = _discover_lineage_documents(args.lineage)
    if isinstance(found, int):
        return found
    loaded = _load_contract_documents(*found, args.out, "glossary builder")
    if isinstance(loaded, int):
        return loaded
    documents = loaded.documents

    out_dir, root = Path(args.out), str(Path(args.lineage))
    options = [overrides, args.format, args.template, args.template_top, root]
    cache = open_cache(args, out_dir, found[1], "glossary", options)
    try:
        glossary = build_glossary(
            [item.document for item in documents],
            artifact_root=root,
            overrides=overrides,
            profiles=_profiles(documents, cache),
        )
    except ValueError as error:
        print(f"{args.lineage}: {error}", file=sys.stderr)
        return 1
    chosen = formats(args.format)
    _write(out_dir, glossary, chosen)
    template = _write_template(glossary, args)
    cache.commit([f"glossary.{name}" for name in sorted(chosen)])
    _report(glossary, template, args, loaded.counters() + cache.counters())
    return 0


def _profiles(documents, cache) -> list[dict]:
    """One semantic profile per document, from the fact cache when it is unchanged.

    The dictionary reads the profile the *document alone* proves, without diagnostics --
    the same profile ``build_glossary`` builds for itself -- so what is cached here is
    not interchangeable with what ``tables`` caches. The index's ``command`` says so.
    """
    from .render.semantic_profile import build_semantic_profile

    return [
        cache.facts(
            item, lambda item=item: {"profile": build_semantic_profile(item.document)}
        )["profile"]
        for item in documents
    ]


def _report(
    glossary: dict,
    template: dict | None,
    args: argparse.Namespace,
    counters: str,
) -> None:
    applied = glossary["overrides_applied"]
    print(
        f"Collected {len(glossary['terms'])} term(s) and {len(glossary['values'])} "
        f"value observation(s) from {glossary['corpus']['task_count']} task(s) "
        f"(overrides terms={applied['terms']}, values={applied['values']}, "
        f"blank={applied['blank']}, unmatched={len(applied['unmatched'])}, "
        f"{counters})"
    )
    if template is not None:
        print(
            f"Wrote a fill-in template of {template['generated']['value_count']} value(s) "
            f"across {template['generated']['column_count']} column(s) to {args.template}"
        )


def _write_template(glossary: dict, args: argparse.Namespace) -> dict | None:
    """WI-2.9 item C: the 取值含义 form, beside the dictionary it was ranked from.

    Two files under one ``--template`` path, because they are one artifact read two ways:
    the markdown is what a person fills in, the same-named JSON is what
    ``glossary --overrides`` reads back.
    """
    path = getattr(args, "template", None)
    if not path:
        return None
    markdown = Path(path)
    template = build_overrides_template(
        glossary, top=getattr(args, "template_top", TEMPLATE_TOP_DEFAULT)
    )
    markdown.parent.mkdir(parents=True, exist_ok=True)
    markdown.write_text(
        render_overrides_template_markdown(template, glossary), encoding="utf-8"
    )
    markdown.with_suffix(".json").write_text(
        json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return template


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
