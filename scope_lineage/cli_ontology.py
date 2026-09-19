"""The ``scope-lineage ontology`` subcommand: parser and runner.

Kept out of ``cli.py`` for the same reason ``tables`` and ``glossary`` are: its unit of
work is the *corpus*. It is also the one command derived on top of two other corpus
documents -- the table cards and the value dictionary -- so it accepts both as files
and builds whichever it was not given from the same corpus it just walked, in memory.
Either way each statement is profiled exactly once and all three corpus artifacts read
that one profile.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .corpus_cache import add_incremental_arguments, open_cache
from .render.ontology import (
    build_ontology,
    render_ontology_index_markdown,
    render_ontology_table_card_markdown,
)
from .render.ontology_export import EXPORT_FILENAMES, EXPORT_FORMATS, render_export
from .render.table_cards import table_card_filename


def add_ontology_parser(subcommands) -> None:
    ontology_cmd = subcommands.add_parser(
        "ontology",
        help=(
            "Aggregate a corpus of Core artifacts into one ontology candidate: "
            "entities, relations, constraints and cross-task conflicts"
        ),
    )
    ontology_cmd.add_argument(
        "--lineage",
        required=True,
        help="One lineage.json file, or a directory searched recursively for lineage.json",
    )
    ontology_cmd.add_argument(
        "--out",
        required=True,
        help=(
            "Directory for ontology.json, ontology.md and the tables/ card "
            "directory (the table cards with the ontology sections appended)"
        ),
    )
    ontology_cmd.add_argument(
        "--tables",
        help=(
            "A tables.json written by `scope-lineage tables`; built in memory over the "
            "same corpus when it is not given"
        ),
    )
    ontology_cmd.add_argument(
        "--glossary",
        help=(
            "A glossary.json written by `scope-lineage glossary`; built in memory over "
            "the same corpus when it is not given"
        ),
    )
    ontology_cmd.add_argument(
        "--overrides",
        help=(
            "A reviewed ontology.overrides.json: the confirmed relations and identity "
            "keys. A confirmed assertion is published at tier `confirmed`; a key or "
            "relation the corpus does not contain is reported in "
            "overrides_applied.unmatched rather than dropped"
        ),
    )
    ontology_cmd.add_argument(
        "--format",
        default="json,md",
        help="Comma-separated output formats: json, md (default: json,md)",
    )
    ontology_cmd.add_argument(
        "--export",
        action="append",
        help=(
            "Also export the candidate for an RDF toolchain: linkml writes "
            "ontology.linkml.yaml and shacl writes ontology.shacl.ttl, beside "
            "ontology.json. Repeatable, or one comma-separated list; nothing is "
            "exported by default"
        ),
    )
    add_incremental_arguments(ontology_cmd)


def formats(value: str | None) -> set[str]:
    return {name.strip() for name in (value or "json,md").split(",") if name.strip()}


def exports(values) -> list[str]:
    """The chosen export formats, in the exporter's own order so a run is stable.

    ``--export`` is both repeatable and comma-separated because a corpus job is as
    likely to be assembled by a shell loop as typed by hand, and the two spellings must
    not mean different things. Anything unknown is kept, sorted, so the caller in
    ``cli.py`` can name it in the argument error rather than silently write nothing.
    """
    chosen = {
        name.strip()
        for value in (values or ())
        for name in str(value).split(",")
        if name.strip()
    }
    known = [name for name in EXPORT_FORMATS if name in chosen]
    return known + sorted(chosen - set(EXPORT_FORMATS))


def _supplied_corpus(args: argparse.Namespace):
    """``(tables, glossary)``, either of them None, or the exit code of a bad flag."""
    from .cli import _load_corpus_document
    from .render.glossary import DOC_FORMAT as GLOSSARY_DOC_FORMAT
    from .render.table_cards import DOC_FORMAT as TABLES_DOC_FORMAT

    tables = _load_corpus_document(
        getattr(args, "tables", None), "--tables", TABLES_DOC_FORMAT
    )
    if isinstance(tables, int):
        return tables
    glossary = _load_corpus_document(
        getattr(args, "glossary", None), "--glossary", GLOSSARY_DOC_FORMAT
    )
    if isinstance(glossary, int):
        return glossary
    return tables, glossary


def run_ontology(args: argparse.Namespace) -> int:
    from .cli import _discover_lineage_documents, _load_contract_documents
    from .cli_glossary import load_overrides

    overrides = load_overrides(getattr(args, "overrides", None))
    if isinstance(overrides, int):
        return overrides
    supplied = _supplied_corpus(args)
    if isinstance(supplied, int):
        return supplied
    tables, glossary = supplied

    found = _discover_lineage_documents(args.lineage)
    if isinstance(found, int):
        return found
    loaded = _load_contract_documents(*found, args.out, "ontology builder")
    if isinstance(loaded, int):
        return loaded

    documents = [item.document for item in loaded.documents]
    out_dir, root = Path(args.out), str(Path(args.lineage))
    chosen_exports = exports(getattr(args, "export", None))
    options = [args.format, root, overrides, tables, glossary, chosen_exports]
    cache = open_cache(args, out_dir, found[1], "ontology", options)
    try:
        collected = _collect(loaded.documents, cache, needs_glossary=glossary is None)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    profiles, glossary, cards = _layers(
        collected, documents, tables=tables, glossary=glossary, root=root
    )
    ontology = build_ontology(
        documents,
        profiles,
        tables=cards,
        glossary=glossary,
        overrides=overrides,
        artifact_root=root,
    )
    chosen = formats(args.format)
    _write_ontology(out_dir, ontology, cards, chosen)
    _write_exports(out_dir, ontology, chosen_exports)
    cache.commit(_written(cards, chosen, chosen_exports))
    _report(
        ontology, overrides, chosen_exports, loaded.counters() + cache.counters()
    )
    return 0


def _layers(collected, documents, *, tables, glossary, root: str):
    """``(profiles, value dictionary, table cards)``: what the builder reads.

    Both derived layers are built here rather than inside the builder, and for the same
    reason: each is also read outside it. The cards are what the ontology *markdown*
    renders -- an ontology card is a table card with five sections appended, and a
    second, separately built copy would be a way for the two halves of one file to
    disagree -- and the dictionary would otherwise be built from a second set of
    profiles rather than the ones already collected (and cached) here.
    """
    from .render.glossary import build_glossary
    from .render.table_cards import build_table_cards

    profiles = [facts["profile"] for facts in collected]
    if glossary is None:
        glossary = build_glossary(
            documents,
            artifact_root=root,
            profiles=[facts["glossary_profile"] for facts in collected],
        )
    cards = dict(tables) if tables else build_table_cards(profiles, artifact_root=root)
    return profiles, glossary, cards


def _report(
    ontology: dict, overrides, chosen_exports: Sequence[str], counters: str
) -> None:
    """The one summary line this command prints."""
    applied = ontology["overrides_applied"]
    exported = f", exported {', '.join(chosen_exports)}" if chosen_exports else ""
    confirmations = ""
    if overrides is not None:
        confirmations = (
            f", confirmed {applied['relations']} relation(s) and "
            f"{applied['keys']} key(s), {len(applied['unmatched'])} unmatched"
        )
    print(
        f"Modelled {len(ontology['entities'])} entity(ies), "
        f"{len(ontology['relations'])} relation(s), "
        f"{len(ontology['constraints'])} constraint(s) and "
        f"{len(ontology['findings'])} finding(s) from "
        f"{ontology['corpus'].get('task_count')} task(s){confirmations}{exported} "
        f"({counters})"
    )


def _collect(items, cache, *, needs_glossary: bool) -> list[dict]:
    """The per-document facts the ontology is merged from, cached under their digests.

    Two profiles per document, because the ontology is derived from two layers that read
    the corpus differently: the entity/relation half reads the profile *with* the task's
    diagnostics, and the value dictionary underneath it reads the profile the document
    alone proves. A supplied ``--glossary`` makes the second one unnecessary.
    """
    from .render.semantic_profile import build_semantic_profile

    def build(item) -> dict:
        facts = {"profile": build_semantic_profile(item.document, item.diagnostics)}
        if needs_glossary:
            facts["glossary_profile"] = build_semantic_profile(item.document)
        return facts

    collected = []
    for item in items:
        try:
            collected.append(cache.facts(item, lambda item=item: build(item)))
        except ValueError as error:
            raise ValueError(f"{item.path}: {error}") from error
    return collected


def _written(
    cards: dict, chosen: set[str], chosen_exports: Sequence[str]
) -> list[str]:
    """Every document one run published, relative to ``--out``."""
    written = ["ontology.json"] if "json" in chosen else []
    written += [EXPORT_FILENAMES[export] for export in chosen_exports]
    if "md" not in chosen:
        return written
    return [
        *written,
        "ontology.md",
        *(
            f"tables/{table_card_filename(card['table'])}"
            for card in cards.get("tables") or []
        ),
    ]


def _write_ontology(out: Path, ontology: dict, cards: dict, chosen: set[str]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    if "json" in chosen:
        (out / "ontology.json").write_text(
            json.dumps(ontology, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if "md" not in chosen:
        return
    (out / "ontology.md").write_text(
        render_ontology_index_markdown(ontology), encoding="utf-8"
    )
    # Same directory and same filename rule as `tables`, so a corpus can be re-rendered
    # over an existing card directory and the links between the two documents hold.
    card_dir = out / "tables"
    card_dir.mkdir(parents=True, exist_ok=True)
    for card in cards.get("tables") or []:
        (card_dir / table_card_filename(card["table"])).write_text(
            render_ontology_table_card_markdown(card, ontology), encoding="utf-8"
        )


def _write_exports(out: Path, ontology: dict, chosen: Sequence[str]) -> None:
    """The thin exports, beside ``ontology.json`` and independent of ``--format``.

    Whoever reads the markdown and whoever loads a graph are two different people, so
    asking for one is never a statement about the other.
    """
    if not chosen:
        return
    out.mkdir(parents=True, exist_ok=True)
    for export in chosen:
        (out / EXPORT_FILENAMES[export]).write_text(
            render_export(ontology, export), encoding="utf-8"
        )
