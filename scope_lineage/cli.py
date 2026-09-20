"""Minimal command line interface for the public Lineage Core."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from .cli_glossary import add_glossary_parser, formats as _glossary_formats, run_glossary
from .cli_ontology import (
    EXPORT_FORMATS as _ONTOLOGY_EXPORTS,
    add_ontology_parser,
    exports as _ontology_exports,
    formats as _ontology_formats,
    run_ontology,
)
from .cli_tables import add_tables_parser, formats as _tables_formats, run_tables
from .contract import write_task_lineage
from .corpus_cache import add_incremental_arguments, open_cache
from .metadata.schema_metadata import load_schema, load_schema_sources
from .metadata.target_table_metadata import load_target_table_metadata
from .scope.expansion_budget import EXPANSION_MAX_SUBSTITUTIONS
from .scope.task_lineage import parse_task_lineage


def _package_version() -> str:
    try:
        from importlib.metadata import version

        return version("scope-lineage")
    except Exception:  # noqa: BLE001 - a source checkout without metadata still deserves --version
        return "unknown (source checkout)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scope-lineage")
    parser.add_argument(
        "--version", action="version", version=f"scope-lineage {_package_version()}"
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    parse_cmd = subcommands.add_parser(
        "parse",
        help="Parse SQL or exported task JSON into Core artifacts",
    )
    input_group = parse_cmd.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--sql-file", help="Path to one SQL file")
    input_group.add_argument(
        "--task-file",
        help="Path to one task JSON (meta/sql wrapper or legacy task_name/sql object)",
    )
    input_group.add_argument(
        "--input-dir",
        action="append",
        help=(
            "Directory of task JSON files; files are discovered recursively. "
            "Repeatable: each directory is walked in the order given and a file named "
            "by more than one of them is parsed once"
        ),
    )
    parse_cmd.add_argument(
        "--include-glob",
        action="append",
        default=[],
        help=(
            "Only parse input-dir JSON paths matching this glob; repeatable. "
            "Default: *.json"
        ),
    )
    parse_cmd.add_argument(
        "--exclude-glob",
        action="append",
        default=[],
        help="Exclude input-dir JSON paths matching this glob; repeatable",
    )
    parse_cmd.add_argument(
        "--task-name",
        help="Override the task name for --sql-file or --task-file",
    )
    parse_cmd.add_argument("--out", required=True, help="Output directory")
    parse_cmd.add_argument(
        "--schema",
        help="Optional source-table schema file or rich-JSON directory (JSON preferred; CSV fallback)",
    )
    parse_cmd.add_argument(
        "--schema-fallback",
        action="append",
        default=[],
        help=(
            "Additional CSV/JSON schema source used only for tables absent from "
            "the authoritative --schema; repeatable"
        ),
    )
    parse_cmd.add_argument(
        "--target-ddl-metadata",
        help="Optional authoritative target-table DDL/Schema JSON file or directory",
    )
    parse_cmd.add_argument(
        "--metadata-patch",
        action="append",
        default=[],
        help=(
            "A reviewed metadata-patch/1 file: confirmed table and column comments that "
            "override the schema and the target DDL. Repeatable; later files win. "
            "Patched entries are marked (comment_source / patch_applied), their "
            "comments are redacted like any other (--no-redact-comments), and keys "
            "that match nothing are reported rather than dropped"
        ),
    )
    parse_cmd.add_argument(
        "--expansion-limit",
        type=int,
        default=None,
        help=(
            "How many upstream expressions may be inlined into one expanded_expression "
            f"before the capacity guard stops (default: {EXPANSION_MAX_SUBSTITUTIONS}). "
            "A task that hits it ends partial with an expression_expansion_bounded gap "
            "naming the limit; raise it to expand deeper nesting at the cost of a "
            "larger artifact"
        ),
    )
    parse_cmd.add_argument(
        "--partition-overwrite-mode",
        help=(
            "The cluster's spark.sql.sources.partitionOverwriteMode (static or dynamic, "
            "case-insensitive). Spark's own default is static; declare what your "
            "deployment actually runs with. A SET in the script always wins. "
            "Requires --contract-version 2.0."
        ),
    )
    parse_cmd.add_argument(
        "--catalog-prefixes",
        help=(
            "Comma-separated leading catalog names to remove from table identities. "
            "Overrides SCOPE_LINEAGE_CATALOG_PREFIXES; by default catalogs are preserved."
        ),
    )
    parse_cmd.add_argument(
        "--sanitize-metadata-nul",
        action="store_true",
        help="Remove NUL bytes from metadata inputs and report provenance",
    )
    parse_cmd.add_argument(
        "--metadata-preflight",
        action="store_true",
        help=(
            "Check schema coverage only: report every referenced table missing from "
            "--schema, write metadata_gaps.json into --out, produce no lineage "
            "artifacts, and return non-zero when gaps exist — so "
            "`parse --metadata-preflight ... && parse ...` stops for a decision "
            "before parsing with incomplete metadata"
        ),
    )
    parse_cmd.add_argument(
        "--allow-partial",
        action="store_true",
        help="Return zero even when a statement produced parse_status=failed",
    )
    parse_cmd.add_argument(
        "--contract-version",
        choices=("2.0",),
        default="2.0",
        help=(
            "Output contract: 2.0, one task-level ordered table-state artifact. "
            "Contract 1.0 was removed after its deprecation window; the flag stays "
            "one release so a 1.0 request fails with this message instead of an "
            "unknown-argument error"
        ),
    )
    parse_cmd.add_argument(
        "--compact-json",
        action="store_true",
        help="Write the same JSON contract without pretty-print whitespace",
    )
    _add_parse_policy_arguments(parse_cmd)

    _add_derived_view_parsers(subcommands)
    add_tables_parser(subcommands)
    add_glossary_parser(subcommands)
    add_ontology_parser(subcommands)

    validate_cmd = subcommands.add_parser(
        "validate",
        help=(
            "Validate existing lineage.json documents: JSON schema, id cross-references, "
            "and cross-layer consistency invariants"
        ),
    )
    validate_cmd.add_argument(
        "--lineage",
        required=True,
        help="One lineage.json file, or a directory searched recursively for lineage.json",
    )

    args = parser.parse_args(argv)
    if args.command == "parse":
        if args.input_dir and args.task_name:
            parser.error("--task-name cannot be used with --input-dir")
        if (args.include_glob or args.exclude_glob) and not args.input_dir:
            parser.error("--include-glob/--exclude-glob require --input-dir")
        if getattr(args, "expansion_limit", None) is not None and args.expansion_limit < 1:
            parser.error(
                "--expansion-limit must be a positive number of substitutions, got "
                f"{args.expansion_limit}"
            )
        if getattr(args, "partition_overwrite_mode", None) is not None:
            # Validated here rather than per input: one bad value is one error, not one
            # per task. `nonstrict` is the neighbouring Hive key's value and the
            # predictable mistake.
            if args.partition_overwrite_mode.strip().lower() not in {"static", "dynamic"}:
                parser.error(
                    "--partition-overwrite-mode must be static or dynamic, got "
                    f"{args.partition_overwrite_mode!r}"
                )
        with _catalog_prefix_override(args.catalog_prefixes):
            return _parse_inputs(args)
    if args.command == "render":
        return _render_inputs(args)
    if args.command == "describe":
        unknown_formats = _describe_formats(args.format) - {"json", "md"}
        if unknown_formats:
            parser.error(
                f"--format accepts json and md, got {sorted(unknown_formats)}"
            )
        return _describe_inputs(args)
    if args.command == "tables":
        unknown_formats = _tables_formats(args.format) - {"json", "md"}
        if unknown_formats:
            parser.error(f"--format accepts json and md, got {sorted(unknown_formats)}")
        if not args.lineage and not args.merge:
            parser.error("one of --lineage or --merge is required")
        return run_tables(args)
    if args.command == "glossary":
        unknown_formats = _glossary_formats(args.format) - {"json", "md"}
        if unknown_formats:
            parser.error(f"--format accepts json and md, got {sorted(unknown_formats)}")
        return run_glossary(args)
    if args.command == "ontology":
        unknown_formats = _ontology_formats(args.format) - {"json", "md"}
        if unknown_formats:
            parser.error(f"--format accepts json and md, got {sorted(unknown_formats)}")
        unknown_exports = [
            name
            for name in _ontology_exports(args.export)
            if name not in _ONTOLOGY_EXPORTS
        ]
        if unknown_exports:
            parser.error(f"--export accepts linkml and shacl, got {unknown_exports}")
        return run_ontology(args)
    if args.command == "validate":
        return _validate_inputs(args)
    parser.error(f"unknown command: {args.command}")
    return 2


def _add_parse_policy_arguments(parse_cmd) -> None:
    """What `parse` is allowed to publish, and when it is allowed to succeed.

    These options do not change what is parsed -- they decide which quality outcomes end
    the run non-zero, and which facts reach the artifact at all.
    """
    parse_cmd.add_argument(
        "--quality-policy",
        choices=("permissive", "balanced", "strict"),
        default="permissive",
        help=(
            "Quality gate: permissive preserves parse-only exit behavior; balanced "
            "rejects unsupported row mutations; strict also rejects recovered syntax, "
            "root-impact lineage gaps, and target-binding fallback"
        ),
    )
    parse_cmd.add_argument(
        "--strip-comments",
        action="store_true",
        help=(
            "Drop the SQL author's comments from the artifacts. They are collected by "
            "default (statement header, per-output, per-logic-block) and may contain "
            "information the SQL itself does not state"
        ),
    )
    parse_cmd.add_argument(
        "--no-redact-comments",
        action="store_true",
        help=(
            "Publish the comments exactly as written. By default an email address, a "
            "phone number or an ID number inside a comment (the SQL author's, the "
            "schema's, a --metadata-patch answer, and the task description) is replaced "
            "by <email>/<phone>/<id>; the rest of the text is "
            "kept either way. Shape matching, so neither exhaustive nor certain -- use "
            "--strip-comments when no comment may leave the machine"
        ),
    )
    parse_cmd.add_argument(
        "--fail-on-root-gap",
        action="store_true",
        help="Return non-zero when a lineage fact gap impacts a final target field",
    )
    parse_cmd.add_argument(
        "--fail-on-unsupported-mutation",
        action="store_true",
        help="Return non-zero when DELETE/UPDATE/TRUNCATE is not modeled",
    )
    parse_cmd.add_argument(
        "--fail-on-binding-fallback",
        action="store_true",
        help="Return non-zero when authoritative target-field binding falls back",
    )


def _add_derived_view_parsers(subcommands) -> None:
    """The two contract-derived view commands. Same input options, different document.

    ``render`` writes the field-mapping view, ``describe`` writes the task-semantic
    view; both walk one lineage.json or a tree of them (``cli._discover_lineage_documents``).
    """
    render_cmd = subcommands.add_parser(
        "render",
        help="Render mapping.md field-mapping documents from existing Core artifacts",
    )
    render_cmd.add_argument(
        "--lineage",
        required=True,
        help="One lineage.json file, or a directory searched recursively for lineage.json",
    )
    render_cmd.add_argument(
        "--out",
        help=(
            "Directory for the rendered mapping.md files, mirroring the input tree; "
            "default writes mapping.md next to each lineage.json"
        ),
    )
    render_cmd.add_argument(
        "--field",
        action="append",
        default=None,
        help="Restrict the per-field step sections to this target field; repeatable",
    )
    render_cmd.add_argument(
        "--expanded",
        action="store_true",
        help="Add the fully expanded physical-field expression under each step",
    )
    render_cmd.add_argument(
        "--sections",
        help="Comma-separated section names to render (default: all)",
    )

    describe_cmd = subcommands.add_parser(
        "describe",
        help=(
            "Describe what a task does: semantic.json / semantic.md derived from "
            "existing Core artifacts"
        ),
    )
    describe_cmd.add_argument(
        "--lineage",
        required=True,
        help="One lineage.json file, or a directory searched recursively for lineage.json",
    )
    describe_cmd.add_argument(
        "--out",
        help=(
            "Directory for the described documents, mirroring the input tree; "
            "default writes semantic.json/semantic.md next to each lineage.json"
        ),
    )
    describe_cmd.add_argument(
        "--sections",
        help=(
            "Comma-separated semantic.md section names (default: all); "
            "fields_table keeps section 5's table without the per-field subsections"
        ),
    )
    describe_cmd.add_argument(
        "--format",
        default="json,md",
        help="Comma-separated output formats: json, md (default: json,md)",
    )
    describe_cmd.add_argument(
        "--glossary",
        help=(
            "A glossary.json written by `scope-lineage glossary`; fields[].value_domain "
            "then carries the corpus's observations and any confirmed value meanings"
        ),
    )
    describe_cmd.add_argument(
        "--tables",
        help=(
            "A tables.json written by `scope-lineage tables`; input tables then carry "
            "their upstream card and the target table lists its downstream consumers"
        ),
    )
    describe_cmd.add_argument(
        "--metadata-patch",
        action="append",
        default=[],
        help=(
            "A reviewed metadata-patch/1 file, applied to the lineage document in "
            "memory before the view is derived -- the same document "
            "`parse --metadata-patch` writes, without re-parsing the corpus and without "
            "rewriting the artifact on disk. Repeatable"
        ),
    )
    add_incremental_arguments(describe_cmd)


def _validate_inputs(args: argparse.Namespace) -> int:
    """Audit lineage documents from disk: schema, cross-references, invariants.

    Three checkers, one pass, because they answer different questions: the JSON schema
    answers "is the shape legal", cross-references answer "does every referenced id
    exist", and the invariants answer "do independently derived layers agree" — the
    question whose absence let a chain claim completeness for a field end_to_end
    reported as ambiguous.
    """
    import jsonschema

    from .contract import (
        validate_contract_invariants,
        validate_cross_references,
        validate_lineage_document,
    )

    root = Path(args.lineage)
    if root.is_file():
        documents = [root]
    elif root.is_dir():
        documents = sorted(root.rglob("lineage.json"))
    else:
        print(f"--lineage path does not exist: {root}", file=sys.stderr)
        return 2
    if not documents:
        print(f"no lineage.json found under {root}", file=sys.stderr)
        return 1

    total_violations = 0
    for lineage_path in documents:
        violations: list[str] = []
        try:
            document = json.loads(lineage_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            violations.append(f"json: {error}")
            document = None
        if document is not None:
            try:
                validate_lineage_document(document)
            except jsonschema.ValidationError as error:
                violations.append(f"schema: {error.message}")
            violations.extend(
                f"cross-reference: {error}"
                for error in validate_cross_references(document)
            )
            violations.extend(
                f"invariant: {error}"
                for error in validate_contract_invariants(document)
            )
        for violation in violations:
            print(f"{lineage_path}: {violation}")
        total_violations += len(violations)

    if total_violations:
        print(
            f"Validated {len(documents)} document(s): {total_violations} violation(s)"
        )
        return 1
    print(f"Validated {len(documents)} document(s): OK")
    return 0


@dataclass(frozen=True)
class _ContractDocument:
    """One renderable lineage document with everything both renderers need."""

    path: Path
    document: dict
    diagnostics: dict | None
    target_dir: Path


def _discover_lineage_documents(lineage: str):
    """``(paths, base, single_file)``, or the exit code when there is nothing to read."""
    root = Path(lineage)
    if root.is_file():
        return [root], root.parent, True
    if not root.is_dir():
        print(f"--lineage path does not exist: {root}", file=sys.stderr)
        return 2
    documents = sorted(root.rglob("lineage.json"))
    if not documents:
        print(f"no lineage.json found under {root}", file=sys.stderr)
        return 1
    return documents, root, False


def _is_derivable_document(document: dict) -> bool:
    """A statement document, or a task document -- the two shapes both views consume."""
    from .render.mapping_markdown import SUPPORTED_SCHEMA_VERSION, TASK_SCHEMA_VERSION

    version = document.get("schema_version")
    if version == SUPPORTED_SCHEMA_VERSION:
        return True
    return (
        version == TASK_SCHEMA_VERSION
        and document.get("artifact_kind") == "task_lineage"
    )


class _ContractWalk(NamedTuple):
    """What one walk over a corpus found, plus the three things it had to skip."""

    documents: list[_ContractDocument]
    skipped_unknown_version: int
    missing_diagnostics: int
    skipped_unreadable: int

    def counters(self) -> str:
        """The one summary every command that shares this walk prints."""
        return (
            f"skipped_unknown_version={self.skipped_unknown_version}, "
            f"missing_diagnostics={self.missing_diagnostics}, "
            f"skipped_unreadable={self.skipped_unreadable}"
        )


def _read_json_object(path: Path) -> dict | None:
    """One JSON object read from disk, or None with one line on stderr saying why.

    A corpus is written by somebody else's job, so a truncated or half-written file is
    an input this tool meets rather than a bug in it: the walk skips that one document
    instead of raising out of ``main`` and hiding every other task in the tree. A
    document that parses but is not an object (a list, a bare string) is the same kind
    of unusable input and is reported in the same sentence.
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"{path}: not a readable JSON document ({error})", file=sys.stderr)
        return None
    if not isinstance(document, dict):
        print(
            f"{path}: not a readable JSON document "
            f"(top level is {type(document).__name__}, not an object)",
            file=sys.stderr,
        )
        return None
    return document


