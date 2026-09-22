"""The corpus-level term and value dictionary (``glossary-json/1``).

WI-2.4. ``describe`` answers "what does this task do" one task at a time; the glossary
answers the question that only a corpus can answer: *this column appears in nine tables,
here is every comment anybody wrote for it, and here is every constant the warehouse's
SQL actually compares it against*. It is the layer the semantic profile was missing --
``'PAID'`` used to land in "待业务确认" because nothing in one statement could say more.

Two halves, deliberately separated:

- **terms** merge column comments across tables by column NAME. Two different comment
  texts for one name is a ``conflict`` -- published side by side, never resolved here.
- **values** are the observations ``glossary_values`` collects, aggregated across tasks,
  with a ``closed_set`` when the SQL proves the set is closed (an IN list; a CASE whose
  branches and ELSE are all constants) and ``meaning_candidates`` when a comment spells
  the value out literally.

``meaning`` stays ``null`` until a human answers. That is what ``glossary.overrides.json``
is for: a reviewed file of ``{column: meaning}`` / ``{column='VALUE': meaning}`` entries,
merged in with ``source: "override"``. A key that matches nothing is reported under
``overrides_applied.unmatched`` rather than dropped, because a typo in a reviewed file is
exactly the thing a reviewer cannot see.

Q1 adds the COLUMN FAMILY key, ``*.<column>='VALUE'``: one code table copied into table
after table is one business question, and answering it once per table is transcription.
A key that names a table wins on that table and the family key answers the rest; how far
the one answer travelled is reported under ``overrides_applied.family_expansions``.

P5 gives that file the ontology review's evidence discipline. An entry may say what its
answer rests on (``basis``, published as ``meaning.confirmed_basis``) and add a ``note``;
a field this release does not read is reported under ``ignored_fields`` rather than
dropped; and an answer signed ``confirmed_by: "agent:…"`` **must** carry a ``basis``, or
the whole entry is refused into ``rejected``. An Agent's answer is read off the corpus
rather than known, so the sentence saying what it was read from is the only thing that
makes it reviewable -- and an unreviewable ``confirmed`` is an inference wearing a
signature.

N6 hangs the whole thing on CONCEPTS. ``terms[]`` merges by bare column NAME, which is
all a dictionary alone can key on -- and one name short of the question a reviewer asks:
three tables spelling ``pay_status`` are the same *attribute of one concept* only if
something says those tables are three representations of one thing. ``ontology.json``
says it. So ``build_glossary(..., ontology=...)`` publishes ``concept_terms[]`` -- one
entry per (concept, attribute), the term facts merged across that concept's
representation tables, carrying the value entries of those columns -- and an overrides
key ``concept:<id>.<attribute>=<value>`` that answers every source column at once. It
sits between the two keys that already exist, and the order is the argument: a key that
NAMES a table wins there, a CONCEPT key is a claim somebody made about which columns are
one thing, and the ``*.<column>`` family key rests on a coincidence of spelling.

Without an ontology none of it happens: no ``concept_terms``, no ``concepts`` back-link,
no concept report -- the dictionary is byte for byte the document it was.

This module is the structure-aligned early slice of the phase-two ontology's
``value_domains`` / ``synonyms``: a ``values[]`` entry carries the same
(column, value, evidence, task count, completeness) shape an ``in_set`` constraint does.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence

from . import glossary_values
from .glossary_markdown import render_glossary_markdown  # noqa: F401 -- public facade
from .glossary_values import (
    AGENT_CONFIRMATION_PREFIX,
    aggregate_values,
    canonical_owner,
    canonical_name,
    same_table,
    statement_observations,
    strip_quotes,
    table_key,
)
from .mapping_markdown import lineage_document_digest
from .semantic_profile import build_semantic_profile


DOC_FORMAT = "glossary-json/1"

MEANING_SOURCE_OVERRIDE = "override"

# Q1. What a COLUMN FAMILY key starts with: `*.pay_status='PAID'` answers that value on
# every table whose column of that name observed it.
FAMILY_KEY_PREFIX = "*."

# N6b. The tier of a concept the ontology invented to hold ONE table nobody's key could
# place (the ontology's own ``concepts.TIER_PROVISIONAL``; the test file pins the two
# together). Such a concept asserts nothing this dictionary does not already know: every
# table has one, its attributes are that table's columns under longer names, and on a
# wide corpus publishing them buries the attributes that really do span several tables --
# which are the only ones a concept-level answer is worth writing. So the concept layer
# is built over the concepts somebody could actually place.
PROVISIONAL_TIER = "provisional"

# N6. What a CONCEPT key starts with -- it is the concept's own id, so the key reads
# `concept:order.pay_status='PAID'`: that attribute of that concept, on every table the
# ontology says represents it.
CONCEPT_KEY_PREFIX = "concept:"

# N6. The three key kinds, in the order they are resolved. A table name beats a concept
# beats a column name, because that is the order of how much each one claims.
KIND_EXACT = "exact"
KIND_CONCEPT = "concept"
KIND_FAMILY = "family"

# P5. Every field one ``terms`` / ``values`` entry of an overrides file may carry.
# Anything else is reported under ``overrides_applied.ignored_fields`` instead of being
# dropped: a misspelled slot in a reviewed file takes effect nowhere and shows nowhere.
OVERRIDE_FIELDS = ("meaning", "text", "confirmed_by", "date", "basis", "note")

# P5. Why a confirmation this file names was refused rather than published.
REASON_MISSING_BASIS = "missing_basis"

# N6. Why a `concept:` key bound nothing. `unmatched` is a list of bare strings and has
# no room for a reason, and these two are not typos in the value half: the file named a
# concept or an attribute this ontology does not have, which is a different mistake.
REASON_UNKNOWN_CONCEPT = "unknown_concept"
REASON_UNKNOWN_ATTRIBUTE = "unknown_attribute"

TASK_SCHEMA_VERSION = "2.0"

# WI-2.12: where a confirmed corpus term lands on the describe side.
TERM_MEANING_KEY = "term_meaning"

# N6: `concept_terms` is published only when an ontology was supplied, so a dictionary
# built without one keeps exactly the keys it always had.
GLOSSARY_KEYS = (
    "doc_format",
    "corpus",
    "terms",
    "concept_terms",
    "concept_terms_summary",
    "values",
    "parameters",
    "overrides_applied",
)

# P2: which keys of a semantic profile ``build_glossary`` reads, and so the whole of what
# `scope-lineage glossary --incremental` stores per task. It lives here, next to the code
# that reads them, so a builder that starts reading a new key has the list under its nose;
# `tests/core/test_corpus_cache_projection.py` fails until the two agree. The dictionary
# takes its terms and its table identity from the contract *documents*, so all it wants
# from the profile is where the constants are: the rules, and the constant projections
# inside each field's derivation. Everything the reader half of a profile is made of --
# `stages`, `confidence`, `inputs`, `output_shape`, the field summaries -- is not read
# here and is not stored.
PROFILE_FIELDS_READ = {
    "profile": (),
    "statement": {
        "statement_id": None,
        "rules": None,
        "fields": (
            "column",
            "sql_alias",
            "sql_comments",
            "mapping_chain_id",
            "derivation",
            "generated_sources",
        ),
    },
}


# A schema-less `SELECT *` leaves the wildcard itself in `column_details`. It is a
# projection marker, not a column anybody can look a meaning up for.
_NOT_A_COLUMN_NAME = frozenset({"*", "EXPAND_ALL"})

_TERM_KEYS = (
    "column",
    "comments",
    "tables_total",
    "tables_without_comment",
    "conflict",
    # N6: which concept attributes this column name feeds. Absent without an ontology.
    "concepts",
    "meaning",
)


def build_glossary(
    documents: Iterable[Mapping],
    *,
    artifact_root: str = ".",
    overrides: Mapping | None = None,
    profiles: Sequence[Mapping] | None = None,
    ontology: Mapping | None = None,
) -> dict:
    """Aggregate a corpus of lineage documents into one term / value dictionary.

    ``documents`` are contract documents (1.0 statement or 2.0 task shape), exactly what
    ``describe`` reads. ``artifact_root`` is recorded verbatim, so a caller that wants
    reproducible bytes passes a relative label rather than an absolute path. ``profiles``
    is one semantic profile per document in the same order -- built *without* diagnostics,
    which is what this builder would build for itself -- so a caller holding them already
    (the incremental CLI reads them from its fact cache) does not pay for them twice.

    ``ontology`` (N6) is an ``ontology-json/2`` document, read as a plain dict: its
    ``concepts[].attributes[].sources[]`` say which (table, column) pairs are one
    attribute of one concept, and that is the only thing this module takes from it. It
    is optional and additive -- without it the document is unchanged.
    """
    documents = list(documents)
    supplied = list(profiles) if profiles is not None else [None] * len(documents)
    statements = [
        pair
        for document, profile in zip(documents, supplied)
        for pair in _statement_pairs(document, profile)
    ]
    canonical = _canonical_tables(statements)
    observations = [
        observation
        for statement, profile, task in statements
        for observation in statement_observations(
            statement,
            profile.get("rules") or [],
            profile.get("fields") or [],
            task=task,
            statement_id=profile.get("statement_id"),
        )
    ]
    values = aggregate_values(observations, canonical)
    columns = _column_comments(statements, canonical)
    concepts = (
        _concept_terms(ontology, columns, values, canonical) if ontology else None
    )
    glossary = {
        "doc_format": DOC_FORMAT,
        "corpus": _corpus_block(documents, statements, artifact_root),
        "terms": _build_terms(columns, concepts),
        "values": values,
        "parameters": _build_parameters(observations, canonical),
        "overrides_applied": {"terms": 0, "values": 0, "blank": 0, "unmatched": []},
    }
    if concepts is not None:
        glossary["concept_terms"] = concepts
        glossary["concept_terms_summary"] = _concept_terms_summary(concepts)
    _apply_overrides(glossary, overrides or {})
    return {key: glossary[key] for key in GLOSSARY_KEYS if key in glossary}


# ---------------------------------------------------------------- corpus traversal


def _statement_pairs(
    document: Mapping, profile: Mapping | None = None
) -> list[tuple[dict, dict, str]]:
    """``(statement document, statement profile, task id)`` for every write statement."""
    profile = dict(profile) if profile is not None else build_semantic_profile(document)
    task = str(document.get("task_id") or "")
    if document.get("schema_version") != TASK_SCHEMA_VERSION:
        return [(dict(document), profile, task)]
    lineage = document.get("statement_lineage") or {}
    return [
        (lineage[statement["statement_id"]], statement, task)
        for statement in profile.get("statements") or []
        if statement.get("statement_id") in lineage
    ]


def _corpus_block(
    documents: Sequence[Mapping], statements: Sequence[tuple], artifact_root: str
) -> dict:
    return {
        "artifact_root": str(artifact_root),
        "task_count": len(documents),
        "statement_count": len(statements),
        "lineage_digests": {
            str(document.get("task_id") or ""): lineage_document_digest(document)
            for document in sorted(
                documents, key=lambda item: str(item.get("task_id") or "")
            )
        },
    }


def _canonical_tables(statements: Sequence[tuple]) -> dict[tuple, str]:
    """``table_key -> most qualified spelling``, so one table is counted once."""
    spellings: dict[tuple, set] = {}
    for statement, _profile, _task in statements:
        metadata = statement.get("related_metadata") or {}
        names = [
            *(statement.get("source_tables") or []),
            *(metadata.get("input_tables") or {}),
            *(metadata.get("output_tables") or {}),
        ]
        if statement.get("target_table"):
            names.append(str(statement["target_table"]))
        for name in names:
            spellings.setdefault(table_key(name), set()).add(str(name))
    return {key: canonical_name(names) for key, names in spellings.items()}


# ----------------------------------------------------------------------- terms


def _column_comments(
    statements: Sequence[tuple], canonical: Mapping
) -> dict[str, dict[str, str | None]]:
    """``column name -> {table: its comment or None}`` over the whole corpus.

    The one traversal both term layers read: ``terms[]`` groups it by column NAME, and
    N6's ``concept_terms[]`` picks out of the same map the (table, column) pairs one
    concept attribute is written on. A table carrying the column with no comment is kept
    with ``None`` -- that is what ``tables_without_comment`` counts.
    """
    tables: dict[str, dict[str, str | None]] = {}
    for statement, _profile, _task in statements:
        metadata = statement.get("related_metadata") or {}
        for group in ("input_tables", "output_tables"):
            for name, item in (metadata.get(group) or {}).items():
                table = canonical_owner(str(name), False, canonical)
                for detail in (item or {}).get("column_details") or []:
                    column = str(detail.get("name"))
                    if column in _NOT_A_COLUMN_NAME:
                        continue
                    comment = detail.get("comment")
                    current = tables.setdefault(column, {})
                    if comment or table not in current:
                        current[table] = comment
    return tables


def _build_terms(columns: Mapping, concepts: Sequence[Mapping] | None) -> list[dict]:
    """Column comments merged across the corpus by column name."""
    links = _concept_links(concepts) if concepts is not None else None
    return [
        _ordered_term(_term(column, columns[column], links)) for column in sorted(columns)
    ]


def _comment_groups(by_table: Mapping[str, str | None]) -> list[dict]:
    """One entry per distinct comment TEXT, commonest first, ties broken by the text."""
    texts: dict[str, list[str]] = {}
    for table, comment in sorted(by_table.items()):
        if comment:
            texts.setdefault(str(comment), []).append(table)
    return [
        {"text": text, "tables": tables, "count": len(tables)}
        for text, tables in sorted(texts.items(), key=lambda item: (-len(item[1]), item[0]))
    ]


def _term(
    column: str, by_table: Mapping[str, str | None], links: Mapping | None = None
) -> dict:
    comments = _comment_groups(by_table)
    term = {
        "column": column,
        "comments": comments,
        "tables_total": len(by_table),
        "tables_without_comment": sorted(
            table for table, comment in by_table.items() if not comment
        ),
        "conflict": len(comments) >= 2,
        "meaning": None,
    }
    if links is not None:
        term["concepts"] = list(links.get(column, ()))
    return term


def _ordered_term(term: dict) -> dict:
    return {key: term[key] for key in _TERM_KEYS if key in term}


# ------------------------------------------------------------------ concept terms


def _concept_terms(
    ontology: Mapping, columns: Mapping, values: Sequence[dict], canonical: Mapping
) -> list[dict]:
    """One entry per (concept, attribute), ordered by concept id then attribute.

    N6. The attribute is the unit a reviewer can answer once: its ``columns`` are the
    (table, column) pairs the ontology says are one thing, its ``comments`` are the same
    merge ``terms[]`` does taken over exactly those pairs, and its ``values`` are the
    dictionary's own entries for them -- the very objects, so a confirmation applied
    afterwards shows through here too.

    N6b: over the concepts somebody could place, and then over **all** of their
    attributes. Dropping a one-table attribute of a real concept would be the wrong cut:
    it is still that concept's attribute, and the next corpus may well be where its
    second representation shows up. What the row says instead is how far it reaches --
    ``representation_count`` -- so a reader can tell the attribute worth one concept-level
    answer from the one that currently has exactly one column.
    """
    entries = [
        _concept_term(concept, attribute, columns, values, canonical)
        for concept in ontology.get("concepts") or []
        if str(concept.get("tier")) != PROVISIONAL_TIER
        for attribute in concept.get("attributes") or []
    ]
    return sorted(entries, key=lambda item: (item["concept"], item["attribute"]))


def _concept_terms_summary(concepts: Sequence[Mapping]) -> dict[str, int]:
    """The three numbers that say what the concept layer is worth on this corpus.

    ``attributes_spanning_multiple_tables`` is the one that matters: those are the
    questions a concept-level answer actually collapses. Published beside the layer so a
    reader does not have to count the rows to find out whether reading it pays.
    """
    return {
        "concepts": len({str(entry["concept"]) for entry in concepts}),
        "attributes": len(concepts),
        "attributes_spanning_multiple_tables": sum(
            1 for entry in concepts if entry["representation_count"] > 1
        ),
    }


def _concept_term(
    concept: Mapping,
    attribute: Mapping,
    columns: Mapping,
    values: Sequence[dict],
    canonical: Mapping,
) -> dict:
    """One concept attribute, under the corpus's own spelling of each source table."""
    sources = sorted(
        {
            (
                canonical_owner(str(item.get("table") or ""), False, canonical),
                str(item.get("column") or ""),
            )
            for item in attribute.get("sources") or []
        }
    )
    by_table = {
        table: columns[column][table]
        for table, column in sources
        if table in columns.get(column, {})
    }
    comments = _comment_groups(by_table)
    return {
        "concept": str(concept.get("id") or ""),
        "name": str(concept.get("name") or ""),
        "attribute": str(attribute.get("stem") or ""),
        "columns": [{"table": table, "column": column} for table, column in sources],
        # N6b. How many representation tables write this attribute. 1 is an attribute
        # that reaches exactly one column today: real, kept, and not yet worth a
        # concept-level answer.
        "representation_count": len({table for table, _column in sources}),
        "comments": comments,
        "conflict": len(comments) >= 2,
        "values": _attribute_values(sources, values),
    }


