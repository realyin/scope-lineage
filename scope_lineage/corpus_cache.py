"""Incremental corpus derivations: a fingerprint index plus a per-task fact cache (A5).

``glossary``, ``tables``, ``ontology`` and ``describe`` all walk the same corpus and all
re-derive every task on every run, even when one task changed. The expensive half of
that work -- the semantic profile each command builds *per document*, before any
corpus-level merge -- depends on nothing but that document and its ``diagnostics.json``.
So it is cached under a digest of exactly those bytes, and a later run re-derives only
the tasks whose digests moved.

Two files, both under the command's own ``--out`` and both disposable:

``<out>/.scope-lineage-corpus-index.json``
    ``corpus-index/1``: the per-task input digests the last run matched on, the digest
    of the options that steered it, and what it wrote. A stored index whose ``command``,
    ``doc_format`` or ``options_sha256`` disagrees with this run is ignored outright --
    that is the invalidation rule for everything outside the corpus (an overrides file's
    *content*, the glossary/tables documents read back, the template flags, the package
    version), rather than trying to reason about which option touched which task.

``<out>/.cache/<task>.json``
    ``corpus-cache/2``: the facts one task contributed, as JSON. Reused only when the
    index entry matched AND the file declares the same command AND the same
    ``payload_version``.

What is deliberately *not* cached is the corpus-level merge: it always runs over every
task, reused and recomputed alike, which is what makes an incremental run byte-identical
to a full one. The cache can only ever be wrong in the direction of doing more work.

**What a task contributes is a PROJECTION of its semantic profile, not the profile**
(P2). ``corpus-cache/1`` stored the profile whole, and a profile is mostly keys no
corpus merge ever looks at -- ``stages``, ``confidence``, every field's step-by-step
``derivation`` -- so the cache grew with the reader-facing half of a view the cache is
not for. Each consumer now publishes the keys its merge reads as a ``PROFILE_FIELDS_READ``
list beside the code that reads them, :func:`project_profile` cuts the profile down to
that list, and the runner feeds the merge exactly what it cached. One shape in, one shape
out: there is no second code path in which a reused task and a recomputed one are fed
different things.

The list is therefore load-bearing, and it is guarded two ways. It goes into the options
digest, so editing one invalidates every index written under the old one; and
``tests/core/test_corpus_cache_projection.py`` builds each merge over the golden corpora
from the full profiles and from the projected ones and compares, which is the only real
proof that a whitelist is complete.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Callable, Mapping, Sequence

INDEX_DOC_FORMAT = "corpus-index/1"
CACHE_DOC_FORMAT = "corpus-cache/2"
INDEX_FILE_NAME = ".scope-lineage-corpus-index.json"
CACHE_DIR_NAME = ".cache"

# What a cache file's ``facts`` mean, independently of the file format around them.
# Version 1 was the whole semantic profile; version 2 is the projection the command's
# merge reads. A stored payload of another version is recomputed rather than read, in
# the index as well as in the fact files -- an index is a promise about fact files that
# a released version may no longer be able to keep.
PAYLOAD_VERSION = 2

_UNSAFE_IN_FILENAME = re.compile(r"[^A-Za-z0-9._-]")


def add_incremental_arguments(command) -> None:
    """The two flags every corpus command shares. Off by default: a run that asks for
    nothing pays nothing -- no digests, no cache files, no extra line in the summary."""
    command.add_argument(
        "--incremental",
        action="store_true",
        help=(
            "Re-derive only the tasks whose lineage.json / diagnostics.json changed "
            "since the last run with the same options, reusing the cached per-task "
            "facts for the rest. The corpus-level result is the same either way. The "
            "first run has nothing to reuse and writes the index and cache for the next"
        ),
    )
    command.add_argument(
        "--no-cache",
        action="store_true",
        help=(
            "Ignore and delete this output directory's incremental index and fact "
            "cache, then run in full"
        ),
    )


def file_digest(path: Path) -> str | None:
    """The sha256 of one file's bytes, or None when it cannot be read."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def options_digest(parts: Sequence) -> str:
    """One digest over everything outside the corpus that steers the derivation.

    Documents are hashed by content rather than by path, so an overrides file edited in
    place invalidates the cache the same way a different ``--overrides`` path does.
    """
    payload = json.dumps(
        [_package_version(), *parts], ensure_ascii=False, sort_keys=True, default=str
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _package_version() -> str:
    from .cli import _package_version as version  # lazy: cli imports this module

    return version()


# ------------------------------------------------------------- profile projection
#
# A field list is ``{"profile": (<task-profile keys>,), "statement": {<key>: <sub-keys
# or None>}}``. ``profile`` names what a 2.0 task profile carries around its statements
# (``statements`` itself is always kept, so it is not listed); ``statement`` names one
# statement profile's keys, mapped either to ``None`` for "the whole value" or to the
# sub-keys of the mapping -- or of every mapping in the list -- underneath it. A 1.0
# profile IS a statement profile, so the ``statement`` half is the whole answer for it.


def project_profile(profile: Mapping, fields: Mapping) -> dict:
    """The part of one semantic profile a corpus merge reads, and nothing else."""
    statements = profile.get("statements")
    if not isinstance(statements, list):
        return _pick(profile, fields["statement"])
    kept = {key: profile[key] for key in fields["profile"] if key in profile}
    kept["statements"] = [_pick(statement, fields["statement"]) for statement in statements]
    return kept


def _pick(source: Mapping, fields: Mapping) -> dict:
    """One mapping narrowed to ``fields``; an absent key stays absent rather than null."""
    return {
        key: source[key] if sub is None else _narrow(source[key], sub)
        for key, sub in fields.items()
        if key in source
    }


def _narrow(value, sub: Sequence[str]):
    """``value`` with only ``sub`` kept, through a list of mappings where it is one."""
    if isinstance(value, list):
        return [_narrow(item, sub) for item in value]
    if isinstance(value, Mapping):
        return {key: item for key, item in value.items() if key in sub}
    return value


def union_fields(*lists: Mapping) -> dict:
    """One field list that keeps what any of several merges reads.

    ``ontology``'s runner stacks three builders on one collected profile, so the profile
    it caches has to answer all three. A whole value always wins over a sub-key list:
    the union of "all of ``fields``" and "two keys of ``fields``" is all of it.
    """
    profile: dict[str, None] = {}
    statement: dict[str, tuple | None] = {}
    for fields in lists:
        profile.update(dict.fromkeys(fields["profile"]))
        for key, sub in fields["statement"].items():
            if key not in statement or sub is None:
                statement[key] = None if sub is None else tuple(sub)
            elif statement[key] is not None:
                statement[key] = tuple(dict.fromkeys((*statement[key], *sub)))
    return {"profile": tuple(profile), "statement": statement}


def purge(out: Path) -> None:
    """Drop the index and the fact cache, leaving the published documents alone."""
    (out / INDEX_FILE_NAME).unlink(missing_ok=True)
    shutil.rmtree(out / CACHE_DIR_NAME, ignore_errors=True)


def open_cache(
    args,
    out: Path,
    base: Path,
    command: str,
    options: Sequence,
    *,
    fields: Sequence[Mapping] = (),
):
    """The cache one corpus command run should use, honouring its two flags.

    ``fields`` is the field list (or lists) the run projects its profiles through. It
    belongs in the options digest for the reason everything else there does: it steers
    what the derivation stores, so a run under a different one may not reuse this one's
    files. Passing it here rather than folding it into ``options`` by hand is what makes
    that impossible to forget.
    """
    if getattr(args, "no_cache", False):
        purge(out)
        return CorpusCache(out, base, command, "", enabled=False)
    return CorpusCache(
        out,
        base,
        command,
        options_digest([*options, *fields]),
        enabled=bool(getattr(args, "incremental", False)),
    )


class CorpusCache:
    """The index and fact cache for one run of one corpus command."""

    def __init__(
        self, out: Path, base: Path, command: str, options: str, *, enabled: bool
    ) -> None:
        self._out = Path(out)
        self._base = Path(base)
        self._command = command
        self._options = options
        self.enabled = enabled
        self._stored = self._load() if enabled else {}
        self._entries: dict[str, dict] = {}
        self.reused = 0
        self.recomputed = 0

    # ------------------------------------------------------------- per task

    def facts(self, item, build: Callable[[], dict]) -> dict:
        """The facts one document contributes: from the cache when its inputs and the
        options are unchanged, otherwise from ``build`` (and written back)."""
        key = self._key(item)
        entry = self._fingerprint(item)
        if self.enabled and self._stored.get(key) == entry:
            payload = self._read_payload(key)
            if payload is not None:
                self._entries[key] = entry
                self.reused += 1
                return payload
        payload = build()
        if self.enabled:
            self._write_payload(key, payload)
        self._entries[key] = entry
        self.recomputed += 1
        return payload

    def unchanged(self, item, outputs: Sequence[Path]) -> bool:
        """``describe`` has no corpus-level merge, so an unchanged task is skipped whole.

        Its own outputs are part of the fingerprint: a semantic.md somebody deleted or
        edited is a reason to describe the task again, even though its inputs stand still.
        """
        key = self._key(item)
        entry = self._fingerprint(item, outputs)
        if self.enabled and self._stored.get(key) == entry:
            self._entries[key] = entry
            self.reused += 1
            return True
        return False

    def record(self, item, outputs: Sequence[Path] = ()) -> None:
        """Count one task as recomputed and fingerprint what it just wrote."""
        self._entries[self._key(item)] = self._fingerprint(item, outputs)
        self.recomputed += 1

    # -------------------------------------------------------------- summary

    @property
    def removed(self) -> int:
        return sum(1 for key in self._stored if key not in self._entries)

    def counters(self) -> str:
        """The incremental half of the one summary line each command prints."""
        if not self.enabled:
            return ""
        return (
            f", reused={self.reused}, recomputed={self.recomputed}, "
            f"removed={self.removed}"
        )

    def commit(self, written: Sequence[str]) -> None:
        """Publish the index for the next run and drop the facts of vanished tasks."""
        if not self.enabled:
            return
        for key in self._stored:
            if key not in self._entries:
                self._payload_path(key).unlink(missing_ok=True)
        payload = {
            "doc_format": INDEX_DOC_FORMAT,
            "command": self._command,
            "payload_version": PAYLOAD_VERSION,
            "inputs": {key: self._entries[key] for key in sorted(self._entries)},
            "options_sha256": self._options,
            "written": sorted(written),
        }
        self._out.mkdir(parents=True, exist_ok=True)
        (self._out / INDEX_FILE_NAME).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    # ----------------------------------------------------------- internals

    def _key(self, item) -> str:
        """The task's directory relative to the corpus root; ``.`` for a single file."""
        return Path(item.path).parent.relative_to(self._base).as_posix()

    def _fingerprint(self, item, outputs: Sequence[Path] = ()) -> dict:
        lineage = Path(item.path)
        entry = {"lineage_sha256": file_digest(lineage)}
        diagnostics = lineage.parent / "diagnostics.json"
        if diagnostics.is_file():
            entry["diagnostics_sha256"] = file_digest(diagnostics)
        for path in outputs:
            entry[_output_key(Path(path).name)] = file_digest(Path(path))
        return entry

    def _payload_path(self, key: str) -> Path:
        stem = _UNSAFE_IN_FILENAME.sub("_", key)[:80]
        suffix = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
        return self._out / CACHE_DIR_NAME / f"{stem}-{suffix}.json"

    def _read_payload(self, key: str) -> dict | None:
        document = _read_json_object(self._payload_path(key))
        if document is None:
            return None
        if (
            document.get("doc_format") != CACHE_DOC_FORMAT
            or document.get("command") != self._command
            or document.get("payload_version") != PAYLOAD_VERSION
        ):
            return None
        facts = document.get("facts")
        return facts if isinstance(facts, dict) else None

    def _write_payload(self, key: str, facts: Mapping) -> None:
        path = self._payload_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "doc_format": CACHE_DOC_FORMAT,
            "command": self._command,
            "payload_version": PAYLOAD_VERSION,
            "facts": facts,
        }
        try:
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        except OSError as error:
            print(f"cannot write {path}: {error}", file=sys.stderr)

    def _load(self) -> dict[str, dict]:
        document = _read_json_object(self._out / INDEX_FILE_NAME)
        if document is None:
            return {}
        if (
            document.get("doc_format") != INDEX_DOC_FORMAT
            or document.get("command") != self._command
            or document.get("payload_version") != PAYLOAD_VERSION
            or document.get("options_sha256") != self._options
        ):
            return {}
        inputs = document.get("inputs")
        return inputs if isinstance(inputs, dict) else {}


def _output_key(name: str) -> str:
    """``semantic.json -> semantic_sha256``, ``semantic.md -> semantic_md_sha256``."""
    stem, _, suffix = name.rpartition(".")
    return f"{stem}_sha256" if suffix == "json" else f"{stem}_{suffix}_sha256"


def _read_json_object(path: Path) -> dict | None:
    """One JSON object read from a cache file, or None: a cache never raises."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return document if isinstance(document, dict) else None