def _load_contract_documents(
    paths: list[Path], base: Path, single_file: bool, out: str | None, label: str
):
    """Read the documents both derived-view commands consume, with their counters.

    ``render`` and ``describe`` answer different questions but walk the same input: a
    file or a tree, each document's sibling ``diagnostics.json``, an unsupported version
    that is fatal for one named file and merely counted in a corpus, and the output
    directory that mirrors the input tree under ``--out``. Returns a
    :class:`_ContractWalk`, or an exit code: 1 when the one file the user named is not a
    supported document, 2 when it cannot be read at all -- the same code
    ``--lineage <missing path>`` already answers with, because "the file you named is
    not usable" is one answer however it failed.
    """
    from .render.mapping_markdown import SUPPORTED_SCHEMA_VERSION, TASK_SCHEMA_VERSION

    loaded: list[_ContractDocument] = []
    skipped_unknown_version = 0
    missing_diagnostics = 0
    skipped_unreadable = 0
    for lineage_path in paths:
        document = _read_json_object(lineage_path)
        if document is None:
            if single_file:
                return 2
            skipped_unreadable += 1
            continue
        version = document.get("schema_version")
        if not _is_derivable_document(document):
            if single_file:
                print(
                    f"{label} supports schema_version {SUPPORTED_SCHEMA_VERSION} "
                    f"statement documents and {TASK_SCHEMA_VERSION} task documents; "
                    f"{lineage_path} declares {version!r}",
                    file=sys.stderr,
                )
                return 1
            skipped_unknown_version += 1
            continue
        diagnostics_path = lineage_path.parent / "diagnostics.json"
        diagnostics = None
        if diagnostics_path.is_file():
            diagnostics = _read_json_object(diagnostics_path)
            if diagnostics is None:
                # A present-but-unreadable sibling is not a missing one: the document
                # still describes, and the counter says which of the two happened.
                skipped_unreadable += 1
        else:
            missing_diagnostics += 1
        target_dir = (
            Path(out) / lineage_path.parent.relative_to(base)
            if out
            else lineage_path.parent
        )
        loaded.append(
            _ContractDocument(lineage_path, document, diagnostics, target_dir)
        )
    return _ContractWalk(
        loaded, skipped_unknown_version, missing_diagnostics, skipped_unreadable
    )