def _attribute_values(sources: Sequence[tuple], values: Sequence[dict]) -> list[dict]:
    """The dictionary's entries for this attribute's columns, in dictionary order.

    Physical entries only: a scope-level reference names an expression inside one
    statement, and no concept is represented by a CTE.
    """
    wanted = {(table_key(table), column) for table, column in sources}
    return [
        entry
        for entry in values
        if not entry.get("logical")
        and (table_key(str(entry["column_ref"]).rsplit(".", 1)[0]), str(entry["column"]))
        in wanted
    ]


def _concept_links(concepts: Sequence[Mapping]) -> dict[str, list[dict]]:
    """``column name -> the concept attributes it feeds``: the ``terms[]`` back-link."""
    links: dict[str, list[dict]] = {}
    for entry in concepts:
        link = {"concept": entry["concept"], "attribute": entry["attribute"]}
        for column in entry["columns"]:
            found = links.setdefault(str(column["column"]), [])
            if link not in found:
                found.append(link)
    return links


# -------------------------------------------------------------------- parameters


def _build_parameters(observations: Sequence[Mapping], canonical: Mapping) -> list[dict]:
    """Substitutions and function calls: they pin a column, but they are not its values."""
    grouped: dict[tuple, list[Mapping]] = {}
    for item in observations:
        if item["kind"] in glossary_values.GLOSSARY_VALUE_KINDS:
            continue
        owner = canonical_owner(
            str(item["column_ref"]).rsplit(".", 1)[0], bool(item.get("logical")), canonical
        )
        reference = f"{owner}.{item['column']}"
        grouped.setdefault((reference, item["expression"], item["kind"]), []).append(item)
    return [
        {
            "column_ref": reference,
            "expression": expression,
            "kind": kind,
            "task_count": len({item["task"] for item in members}),
        }
        for (reference, expression, kind), members in sorted(grouped.items())
    ]


