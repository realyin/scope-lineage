"""``catalog-fragment/1``: its schema, and that its items are the catalog files' own shapes."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from scope_lineage.catalog import FRAGMENT_FORMAT, check_fragment
from scope_lineage.catalog.structure import packaged_schema

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "catalog-fragments" / "disbursement.json"


def _example() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_the_example_fragment_passes_its_schema() -> None:
    fragment = _example()

    assert fragment["doc_format"] == FRAGMENT_FORMAT
    assert check_fragment(fragment, "disbursement.json") == []


def test_each_item_definition_is_the_catalog_schemas_own() -> None:
    """A fragment item merges without translation because it *is* the catalog item."""
    fragment = packaged_schema("catalog-fragment")["definitions"]
    sources = {
        "attribute": ("catalog-concepts", "attribute"),
        "code_set": ("catalog-code-sets", "item"),
        "identifier": ("catalog-identifiers", "item"),
        "constraint": ("catalog-constraints", "item"),
        "term": ("catalog-terms", "item"),
        "representation": ("catalog-mapping", "item"),
        "binding": ("catalog-mapping", "binding"),
    }
    for name, (schema, definition) in sources.items():
        catalog = packaged_schema(schema)["definitions"]
        assert fragment[name] == catalog[definition], name
        for shared in ("id", "status", "source", "evidence", "notes"):
            assert fragment[shared] == catalog[shared], (name, shared)


def test_a_broken_item_is_reported_where_it_is() -> None:
    fragment = _example()
    fragment["representations"][0]["bindings"][6]["to"] = "column"

    findings = check_fragment(fragment, "disbursement.json")

    assert [finding.at for finding in findings] == ["representations[0].bindings[6].to"]
    assert findings[0].file == "disbursement.json"
    assert findings[0].rule == "schema"


def test_attributes_are_keyed_by_concept_id() -> None:
    fragment = _example()
    fragment["attributes"] = {"disbursement": copy.deepcopy(fragment["attributes"]["concept:disbursement"])}

    assert check_fragment(fragment, "f.json")


def test_doc_format_and_group_are_required() -> None:
    assert len(check_fragment({"doc_format": FRAGMENT_FORMAT}, "f.json")) == 1
    assert len(check_fragment({"group": "g"}, "f.json")) == 1
    assert check_fragment({"doc_format": FRAGMENT_FORMAT, "group": "Bad Name"}, "f.json")


def test_the_documented_excerpt_is_a_legal_fragment() -> None:
    docs = Path(__file__).resolve().parents[2] / "docs"
    for language in ("en", "zh-CN"):
        text = (docs / language / "ontology-catalog.md").read_text(encoding="utf-8")
        section = text.split("### `catalog-fragment/1`", 1)[1]
        block = section.split("```json\n", 1)[1].split("```", 1)[0]

        assert check_fragment(json.loads(block), language) == [], language
