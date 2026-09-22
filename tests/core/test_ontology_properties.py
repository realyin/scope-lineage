"""Properties of the corpus ontology that no single rule case can state (WI-11).

The rule tests in ``test_ontology.py`` each pin one inference. These pin what has to
hold over *every* inference at once, and they exist because the failure modes of a
derived ontology are not wrong rules -- they are a name nobody wrote, an assertion with
no way back to the SQL it came from, and a document that differs between two runs over
the same corpus.

Four properties, in the order they would hurt:

1. **Nothing was invented.** Every entity, every relation endpoint, every constraint
   target and every synonym counterpart -- table *and* column -- appears in some
   ``lineage.json`` of the corpus. A model that names a table the corpus never read is
   worse than no model.
2. **Everything weaker than a fact carries its receipt.** Every assertion below
   ``proven`` has a tier and non-empty evidence, and every evidence item's task and
   logic block dereference to a document and a block inside it.
3. **The document is a function of the corpus.** Two runs, and two directory traversal
   orders, produce the same bytes.
4. **The markdown says only what the JSON says.** Every table/column reference in a
   card's ontology sections resolves, and the ER diagram's entity ids are legal Mermaid
   identifiers in bijection with the published entities.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.ontology import (
    MERMAID_ENTITY_LIMIT,
    TIER_PROVEN,
    TIERS,
    build_ontology,
    mermaid_entity_ids,
    render_ontology_index_markdown,
    render_ontology_table_card_markdown,
)
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.render.table_cards import build_table_cards, same_table
from scope_lineage.scope.scope_builder import parse_scope_lineage


FIXTURES = Path(__file__).parent / "fixtures"

# A corpus wide enough that every published slot is populated: a produced table with a
# proven key, a dimension joined directly (hypothesis), the same dimension deduplicated
# by another task (conflict), a UNION (synonyms), renames, closed and open value sets.
SCHEMA = {
    "ods.orders": ["order_id", "customer_id", "amount", "state", "dt"],
    "ods.customer": ["id", "name", "country", "level"],
    "ods.app_order": ["order_id", "pay_amount"],
    "ods.web_order": ["order_id", "order_amount"],
    "mart.customer_daily": ["customer_id", "country", "dt"],
}

CORPUS = (
    (
        "direct_join_task",
        "INSERT OVERWRITE TABLE mart.order_wide PARTITION (dt = '20250101') "
        "SELECT o.order_id, c.name AS customer_name, c.level FROM ods.orders o "
        "LEFT JOIN ods.customer c ON o.customer_id = c.id "
        "WHERE o.state IN ('NEW', 'PAID') AND NOT c.country IS NULL",
    ),
    (
        "dedup_join_task",
        "INSERT OVERWRITE TABLE mart.order_latest PARTITION (dt = '20250101') "
        "SELECT o.order_id, c.country FROM ods.orders o LEFT JOIN "
        "(SELECT id, country FROM ods.customer GROUP BY id, country) c "
        "ON o.customer_id = c.id",
    ),
    (
        "union_task",
        "INSERT OVERWRITE TABLE mart.order_all "
        "SELECT order_id, pay_amount FROM ods.app_order "
        "UNION ALL SELECT order_id, order_amount FROM ods.web_order",
    ),
    (
        "rollup_task",
        "INSERT OVERWRITE TABLE mart.customer_daily PARTITION (dt = '20250101') "
        "SELECT customer_id, max(country) AS country FROM ods.orders "
        "GROUP BY customer_id",
    ),
)


def _documents() -> list[dict]:
    return [
        to_lineage_dict(parse_scope_lineage(sql, task, schema=SCHEMA))
        for task, sql in CORPUS
    ]


def _build(documents) -> tuple[dict, dict]:
    profiles = _profiles(documents)
    cards = build_table_cards(profiles, artifact_root="corpus")
    return (
        build_ontology(documents, profiles, tables=cards, artifact_root="corpus"),
        cards,
    )


def _profiles(documents) -> list[dict]:
    return [build_semantic_profile(document) for document in documents]


@pytest.fixture(scope="module")
def corpus() -> tuple[list[dict], dict, dict]:
    documents = _documents()
    ontology, cards = _build(documents)
    return documents, ontology, cards


# ---------------------------------------------------- 1. nothing was invented


def _names_and_pairs(documents) -> tuple[set[str], set[tuple[str, str]]]:
    """``(every table the corpus wrote, every (table, column) it wrote)``.

    Read off the raw contract documents rather than off anything derived, because a
    derived index would happily confirm an invention the derivation itself made.
    """
    tables: set[str] = set()
    pairs: set[tuple[str, str]] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            table = node.get("table")
            if isinstance(table, str):
                tables.add(table)
                for key in ("field", "column", "name"):
                    if isinstance(node.get(key), str):
                        pairs.add((table, node[key]))
            for key, value in node.items():
                walk(value)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)

    for document in documents:
        target = document.get("target_table")
        tables.update(str(name) for name in document.get("source_tables") or [])
        if isinstance(target, str):
            tables.add(target)
            pairs.update(
                (target, str(entry.get("column")))
                for entry in document.get("end_to_end_lineage") or []
                if entry.get("column")
            )
            # A static partition column is written in the PARTITION clause and never
            # projected, so it reaches the card from here and from nowhere else.
            pairs.update(
                (target, str(column))
                for column in document.get("target_partition_columns") or []
            )
        for group in (document.get("related_metadata") or {}).values():
            if not isinstance(group, dict):
                continue
            for name, meta in group.items():
                tables.add(str(name))
                pairs.update(
                    (str(name), str(column.get("name")))
                    for column in (meta or {}).get("column_details") or []
                    if column.get("name")
                )
        walk(document)
    return tables, pairs


def _known_table(name: str, tables) -> bool:
    return any(same_table(str(name), item) for item in tables)


def _known_column(table: str, column: str, pairs) -> bool:
    return any(
        same_table(str(table), item) and other == str(column) for item, other in pairs
    )


def _published_references(ontology: dict) -> list[tuple[str, str | None]]:
    """Every ``(table, column)`` the ontology names, ``column`` None for a whole table."""
    found: list[tuple[str, str | None]] = []
    for entity in ontology["entities"]:
        found.append((entity["id"], None))
        found.extend((entity["id"], attribute["column"]) for attribute in entity["attributes"])
        found.extend(
            (entity["id"], column)
            for key in entity["identity"]["candidate_keys"]
            for column in key["columns"]
        )
        found.extend(
            (entity["id"], column)
            for item in entity["identity"]["multiplicity"]
            for column in item["columns"]
        )
        found.extend(
            (entity["id"], column) for column in entity["identity"]["partition_columns"]
        )
        found.extend(
            (synonym["entity"], synonym["column"])
            for attribute in entity["attributes"]
            for synonym in attribute["synonyms"]
        )
    for relation in ontology["relations"]:
        for side in ("from", "to"):
            found.append((relation[side]["entity"], None))
            found.extend((relation[side]["entity"], column) for column in relation[side]["columns"])
    for constraint in ontology["constraints"]:
        target = constraint["target"]
        found.append((target["entity"], target.get("column")))
        found.extend((target["entity"], column) for column in constraint.get("columns") or [])
    for finding in ontology["findings"]:
        found.append((finding["entity"], None))
        found.extend((finding["entity"], column) for column in finding["columns"])
    return found


def test_every_name_the_ontology_publishes_was_written_by_the_corpus(corpus) -> None:
    documents, ontology, _cards = corpus
    tables, pairs = _names_and_pairs(documents)

    unknown = [
        (table, column)
        for table, column in _published_references(ontology)
        if not _known_table(table, tables)
        or (column is not None and not _known_column(table, column, pairs))
    ]

    assert unknown == []


def test_the_property_catches_a_table_the_corpus_never_wrote(corpus) -> None:
    """The guard above is only worth having if it fails on an invention."""
    _documents_, ontology, _cards = corpus
    tables, _pairs = _names_and_pairs(_documents_)

    assert not _known_table("ods.invented_table", tables)


# ------------------------------------------- 2. every soft assertion has a receipt


def _assertions(ontology: dict) -> list[tuple[str, dict]]:
    """``(what it is, the assertion)`` for everything that carries a tier."""
    found: list[tuple[str, dict]] = []
    for entity in ontology["entities"]:
        found.extend(
            (f"{entity['id']} candidate_key", key)
            for key in entity["identity"]["candidate_keys"]
        )
        found.extend(
            (f"{entity['id']} multiplicity", item)
            for item in entity["identity"]["multiplicity"]
        )
        found.extend(
            (f"{entity['id']}.{attribute['column']} synonym", synonym)
            for attribute in entity["attributes"]
            for synonym in attribute["synonyms"]
        )
    found.extend(
        (f"{relation['id']} cardinality", {**relation["cardinality"], "evidence": relation["evidence"]})
        for relation in ontology["relations"]
    )
    found.extend(
        (f"{constraint['target']['entity']} {constraint['kind']}", constraint)
        for constraint in ontology["constraints"]
    )
    return found


def test_every_assertion_carries_a_known_tier_and_its_evidence(corpus) -> None:
    _documents_, ontology, _cards = corpus
    assertions = _assertions(ontology)

    assert assertions, "the corpus must exercise the assertion slots"
    for label, assertion in assertions:
        assert str(assertion.get("tier")) in TIERS, label
        assert assertion.get("evidence"), label


def test_no_assertion_is_proven_without_evidence_from_a_statement(corpus) -> None:
    """A ``proven`` claim has to name the statement that proves it, like every other."""
    _documents_, ontology, _cards = corpus

    for label, assertion in _assertions(ontology):
        if str(assertion.get("tier")) != TIER_PROVEN:
            continue
        assert all(item.get("task") for item in assertion["evidence"]), label


def _corpus_ids(documents) -> tuple[set[str], set[str], set[str]]:
    """``(task names, statement ids, block and scope ids)`` the corpus contains."""
    tasks: set[str] = set()
    statements: set[str] = set()
    blocks: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("logic_block_id"), str):
                blocks.add(node["logic_block_id"])
            for value in node.values():
                walk(value)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)

    for document in documents:
        tasks.add(str(document.get("task_id")))
        statements.add(str(document.get("statement_id")))
        blocks.update(str(scope) for scope in document.get("scopes") or {})
        walk(document)
    return tasks, statements, blocks


def test_every_evidence_item_dereferences_to_a_task_and_a_logic_block(corpus) -> None:
    documents, ontology, _cards = corpus
    tasks, statements, blocks = _corpus_ids(documents)

    checked = 0
    for label, assertion in _assertions(ontology):
        for item in assertion["evidence"]:
            if item.get("task"):
                assert str(item["task"]) in tasks, label
                checked += 1
            if item.get("statement_id"):
                assert str(item["statement_id"]) in statements, label
            if item.get("logic_block_id"):
                assert str(item["logic_block_id"]) in blocks, label
    assert checked, "the corpus must exercise task-anchored evidence"


# ------------------------------------------------------- 3. the same bytes, always


def _bytes(ontology: dict) -> str:
    return json.dumps(ontology, ensure_ascii=False, indent=2, sort_keys=False)


def test_two_runs_over_one_corpus_produce_the_same_document() -> None:
    first, _ = _build(_documents())
    second, _ = _build(_documents())

    assert _bytes(first) == _bytes(second)


def test_the_traversal_order_of_the_corpus_does_not_change_the_document() -> None:
    """``rglob`` order is a property of the file system, never of the ontology."""
    documents = _documents()
    forward, _ = _build(documents)
    reverse, _ = _build(list(reversed(documents)))

    assert _bytes(forward) == _bytes(reverse)


def test_the_markdown_is_deterministic_too(corpus) -> None:
    _documents_, ontology, cards = corpus
    card = cards["tables"][0]

    assert render_ontology_index_markdown(ontology) == render_ontology_index_markdown(
        ontology
    )
    assert render_ontology_table_card_markdown(
        card, ontology
    ) == render_ontology_table_card_markdown(card, ontology)


# ------------------------------------------------ 4. the markdown says what JSON says


_CODE_SPAN = re.compile(r"`([^`]+)`")
_MERMAID_ID = re.compile(r"^[A-Za-z0-9_]+$")


def _ontology_sections(card_markdown: str) -> str:
    """Only the sections this layer appends -- the table card has its own tests."""
    head, _, tail = card_markdown.partition("\n## 7. ")
    assert tail, "an ontology card must carry its own sections"
    return tail


def _reference_index(documents, ontology: dict) -> dict:
    """Everything a card is allowed to write inside backticks, built once."""
    tables, pairs = _names_and_pairs(documents)
    tasks, statements, blocks = _corpus_ids(documents)
    # Rule ids are the semantic profile's, not the contract's: a not-null constraint
    # names the conjunct it was read from, and that conjunct lives in the profile.
    rules = {
        str(rule.get("rule_id"))
        for profile in _profiles(documents)
        for rule in profile.get("rules") or []
    }
    vocabulary = {
        *TIERS,
        *(str(relation["cardinality"]["claim"]) for relation in ontology["relations"]),
        *(str(relation["cardinality"]["basis"]) for relation in ontology["relations"]),
        *(str(relation["kind"]) for relation in ontology["relations"]),
        *(str(constraint["kind"]) for constraint in ontology["constraints"]),
        *(
            str(value)
            for constraint in ontology["constraints"]
            for value in constraint.get("values") or []
        ),
        *(
            str(synonym["via"])
            for entity in ontology["entities"]
            for attribute in entity["attributes"]
            for synonym in attribute["synonyms"]
        ),
        # An evidence item with no ids renders as its kind: `group_by`, `column_comment`,
        # `human_confirmation`. They are this layer's vocabulary like any other token.
        *(
            str(item["kind"])
            for _label, assertion in _assertions(ontology)
            for item in assertion.get("evidence") or []
            if item.get("kind")
        ),
        # K4a: section 7 opens with what the table represents -- the concept's id, the
        # basis it belongs on, and, for a table no key could place, the reason.
        *(str(concept["id"]) for concept in ontology.get("concepts") or []),
        *(
            str(member["membership_basis"])
            for concept in ontology.get("concepts") or []
            for member in concept["tables"]
        ),
        *(str(item["reason"]) for item in ontology.get("unassigned_tables") or []),
    }
    return {
        "tables": tables,
        "columns": {column for _table, column in pairs},
        "ids": tasks | statements | blocks | rules,
        "vocabulary": vocabulary,
    }


def _resolvable(span: str, index: dict) -> bool:
    if span in index["vocabulary"]:
        return True
    # A write-back target: `键:<table>=<cols>` / `关系:<from>-><to>`, or the id of one
    # entry in the index's consolidated open list. Their own parts are checked by the
    # entity and column rules, so the prefix is all that is asserted.
    if span.startswith(("键:", "关系:", "open:")):
        return True
    # An evidence id: task/statement/scope/rule/logic block, slash separated.
    if "/" in span:
        return all(part in index["ids"] for part in span.split("/"))
    if _known_table(span, index["tables"]):
        return True
    return span in index["columns"]


def test_every_reference_in_a_card_resolves_to_something_the_corpus_named(corpus) -> None:
    documents, ontology, cards = corpus

    index = _reference_index(documents, ontology)

    unresolved = []
    for card in cards["tables"]:
        body = _ontology_sections(render_ontology_table_card_markdown(card, ontology))
        unresolved.extend(
            (card["table"], span)
            for span in _CODE_SPAN.findall(body)
            if not _resolvable(span, index)
        )

    assert unresolved == []


def test_every_card_the_corpus_publishes_carries_the_five_ontology_sections(corpus) -> None:
    _documents_, ontology, cards = corpus
    titles = ("7. 身份（本体）", "8. 关系", "9. 约束", "10. 属性同义", "11. 待人工判定")

    for card in cards["tables"]:
        body = render_ontology_table_card_markdown(card, ontology)
        assert 'doc_format: "ontology-md/1"' in body, card["table"]
        for title in titles:
            assert f"## {title}" in body, (card["table"], title)


def _mermaid_block(markdown: str) -> list[str]:
    """The table-level ER diagram.

    Named by its opening keyword rather than by position: K4a puts the concept-layer
    `flowchart LR` above it, and the rules below are about the entities.
    """
    _head, _, tail = markdown.partition("```mermaid\nerDiagram\n")
    body, _, _rest = tail.partition("```")
    return ["erDiagram", *(line for line in body.split("\n") if line.strip())]


def test_the_diagram_declares_exactly_the_published_entities(corpus) -> None:
    _documents_, ontology, _cards = corpus
    lines = _mermaid_block(render_ontology_index_markdown(ontology))
    identifiers = mermaid_entity_ids(ontology["entities"])

    assert lines[0] == "erDiagram"
    declared = {
        line.strip().split(" ")[0]
        for line in lines[1:]
        if not line.startswith("        ") and "--" not in line and line.strip() != "}"
    }

    assert declared == set(identifiers.values())
    assert len(identifiers) == len(ontology["entities"])


def test_every_diagram_identifier_is_a_legal_mermaid_name(corpus) -> None:
    _documents_, ontology, _cards = corpus

    for name, identifier in mermaid_entity_ids(ontology["entities"]).items():
        assert _MERMAID_ID.match(identifier), (name, identifier)


def test_two_entities_that_flatten_to_one_name_keep_two_identifiers() -> None:
    entities = [{"id": "a.b"}, {"id": "a_b"}, {"id": "a-b"}]

    identifiers = mermaid_entity_ids(entities)

    assert sorted(identifiers.values()) == ["a_b", "a_b_2", "a_b_3"]
    assert len(set(identifiers.values())) == 3


def test_every_diagram_edge_names_two_declared_entities(corpus) -> None:
    _documents_, ontology, _cards = corpus
    identifiers = set(mermaid_entity_ids(ontology["entities"]).values())

    edges = [line for line in _mermaid_block(render_ontology_index_markdown(ontology)) if "--" in line]

    assert edges, "the corpus must exercise the ER edges"
    for edge in edges:
        left, symbol, right, colon, _label = edge.strip().split(" ", 4)
        assert left in identifiers, edge
        assert right in identifiers, edge
        assert colon == ":", edge
        assert set(symbol) <= set("|o{}-"), edge


def test_the_reference_guard_rejects_a_name_the_corpus_never_wrote(corpus) -> None:
    """The guard above is worth nothing unless an invented span fails it."""
    documents, ontology, _cards = corpus
    index = _reference_index(documents, ontology)

    assert not _resolvable("ods.invented_table", index)
    assert not _resolvable("invented_column", index)
    assert not _resolvable("invented_task/stmt:001", index)


def test_the_diagram_keeps_the_best_connected_entities_and_says_what_it_dropped(
    corpus,
) -> None:
    """Past the limit the overview is a summary, and it is honest about being one."""
    _documents_, ontology, _cards = corpus
    crowded = {
        **ontology,
        "entities": [
            *ontology["entities"],
            *(
                {
                    "id": f"ods.spare_{index:03d}",
                    "kind": "physical_table",
                    "comment": None,
                    "identity": {
                        "candidate_keys": [],
                        "multiplicity": [],
                        "partition_columns": [],
                    },
                    "attributes": [],
                    "naming_hints": {},
                }
                for index in range(MERMAID_ENTITY_LIMIT + 5)
            ),
        ],
    }

    markdown = render_ontology_index_markdown(crowded)
    declared = [
        line.strip().split(" ")[0]
        for line in _mermaid_block(markdown)[1:]
        if not line.startswith("        ") and "--" not in line and line.strip() != "}"
    ]

    assert len(declared) == MERMAID_ENTITY_LIMIT
    assert f"省略 {len(crowded['entities']) - MERMAID_ENTITY_LIMIT} 个" in markdown
    # The connected ones survive: every entity with an edge is still in the picture.
    for relation in crowded["relations"]:
        for side in ("from", "to"):
            name = str(relation[side]["entity"])
            assert mermaid_entity_ids(crowded["entities"])[name] in declared