# --------------------------------------------------------------------- overrides


def _apply_overrides(glossary: dict, overrides: Mapping) -> None:
    concepts = glossary.get("concept_terms")
    report = _Report()
    terms = _apply_term_overrides(glossary["terms"], overrides.get("terms") or {}, report)
    values = _apply_value_overrides(
        glossary["values"], overrides.get("values") or {}, report, concepts
    )
    glossary["overrides_applied"] = {
        "terms": terms,
        "values": values,
        # N6. The concept half of the same report, and only when there was an ontology
        # to read concepts from: what each `concept:<id>.<attribute>=<value>` key
        # reached, and which of them named a concept or an attribute that is not there.
        **(
            {
                "concept_expansions": report.concept_expansions,
                "concept_unmatched": report.concept_unmatched,
            }
            if concepts is not None
            else {}
        ),
        # Q1. What each `*.<column>=<value>` key reached. One code table repeated across
        # many tables is one question, and a reviewer who answers it once has to be able
        # to see how far that one answer travelled.
        "family_expansions": report.family_expansions,
        # WI-2.9 item C. A key whose meaning is still empty: the `glossary --template`
        # form ships every entry blank, and a half-filled form comes back with the rest
        # unanswered. Writing `""` in as a confirmed meaning would turn "nobody has said"
        # into "somebody said nothing", which is the one reading this layer must not
        # publish. So a blank is counted and left alone.
        "blank": len(report.blank),
        "unmatched": sorted(report.unmatched),
        # P5, mirroring the ontology's H2 / the rejection half of its evidence mode.
        "ignored_fields": sorted(report.ignored_fields, key=lambda item: item["key"]),
        "rejected": sorted(
            report.rejected, key=lambda item: (item["key"], item["reason"])
        ),
    }