def _write_derived_document(target_dir: Path, name: str, text: str) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / name).write_text(text, encoding="utf-8")


def _render_inputs(args: argparse.Namespace) -> int:
    from .render.mapping_markdown import (
        render_mapping_markdown,
        render_warnings_markdown,
    )

    found = _discover_lineage_documents(args.lineage)
    if isinstance(found, int):
        return found
    loaded = _load_contract_documents(*found, args.out, "mapping renderer")
    if isinstance(loaded, int):
        return loaded
    documents = loaded.documents

    sections = args.sections.split(",") if args.sections else None
    for item in documents:
        try:
            markdown = render_mapping_markdown(
                item.document,
                item.diagnostics,
                fields=args.field,
                expanded=args.expanded,
                sections=sections,
            )
        except ValueError as error:
            print(f"{item.path}: {error}", file=sys.stderr)
            return 1
        _write_derived_document(item.target_dir, "mapping.md", markdown)
        warnings_markdown = render_warnings_markdown(item.diagnostics, item.document)
        if warnings_markdown is not None:
            _write_derived_document(item.target_dir, "warnings.md", warnings_markdown)

    print(f"Rendered {len(documents)} mapping document(s) ({loaded.counters()})")
    return 0


def _describe_formats(value: str | None) -> set[str]:
    return {name.strip() for name in (value or "json,md").split(",") if name.strip()}


