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
from collections.abc import Mapping, Sequence
from pathlib import Path

from .corpus_cache import (
    add_incremental_arguments,
    open_cache,
    project_profile,
    union_fields,
)
from .render.glossary import PROFILE_FIELDS_READ as GLOSSARY_FIELDS_READ
from .render.ontology import (
    PROFILE_FIELDS_READ as ONTOLOGY_FIELDS_READ,
)
from .render.ontology import (
    build_ontology,
    entity_table_cards,
    render_ontology_index_markdown,
    render_ontology_table_card_markdown,
)
from .render.ontology_export import EXPORT_FILENAMES, EXPORT_FORMATS, render_export
from .render.review_batches import (
    BATCH_BY,
    BATCHES_DIR,
    DEFAULT_BATCH_SIZE,
    write_review_batches,
)
from .render.table_cards import PROFILE_FIELDS_READ as TABLE_FIELDS_READ
from .render.table_cards import table_card_filename

# P2. The ontology is merged from three builders over one collected profile -- itself,
# the table cards (built here unless `--tables` supplied one) and, underneath both, the
# value dictionary. The first two read the same profile, so the cached payload is the
# union of their two lists; the dictionary reads a profile built *without* diagnostics,
# which is a second, separately projected payload rather than a subset of the first.
PROFILE_FIELDS_CACHED = union_fields(ONTOLOGY_FIELDS_READ, TABLE_FIELDS_READ)
CACHED_FIELDS = (PROFILE_FIELDS_CACHED, GLOSSARY_FIELDS_READ)