class _Report:
    """What one overrides file produced besides confirmations, gathered in one place."""

    def __init__(self) -> None:
        self.blank: list[str] = []
        self.unmatched: list[str] = []
        self.ignored_fields: list[dict] = []
        self.rejected: list[dict] = []
        self.family_expansions: list[dict] = []
        self.concept_expansions: list[dict] = []
        self.concept_unmatched: list[dict] = []

    def expanded(self, kind: str, key: str, count: int) -> None:
        """Record how far one answer travelled, for the two keys that travel at all."""
        if kind == KIND_CONCEPT:
            self.concept_expansions.append({"key": key, "applied_to": count})
        elif kind == KIND_FAMILY:
            self.family_expansions.append({"key": key, "applied_to": count})

    def accepts(self, key: str, payload) -> bool:
        """False for a confirmation this release refuses to publish (P5).

        One refusal so far: an Agent signature with no ``basis``. An Agent's answer is
        read off the corpus rather than known, so the sentence saying what closed the
        question IS the confirmation's evidence -- without it nobody can ever review
        why this value is ``confirmed``, which is the one thing a reviewed file owes
        its next reader. Reported in its own list because ``unmatched`` is a list of
        bare key strings that carries no room for a reason, and the key here is not a
        typo: it names something real.
        """
        values = payload if isinstance(payload, Mapping) else {}
        signature = str(values.get("confirmed_by") or "")
        if signature.startswith(AGENT_CONFIRMATION_PREFIX) and not values.get("basis"):
            self.rejected.append({"key": key, "reason": REASON_MISSING_BASIS})
            return False
        return True

    def record_ignored(self, key: str, payload) -> None:
        """A field this release does not read is reported, never dropped in silence."""
        if not isinstance(payload, Mapping):
            return
        extra = sorted(
            str(field) for field in payload if str(field) not in OVERRIDE_FIELDS
        )
        if extra:
            self.ignored_fields.append({"key": key, "fields": extra})