def _load_corpus_document(path: str | None, flag: str, doc_format: str):
    """A corpus artifact named on a ``describe`` flag, or the exit code, or None.

    A path the user named and the tool cannot read is an error, never a silent fallback
    to "no corpus": the reader would get a document quietly missing the upstream answers
    they asked for -- and a corpus that observed nothing looks exactly the same in the
    output. Which is why the declared ``doc_format`` is checked as well as the bytes:
    ``--glossary`` and ``glossary --overrides`` sit one line apart in every runbook, both
    take a JSON object, and only the format tells them apart.
    """
    if not path:
        return None
    source = Path(path)
    if not source.is_file():
        print(f"{flag} path does not exist: {source}", file=sys.stderr)
        return 2
    document = _read_json_object(source)
    if document is None:
        return 2
    if document.get("doc_format") != doc_format:
        print(
            f"{flag} expects a {doc_format} document; {source} declares "
            f"{document.get('doc_format')!r}",
            file=sys.stderr,
        )
        return 1
    return document


def _describe_inputs(args: argparse.Namespace) -> int:
    from .metadata.metadata_patch import MetadataPatchError, load_metadata_patch
    from .render.glossary import DOC_FORMAT as GLOSSARY_DOC_FORMAT
    from .render.table_cards import DOC_FORMAT as TABLES_DOC_FORMAT

    # WI-2.4: the corpus glossary, or None. Without it the profile keeps the value
    # domain it derived from this task alone.
    glossary = _load_corpus_document(
        getattr(args, "glossary", None), "--glossary", GLOSSARY_DOC_FORMAT
    )
    if isinstance(glossary, int):
        return glossary
    # WI-2.6: the confirmed comments, applied to the document in memory. The artifact on
    # disk is never rewritten -- a derived view may not edit the contract it derives from.
    try:
        patch = load_metadata_patch(getattr(args, "metadata_patch", None))
    except MetadataPatchError as error:
        print(str(error), file=sys.stderr)
        return 2
    found = _discover_lineage_documents(args.lineage)
    if isinstance(found, int):
        return found
    loaded = _load_contract_documents(*found, args.out, "semantic describer")
    if isinstance(loaded, int):
        return loaded
    documents = loaded.documents

    sections = args.sections.split(",") if args.sections else None
    formats = _describe_formats(args.format)
    # WI-2.5: the corpus's table cards, or None. A profile built without them is byte
    # for byte the document describe wrote before table cards existed.
    table_cards = _load_corpus_document(
        getattr(args, "tables", None), "--tables", TABLES_DOC_FORMAT
    )
    if isinstance(table_cards, int):
        return table_cards
    cache = _describe_cache(args, found[1], glossary, table_cards)
    failure = _describe_corpus(
        documents,
        cache,
        reuse=cache.enabled and not _patch_is_corpus_wide(patch, cache),
        formats=formats,
        options=(patch, table_cards, glossary, sections),
    )
    if failure is not None:
        return failure
    cache.commit(sorted(_describe_output_names(formats)))
    print(
        f"Described {len(documents)} task(s) "
        f"({loaded.counters()}{_patch_report(patch)}{cache.counters()})"
    )
    return 0


