"""Table identity: the one answer to "are these two spellings the same table?" (audit WP5).

Every layer asks it -- metadata lookup, the lineage target, the table cards, the
glossary, the catalog view -- and they used to answer it four different ways, so the
same corpus was one table in one view and two in the next. This leaf module owns both
halves of the answer, and each layer calls it:

* **Normalization** (:func:`canonical_table_name`): identifier quotes dropped, lower case
  (Spark identifiers are case-insensitive), and a leading catalog segment dropped *only
  when* ``SCOPE_LINEAGE_CATALOG_PREFIXES`` names it (D1: the configuration decides). A
  three-part name is ambiguous text -- ``catalog.db.table`` or ``db.table.column`` -- so
  nothing is ever stripped by position alone, and two catalogs' ``ods.t`` stay two tables.
* **Grouping** (:func:`group_spellings`, :class:`TableResolver`): a dotted suffix of the
  other name is the same table (one corpus records ``dwd.t`` at a hive-style read and
  ``catalog.dwd.t`` at the iceberg writer), with one stop: a less qualified spelling joins
  only the one host it could be. When two hosts could be it -- a bare ``orders`` beside
  ``dwd.orders`` and ``ods.orders``, or an ``ods.t`` beside ``cat1.ods.t`` and
  ``cat2.ods.t`` -- it stays its own name and is reported ambiguous. Guessing would
  publish one table's facts as the other's.

A package-root leaf module: it imports nothing from ``scope_lineage``, so the metadata,
scope and render layers can all use it without a new dependency edge.
"""

from __future__ import annotations

import os
import re
from typing import Iterable, Mapping, Optional, Sequence

CATALOG_PREFIXES_ENV = "SCOPE_LINEAGE_CATALOG_PREFIXES"

# Catalog stripping is deployment-specific. Public Core has no built-in catalog vocabulary;
# callers opt in through the environment variable above.
DEFAULT_CATALOG_PREFIXES: tuple[str, ...] = ()

# An unbound run parameter (``${name}``) is a template slot, not an identifier: its
# spelling is what the run binds, so it keeps its case.
_PARAMETER = re.compile(r"\$\{\w+\}")


def catalog_prefixes() -> frozenset:
    """Catalog segments to strip from qualified names.

    3-segment strings are ambiguous (catalog.db.table vs db.table.field), so
    stripping must be vocabulary-conditioned, never unconditional. Configure
    SCOPE_LINEAGE_CATALOG_PREFIXES with a comma-separated allowlist when needed.
    """
    env = os.environ.get(CATALOG_PREFIXES_ENV)
    if env is not None:
        return frozenset(part.strip().lower() for part in env.split(",") if part.strip())
    return frozenset(DEFAULT_CATALOG_PREFIXES)


def _segment(part: str) -> str:
    part = part.strip().strip("`").strip()
    if _PARAMETER.search(part):
        # Lower-case around the slots, never inside them.
        pieces = _PARAMETER.split(part)
        slots = _PARAMETER.findall(part)
        out = pieces[0].lower()
        for slot, rest in zip(slots, pieces[1:]):
            out += slot + rest.lower()
        return out
    return part.lower()


def strip_catalog_prefix(value: str) -> str:
    """Drop a LEADING configured catalog segment (safe for ``db.table.field`` refs).

    The spelling is otherwise left alone; :func:`canonical_table_name` is the full
    normalization. The catalog test itself ignores quotes and case, so
    ``SPARK_CATALOG.mart.y`` loses its catalog the way ``spark_catalog.mart.y`` does.
    """
    parts = [part for part in str(value or "").split(".") if part]
    if len(parts) >= 3 and _segment(parts[0]) in catalog_prefixes():
        parts = parts[1:]
    return ".".join(parts)


def canonical_table_name(name: object) -> str:
    """The one spelling of a table name every layer keys on.

    ``\\`ODS\\`.\\`Orders\\``` -> ``ods.orders``; ``SPARK_CATALOG.mart.y`` -> ``mart.y``
    when ``spark_catalog`` is configured, kept whole when it is not.
    """
    parts = [_segment(part) for part in str(name or "").strip().split(".")]
    parts = [part for part in parts if part]
    if len(parts) >= 3 and parts[0] in catalog_prefixes():
        parts = parts[1:]
    return ".".join(parts)


def same_table(left: str, right: str) -> bool:
    """The corpus-wide suffix rule: equal, or a dotted suffix of the other name.

    Mirrors ``skills/scope-lineage/scripts/query.py::_same_table``; a packaged module may
    not import a script. Compares the spellings as given: callers that may hold raw
    spellings normalize first.
    """
    left, right = str(left), str(right)
    return left == right or left.endswith("." + right) or right.endswith("." + left)


def table_bucket(name: object) -> str:
    """The last segment: the only names ``same_table`` can ever relate share it.

    The rule is equality or "a dotted suffix of the other", and a dotted suffix ends
    where the other name ends, so grouping never crosses two last segments. A caller that
    wants *the spellings that could be this table* selects on this key alone.
    """
    return str(name or "").rpartition(".")[2]


def _depth(name: str) -> int:
    return name.count(".") + 1