def _apply_term_overrides(terms: Sequence[dict], overrides: Mapping, report: _Report) -> int:
    applied = 0
    for key, payload in overrides.items():
        matches = [term for term in terms if term["column"] == str(key).strip()]
        if not _admitted(str(key), payload, matches, report):
            continue
        for term in matches:
            term["meaning"] = _meaning(payload)
            applied += 1
    return applied


def _apply_value_overrides(
    values: Sequence[dict],
    overrides: Mapping,
    report: _Report,
    concepts: Sequence[Mapping] | None = None,
) -> int:
    """Exact keys first, then the concept keys, then the family keys.

    Q1. ``*.<column>=<value>`` is one answer for a code table the warehouse copied into
    table after table -- the same business question, asked once. The order is the whole
    rule: a key that NAMES a table is a statement about that table, so it wins there,
    and the wider keys answer the rest. Applying them in file order instead would make
    the answer depend on which line the reviewer happened to type first.

    N6 puts the CONCEPT key between the two, and the middle is where it belongs: it
    reaches further than one table because somebody asserted these columns are one
    attribute, and it yields to the family key nowhere, because a shared column NAME is
    a coincidence until an ontology says otherwise.
    """
    applied = 0
    answered: set[int] = set()
    for kind, items in _key_groups(overrides, concepts):
        for key, payload in items.items():
            matches = _matching_values(kind, str(key), values, answered, concepts, report)
            if not _admitted(str(key), payload, matches, report):
                continue
            report.expanded(kind, str(key), len(matches))
            for entry in matches:
                entry["meaning"] = _meaning(payload)
                answered.add(id(entry))
                applied += 1
    return applied


