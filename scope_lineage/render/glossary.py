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

P5 gives that file the ontology review's evidence discipline. An entry may say what its
answer rests on (``basis``, published as ``meaning.confirmed_basis``) and add a ``note``;
a field this release does not read is reported under ``ignored_fields`` rather than
dropped; and an answer signed ``confirmed_by: "agent:…"`` **must** carry a ``basis``, or
the whole entry is refused into ``rejected``. An Agent's answer is read off the corpus
rather than known, so the sentence saying what it was read from is the only thing that
makes it reviewable -- and an unreviewable ``confirmed`` is an inference wearing a
signature.

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

# P5. Every field one ``terms`` / ``values`` entry of an overrides file may carry.
# Anything else is reported under ``overrides_applied.ignored_fields`` instead of being
# dropped: a misspelled slot in a reviewed file takes effect nowhere and shows nowhere.
OVERRIDE_FIELDS = ("meaning", "text", "confirmed_by", "date", "basis", "note")

# P5. Why a confirmation this file names was refused rather than published.
REASON_MISSING_BASIS = "missing_basis"

TASK_SCHEMA_VERSION = "2.0"

# WI-2.12: where a confirmed corpus term lands on the describe side.
TERM_MEANING_KEY = "term_meaning"

GLOSSARY_KEYS = (
    "doc_format",
    "corpus",
    "terms",
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
    "meaning",
)


def build_glossary(
    documents: Iterable[Mapping],
    *,
    artifact_root: str = ".",
    overrides: Mapping | None = None,
    profiles: Sequence[Mapping] | None = None,
) -> dict:
    """Aggregate a corpus of lineage documents into one term / value dictionary.

    ``documents`` are contract documents (1.0 statement or 2.0 task shape), exactly what
    ``describe`` reads. ``artifact_root`` is recorded verbatim, so a caller that wants
    reproducible bytes passes a relative label rather than an absolute path. ``profiles``
    is one semantic profile per document in the same order -- built *without* diagnostics,
    which is what this builder would build for itself -- so a caller holding them already
    (the incremental CLI reads them from its fact cache) does not pay for them twice.
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
    glossary = {
        "doc_format": DOC_FORMAT,
        "corpus": _corpus_block(documents, statements, artifact_root),
        "terms": _build_terms(statements, canonical),
        "values": aggregate_values(observations, canonical),
        "parameters": _build_parameters(observations, canonical),
        "overrides_applied": {"terms": 0, "values": 0, "blank": 0, "unmatched": []},
    }
    _apply_overrides(glossary, overrides or {})
    return {key: glossary[key] for key in GLOSSARY_KEYS}


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


def _build_terms(statements: Sequence[tuple], canonical: Mapping) -> list[dict]:
    """Column comments merged across the corpus by column name."""
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
    return [_ordered_term(_term(column, tables[column])) for column in sorted(tables)]


def _term(column: str, by_table: Mapping[str, str | None]) -> dict:
    texts: dict[str, list[str]] = {}
    for table, comment in sorted(by_table.items()):
        if comment:
            texts.setdefault(str(comment), []).append(table)
    comments = [
        {"text": text, "tables": tables, "count": len(tables)}
        for text, tables in sorted(texts.items(), key=lambda item: (-len(item[1]), item[0]))
    ]
    return {
        "column": column,
        "comments": comments,
        "tables_total": len(by_table),
        "tables_without_comment": sorted(
            table for table, comment in by_table.items() if not comment
        ),
        "conflict": len(texts) >= 2,
        "meaning": None,
    }


def _ordered_term(term: dict) -> dict:
    return {key: term[key] for key in _TERM_KEYS if key in term}


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
    report = _Report()
    terms = _apply_term_overrides(glossary["terms"], overrides.get("terms") or {}, report)
    values = _apply_value_overrides(
        glossary["values"], overrides.get("values") or {}, report
    )
    glossary["overrides_applied"] = {
        "terms": terms,
        "values": values,
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
    values: Sequence[dict], overrides: Mapping, report: _Report
) -> int:
    applied = 0
    for key, payload in overrides.items():
        matches = [entry for entry in values if _value_key_matches(str(key), entry)]
        if not _admitted(str(key), payload, matches, report):
            continue
        for entry in matches:
            entry["meaning"] = _meaning(payload)
            applied += 1
    return applied


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
    task = str(profile.get("task_id") or "")
    for statement in profile.get("statements") or [profile]:
        _apply_statement_glossary(statement, entries, terms, task)
    return profile


def _apply_statement_glossary(
    statement: dict, entries: Sequence[Mapping], terms: Mapping, task: str
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
    _record_confirmations(statement, fields, rules, terms, entries)


def _record_confirmations(
    statement: dict,
    fields: Sequence[Mapping],
    rules: Sequence[Mapping],
    terms: Mapping,
    entries: Sequence[Mapping] = (),
) -> None:
    """WI-2.6 / WI-2.12: the halves of "what has been answered" only the corpus knows."""
    coverage = glossary_values.glossary_coverage(fields, rules, entries)
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
    confirmations["terms_confirmed"] = _term_confirmations(statement, set(terms))


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


def _term_confirmations(statement: Mapping, confirmed: set) -> int:
    """How many of the column names THIS task touches carry a confirmed meaning.

    Counted over the names the task actually uses -- its output columns and the input
    columns it reads -- because a corpus-wide count would say the same number for every
    task and answer nobody's question about this one.
    """
    names = {str(field.get("column")) for field in statement.get("fields") or []}
    names.update(
        str(column.get("name"))
        for item in statement.get("inputs") or []
        for column in item.get("used_columns") or []
    )
    return len(names & confirmed)
