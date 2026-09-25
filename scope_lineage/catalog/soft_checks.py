"""The warnings: what a reviewer should look at, none of which fails the catalog."""

from __future__ import annotations

from .model import Catalog, Finding

# Every object that carries a status of its own (attributes and bindings inherit theirs).
STATUS_KINDS = (
    "domains",
    "identifiers",
    "code_sets",
    "concepts",
    "relations",
    "constraints",
    "terms",
    "mapping",
)


def status_counts(catalog: Catalog) -> dict[str, int]:
    counts = {"drafted": 0, "confirmed": 0, "deprecated": 0}
    for kind in STATUS_KINDS:
        for _file, obj in catalog.records(kind):
            status = obj.get("status", "drafted")
            if status in counts:
                counts[status] += 1
    return counts


def unknown_file_warnings(catalog: Catalog) -> list[Finding]:
    return [
        Finding("unknown_file", file, None, "not part of the catalog layout; ignored")
        for file in catalog.unknown_files
    ]


def soft_checks(catalog: Catalog) -> list[Finding]:
    return [
        *_drafted_ratio(catalog),
        *_concepts_without_definition(catalog),
        *_relations_without_name(catalog),
        *_empty_code_sets(catalog),
        *_unmapped_bindings(catalog),
    ]


def _drafted_ratio(catalog: Catalog) -> list[Finding]:
    counts = status_counts(catalog)
    total = sum(counts.values())
    drafted = counts["drafted"]
    if not drafted:
        return []
    share = round(100 * drafted / total)
    return [
        Finding(
            "drafted_ratio", None, None,
            f"{drafted}/{total} objects ({share}%) are still drafted -- "
            "nothing an owner has not confirmed should be read as settled",
        )
    ]


def _concepts_without_definition(catalog: Catalog) -> list[Finding]:
    return [
        Finding("concept_without_definition", file, concept["id"], "has no definition")
        for file, concept in catalog.records("concepts")
        if not str(concept.get("definition") or "").strip()
    ]


def _relations_without_name(catalog: Catalog) -> list[Finding]:
    return [
        Finding("relation_without_name", file, relation["id"], "has no verb (name)")
        for file, relation in catalog.records("relations")
        if not str(relation.get("name") or "").strip()
    ]


def _empty_code_sets(catalog: Catalog) -> list[Finding]:
    return [
        Finding("empty_code_set", file, code_set["id"], "lists no values")
        for file, code_set in catalog.records("code_sets")
        if not code_set["values"]
    ]


def _unmapped_bindings(catalog: Catalog) -> list[Finding]:
    return [
        Finding(
            "unmapped_binding", file, f"{representation['table']}.{binding['column']}",
            "column not yet bound to anything in the concept layer",
        )
        for file, representation in catalog.records("mapping")
        for binding in representation["bindings"]
        if binding["to"] == "unmapped"
    ]