def _key_groups(overrides: Mapping, concepts: Sequence[Mapping] | None) -> list[tuple]:
    """The value keys of one overrides file, grouped by kind, in resolution order."""
    kinds = {key: _key_kind(key, concepts) for key in overrides}
    return [
        (kind, {key: overrides[key] for key in overrides if kinds[key] == kind})
        for kind in (KIND_EXACT, KIND_CONCEPT, KIND_FAMILY)
    ]


def _key_kind(key, concepts: Sequence[Mapping] | None) -> str:
    """Which of the three a key is. Without an ontology there is no concept kind: a
    ``concept:`` key then binds nothing and is reported ``unmatched`` like any other."""
    text = str(key).strip()
    if _is_family_key(text):
        return KIND_FAMILY
    if concepts is not None and text.startswith(CONCEPT_KEY_PREFIX):
        return KIND_CONCEPT
    return KIND_EXACT


def _matching_values(
    kind: str,
    key: str,
    values: Sequence[dict],
    answered: set,
    concepts: Sequence[Mapping] | None,
    report: _Report,
) -> list[dict]:
    """The entries one key still reaches -- the stronger kinds have already been applied."""
    if kind == KIND_FAMILY:
        matches = (entry for entry in values if _family_key_matches(key, entry))
    elif kind == KIND_CONCEPT:
        sources = _concept_sources(key, concepts or (), report)
        matches = (entry for entry in values if _concept_key_matches(key, sources, entry))
    else:
        matches = (entry for entry in values if _value_key_matches(key, entry))
    return [entry for entry in matches if id(entry) not in answered]


def _concept_sources(key: str, concepts: Sequence[Mapping], report: _Report) -> set:
    """``{(table key, column)}`` the attribute this key names is written on.

    An empty set is a key that reaches nothing, and the two structural ways that happens
    are reported with their reason: the file named a concept, or an attribute of it,
    that this ontology does not have. A key that names a real attribute no value of
    which was observed is an ordinary miss and lands in ``unmatched`` alone.
    """
    concept, _, attribute = key.partition("=")[0].strip().rpartition(".")
    of_concept = [item for item in concepts if item["concept"] == concept]
    if not of_concept:
        report.concept_unmatched.append({"key": key, "reason": REASON_UNKNOWN_CONCEPT})
        return set()
    entry = next((item for item in of_concept if item["attribute"] == attribute), None)
    if entry is None:
        report.concept_unmatched.append({"key": key, "reason": REASON_UNKNOWN_ATTRIBUTE})
        return set()
    return {
        (table_key(column["table"]), str(column["column"])) for column in entry["columns"]
    }


