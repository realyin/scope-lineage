"""The ``scope-lineage domain-profile`` subcommands: ``evidence`` and ``check``.

``evidence`` counts what a parsed corpus says about its own conventions; a model drafts
a ``domain-profile/1`` file from it; ``check`` holds the draft to that evidence, and,
after a person has answered what was left pending, to their answers too. This module
loads the files and hands plain data to :mod:`scope_lineage.semantics.profile_evidence`
and :mod:`scope_lineage.semantics.profile_check`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from .cli_semantic import metadata_lookup
from .metadata.metadata_patch import (
    MetadataPatchError,
    apply_metadata_patch_to_document,
    load_metadata_patch,
)


def add_domain_profile_parser(subcommands) -> None:
    command = subcommands.add_parser(
        "domain-profile",
        help=(
            "Draft a domain-profile/1 from the corpus: count the evidence, then check a "
            "written draft against it"
        ),
    )
    actions = command.add_subparsers(dest="domain_profile_command", required=True)
    _add_evidence_parser(actions)
    _add_check_parser(actions)


def _add_evidence_parser(actions) -> None:
    evidence = actions.add_parser(
        "evidence",
        help="Write evidence.json and evidence.md: suffix readings and comment material",
    )
    evidence.add_argument(
        "--lineage", required=True,
        help="The parse output: one lineage.json, or a directory searched for lineage.json",
    )
    evidence.add_argument(
        "--schema", required=True,
        help=(
            "Schema metadata, as `parse --schema` reads it. Required: without it a partition "
            "column of an unusual name goes unseen and the readings are quietly wrong"
        ),
    )
    evidence.add_argument(
        "--schema-fallback", action="append", default=[],
        help="Additional schema source for tables absent from --schema; repeatable",
    )
    evidence.add_argument(
        "--metadata-patch", action="append", default=[],
        help="A reviewed metadata-patch/1 file laid over the comments, as `semantic packet` "
             "reads it; repeatable",
    )
    evidence.add_argument("--out", required=True, help="Directory for evidence.json and evidence.md")


def _add_check_parser(actions) -> None:
    check = actions.add_parser(
        "check",
        help="Check a domain-profile/1 draft against its evidence, reasons and confirmations",
    )
    check.add_argument("--profile", required=True, help="The domain-profile/1 file to check")
    check.add_argument(
        "--reasons", help="The draft's reasons file (domain-profile.reasons.md); "
                          "required unless --format-only")
    check.add_argument(
        "--evidence", help="evidence.json from `domain-profile evidence`; required unless "
                           "--format-only")
    check.add_argument(
        "--confirmed",
        help="A domain-profile-confirmations/1 file of a person's answers: its accepted "
             "suffix classifications pass",
    )
    check.add_argument(
        "--lineage",
        help="The parse output the evidence was counted from: a hint when it changed since",
    )
    check.add_argument(
        "--format-only", action="store_true",
        help="Check the format only (a hand-edited profile); then only --profile is needed",
    )


def run_domain_profile(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.domain_profile_command == "evidence":
        return _run_evidence(args)
    if not args.format_only and not (args.reasons and args.evidence):
        parser.error("domain-profile check: --reasons and --evidence are required "
                     "unless --format-only")
    return _run_check(args)


# ------------------------------------------------------------------ evidence


def lineage_digest(paths: list[Path], base: Path) -> str:
    """Every lineage.json's sha256, ordered by relative path, hashed once more."""
    ordered = sorted(paths, key=lambda path: path.relative_to(base).as_posix())
    digests = "".join(hashlib.sha256(path.read_bytes()).hexdigest() for path in ordered)
    return hashlib.sha256(digests.encode("ascii")).hexdigest()


def discover_lineage(lineage: str):
    """``(paths, base, single_file)`` of a ``--lineage`` argument, or exit 2."""
    from .cli import _discover_lineage_documents

    found = _discover_lineage_documents(lineage)
    return 2 if isinstance(found, int) else found


def tool_version() -> str:
    from .semantics.profile_check import current_version

    return current_version()


