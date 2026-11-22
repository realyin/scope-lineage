"""``domain-profile/1``: the business vocabulary and naming rules a caller brings along.

The package is domain-neutral (CONTRIBUTING): it ships generic defaults only, and every
word or warehouse convention that belongs to one business reaches it as data. One JSON
file carries all of it, and each command that reads part of it takes the same flag,
``--domain-profile``:

* ``qualifier_terms`` -- more qualifiers for check 12 (``semantic validate``), added to
  the generic ones;
* ``table_name_convention`` -- the table-name suffixes that mark a full-snapshot or an
  incremental table (``semantic packet``, and the concept layer of ``ontology``: a
  member's role, the increment vote on its kind, the stem a comment-less table is named
  by); without it no suffix means anything;
* ``concept_words`` -- more words for the concept layer (``ontology``): ``event`` /
  ``entity`` / ``summary`` votes, ``measure_suffixes`` and ``filter_words`` for ranking
  name candidates, each added to the generic ones.

Every section is optional, an empty profile changes nothing, and an unknown key is an
error rather than a silently ignored typo.

When a command is not given ``--domain-profile`` it reads the file named by the
``SCOPE_LINEAGE_DOMAIN_PROFILE`` environment variable (``DOMAIN_PROFILE_ENV``), so a run
that calls several commands sets it once; the flag wins when both are given.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

DOC_FORMAT = "domain-profile/1"
#: The environment variable that names the profile when ``--domain-profile`` is not given.
DOMAIN_PROFILE_ENV = "SCOPE_LINEAGE_DOMAIN_PROFILE"
FLAG = "--domain-profile"

CONVENTION_KINDS = ("full", "incremental")
CONCEPT_WORD_KINDS = ("event", "entity", "summary", "measure_suffixes", "filter_words")
_KEYS = ("doc_format", "qualifier_terms", "table_name_convention", "concept_words")
_SUFFIX = re.compile(r"[a-z0-9]+")


class DomainProfileError(ValueError):
    """A profile that cannot be read; the message names the field."""


@dataclass(frozen=True)
class DomainProfile:
    qualifier_terms: tuple[str, ...] = ()
    # ``{"full": (...), "incremental": (...)}``, or None when no convention is configured.
    name_convention: dict[str, tuple[str, ...]] | None = None
    concept_words: dict[str, tuple[str, ...]] = field(default_factory=dict)


def load_domain_profile(path: str | Path, source: str = FLAG) -> DomainProfile:
    """Read one profile file; ``source`` (the flag or ``DOMAIN_PROFILE_ENV``) heads every error."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise DomainProfileError(f"{source} {path}: not a readable JSON file ({error})") from None
    try:
        return parse_domain_profile(document)
    except DomainProfileError as error:
        raise DomainProfileError(f"{source} {path}: {error}") from None


def parse_domain_profile(document) -> DomainProfile:
    if not isinstance(document, dict):
        raise DomainProfileError(f"top level is {type(document).__name__}, not an object")
    if document.get("doc_format") != DOC_FORMAT:
        raise DomainProfileError(f"doc_format must be {DOC_FORMAT!r}")
    unknown = sorted(set(document) - set(_KEYS))
    if unknown:
        raise DomainProfileError(f"unknown key(s): {', '.join(unknown)}")
    convention = document.get("table_name_convention")
    return DomainProfile(
        qualifier_terms=_words(document.get("qualifier_terms", []), "qualifier_terms"),
        name_convention=None if convention is None else _convention(convention),
        concept_words=_sections(document.get("concept_words", {}), "concept_words",
                                CONCEPT_WORD_KINDS),
    )


def _convention(value) -> dict[str, tuple[str, ...]]:
    sections = _sections(value, "table_name_convention", CONVENTION_KINDS)
    for kind, suffixes in sections.items():
        lowered = tuple(suffix.lower() for suffix in suffixes)
        bad = [suffix for suffix in lowered if not _SUFFIX.fullmatch(suffix)]
        if bad:
            raise DomainProfileError(
                f"table_name_convention.{kind}: a suffix is letters and digits only, "
                f"written without its '_' ({bad[0]!r})")
        sections[kind] = lowered
    return sections


def _sections(value, name: str, kinds: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, dict):
        raise DomainProfileError(f"{name} must be an object")
    unknown = sorted(set(value) - set(kinds))
    if unknown:
        raise DomainProfileError(
            f"{name}: unknown key(s) {', '.join(unknown)} (known: {', '.join(kinds)})")
    return {kind: _words(value[kind], f"{name}.{kind}") for kind in kinds if kind in value}


def _words(value, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise DomainProfileError(f"{name} must be a list of non-empty strings")
    return tuple(dict.fromkeys(item.strip() for item in value))