def group_spellings(names: Iterable[str]) -> tuple[list[list[str]], set[str]]:
    """``(groups, ambiguous names)`` -- the suffix rule, with its one stop.

    Names are taken most qualified first. Each one joins the group it is a suffix of when
    there is exactly one such group; when there is none it starts its own; when there are
    several it starts its own and is reported ambiguous. So ``catalog.dwd.t``, ``dwd.t``
    and ``t`` are one table, while ``cat1.ods.t`` and ``cat2.ods.t`` are two and an
    ``ods.t`` written beside both is neither: a less qualified name is resolved, never
    used as the bridge that merges two tables into one.

    The spellings are compared as given; normalize them first when they may differ in
    quotes or case. Groups are sorted, and listed in a stable order.
    """
    ordered = sorted({str(name) for name in names if str(name)}, key=lambda n: (-_depth(n), n))
    groups: list[list[str]] = []
    by_bucket: dict[str, list[list[str]]] = {}
    ambiguous: set[str] = set()
    for name in ordered:
        bucket = by_bucket.setdefault(table_bucket(name), [])
        hosts = [group for group in bucket if any(same_table(name, item) for item in group)]
        if len(hosts) == 1:
            hosts[0].append(name)
            continue
        if hosts:
            ambiguous.add(name)
        group = [name]
        groups.append(group)
        bucket.append(group)
    for group in groups:
        group.sort()
    groups.sort()
    return groups, ambiguous


def ambiguous_names(names: Iterable[str]) -> set[str]:
    """The less qualified names more than one table in ``names`` could be."""
    return group_spellings(names)[1]


def primary_name(group: Sequence[str]) -> str:
    """The most qualified spelling; ties break by name so the choice cannot drift."""
    return min(group, key=lambda name: (-len(name), name))


class TableResolver:
    """Resolve any spelling against a known set of table names.

    ``primary(name)`` is the primary spelling of the group ``name`` belongs to: an exact
    (normalized) spelling first; otherwise the one group it is a dotted suffix of, or that
    is a dotted suffix of it; ``None`` when no group or several could be it. The second
    direction lets ``lake.ods.t`` find metadata keyed ``ods.t``, and the uniqueness stop
    keeps ``ods.t`` from borrowing ``cat1.ods.t`` when ``cat2.ods.t`` is also known.
    """

    def __init__(self, names: Iterable[str], *, normalize: bool = True) -> None:
        self._normalize = normalize
        spellings = [self._key(name) for name in names]
        groups, self.ambiguous = group_spellings(spellings)
        self._primary: dict[str, str] = {}
        self._buckets: dict[str, set[str]] = {}
        for group in groups:
            head = primary_name(group)
            for member in group:
                self._primary[member] = head
                self._buckets.setdefault(table_bucket(member), set()).add(member)

    def _key(self, name: object) -> str:
        return canonical_table_name(name) if self._normalize else str(name or "")

    def primary(self, name: object) -> Optional[str]:
        key = self._key(name)
        if not key:
            return None
        if key in self._primary:
            return self._primary[key]
        hosts = {
            self._primary[member]
            for member in self._buckets.get(table_bucket(key), ())
            if same_table(key, member)
        }
        return next(iter(hosts)) if len(hosts) == 1 else None

    def groups(self) -> dict[str, list[str]]:
        """``primary -> every spelling``, as given to the constructor (normalized)."""
        found: dict[str, list[str]] = {}
        for member, head in self._primary.items():
            found.setdefault(head, []).append(member)
        return {head: sorted(members) for head, members in found.items()}


def resolve_key(name: object, keys: Iterable[str], *, min_depth: int = 1) -> Optional[str]:
    """The one key of ``keys`` that names the same table as ``name``, or None.

    An exact normalized key first; otherwise the single key related to it by the suffix
    rule. ``min_depth`` excludes shorter keys and names from the suffix step: metadata
    passes 2, so a bare ``t`` never borrows ``ods.t``'s columns, as it never did.
    """
    key = canonical_table_name(name)
    if not key:
        return None
    pool = list(keys)
    if key in pool:
        return key
    if _depth(key) < min_depth:
        return None
    found = [
        item for item in pool if _depth(item) >= min_depth and same_table(key, item)
    ]
    return found[0] if len(found) == 1 else None


def card_spellings(card: Mapping) -> list[str]:
    """Every name a table card answers to: its ``table`` and its ``aliases``."""
    return [str(item) for item in [card.get("table"), *(card.get("aliases") or [])] if item]


def find_card(cards: Sequence[Mapping], table: object) -> Optional[Mapping]:
    """The table card for ``table``, or None: the one lookup both card readers share.

    An exact (normalized) spelling first -- the card's ``table`` or one of its
    ``aliases`` -- so a bare ``orders`` with its own card finds that card rather than
    ``dwd.orders`` (WP2d). Otherwise the suffix rule, taken only when it names one card:
    a name two cards could be finds neither.
    """
    key = canonical_table_name(table)
    if not key:
        return None
    for card in cards:
        if key in [canonical_table_name(name) for name in card_spellings(card)]:
            return card
    found = [
        card
        for card in cards
        if any(same_table(key, canonical_table_name(name)) for name in card_spellings(card))
    ]
    return found[0] if len(found) == 1 else None