def add_ontology_parser(subcommands) -> None:
    ontology_cmd = subcommands.add_parser(
        "ontology",
        help=(
            "Aggregate a corpus of Core artifacts into one ontology candidate: "
            "concepts, the relations between them, the tables that represent them, "
            "constraints and cross-task conflicts"
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
        action="append",
        help=(
            "A tables.json written by `scope-lineage tables`; built in memory over the "
            "same corpus when it is not given. Repeatable: several are merged first "
            "(P7), so a key proven in another corpus can carry a relation here, with "
            "that corpus named in the relation's evidence"
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
        "--concept-overrides",
        action="append",
        help=(
            "A reviewed concepts.overrides.json (concept-overrides/1): the confirmed "
            "concept names, kinds, member roles, the concepts it creates, the merges "
            "and the splits. Applied after the concept layer is built and before the "
            "concept relations are folded, so a "
            "merge moves that concept's edges too; anything it names that the corpus "
            "does not contain is reported in concept_overrides_applied.unmatched. "
            "Repeatable (N1a): a wide corpus is reviewed one batch at a time and each "
            "batch writes its own file, so the files are folded in the order given -- "
            "a target key two of them name is won by the later one and the pair is "
            "reported in concept_overrides_applied.conflicts, and "
            "concept_overrides_applied.sources says how many entries each file won"
        ),
    )
    _add_review_batch_arguments(ontology_cmd)
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
    ontology_cmd.add_argument(
        "--legacy-keys",
        action="store_true",
        help=(
            "DEPRECATED. Also write the ontology-json/1 key spellings (entities, "
            "concept_relations, concept_representation_links, unassigned_tables) as "
            "aliases of the ontology-json/2 keys, so a consumer can migrate over one "
            "release. `relations` is not aliased: it now holds the concept relations, "
            "and the table-level edges moved to `table_relations`"
        ),
    )
    add_incremental_arguments(ontology_cmd)


def _add_review_batch_arguments(ontology_cmd) -> None:
    """N1b: cut the provisional concepts into batches a reviewer can finish.

    A flag on ``ontology`` rather than an ``ontology review-batches`` sub-subcommand,
    because every command of this CLI is a flat subcommand of one parser and a nested
    one here would be the only place a reader has to look twice. It runs *after* the
    build, over the ontology this same run published, which is also what makes it
    cheap: the corpus is already walked and the concepts are already folded.
    """
    ontology_cmd.add_argument(
        "--review-batches",
        help=(
            "Also cut the provisional concepts into review batches under "
            f"<dir>/{BATCHES_DIR}: one batch-NN.md worksheet, one "
            "batch-NN.overrides.json skeleton and one index.md saying in which order "
            "to work them. Written after the ontology, from the one this run built"
        ),
    )
    ontology_cmd.add_argument(
        "--review-batches-by",
        default=BATCH_BY[0],
        help=(
            "How the batches are cut: family groups the concepts by table family, "
            "domain by the tables' naming_hints.domain (then project), size is a plain "
            f"chunk in impact order (one of {', '.join(BATCH_BY)}; default {BATCH_BY[0]})"
        ),
    )
    ontology_cmd.add_argument(
        "--review-batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=(
            "How many concepts one batch holds before the next one starts "
            f"(default {DEFAULT_BATCH_SIZE}); a family or a domain larger than this "
            "stays whole in a batch of its own rather than being cut in two"
        ),
    )


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


def _supplied_tables(args: argparse.Namespace, documents: Sequence[Mapping]):
    """The ``--tables`` documents merged into one, None when none was given, or the code.

    P7: several corpora's cards are folded together before anything is built, so the
    ontology asks one question -- "what does the card say about this table" -- whether
    the answer came from the corpus in front of it or from a batch walked elsewhere.

    Q6: folded together *for this corpus*. A batch walked over a whole warehouse can be
    orders of magnitude larger than the corpus borrowing from it, and every table in it
    the corpus never names is a card merged, held and scanned for nothing. The corpus's
    own table names decide what comes in, so the run costs the corpus rather than the
    batch. ``tables --merge`` still merges everything: that document is published for
    readers who have no corpus in hand, and a card missing from it is simply missing.
    """
    from .cli import _load_corpus_document
    from .render.ontology import corpus_table_names
    from .render.table_cards import DOC_FORMAT as TABLES_DOC_FORMAT
    from .render.table_cards import merge_table_cards

    supplied = []
    for path in getattr(args, "tables", None) or []:
        document = _load_corpus_document(path, "--tables", TABLES_DOC_FORMAT)
        if isinstance(document, int):
            return document
        supplied.append(document)
    if not supplied:
        return None
    return merge_table_cards(*supplied, needed=corpus_table_names(documents))


def _supplied_corpus(args: argparse.Namespace, documents: Sequence[Mapping]):
    """``(tables, glossary)``, either of them None, or the exit code of a bad flag."""
    from .cli import _load_corpus_document
    from .render.glossary import DOC_FORMAT as GLOSSARY_DOC_FORMAT

    tables = _supplied_tables(args, documents)
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
    reviewed = _concept_overrides(args)
    if isinstance(reviewed, int):
        return reviewed
    concept_files, concept_overrides = reviewed
    found = _discover_lineage_documents(args.lineage)
    if isinstance(found, int):
        return found
    loaded = _load_contract_documents(*found, args.out, "ontology builder")
    if isinstance(loaded, int):
        return loaded

    documents = [item.document for item in loaded.documents]
    # Q6: the corpus is walked first because the cards are merged *for* it -- the
    # narrowing needs the table names before it can decide what to fold in.
    supplied = _supplied_corpus(args, documents)
    if isinstance(supplied, int):
        return supplied
    tables, glossary = supplied

    out_dir, root = Path(args.out), str(Path(args.lineage))
    chosen_exports = exports(getattr(args, "export", None))
    # Q7: no corpus path in the digest -- the same task modelled from another
    # directory derives the same facts, and ``--cache-from`` borrows them.
    options = [
        args.format,
        bool(getattr(args, "legacy_keys", False)),
        overrides,
        concept_overrides,
        tables,
        glossary,
        chosen_exports,
    ]
    # N1a: the digest is over the documents, not the paths -- but the *order* they
    # apply in is part of the answer, and the list above already carries it.
    cache = open_cache(args, out_dir, found[1], "ontology", options, fields=CACHED_FIELDS)
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
        concept_overrides=concept_overrides,
        concept_override_files=concept_files,
        artifact_root=root,
        legacy_keys=bool(getattr(args, "legacy_keys", False)),
    )
    # P7: one card file per entity. Cards merged in from another corpus that this one
    # never touched lent their evidence to the build; they are not tables of this model.
    cards = entity_table_cards(cards, ontology)
    chosen = formats(args.format)
    _write_ontology(out_dir, ontology, cards, chosen)
    _write_exports(out_dir, ontology, chosen_exports)
    cache.commit(_written(cards, chosen, chosen_exports))
    _report(
        ontology,
        overrides,
        concept_overrides,
        chosen_exports,
        loaded.counters() + cache.counters(),
    )
    return _write_review_batches(args, ontology)


