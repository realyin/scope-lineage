"""The warnings: what a reviewer should look at, none of which fails the catalog."""

from __future__ import annotations

from .index import build_index
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
        *_code_sets_missing_the_attributes(catalog),
        *_held_forms_the_code_sets_lack(catalog),
        *_unmapped_bindings(catalog),
        *_self_references_without_relation_named(catalog),
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
    """A code set that neither lists its values nor says where they live (``lookup``)."""
    return [
        Finding("empty_code_set", file, code_set["id"], "lists no values and has no lookup")
        for file, code_set in catalog.records("code_sets")
        if not code_set["values"] and "lookup" not in code_set
    ]


def _code_sets_missing_the_attributes(catalog: Catalog) -> list[Finding]:
    """A binding lists the code sets that translate its column, and the bound attribute's
    own code set is not among them: one of the two is probably wrong."""
    code_set_of = {
        attribute.get("id"): attribute.get("code_set")
        for _file, concept in catalog.records("concepts")
        for attribute in concept.get("attributes") or []
        if "code_set" in attribute
    }
    findings = []
    for file, representation in catalog.records("mapping"):
        for binding in representation["bindings"]:
            expected = code_set_of.get(binding.get("ref"))
            if "code_sets" in binding and expected and expected not in binding["code_sets"]:
                findings.append(Finding(
                    "binding_code_sets_miss_attribute", file,
                    f"{representation['table']}.{binding['column']}",
                    f"code_sets does not include {expected!r}, the code set of {binding['ref']}",
                ))
    return findings


def _held_forms_the_code_sets_lack(catalog: Catalog) -> list[Finding]:
    """A column said to hold keys, or meanings in one language, whose code sets have no
    key column, or no meaning column in that language: the catalog cannot translate it."""
    index = build_index(catalog)
    findings = []
    for file, representation in catalog.records("mapping"):
        for binding in representation["bindings"]:
            at = f"{representation['table']}.{binding['column']}"
            held = [
                index.get(code_set).obj
                for code_set in index.held_code_sets(binding)
                if index.is_type(code_set, "code_set")
            ]
            lookups = [code_set["lookup"] for code_set in held if "lookup" in code_set]
            keyed = any("key_column" in x for x in lookups) or any(
                "key" in value for code_set in held for value in code_set.get("values") or []
            )
            if "key" in (binding.get("holds") or []) and not keyed:
                findings.append(Finding(
                    "binding_key_without_key_column", file, at,
                    "holds key, and none of its code sets has a lookup with a key_column "
                    "or values carrying a key",
                ))
            langs = sorted({column.get("lang") or "" for x in lookups for column in x["meaning_columns"]})
            if "lang" in binding and lookups and binding["lang"] not in langs:
                findings.append(Finding(
                    "binding_lang_unknown", file, at,
                    f"lang {binding['lang']!r}, and its code sets' lookups have meaning columns "
                    f"only in {[lang for lang in langs if lang] or 'no language'}",
                ))
    return findings


def _self_references_without_relation_named(catalog: Catalog) -> list[Finding]:
    """A column naming another instance of its table's own concept, which has two or more
    relations to itself, and no ``relation`` saying which one the column realises: every
    page and query then attributes it to all of them."""
    index = build_index(catalog)
    findings = []
    for file, representation in catalog.records("mapping"):
        owners = index.binding_owners(representation["concept"]) or ()
        for binding in representation["bindings"]:
            if binding["to"] != "foreign_identifier" or "relation" in binding:
                continue
            selves = [owner for owner in owners if binding["ref"] in index.identifiers_of(owner)]
            candidates = sorted({r for owner in selves for r in index.self_relations(owner)})
            if len(candidates) >= 2:
                findings.append(Finding(
                    "self_reference_relation_unnamed", file,
                    f"{representation['table']}.{binding['column']}",
                    f"names another instance of {selves[0]}, which has {len(candidates)} "
                    f"relations to itself ({', '.join(candidates)}); say which one this "
                    "column realises with relation",
                ))
    return findings


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
