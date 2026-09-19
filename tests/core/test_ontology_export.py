"""Thin exporters from the ontology candidate to LinkML and SHACL (WI A4).

``ontology.json`` already carries every slot an RDF toolchain wants; these exporters are
a *rename*, never a re-derivation. So the tests here are about faithfulness rather than
inference: the SQL type lands on the right range, the identifier rule follows the tier,
no tier is dropped on the way out, and every assertion in the JSON reaches each export
exactly once -- nothing invented, nothing lost.

The golden files are recorded and asserted by one function (``_record_golden``), for the
same reason the ontology's own golden is: a recording path that differs from the asserted
path can record a file no test would have accepted.
"""

from __future__ import annotations

import pytest

from scope_lineage.render.ontology import mermaid_entity_ids
from scope_lineage.render.ontology_export import (
    BASE_IRI,
    EXPORT_FILENAMES,
    EXPORT_FORMATS,
    constraint_ids,
    entity_class_ids,
    linkml_range,
    render_export,
    render_linkml,
    render_shacl,
    shacl_datatype,
)

from .test_ontology import GOLDEN_DIR, _golden_ontology


# ----------------------------------------------------------------- the type mapping


@pytest.mark.parametrize(
    "sql_type, expected",
    [
        (None, "string"),
        ("", "string"),
        ("string", "string"),
        ("STRING", "string"),
        ("varchar(64)", "string"),
        ("char(3)", "string"),
        ("int", "integer"),
        ("bigint", "integer"),
        ("smallint", "integer"),
        ("tinyint", "integer"),
        ("decimal(18,2)", "float"),
        ("double", "float"),
        ("float", "float"),
        ("date", "date"),
        ("timestamp", "datetime"),
        ("boolean", "boolean"),
        ("map<string,string>", "string"),
        ("struct<a:int>", "string"),
    ],
)
def test_the_sql_type_maps_onto_a_linkml_range(sql_type, expected: str) -> None:
    assert linkml_range(sql_type) == expected


@pytest.mark.parametrize(
    "sql_type, expected",
    [
        (None, "xsd:string"),
        ("string", "xsd:string"),
        ("bigint", "xsd:integer"),
        ("INT", "xsd:integer"),
        ("decimal(18,2)", "xsd:decimal"),
        ("double", "xsd:double"),
        ("float", "xsd:double"),
        ("date", "xsd:date"),
        ("timestamp", "xsd:dateTime"),
        ("boolean", "xsd:boolean"),
        ("array<string>", "xsd:string"),
    ],
)
def test_the_sql_type_maps_onto_an_xsd_datatype(sql_type, expected: str) -> None:
    assert shacl_datatype(sql_type) == expected


def test_an_unknown_type_is_a_string_rather_than_a_dropped_slot() -> None:
    """The corpus rarely knows a physical table's types; that is not a reason to omit."""
    ontology = _golden_ontology()
    untyped = [
        attribute
        for entity in ontology["entities"]
        for attribute in entity["attributes"]
        if attribute["type"] is None
    ]

    assert untyped, "the golden corpus is supposed to contain untyped columns"
    assert 'range: "string"' in render_linkml(ontology)


# ------------------------------------------------------------- the identifier rule


def test_the_class_id_is_the_identifier_the_er_diagram_already_uses() -> None:
    """One warehouse name, one safe identifier, in every rendering of this corpus."""
    ontology = _golden_ontology()

    assert entity_class_ids(ontology["entities"]) == mermaid_entity_ids(
        ontology["entities"]
    )


def _entity_with(ontology, key_columns, tier):
    for entity in ontology["entities"]:
        for key in entity["identity"]["candidate_keys"]:
            if key["columns"] == list(key_columns) and key["tier"] == tier:
                return entity
    raise AssertionError(f"no entity with a {tier} key on {key_columns}")