def _concept_overrides(args: argparse.Namespace):
    """N1a: every ``--concept-overrides`` file, in order, or the exit code of a bad one.

    ``(files, documents)`` rather than one merged document, because the merge itself is
    what has to be reported: which file won a key both of them name is an answer a
    reviewer needs, and only the builder can see whether a key was named twice.
    """
    from .cli_glossary import load_overrides

    files, documents = [], []
    for path in getattr(args, "concept_overrides", None) or []:
        document = load_overrides(path, "--concept-overrides")
        if isinstance(document, int):
            return document
        files.append(str(path))
        documents.append(document)
    return files, documents


def _write_review_batches(args: argparse.Namespace, ontology: Mapping) -> int:
    """N1b: the review batches, written from the ontology this run just published."""
    target = getattr(args, "review_batches", None)
    if not target:
        return 0
    by = str(getattr(args, "review_batches_by", None) or BATCH_BY[0])
    size = int(getattr(args, "review_batch_size", None) or DEFAULT_BATCH_SIZE)
    written = write_review_batches(ontology, Path(target), by=by, batch_size=size)
    batches = (len(written) - 1) // 2
    print(
        f"Wrote review batches: {batches} batch(es) over "
        f"{ontology.get('provisional_count')} provisional concept(s) by {by} "
        f"(at most {size} each) to {Path(target) / BATCHES_DIR}"
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
    ontology: dict,
    overrides,
    concept_overrides,
    chosen_exports: Sequence[str],
    counters: str,
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
    confirmations += _concept_confirmations(ontology, concept_overrides)
    print(
        f"Modelled {len(ontology['concepts'])} concept(s), "
        f"{len(ontology['relations'])} relation(s), "
        f"{len(ontology['tables'])} table(s), "
        f"{len(ontology['table_relations'])} table relation(s), "
        f"{len(ontology['constraints'])} constraint(s) and "
        f"{len(ontology['findings'])} finding(s) from "
        f"{ontology['corpus'].get('task_count')} task(s){confirmations}{exported} "
        f"({counters})"
    )


def _concept_confirmations(ontology: dict, concept_overrides) -> str:
    """What the reviewed concept layer changed, printed only when one was supplied.

    N1a: the conflict count is on this line rather than left to the JSON, because a
    reviewer who split the round over several files finds out here that two of them
    answered the same question -- which is the one thing about a batched round that
    nobody set out to do.
    """
    if not concept_overrides:
        return ""
    applied = ontology["concept_overrides_applied"]
    return (
        f", reviewed {applied['concepts']} concept(s) from "
        f"{len(applied['sources'])} file(s), "
        f"created {len(applied['created'])}, tables_added {applied['tables_added']}, "
        f"{applied['merges']} merge(s) "
        f"and {applied['splits']} split(s), {len(applied['unmatched'])} unmatched, "
        f"{len(applied['conflicts'])} conflict(s)"
    )


def _collect(items, cache, *, needs_glossary: bool) -> list[dict]:
    """The per-document facts the ontology is merged from, cached under their digests.

    Two profiles per document, because the ontology is derived from two layers that read
    the corpus differently: the entity/relation half reads the profile *with* the task's
    diagnostics, and the value dictionary underneath it reads the profile the document
    alone proves. A supplied ``--glossary`` makes the second one unnecessary.

    P2: each is cut to what the builders that read it read, and each builder is handed
    the same cut whether it came from the cache or from this run.
    """
    from .render.semantic_profile import build_semantic_profile

    def build(item) -> dict:
        profile = build_semantic_profile(item.document, item.diagnostics)
        facts = {"profile": project_profile(profile, PROFILE_FIELDS_CACHED)}
        if needs_glossary:
            facts["glossary_profile"] = project_profile(
                build_semantic_profile(item.document), GLOSSARY_FIELDS_READ
            )
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
