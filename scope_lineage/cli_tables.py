"""The ``scope-lineage tables`` subcommand: parser and runner.

Kept out of ``cli.py`` on purpose. ``tables`` is the one command whose unit of work is the
*corpus* rather than the document -- it reads every ``lineage.json`` under one root, builds
one semantic profile per task and publishes what the tasks together prove about each table.
The shared walk (``cli._discover_lineage_documents`` / ``cli._load_contract_documents``) is
imported inside the runner so this module can be imported from ``cli`` without a cycle.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .corpus_cache import add_incremental_arguments, open_cache, project_profile
from .metadata.column_samples import (
    SAMPLES_TOP_DEFAULT,
    ColumnSamplesError,
    load_column_samples,
)
from .render.table_cards import (
    PROFILE_FIELDS_READ,
    build_table_cards,
    render_table_card_markdown,
    render_table_index_markdown,
    table_card_filename,
)


def add_tables_parser(subcommands) -> None:
    tables_cmd = subcommands.add_parser(
        "tables",
        help=(
            "Aggregate a corpus of Core artifacts into per-table cards: "
            "tables.json, tables.md and tables/<db.table>.md"
        ),
    )
    tables_cmd.add_argument(
        "--lineage",
        required=True,
        help="One lineage.json file, or a directory searched recursively for lineage.json",
    )
    tables_cmd.add_argument(
        "--out",
        required=True,
        help="Directory for tables.json, tables.md and the tables/ card directory",
    )
    tables_cmd.add_argument(
        "--samples",
        help=(
            "Sample values to put on the cards: a table,column,value[,count] CSV, a "
            "directory of such CSVs, or a samples/1 JSON. Values are always masked for "
            "contact shapes and cut to length; keys that match no table or column are "
            "reported under samples_applied.unmatched rather than dropped"
        ),
    )
    tables_cmd.add_argument(
        "--samples-top",
        type=int,
        default=SAMPLES_TOP_DEFAULT,
        help=(
            "How many distinct values each column publishes, most frequent first where "
            f"the file gave counts (default: {SAMPLES_TOP_DEFAULT})"
        ),
    )
    tables_cmd.add_argument(
        "--format",
        default="json,md",
        help="Comma-separated output formats: json, md (default: json,md)",
    )
    add_incremental_arguments(tables_cmd)


def formats(value: str | None) -> set[str]:
    return {name.strip() for name in (value or "json,md").split(",") if name.strip()}


def _facts(item) -> dict:
    """What one task contributes to the cards: its profile, cut to what they read.

    P2. The builder is handed the projection whether it came from the fact cache or from
    this run, so a reused task and a recomputed one are the same shape by construction
    rather than by a comparison somebody remembered to make.
    """
    from .render.semantic_profile import build_semantic_profile

    profile = build_semantic_profile(item.document, item.diagnostics)
    return {"profile": project_profile(profile, PROFILE_FIELDS_READ)}


def run_tables(args: argparse.Namespace) -> int:
    from .cli import _discover_lineage_documents, _load_contract_documents

    try:
        samples = load_column_samples(
            getattr(args, "samples", None),
            top=getattr(args, "samples_top", SAMPLES_TOP_DEFAULT),
        )
    except ColumnSamplesError as error:
        print(error, file=sys.stderr)
        return 2
    found = _discover_lineage_documents(args.lineage)
    if isinstance(found, int):
        return found
    loaded = _load_contract_documents(*found, args.out, "table card builder")
    if isinstance(loaded, int):
        return loaded
    documents = loaded.documents

    out_dir, root = Path(args.out), str(Path(args.lineage))
    options = [args.format, root, _samples_digest(args), args.samples_top]
    cache = open_cache(
        args, out_dir, found[1], "tables", options, fields=[PROFILE_FIELDS_READ]
    )

    profiles = []
    for item in documents:
        try:
            profiles.append(cache.facts(item, lambda item=item: _facts(item))["profile"])
        except ValueError as error:
            print(f"{item.path}: {error}", file=sys.stderr)
            return 1
    cards = build_table_cards(profiles, artifact_root=root, samples=samples)
    chosen = formats(args.format)
    _write_cards(out_dir, cards, chosen)
    cache.commit(_written(cards, chosen))

    print(
        f"Carded {len(cards['tables'])} table(s) from {cards['corpus']['task_count']} "
        f"task(s) ({loaded.counters()}{_samples_report(cards)}{cache.counters()})"
    )
    return 0


def _written(cards: dict, chosen: set[str]) -> list[str]:
    """Every document one run published, relative to ``--out``."""
    written = ["tables.json"] if "json" in chosen else []
    if "md" not in chosen:
        return written
    return [
        *written,
        "tables.md",
        *(f"tables/{table_card_filename(card['table'])}" for card in cards["tables"]),
    ]


def _samples_digest(args: argparse.Namespace) -> list[str | None]:
    """The sample files' *contents*, so editing one in place invalidates the cache.

    Samples land on the cards rather than in the per-task facts, so a cached profile is
    still correct when they change. The digest is in the options anyway, for the reason
    the whole options digest exists: one rule -- anything outside the corpus that steers
    the run invalidates the index -- is worth more than a per-flag argument about which
    half of the pipeline each flag reaches.
    """
    from .corpus_cache import file_digest

    source = getattr(args, "samples", None)
    if not source:
        return []
    root = Path(source)
    files = sorted(root.rglob("*")) if root.is_dir() else [root]
    return [file_digest(path) for path in files if path.is_file()]


def _samples_report(cards: dict) -> str:
    """The samples half of a run, or nothing at all when no samples file was supplied.

    The unmatched keys are named, not merely counted: a typo in a hand-made export is
    exactly what its author cannot see, and a count alone does not say which line to fix.
    """
    applied = cards.get("samples_applied")
    if applied is None:
        return ""
    unmatched = applied["unmatched"]
    detail = f" ({'、'.join(unmatched)})" if unmatched else ""
    return (
        f", samples_columns={applied['columns_sampled']}, "
        f"samples_unmatched={len(unmatched)}{detail}"
    )


def _write_cards(out: Path, cards: dict, chosen: set[str]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    if "json" in chosen:
        (out / "tables.json").write_text(
            json.dumps(cards, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if "md" not in chosen:
        return
    (out / "tables.md").write_text(render_table_index_markdown(cards), encoding="utf-8")
    card_dir = out / "tables"
    card_dir.mkdir(parents=True, exist_ok=True)
    for card in cards["tables"]:
        (card_dir / table_card_filename(card["table"])).write_text(
            render_table_card_markdown(card), encoding="utf-8"
        )
