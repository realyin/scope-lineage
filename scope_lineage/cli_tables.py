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

from .corpus_cache import add_incremental_arguments, open_cache
from .render.table_cards import (
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
        "--format",
        default="json,md",
        help="Comma-separated output formats: json, md (default: json,md)",
    )
    add_incremental_arguments(tables_cmd)


def formats(value: str | None) -> set[str]:
    return {name.strip() for name in (value or "json,md").split(",") if name.strip()}


def run_tables(args: argparse.Namespace) -> int:
    from .cli import _discover_lineage_documents, _load_contract_documents
    from .render.semantic_profile import build_semantic_profile

    found = _discover_lineage_documents(args.lineage)
    if isinstance(found, int):
        return found
    loaded = _load_contract_documents(*found, args.out, "table card builder")
    if isinstance(loaded, int):
        return loaded
    documents = loaded.documents

    out_dir = Path(args.out)
    cache = open_cache(
        args, out_dir, found[1], "tables", [args.format, str(Path(args.lineage))]
    )
    profiles = []
    for item in documents:
        try:
            profiles.append(
                cache.facts(
                    item,
                    lambda item=item: {
                        "profile": build_semantic_profile(item.document, item.diagnostics)
                    },
                )["profile"]
            )
        except ValueError as error:
            print(f"{item.path}: {error}", file=sys.stderr)
            return 1
    cards = build_table_cards(profiles, artifact_root=str(Path(args.lineage)))
    chosen = formats(args.format)
    _write_cards(out_dir, cards, chosen)
    cache.commit(_written(cards, chosen))

    print(
        f"Carded {len(cards['tables'])} table(s) from {cards['corpus']['task_count']} "
        f"task(s) ({loaded.counters()}{cache.counters()})"
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