def _describe_cache(args: argparse.Namespace, base: Path, glossary, table_cards):
    """``describe``'s index and fact cache, beside the documents it writes.

    Without ``--out`` the described documents land beside their lineage.json, so the
    index does too: it belongs with the outputs it fingerprints, wherever those are.
    """
    from .corpus_cache import file_digest

    patches = [
        file_digest(Path(path))
        for path in (getattr(args, "metadata_patch", None) or [])
    ]
    out = Path(args.out) if getattr(args, "out", None) else base
    return open_cache(
        args,
        out,
        base,
        "describe",
        [args.sections, args.format, glossary, table_cards, sorted(patches, key=str)],
    )


def _patch_is_corpus_wide(patch, cache) -> bool:
    """A ``--metadata-patch`` run cannot skip tasks, and says so once.

    ``patch_unmatched`` answers "which confirmed comment matched nothing *in the whole
    corpus*", so it is only true when every task was actually described. Reuse would
    turn a skipped match into a reported miss -- the one lie this report must not tell.
    """
    if not patch:
        return False
    if cache.enabled:
        print(
            "--incremental describes every task while --metadata-patch is in play: "
            "the patch's unmatched report is corpus-wide",
            file=sys.stderr,
        )
    return True


def _describe_output_names(formats: set) -> list[str]:
    names = ["semantic.json"] if "json" in formats else []
    return [*names, "semantic.md"] if "md" in formats else names


def _describe_corpus(documents, cache, *, reuse: bool, formats: set, options) -> int | None:
    """Describe every task that needs it; the exit code of the first failure, or None."""
    for item in documents:
        outputs = [item.target_dir / name for name in _describe_output_names(formats)]
        if reuse and cache.unchanged(item, outputs):
            continue
        try:
            profile, markdown = _describe_one(item, formats, *options)
        except ValueError as error:
            print(f"{item.path}: {error}", file=sys.stderr)
            return 1
        if "json" in formats:
            _write_derived_document(
                item.target_dir,
                "semantic.json",
                json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
            )
        if markdown is not None:
            _write_derived_document(item.target_dir, "semantic.md", markdown)
        cache.record(item, outputs)
    return None


def _describe_one(item, formats: set, patch, table_cards, glossary, sections):
    """``(semantic profile, semantic.md or None)`` for one task."""
    from .render.semantic_markdown import render_semantic_markdown
    from .render.semantic_profile import build_semantic_profile
    from .metadata.metadata_patch import apply_metadata_patch_to_document
    from .render.glossary import apply_glossary
    from .render.table_cards import apply_table_cards

    apply_metadata_patch_to_document(item.document, patch)
    profile = apply_glossary(
        apply_table_cards(
            build_semantic_profile(
                item.document, item.diagnostics, table_cards=table_cards
            ),
            table_cards,
        ),
        glossary,
    )
    markdown = (
        render_semantic_markdown(profile, sections=sections)
        if "md" in formats
        else None
    )
    return profile, markdown


def _patch_report(patch) -> str:
    """The unmatched half of a patch run, or nothing when no patch was supplied."""
    if not patch:
        return ""
    unmatched = patch.unmatched()
    return f", patch_unmatched={len(unmatched)}" + (
        f" ({'、'.join(unmatched)})" if unmatched else ""
    )


class _SourceFile(NamedTuple):
    """One input file and the ``--input-dir`` it was discovered under (None for a file).

    The root travels with the file rather than with the run: ``--input-dir`` is
    repeatable, so "relative to the input root" only has an answer per file.
    """

    path: Path
    root: Path | None


@dataclass(frozen=True)
class _TaskInput:
    source_path: Path
    relative_parent: Path
    task_name: str
    sql: str
    task_dependencies: dict
    # The exported task object's `meta`, plus the file it was read from. None for a
    # `.sql` input, which is why a `.sql` document carries no `task_meta` key (WI-2.2).
    task_meta: dict | None = None


@contextmanager
def _catalog_prefix_override(value: str | None):
    """Apply a CLI-only catalog policy without leaking it to later in-process calls."""
    if value is None:
        yield
        return
    key = "SCOPE_LINEAGE_CATALOG_PREFIXES"
    previous = os.environ.get(key)
    os.environ[key] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def _parse_inputs(args: argparse.Namespace) -> int:
    schema_paths = [
        path
        for path in [args.schema, *args.schema_fallback]
        if path
    ]
    schema = None
    if schema_paths:
        loader = load_schema_sources if len(schema_paths) > 1 else load_schema
        schema = loader(
            schema_paths if len(schema_paths) > 1 else schema_paths[0],
            sanitize_nul=args.sanitize_metadata_nul,
        )
    target_metadata = (
        load_target_table_metadata(
            args.target_ddl_metadata,
            sanitize_nul=args.sanitize_metadata_nul,
        )
        if args.target_ddl_metadata
        else None
    )
    # WI-2.6. Applied to each statement document by the same function
    # `describe --metadata-patch` uses, so the two paths publish one document.
    # The answers are masked as they are read, under the same switch the SQL author's
    # comments obey: the patch lands after `parse_task_lineage` has already redacted what
    # it loaded, so an unmasked patch would be the one comment published verbatim.
    from .metadata.metadata_patch import MetadataPatchError, load_metadata_patch

    try:
        patch = load_metadata_patch(
            getattr(args, "metadata_patch", None),
            redact_comments=not bool(getattr(args, "no_redact_comments", False)),
        )
    except MetadataPatchError as error:
        print(str(error), file=sys.stderr)
        return 2
    out_root = Path(args.out)
    return _parse_task_inputs_v2(
        args,
        schema=schema,
        target_metadata=target_metadata,
        out_root=out_root,
        source_files=_source_paths(args),
        metadata_patch=patch,
    )