def _concept_key_matches(key: str, sources: set, entry: Mapping) -> bool:
    """``concept:order.pay_status='PAID'`` matches that value on every source column."""
    right = key.partition("=")[2]
    if not sources or entry.get("logical"):
        return False
    owner = str(entry["column_ref"]).rsplit(".", 1)[0]
    if (table_key(owner), str(entry["column"])) not in sources:
        return False
    return strip_quotes(entry["value"]) == strip_quotes(right.strip())


def _is_family_key(key) -> bool:
    return str(key).strip().startswith(FAMILY_KEY_PREFIX)


def _family_key_matches(key: str, entry: Mapping) -> bool:
    """``*.pay_status='PAID'`` matches that value on every TABLE that observed it.

    Physical columns only: ``*.`` says "every table", and a scope-level reference names
    an expression inside one statement rather than a table anybody can look up.
    """
    left, separator, right = key.strip().partition("=")
    if not separator or entry.get("logical"):
        return False
    column = left.strip()[len(FAMILY_KEY_PREFIX):]
    return bool(column) and entry["column"] == column and strip_quotes(
        entry["value"]
    ) == strip_quotes(right.strip())


def _admitted(key: str, payload, matches: Sequence, report: _Report) -> bool:
    """The three ways one entry stops short of becoming a confirmation, in order."""
    if not _meaning(payload)["text"]:
        report.blank.append(key)
        return False
    if not report.accepts(key, payload):
        return False
    if not matches:
        report.unmatched.append(key)
        return False
    report.record_ignored(key, payload)
    return True


def _value_key_matches(key: str, entry: Mapping) -> bool:
    """``ods.t.col='X'`` matches one column; ``col='X'`` matches every same-named one."""
    left, separator, right = key.partition("=")
    if not separator:
        return False
    left, right = left.strip(), right.strip()
    if strip_quotes(entry["value"]) != strip_quotes(right):
        return False
    if "." not in left:
        return entry["column"] == left
    table, _, column = left.rpartition(".")
    owner = str(entry["column_ref"]).rsplit(".", 1)[0]
    return entry["column"] == column and same_table(owner, table)


def _meaning(payload) -> dict:
    """One confirmation as the dictionary publishes it.

    P5. ``basis`` is published as ``confirmed_basis`` -- the same name the ontology
    gives it -- and both it and ``note`` appear only when the reviewer wrote them, so a
    file that carries neither produces the four-key meaning it always has.
    """
    values = payload if isinstance(payload, Mapping) else {"meaning": payload}
    meaning = {
        "text": str(values.get("meaning") or values.get("text") or ""),
        "source": MEANING_SOURCE_OVERRIDE,
        "confirmed_by": values.get("confirmed_by"),
        "date": values.get("date"),
    }
    for field, published in (("basis", "confirmed_basis"), ("note", "note")):
        if values.get(field):
            meaning[published] = str(values[field])
    return meaning


# ------------------------------------------------------ describe-side consumption


def apply_glossary(profile: dict, glossary: Mapping | None) -> dict:
    """Re-answer every field's ``value_domain`` from a corpus glossary, in place.

    ``describe`` already publishes a value domain built from the one statement it read.
    A corpus glossary widens it two ways a single statement cannot: another task may pin
    the same column to a value this one never mentions, and a human may have confirmed
    what the value means in ``glossary.overrides.json``. ``None`` leaves the profile
    exactly as ``build_semantic_profile`` wrote it, so ``describe`` without ``--glossary``
    is byte for byte the document it was before.
    """
    if not glossary:
        return profile
    entries = glossary.get("values") or []
    terms = _confirmed_term_meanings(glossary)
    concepts = glossary.get("concept_terms") or ()
    task = str(profile.get("task_id") or "")
    for statement in profile.get("statements") or [profile]:
        _apply_statement_glossary(statement, entries, terms, task, concepts)
    return profile


def _apply_statement_glossary(
    statement: dict,
    entries: Sequence[Mapping],
    terms: Mapping,
    task: str,
    concepts: Sequence[Mapping] = (),
) -> None:
    """One statement's three consumers of the dictionary: fields, rules and terms."""
    fields = statement.get("fields") or []
    rules = statement.get("rules") or []
    task_block = statement.get("task") or {}
    glossary_values.apply_value_domains(fields, entries, task_block.get("target_table"))
    # WI-2.12. A 1.0 statement profile names its task only inside `task.task_name`; a 2.0
    # task profile carries the id the observations were filed under at the top.
    glossary_values.apply_rule_value_meanings(
        rules, entries, task or str(task_block.get("task_name") or "")
    )
    _apply_term_meanings(statement, terms)
    _record_confirmations(statement, fields, rules, terms, entries, concepts)


