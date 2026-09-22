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
    concept_class_ids,
    constraint_ids,
    entity_class_ids,
    finding_ids,
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
        for entity in ontology["tables"]
        for attribute in entity["attributes"]
        if attribute["type"] is None
    ]

    assert untyped, "the golden corpus is supposed to contain untyped columns"
    assert 'range: "string"' in render_linkml(ontology)


# ------------------------------------------------------------- the identifier rule


def test_the_class_id_is_the_identifier_the_er_diagram_already_uses() -> None:
    """One warehouse name, one safe identifier, in every rendering of this corpus."""
    ontology = _golden_ontology()

    assert entity_class_ids(ontology["tables"]) == mermaid_entity_ids(
        ontology["tables"]
    )


def _entity_with(ontology, key_columns, tier):
    for entity in ontology["tables"]:
        for key in entity["identity"]["candidate_keys"]:
            if key["columns"] == list(key_columns) and key["tier"] == tier:
                return entity
    raise AssertionError(f"no entity with a {tier} key on {key_columns}")


def test_a_single_column_proven_key_becomes_an_identifier() -> None:
    ontology = {
        "corpus": {"artifact_root": "corpus", "task_count": 1},
        "tables": [
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
        "table_relations": [],
        "constraints": [],
    }

    text = render_linkml(ontology)

    assert "identifier: true" in text
    assert "unique_keys:" not in text


def test_a_multi_column_key_becomes_a_unique_keys_entry_not_an_identifier() -> None:
    """LinkML's ``identifier`` is one slot; a composite key is a ``unique_keys`` entry."""
    ontology = _golden_ontology()
    entity = _entity_with(ontology, ["segment", "band"], "proven")
    class_id = entity_class_ids(ontology["tables"])[entity["id"]]

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
    class_id = entity_class_ids(ontology["tables"])[entity["id"]]

    block = _class_block(render_linkml(ontology), class_id)

    assert "identifier: true" not in block
    assert "unique_keys:" in block
    assert 'tier: "hypothesis"' in block


# ------------------------------------------------------------------ tiers survive


def test_every_relation_slot_carries_its_tier_and_claim() -> None:
    ontology = _golden_ontology()

    text = render_linkml(ontology)

    for relation in ontology["table_relations"]:
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
    tiers = {relation["cardinality"]["tier"] for relation in ontology["table_relations"]}
    tiers |= {constraint["tier"] for constraint in ontology["constraints"]}

    linkml, shacl = render_linkml(ontology), render_shacl(ontology)

    for tier in tiers:
        assert f'"{tier}"' in linkml, tier
        assert f'"{tier}"' in shacl, tier


def test_the_relation_multiplicity_follows_the_cardinality_claim() -> None:
    ontology = _golden_ontology()

    text = render_linkml(ontology)
    turtle = render_shacl(ontology)

    for relation in ontology["table_relations"]:
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

    for entity in ontology["tables"]:
        assert text.count(f'"{entity["id"]}"') == 1, entity["id"]
    for relation in ontology["table_relations"]:
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
        "tables": [],
        "table_relations": [],
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


# --------------------------------------- P6: the governance and metadata facts (WI P6)


def _annotated_ontology() -> dict:
    """A synthetic corpus carrying the facts the golden corpus has no example of.

    The golden corpus has no finding, no declared key hint and no relation hint, and
    growing it would change an inference fixture this work item must not touch. So the
    export's completeness on those three is asserted against a corpus written here, by
    hand, in the shape ``build_ontology`` produces.
    """
    return {
        "corpus": {"artifact_root": "corpus", "task_count": 1},
        "tables": [_annotated_entity(), _hint_target_entity()],
        "table_relations": [],
        "constraints": [],
        "findings": [
            {
                "kind": "key_hint_conflict",
                "entity": "ods.event",
                "columns": ["event_id"],
                "tasks": {},
                "text": "注释与语料的候选键不一致，请人工判定（合成）。",
            }
        ],
        "open_items": [
            {
                "id": "open:finding:key_hint_conflict:ods.event=event_id",
                "kind": "finding",
                "entity": "ods.event",
                "relation": None,
                "columns": ["event_id"],
                "tier": "hypothesis",
                "write_back": None,
                "text": "请人工判定注释与语料哪一个是身份键（合成）。",
            }
        ],
    }


def _annotated_entity() -> dict:
    return {
        "id": "ods.event",
        "kind": "physical_table",
        "comment": None,
        "identity": _annotated_identity(),
        "attributes": [
            {
                "column": column,
                "type": sql_type,
                "comment": comment,
                "synonyms": [],
            }
            for column, sql_type, comment in (
                ("event_id", "bigint", "主键id（合成）"),
                ("owner_code", "string", "关联 dim.party.party_code"),
                ("loose_code", "string", "关联 dim.absent.code"),
            )
        ],
        "naming_hints": {
            "table_comment": None,
            "domain": "合成域",
            "project": "合成项目",
            "owner": "synthetic_owner",
        },
        "relation_hints": _annotated_relation_hints(),
    }


def _annotated_identity() -> dict:
    return {
        "candidate_keys": [],
        "declared_hints": [
            {
                "columns": ["event_id"],
                "evidence": "column_comment",
                "text": "主键id（合成）",
            }
        ],
        "multiplicity": [
            {
                "columns": ["owner_code"],
                "tier": "implied",
                "claim": "multiple_rows_per_key",
                "evidence": [{"task": "synthetic_task", "statement_id": "stmt:001"}],
            }
        ],
        "partition_columns": [],
    }


def _annotated_relation_hints() -> list[dict]:
    """One hint that resolves against the corpus, and one that names no known table."""
    return [
        {
            "from_column": "owner_code",
            "to": {"entity": "dim.party", "column": "party_code"},
            "evidence": "column_comment",
            "text": "关联 dim.party.party_code",
        },
        {
            "from_column": "loose_code",
            "to": {"entity": "dim.absent", "column": "code"},
            "evidence": "column_comment",
            "text": "关联 dim.absent.code",
            "unresolved": "unknown_entity: dim.absent",
        },
    ]


def _hint_target_entity() -> dict:
    return {
        "id": "dim.party",
        "kind": "physical_table",
        "comment": None,
        "identity": {
            "candidate_keys": [],
            "declared_hints": [],
            "multiplicity": [],
            "partition_columns": [],
        },
        "attributes": [
            {"column": "party_code", "type": "string", "comment": None, "synonyms": []}
        ],
        "naming_hints": {},
    }


@pytest.mark.parametrize("fmt", EXPORT_FORMATS)
def test_the_naming_hints_reach_the_export(fmt: str) -> None:
    """``domain`` / ``project`` / ``owner`` are metadata a downstream catalog wants.

    Counted over the whole corpus rather than one entity: two tables may share a domain,
    and each of them is supposed to say so once.
    """
    ontology = _golden_ontology()
    declared = [
        (key, str(entity["naming_hints"][key]))
        for entity in ontology["tables"]
        for key in ("domain", "project", "owner")
        if (entity.get("naming_hints") or {}).get(key)
    ]

    assert declared, "the golden corpus is supposed to declare naming hints"
    text = render_export(ontology, fmt)

    for key, value in set(declared):
        expected = sum(1 for item in declared if item == (key, value))
        assert text.count(f'"{value}"') == expected, (key, value)


@pytest.mark.parametrize("fmt", EXPORT_FORMATS)
def test_a_declared_key_hint_reaches_the_export_exactly_once(fmt: str) -> None:
    """The hint text is also the column's comment, so only the hint itself is counted."""
    ontology = _annotated_ontology()
    hint = ontology["tables"][0]["identity"]["declared_hints"][0]

    text = render_export(ontology, fmt)

    assert text.count(f"declared key on event_id: {hint['text']}") == 1
    assert "column_comment" in text


@pytest.mark.parametrize("fmt", EXPORT_FORMATS)
def test_a_relation_hint_reaches_the_export_resolved_or_with_its_reason(
    fmt: str,
) -> None:
    ontology = _annotated_ontology()
    resolved, unresolved = ontology["tables"][0]["relation_hints"]

    text = render_export(ontology, fmt)

    assert text.count(f"owner_code -> dim.party.party_code: {resolved['text']}") == 1
    assert text.count(f"loose_code -> dim.absent.code: {unresolved['text']}") == 1
    assert text.count(f"unresolved: {unresolved['unresolved']}") == 1


@pytest.mark.parametrize("fmt", EXPORT_FORMATS)
def test_the_identity_multiplicity_reaches_the_export_with_its_tier(fmt: str) -> None:
    ontology = _golden_ontology()
    claims = [
        item
        for entity in ontology["tables"]
        for item in entity["identity"]["multiplicity"]
    ]

    assert claims, "the golden corpus is supposed to contain a multiplicity claim"
    text = render_export(ontology, fmt)

    for item in claims:
        assert ", ".join(item["columns"]) in text
        assert item["claim"] in text
        assert f'"{item["tier"]}"' in text


@pytest.mark.parametrize("fmt", EXPORT_FORMATS)
def test_a_synonym_reaches_the_export_with_its_via_and_tier(fmt: str) -> None:
    ontology = _golden_ontology()
    synonyms = [
        synonym
        for entity in ontology["tables"]
        for attribute in entity["attributes"]
        for synonym in attribute["synonyms"]
    ]

    assert synonyms, "the golden corpus is supposed to contain a synonym"
    text = render_export(ontology, fmt)

    for synonym in synonyms:
        # The qualified column also appears as a concept attribute's source (M1 gives
        # every table a concept, so every column reaches one), so the *synonym note* is
        # what has to appear exactly once.
        target = f"{synonym['entity']}.{synonym['column']}"
        assert text.count(f"{target} (via ") == 1, target
        assert synonym["via"] in text
        assert f'"{synonym["tier"]}"' in text


@pytest.mark.parametrize("fmt", EXPORT_FORMATS)
def test_every_governance_item_reaches_the_export_exactly_once(fmt: str) -> None:
    """A finding absent from the export is a governance item no downstream ever sees."""
    ontology = _annotated_ontology()
    findings = ontology["findings"]

    text = render_export(ontology, fmt)

    for item_id in finding_ids(findings):
        assert text.count(item_id) == 1, item_id
    for finding in findings:
        assert text.count(finding["text"]) == 1
    for item in ontology["open_items"]:
        assert text.count(item["id"]) == 1, item["id"]
        assert text.count(item["text"]) == 1


@pytest.mark.parametrize("fmt", EXPORT_FORMATS)
def test_the_golden_open_items_reach_the_export_exactly_once(fmt: str) -> None:
    ontology = _golden_ontology()

    assert ontology["open_items"], "the golden corpus is supposed to have open items"
    text = render_export(ontology, fmt)

    for item in ontology["open_items"]:
        assert text.count(item["id"]) == 1, item["id"]


@pytest.mark.parametrize("fmt", EXPORT_FORMATS)
def test_the_evidence_is_a_count_and_a_first_task_not_the_whole_list(fmt: str) -> None:
    """Evidence is the biggest list in the JSON; a schema wants its size, not its rows."""
    ontology = _golden_ontology()
    relation = ontology["table_relations"][0]

    text = render_export(ontology, fmt)

    assert str(len(relation["evidence"])) in text
    assert str(relation["evidence"][0]["task"]) in text
    for item in relation["evidence"]:
        assert str(item["logic_block_id"]) not in text
    assert "statement_id" not in text


def test_the_finding_ids_are_positional_and_stable() -> None:
    findings = _annotated_ontology()["findings"]

    assert finding_ids(findings) == [
        f"sl:finding_{index:03d}" for index in range(1, len(findings) + 1)
    ]


# ------------------------------------------- K5: the concept layer in the two exports


#: The tables the synthetic concept corpus folds: ``(table, its one key column)``.
_CONCEPT_TABLES = (
    ("dim.party", "party_no"),
    ("dwd.party_df", "party_no"),
    ("ods.order_event", "order_no"),
    ("mart.party_daily", "party_no"),
    ("tmp.stage_party", "stage_no"),
)


def _concept_ontology() -> dict:
    """A synthetic corpus carrying every concept shape the golden corpus lacks.

    The golden corpus folds exactly one concept, no concept relation and no
    representation link, and growing it would change an inference fixture this work item
    must not touch. So the three kinds, a participation with roles, an aggregation, a
    seam between two representations are written here by hand, in the shape
    ``build_concepts`` and ``build_concept_relations`` produce.
    """
    return {
        "corpus": {"artifact_root": "corpus", "task_count": 2},
        "tables": [_concept_entity(table, column) for table, column in _CONCEPT_TABLES],
        "table_relations": [],
        "constraints": [],
        "concepts": [_party_concept(), _order_concept(), _daily_concept()],
        "relations": _synthetic_concept_relations(),
        "representation_links": [
            {
                "concept": "concept:party",
                "from_table": "dwd.party_df",
                "to_table": "dim.party",
                "evidence": ["rel:004"],
            }
        ],
    }


def _concept_entity(table: str, column: str) -> dict:
    return {
        "id": table,
        "kind": "physical_table",
        "comment": None,
        "identity": {
            "candidate_keys": [],
            "declared_hints": [],
            "multiplicity": [],
            "partition_columns": [],
        },
        "attributes": [
            {"column": column, "type": "string", "comment": None, "synonyms": []}
        ],
        "naming_hints": {},
    }


def _party_concept() -> dict:
    return {
        "id": "concept:party",
        "name": "客户（合成）",
        "name_tier": "hypothesis",
        "name_candidates": [
            {"text": "客户（合成）", "source": "table_comment", "count": 2},
            {"text": "party", "source": "key_stem", "count": 1},
        ],
        "kind": "entity",
        "kind_tier": "implied",
        "kind_evidence": [],
        "identity": {"stem": "party", "columns_seen": ["party_no"]},
        "tables": [
            _member("dim.party", "primary", "key:hypothesis", "party_no"),
            _member("dwd.party_df", "snapshot", "key:hypothesis", "party_no"),
            _member("ods.order_event", "reference", "reference", "party_no"),
        ],
        "attributes": [
            {
                "stem": "party",
                "type": "string",
                "comment": "客户编号（合成）",
                "sources": [{"table": "dim.party", "column": "party_no"}],
            }
        ],
        "tier": "hypothesis",
    }


def _order_concept() -> dict:
    return {
        "id": "concept:order",
        "name": "订单（合成）",
        "name_tier": "hypothesis",
        "name_candidates": [
            {"text": "订单（合成）", "source": "table_comment", "count": 1}
        ],
        "kind": "event",
        "kind_tier": "implied",
        "kind_evidence": [],
        "identity": {"stem": "order", "columns_seen": ["order_no"]},
        "tables": [_member("ods.order_event", "primary", "key:hypothesis", "order_no")],
        "attributes": [
            {
                "stem": "order",
                "type": "bigint",
                "comment": None,
                "sources": [{"table": "ods.order_event", "column": "order_no"}],
            }
        ],
        "tier": "hypothesis",
    }


def _daily_concept() -> dict:
    return {
        "id": "concept:party_daily",
        "name": "客户日汇总（合成）",
        "name_tier": "hypothesis",
        "name_candidates": [
            {"text": "客户日汇总（合成）", "source": "table_comment", "count": 1}
        ],
        "possible_duplicate_of": ["concept:party"],
        "kind": "summary",
        "kind_tier": "hypothesis",
        "kind_evidence": [],
        "identity": {"stem": "party_daily", "columns_seen": ["party_no"]},
        "tables": [_member("mart.party_daily", "summary", "key:hypothesis", "party_no")],
        "attributes": [
            {
                "stem": "party_daily",
                "type": None,
                "comment": None,
                "sources": [{"table": "mart.party_daily", "column": "party_no"}],
            }
        ],
        "tier": "hypothesis",
    }


def _member(table: str, role: str, basis: str, column: str) -> dict:
    return {
        "table": table,
        "role": role,
        "membership_basis": basis,
        "key_columns": [column],
        "grain": None,
    }


def _synthetic_concept_relations() -> list[dict]:
    return [
        {
            "from": "concept:order",
            "to": "concept:party",
            "type": "participation",
            "roles": ["下单方（合成）"],
            "cardinality": {"claim": "many_to_one", "tier": "proven", "basis": ["rel:001"]},
            "task_count": 2,
            "evidence": ["rel:001", "rel:002"],
        },
        {
            "from": "concept:party_daily",
            "to": "concept:party",
            "type": "aggregation",
            "cardinality": {"claim": "one_to_many", "tier": "implied", "basis": ["rel:003"]},
            "task_count": 1,
            "evidence": ["rel:003"],
        },
    ]


def _concept_ids(ontology) -> dict[str, str]:
    return concept_class_ids(ontology["concepts"], entity_class_ids(ontology["tables"]))


def _shacl_shape(turtle: str, class_id: str) -> str:
    """The Turtle statement of one node shape, up to the blank line after it."""
    start = turtle.index(f"sl:{class_id}Shape\n")
    return turtle[start:].split("\n\n", 1)[0]


def test_the_three_concept_kinds_become_abstract_base_classes() -> None:
    """Whether a concept is a thing, a happening or a figure is what it inherits from."""
    text = render_linkml(_concept_ontology())

    for class_id, category in (
        ("Entity", "continuant"),
        ("Event", "occurrent"),
        ("Summary", "aggregate"),
    ):
        block = _class_block(text, class_id)
        assert "abstract: true" in block
        assert f'category: "{category}"' in block


def test_a_corpus_with_no_concept_gets_no_base_classes() -> None:
    """The bases exist to be inherited from; with no concept they assert nothing."""
    text = render_linkml(_annotated_ontology())

    assert "abstract: true" not in text
    assert "continuant" not in text


def test_a_concept_becomes_a_class_under_its_kind_base() -> None:
    ontology = _concept_ontology()
    concept = ontology["concepts"][0]

    block = _class_block(render_linkml(ontology), _concept_ids(ontology)[concept["id"]])

    assert 'is_a: "Entity"' in block
    assert f'title: "{concept["name"]}"' in block
    assert "party" in block, "the description is supposed to list the name candidates"
    assert f'kind_tier: "{concept["kind_tier"]}"' in block
    assert f'name_tier: "{concept["name_tier"]}"' in block
    assert "dim.party -> primary" in block


def test_a_possible_duplicate_is_published_without_being_merged() -> None:
    ontology = _concept_ontology()
    ids = _concept_ids(ontology)

    block = _class_block(render_linkml(ontology), ids["concept:party_daily"])

    assert "possible_duplicate_of" in block
    assert "concept:party" in block


def test_a_concept_shape_targets_its_class_and_subclasses_its_kind() -> None:
    ontology = _concept_ontology()
    class_id = _concept_ids(ontology)["concept:order"]

    shape = _shacl_shape(render_shacl(ontology), class_id)

    assert "a sh:NodeShape ;" in shape
    assert f"sh:targetClass sl:{class_id} ;" in shape
    assert "rdfs:subClassOf sl:Event ;" in shape
    assert 'sl:tier "hypothesis"' in shape


def test_the_shacl_kind_classes_are_subclasses_of_concept() -> None:
    turtle = render_shacl(_concept_ontology())

    for class_id in ("Entity", "Event", "Summary"):
        assert f"sl:{class_id}\n" in turtle
    assert turtle.count("rdfs:subClassOf sl:Concept ;") == 3


@pytest.mark.parametrize("fmt", EXPORT_FORMATS)
def test_a_concept_attribute_reaches_the_export_with_its_sources(fmt: str) -> None:
    ontology = _concept_ontology()
    attribute = ontology["concepts"][0]["attributes"][0]

    text = render_export(ontology, fmt)

    assert text.count("dim.party.party_no") == 1
    assert text.count(str(attribute["comment"])) == 1


@pytest.mark.parametrize("fmt", EXPORT_FORMATS)
def test_a_table_class_says_which_concept_it_represents(fmt: str) -> None:
    """A table is a *representation* of a concept: the export says which, and as what."""
    ontology = _concept_ontology()

    text = render_export(ontology, fmt)

    for concept in ontology["concepts"]:
        for member in concept["tables"]:
            assert text.count(f"{concept['id']} ({member['role']})") == 1


def test_a_concept_relation_is_a_slot_on_the_from_class() -> None:
    ontology = _concept_ontology()
    ids = _concept_ids(ontology)
    text = render_linkml(ontology)

    for relation in ontology["relations"]:
        block = _class_block(text, ids[relation["from"]])
        assert block.count(f'relation_type: "{relation["type"]}"') == 1
        assert block.count(f'range: "{ids[relation["to"]]}"') == 1


def test_a_concept_relation_multiplicity_follows_its_claim() -> None:
    ontology = _concept_ontology()
    ids = _concept_ids(ontology)
    text, turtle = render_linkml(ontology), render_shacl(ontology)

    for relation in ontology["relations"]:
        single = relation["cardinality"]["claim"] == "many_to_one"
        block = _class_block(text, ids[relation["from"]])
        shape = _shacl_shape(turtle, ids[relation["from"]])
        assert ("multivalued: false" in block) is single
        assert ("sh:maxCount 1" in shape) is single


def test_a_concept_relation_property_shape_names_the_to_concept() -> None:
    ontology = _concept_ontology()
    ids = _concept_ids(ontology)
    turtle = render_shacl(ontology)

    for relation in ontology["relations"]:
        shape = _shacl_shape(turtle, ids[relation["from"]])
        assert f"sh:class sl:{ids[relation['to']]} ;" in shape
        assert f'sl:relationType "{relation["type"]}"' in shape
        assert f'sl:tier "{relation["cardinality"]["tier"]}"' in shape


@pytest.mark.parametrize("fmt", EXPORT_FORMATS)
def test_a_participation_publishes_the_role_and_the_evidence_count(fmt: str) -> None:
    ontology = _concept_ontology()
    relation = ontology["relations"][0]

    text = render_export(ontology, fmt)

    assert text.count(relation["roles"][0]) == 1
    assert str(len(relation["evidence"])) in text
    for item in relation["evidence"]:
        assert item not in text, "the member edge ids stay in ontology.json"


@pytest.mark.parametrize("fmt", EXPORT_FORMATS)
def test_a_representation_link_reaches_both_table_classes(fmt: str) -> None:
    """A seam in the fold belongs to the two tables it joins, so it lands on both."""
    ontology = _concept_ontology()
    link = ontology["representation_links"][0]

    text = render_export(ontology, fmt)

    assert text.count(f"{link['from_table']} and {link['to_table']}") == 2


@pytest.mark.parametrize("fmt", EXPORT_FORMATS)
def test_every_concept_assertion_reaches_the_export_exactly_once(fmt: str) -> None:
    """The round trip of K5: nothing folded is invented, nothing folded is lost."""
    ontology = _concept_ontology()
    text = render_export(ontology, fmt)

    for concept in ontology["concepts"]:
        assert text.count(f'"{concept["id"]}"') == 1, concept["id"]
    for relation in ontology["relations"]:
        assert text.count(f'"{relation["type"]}"') == 1, relation["type"]
    for entity in ontology["tables"]:
        assert text.count(f'"{entity["id"]}"') == 1, entity["id"]


def test_every_concept_triple_group_in_the_turtle_carries_a_tier() -> None:
    ontology = _concept_ontology()
    turtle = render_shacl(ontology)

    for class_id in _concept_ids(ontology).values():
        shape = _shacl_shape(turtle, class_id)
        assert shape.count("sl:tier") == shape.count("sh:property [") + 1


@pytest.mark.parametrize("fmt", EXPORT_FORMATS)
def test_the_golden_concept_reaches_both_exports(fmt: str) -> None:
    ontology = _golden_ontology()

    assert ontology["concepts"], "the golden corpus is supposed to fold one concept"
    text = render_export(ontology, fmt)

    for concept in ontology["concepts"]:
        assert text.count(f'"{concept["id"]}"') == 1, concept["id"]
        assert concept["name"] in text