def test_a_single_column_proven_key_becomes_an_identifier() -> None:
    ontology = {
        "corpus": {"artifact_root": "corpus", "task_count": 1},
        "entities": [
            {
                "id": "mart.t",
                "kind": "produced_table",
                "comment": None,
                "identity": {
                    "candidate_keys": [
                        {"columns": ["k"], "tier": "proven", "evidence": []}
                    ],
                    "declared_hints": [],
                    "multiplicity": [],
                    "partition_columns": [],
                },
                "attributes": [
                    {"column": "k", "type": "string", "comment": None, "synonyms": []}
                ],
                "naming_hints": {},
            }
        ],
        "relations": [],
        "constraints": [],
    }

    text = render_linkml(ontology)

    assert "identifier: true" in text
    assert "unique_keys:" not in text


def test_a_multi_column_key_becomes_a_unique_keys_entry_not_an_identifier() -> None:
    """LinkML's ``identifier`` is one slot; a composite key is a ``unique_keys`` entry."""
    ontology = _golden_ontology()
    entity = _entity_with(ontology, ["segment", "band"], "proven")
    class_id = entity_class_ids(ontology["entities"])[entity["id"]]

    text = render_linkml(ontology)
    block = _class_block(text, class_id)

    assert "identifier: true" not in block
    assert "unique_keys:" in block
    assert "key_segment_band" in block


def test_a_key_the_corpus_only_assumed_is_not_an_identifier() -> None:
    """``hypothesis`` is an author's assumption; publishing it as *the* identifier
    would launder it into a fact."""
    ontology = _golden_ontology()
    entity = _entity_with(ontology, ["channel_code"], "hypothesis")
    class_id = entity_class_ids(ontology["entities"])[entity["id"]]

    block = _class_block(render_linkml(ontology), class_id)

    assert "identifier: true" not in block
    assert "unique_keys:" in block
    assert 'tier: "hypothesis"' in block


# ------------------------------------------------------------------ tiers survive


def test_every_relation_slot_carries_its_tier_and_claim() -> None:
    ontology = _golden_ontology()

    text = render_linkml(ontology)

    for relation in ontology["relations"]:
        block = _slot_block(text, relation["id"])
        assert f'tier: "{relation["cardinality"]["tier"]}"' in block
        assert f'claim: "{relation["cardinality"]["claim"]}"' in block
        assert f'task_count: {relation["task_count"]}' in block


def test_every_shacl_shape_carries_a_tier() -> None:
    """A SHACL shape with no tier reads as a validated fact. Most of these are not."""
    turtle = render_shacl(_golden_ontology())

    shapes = [line for line in turtle.splitlines() if line.strip() == "sh:property ["]
    tiers = [line for line in turtle.splitlines() if "sl:tier" in line]

    assert shapes
    assert len(tiers) >= len(shapes)


def test_no_tier_token_in_the_json_is_missing_from_either_export() -> None:
    ontology = _golden_ontology()
    tiers = {relation["cardinality"]["tier"] for relation in ontology["relations"]}
    tiers |= {constraint["tier"] for constraint in ontology["constraints"]}

    linkml, shacl = render_linkml(ontology), render_shacl(ontology)

    for tier in tiers:
        assert f'"{tier}"' in linkml, tier
        assert f'"{tier}"' in shacl, tier


def test_the_relation_multiplicity_follows_the_cardinality_claim() -> None:
    ontology = _golden_ontology()

    text = render_linkml(ontology)
    turtle = render_shacl(ontology)

    for relation in ontology["relations"]:
        claim = relation["cardinality"]["claim"]
        block = _slot_block(text, relation["id"])
        single = claim in ("many_to_one", "many_to_one_assumed", "one_to_one_assumed")
        assert ("multivalued: false" in block) is single
        assert ("sh:maxCount 1" in _shacl_property(turtle, relation["id"])) is single


# ------------------------------------------------------------------- the round trip


@pytest.mark.parametrize("fmt", EXPORT_FORMATS)
def test_every_assertion_in_the_json_reaches_the_export_exactly_once(fmt: str) -> None:
    """Nothing invented, nothing lost: the two halves of "thin"."""
    ontology = _golden_ontology()
    text = render_export(ontology, fmt)

    for entity in ontology["entities"]:
        assert text.count(f'"{entity["id"]}"') == 1, entity["id"]
    for relation in ontology["relations"]:
        assert text.count(f'"{relation["id"]}"') == 1, relation["id"]
    for item in constraint_ids(ontology["constraints"]):
        assert text.count(f'"{item}"') == 1, item