def _record_confirmations(
    statement: dict,
    fields: Sequence[Mapping],
    rules: Sequence[Mapping],
    terms: Mapping,
    entries: Sequence[Mapping] = (),
    concepts: Sequence[Mapping] = (),
) -> None:
    """WI-2.6 / WI-2.12: the halves of "what has been answered" only the corpus knows."""
    coverage = glossary_values.glossary_coverage(fields, rules, entries)
    coverage.update(_concept_coverage(concepts, _statement_column_names(statement)))
    confidence = statement.get("confidence") or {}
    if confidence.get("metadata_coverage") is not None:
        confidence["metadata_coverage"]["glossary"] = coverage
    if confidence.get("confirmations") is None:
        return
    confirmations = confidence["confirmations"]
    # `values_confirmed` stays the FIELD half it has always been; the rule half is its
    # own count rather than folded in, because they are answered by different questions.
    confirmations["values_confirmed"] = coverage["field_values_confirmed"]
    confirmations["rule_values_confirmed"] = coverage["rule_values_confirmed"]
    confirmations["terms_confirmed"] = len(
        _statement_column_names(statement) & set(terms)
    )


def _concept_coverage(concepts: Sequence[Mapping], names: set) -> dict[str, int]:
    """How many CONCEPT ATTRIBUTES this task touches, and how many are already answered.

    N6. Counted over the column names the task actually uses, for the same reason
    ``terms_confirmed`` is: a corpus-wide count would say the same number for every task
    and answer nobody's question about this one. Absent entirely when the dictionary
    carries no concept layer -- "no ontology was read" and "no attribute qualified" are
    different facts, and a pair of zeroes reads as the second.
    """
    if not concepts:
        return {}
    touched = [
        entry
        for entry in concepts
        if names & {str(column["column"]) for column in entry["columns"]}
    ]
    return {
        "concept_attributes_total": len(touched),
        "concept_attributes_with_confirmed_values": sum(
            1
            for entry in touched
            if any(
                (value.get("meaning") or {}).get("text") for value in entry["values"]
            )
        ),
    }


def _apply_term_meanings(statement: dict, terms: Mapping) -> None:
    """Carry a confirmed COLUMN meaning to the two places a reader looks for one.

    WI-2.12. A term is not a comment: it is what the corpus calls this column name, and
    the warehouse may never have written a comment for this particular table. So an
    input column carries it beside its own comment, and a target field carries it only
    where ``target_comment`` is empty -- filling that slot would publish a comment the
    metadata does not have, which is the one thing this layer must never do.
    """
    for item in statement.get("inputs") or []:
        for column in item.get("used_columns") or []:
            meaning = terms.get(str(column.get("name")))
            glossary_values.splice_before(column, "usages", TERM_MEANING_KEY, meaning)
    for field in statement.get("fields") or []:
        meaning = (
            None if field.get("target_comment") else terms.get(str(field.get("column")))
        )
        glossary_values.splice_before(
            field, ("sql_comments", "type"), TERM_MEANING_KEY, meaning
        )


def _confirmed_term_meanings(glossary: Mapping) -> dict[str, dict]:
    """``column -> {text, status}`` for every term a human has confirmed, corpus-wide.

    The same two-key shape ``value_domain[].meaning`` publishes, so a consumer reads one
    shape wherever a meaning appears. Only ``confirmed`` is carried: a term has no
    candidate half -- a column comment IS the comment, and this layer only republishes
    what somebody signed.
    """
    return {
        str(term.get("column")): {
            "text": str((term.get("meaning") or {}).get("text") or ""),
            "status": glossary_values.MEANING_STATUS_CONFIRMED,
        }
        for term in glossary.get("terms") or []
        if (term.get("meaning") or {}).get("text")
    }


def _confirmed_term_columns(glossary: Mapping) -> set:
    """Column names a human has confirmed a meaning for, corpus-wide."""
    return set(_confirmed_term_meanings(glossary))


def _statement_column_names(statement: Mapping) -> set:
    """The column names THIS task touches: its output columns and the inputs it reads.

    The denominator of every per-task count this module writes, because a corpus-wide
    one would say the same number for every task and answer nobody's question about
    this one.
    """
    names = {str(field.get("column")) for field in statement.get("fields") or []}
    names.update(
        str(column.get("name"))
        for item in statement.get("inputs") or []
        for column in item.get("used_columns") or []
    )
    return names
