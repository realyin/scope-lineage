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

This module is the structure-aligned early slice of the phase-two ontology's
``value_domains`` / ``synonyms``: a ``values[]`` entry carries the same
(column, value, evidence, task count, completeness) shape an ``in_set`` constraint does.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence

from . import glossary_values
from .glossary_markdown import render_glossary_markdown  # noqa: F401 -- public facade
from .glossary_values import (
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

TASK_SCHEMA_VERSION = "2.0"

GLOSSARY_KEYS = (
    "doc_format",
    "corpus",
    "terms",
    "values",
    "parameters",
    "overrides_applied",
)


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
) -> dict:
    """Aggregate a corpus of lineage documents into one term / value dictionary.

    ``documents`` are contract documents (1.0 statement or 2.0 task shape), exactly what
    ``describe`` reads. ``artifact_root`` is recorded verbatim, so a caller that wants
    reproducible bytes passes a relative label rather than an absolute path.
    """
    documents = list(documents)
    statements = [pair for document in documents for pair in _statement_pairs(document)]
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
        "overrides_applied": {"terms": 0, "values": 0, "unmatched": []},
    }
    _apply_overrides(glossary, overrides or {})
    return {key: glossary[key] for key in GLOSSARY_KEYS}


# ---------------------------------------------------------------- corpus traversal


def _statement_pairs(document: Mapping) -> list[tuple[dict, dict, str]]:
    """``(statement document, statement profile, task id)`` for every write statement."""
    profile = build_semantic_profile(document)
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
    unmatched: list[str] = []
    terms = _apply_term_overrides(glossary["terms"], overrides.get("terms") or {}, unmatched)
    values = _apply_value_overrides(
        glossary["values"], overrides.get("values") or {}, unmatched
    )
    glossary["overrides_applied"] = {
        "terms": terms,
        "values": values,
        "unmatched": sorted(unmatched),
    }


def _apply_term_overrides(
    terms: Sequence[dict], overrides: Mapping, unmatched: list[str]
) -> int:
    applied = 0
    for key, payload in overrides.items():
        matches = [term for term in terms if term["column"] == str(key).strip()]
        if not matches:
            unmatched.append(str(key))
            continue
        for term in matches:
            term["meaning"] = _meaning(payload)
            applied += 1
    return applied


def _apply_value_overrides(
    values: Sequence[dict], overrides: Mapping, unmatched: list[str]
) -> int:
    applied = 0
    for key, payload in overrides.items():
        matches = [entry for entry in values if _value_key_matches(str(key), entry)]
        if not matches:
            unmatched.append(str(key))
            continue
        for entry in matches:
            entry["meaning"] = _meaning(payload)
            applied += 1
    return applied


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
    values = payload if isinstance(payload, Mapping) else {"meaning": payload}
    return {
        "text": str(values.get("meaning") or values.get("text") or ""),
        "source": MEANING_SOURCE_OVERRIDE,
        "confirmed_by": values.get("confirmed_by"),
        "date": values.get("date"),
    }


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
    for statement in profile.get("statements") or [profile]:
        fields = statement.get("fields") or []
        glossary_values.apply_value_domains(fields, entries)
        coverage = (statement.get("confidence") or {}).get("metadata_coverage")
        if coverage is not None:
            coverage["glossary"] = glossary_values.glossary_coverage(fields)
    return profile