def _parse_task_inputs_v2(
    args: argparse.Namespace,
    *,
    schema,
    target_metadata,
    out_root: Path,
    source_files: list["_SourceFile"],
    metadata_patch=None,
) -> int:
    from .metadata.metadata_patch import apply_metadata_patch_to_statements

    task_count = 0
    statement_count = 0
    modeled_count = 0
    failed_count = 0
    input_failed_count = 0
    partial_task_count = 0
    partial_reason_counts: Counter = Counter()
    capacity_guard_count = 0
    unsupported_mutation_count = 0
    root_gap_result_count = 0
    binding_fallback_count = 0
    binding_fallback_reasons: Counter = Counter()
    binding_not_applicable_count = 0
    recovered_syntax_count = 0
    claimed_output_dirs: dict[Path, Path] = {}
    preflight_only = bool(getattr(args, "metadata_preflight", False))
    referenced_tables: set[str] = set()
    covered_tables: set[str] = set()
    missing_referencers: dict[str, set[str]] = {}

    for source_path, input_root in source_files:
        try:
            task = _load_task_input(source_path, input_root, args.task_name)
            result = parse_task_lineage(
                task.sql,
                task_name=task.task_name,
                schema=schema,
                target_metadata=target_metadata,
                task_dependencies=task.task_dependencies,
                partition_overwrite_mode=getattr(args, "partition_overwrite_mode", None),
                task_meta=task.task_meta,
                strip_comments=bool(getattr(args, "strip_comments", False)),
                redact_comments=not bool(getattr(args, "no_redact_comments", False)),
                expansion_limit=getattr(args, "expansion_limit", None),
            )
            if metadata_patch:
                apply_metadata_patch_to_statements(
                    [
                        statement
                        for statement in result.statement_lineage.values()
                        if isinstance(statement, dict)
                    ],
                    metadata_patch,
                )
            # One derivation path for coverage: the same per-task
            # diagnostics.metadata_coverage fact a consumer reads, only aggregated.
            coverage = result.diagnostics.get("metadata_coverage") or {}
            task_covered = {str(t) for t in coverage.get("covered_tables") or []}
            task_missing = {str(t) for t in coverage.get("missing_tables") or []}
            covered_tables |= task_covered
            referenced_tables |= task_covered | task_missing
            for table in task_missing:
                missing_referencers.setdefault(table, set()).add(result.task_id)
            if preflight_only:
                task_count += 1
                continue
            task_out = _task_output_dir(
                out_root,
                task.relative_parent,
                result.task_id,
            )
            claimed_by = claimed_output_dirs.get(task_out)
            if claimed_by is not None and claimed_by != source_path:
                raise ValueError(
                    f"output directory collision: {task_out} is already used by "
                    f"{claimed_by}"
                )
            claimed_output_dirs[task_out] = source_path
            write_task_lineage(
                result,
                task_out,
                compact=args.compact_json,
            )
            task_count += 1
            statement_count += len(result.statements)
            modeled_count += sum(
                item.get("model_status") == "modeled"
                for item in result.statements
            )
            failed_count += sum(
                item.get("model_status") == "failed"
                for item in result.statements
            )
            partial_task_count += result.analysis_status.get("status") == "partial"
            if result.analysis_status.get("status") == "partial":
                # The task's own answer to "why", not a second derivation of it: the same
                # reasons `analysis_status.blocking_reasons` publishes, one count per task.
                partial_reason_counts.update(
                    str(reason)
                    for reason in result.analysis_status.get("blocking_reasons") or []
                )
            # One per task, not per event: the operator's next move is to re-run the task
            # with a larger --expansion-limit, and a task is what gets re-run.
            capacity_guard_count += _hit_the_expansion_guard(result)
            unsupported_mutation_count += sum(
                item.get("category") == "row_mutation"
                and item.get("model_status") != "modeled"
                for item in result.statements
            )
            root_gap_result_count += any(
                gap.get("root_impact")
                for gap in result.diagnostics.get("lineage_fact_gaps", [])
                if isinstance(gap, dict)
            )
            fallbacks, not_applicable = _binding_status_counts(
                result, binding_fallback_reasons
            )
            binding_fallback_count += fallbacks
            binding_not_applicable_count += not_applicable
            recovered_syntax_count += result.syntax_status == "recovered"
        except Exception as exc:  # noqa: BLE001 - batch boundary: one bad input must not kill the run; type+traceback go to stderr
            input_failed_count += 1
            print(
                f"  FAILED {source_path}: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            # The traceback is what separates a Core bug from a bad input file.
            print(traceback.format_exc().rstrip(), file=sys.stderr)

    manifest_path = out_root / "metadata_gaps.json"
    if preflight_only:
        _write_metadata_gap_manifest(
            manifest_path,
            referenced_tables=referenced_tables,
            covered_tables=covered_tables,
            missing_referencers=missing_referencers,
            input_count=len(source_files),
            input_failed_count=input_failed_count,
        )
        print(
            f"Metadata preflight: {len(referenced_tables)} referenced table(s), "
            f"{len(covered_tables)} covered, {len(missing_referencers)} missing "
            f"across {task_count} task(s); manifest written to {manifest_path}"
        )
        for table, tasks in sorted(
            missing_referencers.items(), key=lambda item: (-len(item[1]), item[0])
        ):
            names = "、".join(sorted(tasks)[:5])
            more = f" +{len(tasks) - 5}" if len(tasks) > 5 else ""
            print(f"  - {table} (referenced by: {names}{more})")
        return 1 if missing_referencers or input_failed_count else 0

    if missing_referencers:
        # The batch manifest lands next to the artifacts; a single-file parse keeps
        # its output directory to exactly the task artifact and lists gaps inline.
        if getattr(args, "input_dir", None):
            _write_metadata_gap_manifest(
                manifest_path,
                referenced_tables=referenced_tables,
                covered_tables=covered_tables,
                missing_referencers=missing_referencers,
                input_count=len(source_files),
                input_failed_count=input_failed_count,
            )
            detail = f"list written to {manifest_path}"
        else:
            detail = "、".join(sorted(missing_referencers))
        print(
            f"Metadata gaps: {len(missing_referencers)} referenced table(s) have no "
            f"schema metadata; {detail} "
            "(run with --metadata-preflight to review before parsing)"
        )
    if metadata_patch:
        unmatched = metadata_patch.unmatched()
        detail = f"; unmatched: {'、'.join(unmatched)}" if unmatched else ""
        print(
            f"Metadata patch: {len(metadata_patch.tables)} table entry/entries and "
            f"{len(metadata_patch.columns)} column entry/entries from "
            f"{len(metadata_patch.sources)} file(s), unmatched={len(unmatched)}{detail}"
        )
    print(
        f"Parsed {statement_count} statement(s) from {len(source_files)} input(s) "
        f"into {out_root} using contract 2.0 "
        f"(tasks={task_count}, modeled={modeled_count}, failed={failed_count}, "
        f"input_failed={input_failed_count}, partial_tasks={partial_task_count}, "
        f"unsupported_mutations={unsupported_mutation_count}, "
        f"root_gap_results={root_gap_result_count}, "
        f"binding_fallbacks={binding_fallback_count}"
        f"{_binding_reasons_report(binding_fallback_reasons)}, "
        f"recovered_syntax={recovered_syntax_count}"
        f"{_binding_not_applicable_report(binding_not_applicable_count)}"
        f"{_capacity_guard_report(capacity_guard_count)}"
        f"{_partial_reasons_report(partial_reason_counts)})"
    )
    quality_failed = _quality_gate_failed(
        args,
        unsupported_mutation_count=unsupported_mutation_count,
        root_gap_result_count=root_gap_result_count,
        binding_fallback_count=binding_fallback_count,
        recovered_syntax_count=recovered_syntax_count,
    )
    if not failed_count and not input_failed_count and not quality_failed:
        return 0
    if quality_failed:
        return 1
    return 0 if args.allow_partial else 1


def _hit_the_expansion_guard(result) -> bool:
    """Whether one task's expansion stopped at a guard, however it was reported.

    Two shapes, one fact: a truncation warning where the sources were nonetheless complete
    (Q2), and a capacity gap where they were not. The counter is the cue to re-run with a
    larger `--expansion-limit`, and that cue does not depend on which of the two it was.
    """
    if any(
        gap.get("gap_bucket") == "capacity_guard"
        for gap in result.diagnostics.get("lineage_fact_gaps", [])
        if isinstance(gap, dict)
    ):
        return True
    return any(
        warning.get("type") == "expansion_truncated"
        for lineage in result.statement_lineage.values()
        if isinstance(lineage, dict)
        for warning in (lineage.get("diagnostics") or {}).get("warnings") or []
        if isinstance(warning, dict)
    )


def _binding_status_counts(result, reasons: Counter) -> tuple[int, int]:
    """This task's fallen-back and not-applicable bindings, tallying the fallback reasons.

    Read off the published block rather than recomputed: the block is what a consumer sees,
    so a summary derived from anything else could disagree with the artifact it summarises.
    """
    fallbacks = 0
    not_applicable = 0
    for lineage in result.statement_lineage.values():
        binding = lineage.get("target_field_binding") or {}
        status = binding.get("status")
        if status == "fallback":
            fallbacks += 1
            reasons[str(binding.get("fallback_reason") or "other")] += 1
        elif status == "not_applicable":
            not_applicable += 1
    return fallbacks, not_applicable


def _binding_reasons_report(counts: Counter) -> str:
    """What the fallbacks fell back on, commonest first, or nothing when there were none.

    `binding_fallbacks=9` is not actionable on its own -- a target nobody supplied metadata
    for and a projection that disagrees with the DDL are the same number and different work.
    Ties break on the token's name, like `partial_reasons`, so two runs over the same corpus
    print the same line.
    """
    if not counts:
        return ""
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return " (" + ",".join(f"{reason}:{count}" for reason, count in ordered) + ")"


def _binding_not_applicable_report(count: int) -> str:
    """The statements with no binding to make, or nothing when every statement had one.

    Said only when it happened, like `capacity_guard`: these are not a gap to close -- a
    CTAS defines its own columns -- and a counter that is usually zero would only dilute the
    one beside it that does need work.
    """
    return f", binding_not_applicable={count}" if count else ""


def _capacity_guard_report(count: int) -> str:
    """The tasks whose expansion stopped at the guard, or nothing when none did.

    Said only when it happened: a counter that is always zero is a counter nobody reads,
    and this one is the cue to re-run with a larger --expansion-limit.
    """
    return f", capacity_guard={count}" if count else ""


def _partial_reasons_report(counts: Counter) -> str:
    """What the partial tasks were blocked on, commonest first, or nothing.

    ``partial_tasks=7`` is not actionable on its own -- seven read-only SELECTs and seven
    lineage gaps are the same number and different work. Ties break on the reason's name
    so two runs over the same corpus print the same line.
    """
    if not counts:
        return ""
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    breakdown = ",".join(f"{reason}:{count}" for reason, count in ordered)
    return f", partial_reasons={breakdown}"


def _write_metadata_gap_manifest(
    path: Path,
    *,
    referenced_tables: set[str],
    covered_tables: set[str],
    missing_referencers: dict[str, set[str]],
    input_count: int,
    input_failed_count: int,
) -> None:
    """Write the batch metadata-gap report (deterministic, no timestamps)."""
    manifest = {
        "artifact_kind": "metadata_gap_report",
        "input_count": input_count,
        "input_failed_count": input_failed_count,
        "referenced_table_count": len(referenced_tables),
        "covered_table_count": len(covered_tables),
        "missing_table_count": len(missing_referencers),
        "missing_tables": [
            {
                "table": table,
                "referenced_by_task_count": len(tasks),
                "referenced_by": sorted(tasks),
            }
            for table, tasks in sorted(
                missing_referencers.items(),
                key=lambda item: (-len(item[1]), item[0]),
            )
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _safe_task_output_component(task_id: str) -> str:
    """Keep a task identity as data instead of letting it become a path expression."""
    if (
        not task_id
        or task_id in {".", ".."}
        or "\x00" in task_id
        or "/" in task_id
        or "\\" in task_id
        or Path(task_id).is_absolute()
    ):
        raise ValueError(
            "task_id must be one non-empty output-directory component without "
            f"path separators, got {task_id!r}"
        )
    return task_id.replace("#", "_")


def _task_output_dir(out_root: Path, relative_parent: Path, task_id: str) -> Path:
    """Resolve one task directory and prove it remains below the requested root."""
    resolved_root = out_root.resolve(strict=False)
    component = _safe_task_output_component(task_id)
    candidate = (resolved_root / relative_parent / component).resolve(strict=False)
    try:
        candidate.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(
            f"task output directory escapes --out: task_id={task_id!r}"
        ) from error
    return candidate


def _quality_gate_failed(
    args: argparse.Namespace,
    *,
    unsupported_mutation_count: int,
    root_gap_result_count: int,
    binding_fallback_count: int,
    recovered_syntax_count: int,
) -> bool:
    balanced = args.quality_policy in {"balanced", "strict"}
    strict = args.quality_policy == "strict"
    return bool(
        (unsupported_mutation_count and (balanced or args.fail_on_unsupported_mutation))
        or (root_gap_result_count and (strict or args.fail_on_root_gap))
        or (binding_fallback_count and (strict or args.fail_on_binding_fallback))
        or (recovered_syntax_count and strict)
    )


def _source_paths(args: argparse.Namespace) -> list[_SourceFile]:
    """Every input file to parse, each paired with the directory it was found under.

    ``--input-dir`` is repeatable, so the root is per file rather than per run: the
    output tree mirrors each file's position under *its own* directory, and a task
    dependency names its source relative to the same root. Directories are walked in the
    order given and a file two of them both name -- a parent and its own subdirectory,
    or one tree spelled two ways -- is parsed once, under the first root that named it.
    """
    if args.sql_file:
        return [_SourceFile(Path(args.sql_file), None)]
    if args.task_file:
        return [_SourceFile(Path(args.task_file), None)]
    found: dict[Path, _SourceFile] = {}
    for raw in args.input_dir:
        for item in _directory_source_files(raw, args):
            found.setdefault(item.path.resolve(), item)
    return list(found.values())


def _directory_source_files(
    raw: str, args: argparse.Namespace
) -> list[_SourceFile]:
    """One directory's matching files, in path order; empty is refused, not ignored."""
    input_root = Path(raw)
    if not input_root.is_dir():
        raise ValueError(f"task input directory does not exist: {input_root}")
    includes = args.include_glob or ["*.json"]
    excludes = args.exclude_glob or []
    paths = sorted(
        path
        for path in input_root.rglob("*.json")
        if any(path.relative_to(input_root).match(pattern) for pattern in includes)
        and not any(path.relative_to(input_root).match(pattern) for pattern in excludes)
    )
    if not paths:
        raise ValueError(
            "task input directory contains no JSON files matching the configured globs: "
            f"{input_root}"
        )
    return [_SourceFile(path, input_root) for path in paths]


def _load_task_input(
    source_path: Path,
    input_root: Path | None,
    task_name_override: str | None,
) -> _TaskInput:
    relative_parent = (
        source_path.parent.relative_to(input_root)
        if input_root is not None
        else Path()
    )
    source_label = (
        source_path.relative_to(input_root).as_posix()
        if input_root is not None
        else source_path.name
    )
    if source_path.suffix.lower() == ".sql":
        return _TaskInput(
            source_path=source_path,
            relative_parent=relative_parent,
            task_name=task_name_override or source_path.stem,
            sql=source_path.read_text(encoding="utf-8"),
            task_dependencies=_empty_task_dependencies("sql_file"),
        )

    document = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("task JSON top level must be an object")
    meta = document.get("meta")
    payload = meta if isinstance(meta, dict) else document
    sql = payload.get("sql")
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("task JSON must contain a non-empty string at meta.sql or sql")
    task_name = (
        task_name_override
        or _clean_value(payload.get("task_name"))
        or _clean_value(payload.get("task_id"))
        or source_path.stem
    )
    return _TaskInput(
        source_path=source_path,
        relative_parent=relative_parent,
        task_name=task_name,
        sql=sql,
        task_dependencies=_task_dependencies(document, source_label),
        # The file the metadata came from travels with it: a task document read out of a
        # batch directory is otherwise unattributable to its input.
        task_meta={**payload, "source_file": source_label},
    )


def _task_dependencies(document: dict, source_label: str) -> dict:
    meta = document.get("meta")
    if not isinstance(meta, dict):
        return _empty_task_dependencies("task_json_legacy")
    upstream = _dependency_items(
        meta.get("upstream_tasks"), "upstream", source_label
    )
    downstream = _dependency_items(
        meta.get("downstream_tasks"), "downstream", source_label
    )
    return {
        "upstream_tasks": upstream,
        "downstream_tasks": downstream,
        "source_summary": {
            "source_format": "task_info_meta",
            "upstream_count": len(upstream),
            "downstream_count": len(downstream),
            "has_declared_task_dependencies": bool(upstream or downstream),
        },
    }


def _dependency_items(records, direction: str, source_label: str) -> list[dict]:
    items = []
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict):
            continue
        task_name = _clean_value(record.get("task_name") or record.get("task_id"))
        if not task_name:
            continue
        items.append(
            {
                "dependency_id": f"taskdep:{direction}:{len(items) + 1:03d}",
                "direction": direction,
                "task_id": _clean_value(record.get("task_id")),
                "task_name": task_name,
                "task_group": _clean_value(record.get("task_group")),
                "project_name": _clean_value(record.get("project_name")),
                "dependency_type": "declared",
                "dependency_table": _clean_value(
                    record.get("dependency_table") or record.get("table")
                ),
                "source": f"task_info.meta.{direction}_tasks",
                "source_file": source_label,
                "raw_record": record,
            }
        )
    return items


def _empty_task_dependencies(source_format: str) -> dict:
    return {
        "upstream_tasks": [],
        "downstream_tasks": [],
        "source_summary": {
            "source_format": source_format,
            "upstream_count": 0,
            "downstream_count": 0,
            "has_declared_task_dependencies": False,
        },
    }


def _clean_value(value) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _print_parse_failure(result) -> None:
    reasons = [
        warning.msg
        for warning in result.diagnostics.warnings
        if warning.type == "LINEAGE_ERROR"
    ]
    print(
        f"  FAILED {result.task_id}: "
        f"{reasons[0] if reasons else 'scope build failed'}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    raise SystemExit(main())