def _relative(path: str | None) -> str | None:
    if not path:
        return None
    try:
        return Path(os.path.relpath(path)).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _run_evidence(args: argparse.Namespace) -> int:
    from .cli import _load_contract_documents
    from .semantics.profile_evidence import build_evidence, evidence_summary, render_evidence_markdown

    try:
        patch = load_metadata_patch(args.metadata_patch)
    except MetadataPatchError as error:
        print(str(error), file=sys.stderr)
        return 2
    found = discover_lineage(args.lineage)
    if isinstance(found, int):
        return found
    paths, base, single_file = found
    loaded = _load_contract_documents(paths, base, single_file, None, "domain-profile evidence")
    if isinstance(loaded, int):
        return 2
    for item in loaded.documents:
        apply_metadata_patch_to_document(item.document, patch)
    metadata = metadata_lookup(args, None, patch)
    if isinstance(metadata, int) or metadata is None:
        return 2
    inputs = {
        "lineage_digest": lineage_digest(paths, base),
        "tool_version": tool_version(),
        "lineage": _relative(args.lineage),
        "schema": _relative(args.schema),
        "schema_fallback": [_relative(path) for path in args.schema_fallback],
        "metadata_patch": [_relative(path) for path in args.metadata_patch],
    }
    evidence = build_evidence(
        [(item.document, item.diagnostics) for item in loaded.documents], metadata, inputs=inputs)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "evidence.md").write_text(render_evidence_markdown(evidence), encoding="utf-8")
    print(evidence_summary(evidence))
    return 0


# ------------------------------------------------------------------ check


def _read_text(path: str, flag: str) -> str | int:
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        print(f"{flag} {path}: not readable ({error})", file=sys.stderr)
        return 2


def _read_json(path: str, flag: str, *, bad_json_code: int):
    """The parsed file, or ``(exit code,)`` -- unreadable is 2, not JSON ``bad_json_code``."""
    text = _read_text(path, flag)
    if isinstance(text, int):
        return (text,)
    try:
        return json.loads(text)
    except ValueError as error:
        print(f"{flag} {path}: not valid JSON ({error})", file=sys.stderr)
        return (bad_json_code,)


def _failed(value) -> bool:
    return isinstance(value, tuple)


def _run_check(args: argparse.Namespace) -> int:
    from .semantics.profile_check import EvidenceError, check_format, check_profile, stale_hint

    # A draft that is not JSON is the writer's mistake: rewrite it (1), not a usage error.
    profile = _read_json(args.profile, "--profile", bad_json_code=1)
    if _failed(profile):
        return profile[0]
    if args.format_only:
        errors = check_format(profile)
        return _report(errors, [], 0 if errors else _entry_count(profile))
    reasons = _read_text(args.reasons, "--reasons")
    evidence = _read_json(args.evidence, "--evidence", bad_json_code=2)
    confirmed = (None if not args.confirmed
                 else _read_json(args.confirmed, "--confirmed", bad_json_code=1))
    for value in (reasons, evidence, confirmed):
        if isinstance(value, int) or _failed(value):
            return value if isinstance(value, int) else value[0]
    try:
        result = check_profile(profile, reasons, evidence, confirmed)
    except EvidenceError as error:
        print(str(error), file=sys.stderr)
        return 2
    if args.lineage:
        found = discover_lineage(args.lineage)
        if isinstance(found, int):
            return found
        hint = stale_hint(evidence, lineage_digest(found[0], found[1]))
        if hint:
            result.hints.append(hint)
    return _report(result.errors, result.hints, result.entries)


def _entry_count(profile) -> int:
    from .semantics.profile_check import draft_entries

    return len(set(draft_entries(profile)))


def _report(errors: list[str], hints: list[str], entries: int) -> int:
    for error in errors:
        print(f"error: {error}")
    for hint in hints:
        print(f"hint: {hint}")
    print(f"Checked {entries} entr(ies): {len(errors)} error(s), {len(hints)} hint(s)")
    return 1 if errors else 0