def test_the_constraint_ids_are_positional_and_stable() -> None:
    ontology = _golden_ontology()

    assert constraint_ids(ontology["constraints"]) == [
        f"cst:{index:03d}" for index in range(1, len(ontology["constraints"]) + 1)
    ]


def test_a_closed_value_set_becomes_an_enum_and_an_open_one_only_a_comment() -> None:
    ontology = _golden_ontology()
    closed = [
        item
        for item in ontology["constraints"]
        if item["kind"] == "in_set" and item["completeness"] == "complete"
    ]
    open_set = [
        item
        for item in ontology["constraints"]
        if item["kind"] == "in_set" and item["completeness"] != "complete"
    ]

    assert closed and open_set, "the golden corpus needs one of each"
    text, turtle = render_linkml(ontology), render_shacl(ontology)

    assert text.count("permissible_values:") == len(closed)
    assert turtle.count("sh:in (") == len(closed)
    for item in open_set:
        assert str(item["values"][0]) in text
        assert str(item["values"][0]) in turtle


def test_the_composite_uniqueness_limitation_is_stated_in_the_turtle() -> None:
    """SHACL core has no composite unique constraint. Say so rather than pretend."""
    turtle = render_shacl(_golden_ontology())

    assert "SHACL core" in turtle
    assert "unique_per" in turtle


def test_the_turtle_declares_the_placeholder_base_iri() -> None:
    turtle = render_shacl(_golden_ontology())

    assert f"@prefix sl: <{BASE_IRI}> ." in turtle
    assert "example.org" in BASE_IRI


def test_an_empty_ontology_still_renders_a_valid_skeleton() -> None:
    empty = {
        "corpus": {"artifact_root": "corpus", "task_count": 0},
        "entities": [],
        "relations": [],
        "constraints": [],
    }

    assert render_linkml(empty).startswith("id: ")
    assert "classes: {}" in render_linkml(empty)
    assert render_shacl(empty).startswith("@prefix ")


def test_an_unknown_export_format_is_refused() -> None:
    with pytest.raises(ValueError):
        render_export(_golden_ontology(), "owl")


# -------------------------------------------------------------------- golden bytes


def _record_golden() -> dict[str, str]:
    """The recording path and the asserted path, deliberately one function."""
    ontology = _golden_ontology()
    return {
        EXPORT_FILENAMES[fmt]: render_export(ontology, fmt) for fmt in EXPORT_FORMATS
    }


def test_golden_exports_match_the_baseline() -> None:
    first = _record_golden()
    second = _record_golden()

    for name, body in first.items():
        assert body == (GOLDEN_DIR / name).read_text(encoding="utf-8"), name
    assert second == first


def test_every_export_ends_with_exactly_one_newline() -> None:
    for body in _record_golden().values():
        assert body.endswith("\n")
        assert not body.endswith("\n\n")


# ------------------------------------------------------------------------- helpers


def _class_block(text: str, class_id: str) -> str:
    """The YAML lines of one class, up to the next line at the same indent."""
    lines = text.splitlines()
    return _block_from(lines, lines.index(f"  {class_id}:"))


def _slot_block(text: str, relation_id: str) -> str:
    """The YAML lines of the slot whose annotations name ``relation_id``."""
    lines = text.splitlines()
    marker = f'          relation_id: "{relation_id}"'
    start = lines.index(marker)
    while len(lines[start]) - len(lines[start].lstrip()) > 6:
        start -= 1
    return _block_from(lines, start)


def _block_from(lines: list[str], start: int) -> str:
    indent = len(lines[start]) - len(lines[start].lstrip())
    for offset, line in enumerate(lines[start + 1 :], start + 1):
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            return "\n".join(lines[start:offset])
    return "\n".join(lines[start:])


def _shacl_property(turtle: str, relation_id: str) -> str:
    for block in turtle.split("sh:property ["):
        if f'sl:relation "{relation_id}"' in block:
            return block.split("\n    ]")[0]
    raise AssertionError(f"no property shape for {relation_id}")
