"""Behavioural tests for the corpus ontology candidate (WI-8 / WI-9, rules O1-O7).

Every rule here is an *inference over a corpus*, so each one gets a positive case and a
"looks like it but is not provable" negative case -- the same discipline the shape rules
follow, for the same reason: a wrongly granted ``proven`` teaches every later reader a
fact the SQL never contained.

Two properties sit at the bottom and cover what no single case can: nothing published
was invented (every entity, column and task appears in some contract document), and
every assertion weaker than ``proven`` carries both its tier and its evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.ontology import (
    BASIS_HUMAN_CONFIRMATION,
    CARDINALITY_MANY_TO_ONE,
    CARDINALITY_MANY_TO_ONE_ASSUMED,
    CARDINALITY_ONE_TO_MANY,
    CONSTRAINT_IN_SET,
    CONSTRAINT_NOT_NULL,
    CONSTRAINT_PARTITION,
    CONSTRAINT_UNIQUE_PER,
    DOC_FORMAT,
    FINDING_CARDINALITY_CONFLICT,
    RELATION_JOIN,
    RELATION_UNION,
    SYNONYM_DIRECT_RENAME,
    SYNONYM_UNION_ALIGNMENT,
    TIER_CONFIRMED,
    TIER_HYPOTHESIS,
    TIER_IMPLIED,
    TIER_PROVEN,
    TIERS,
    build_ontology,
    relation_override_key,
    render_ontology_index_markdown,
    render_ontology_table_card_markdown,
)
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.render.table_cards import build_table_cards, table_card_filename
from scope_lineage.scope.scope_builder import parse_scope_lineage


FIXTURES = Path(__file__).parent / "fixtures"

SCHEMA = {
    "ods.orders": ["order_id", "customer_id", "amount", "state", "dt"],
    "ods.customer": ["id", "name", "country"],
    "ods.pay": ["driver_id", "amt", "paid_at"],
    "ods.driver": ["id", "name"],
    "ods.app_order": ["order_id", "pay_amount"],
    "ods.web_order": ["order_id", "order_amount"],
    "ods.main": ["id", "name"],
    "ods.side": ["id", "v"],
    "spark_catalog.ods.customer": ["id", "name", "country"],
    "mart.customer_daily": ["customer_id", "country", "dt"],
}


def _document(task: str, sql: str, schema=None) -> dict:
    return to_lineage_dict(
        parse_scope_lineage(sql, task, schema=schema if schema is not None else SCHEMA)
    )


def _one(cases, *, schema=None, tables=None, glossary=None, overrides=None) -> dict:
    """One ontology over the corpus these ``(task, sql)`` pairs describe."""
    documents = [_document(task, sql, schema) for task, sql in cases]
    return build_ontology(
        documents,
        tables=tables,
        glossary=glossary,
        overrides=overrides,
        artifact_root="corpus",
    )


def _relations(ontology: dict, kind: str = RELATION_JOIN) -> list[dict]:
    return [item for item in ontology["relations"] if item["kind"] == kind]


def _edge(ontology: dict, source: str, target: str) -> dict:
    return next(
        item
        for item in ontology["relations"]
        if item["from"]["entity"] == source and item["to"]["entity"] == target
    )


def _entity(ontology: dict, name: str) -> dict:
    return next(item for item in ontology["entities"] if item["id"] == name)


def _attribute(ontology: dict, name: str, column: str) -> dict:
    return next(
        item for item in _entity(ontology, name)["attributes"] if item["column"] == column
    )


def _constraints(ontology: dict, kind: str, entity: str | None = None) -> list[dict]:
    return [
        item
        for item in ontology["constraints"]
        if item["kind"] == kind
        and (entity is None or item["target"]["entity"] == entity)
    ]


# ------------------------------------------------------------------ O1: relations


DIRECT_JOIN = (
    "INSERT INTO mart.t SELECT o.order_id, c.name FROM ods.orders o "
    "LEFT JOIN ods.customer c ON o.customer_id = c.id"
)


def test_o1_a_join_between_two_physical_tables_is_one_relation() -> None:
    ontology = _one([("task_a", DIRECT_JOIN)])
    edge = _edge(ontology, "ods.orders", "ods.customer")

    assert edge["id"] == "rel:001"
    assert edge["kind"] == RELATION_JOIN
    assert edge["from"]["columns"] == ["customer_id"]
    assert edge["to"]["columns"] == ["id"]
    assert edge["join_types"] == ["LEFT_OUTER"]
    assert edge["task_count"] == 1
    assert edge["evidence"][0]["task"] == "task_a"
    assert edge["evidence"][0]["logic_block_id"].startswith("logic:ROOT:join")


def test_o1_the_same_pair_written_in_two_tasks_is_one_relation() -> None:
    """Two catalog spellings of one table are one entity, so the edge merges too."""
    other = DIRECT_JOIN.replace("ods.customer c", "spark_catalog.ods.customer c")
    ontology = _one([("task_a", DIRECT_JOIN), ("task_b", other)])
    relations = _relations(ontology)

    assert len(relations) == 1
    assert relations[0]["to"]["entity"] == "spark_catalog.ods.customer"
    assert relations[0]["task_count"] == 2
    assert [item["task"] for item in relations[0]["evidence"]] == ["task_a", "task_b"]


def test_o1_a_cte_side_is_pierced_to_its_physical_table_and_the_path_recorded() -> None:
    sql = (
        "INSERT INTO mart.t SELECT j.order_id, c.name FROM ("
        "  SELECT o.order_id AS order_id, o.customer_id AS customer_id FROM ods.orders o"
        ") j LEFT JOIN ods.customer c ON j.customer_id = c.id"
    )
    edge = _edge(_one([("task_a", sql)]), "ods.orders", "ods.customer")

    assert edge["from"]["columns"] == ["customer_id"]
    assert edge["evidence"][0]["left_via_scopes"] == ["subq:j"]


def test_o1_a_join_whose_other_side_is_not_a_table_makes_no_relation() -> None:
    """A CTE over constants has no entity behind it, so the pair names no relation."""
    sql = (
        "INSERT INTO mart.t WITH c AS (SELECT 'ACTIVE' AS k) "
        "SELECT o.order_id FROM ods.orders o JOIN c ON o.state = c.k"
    )
    assert _relations(_one([("task_a", sql)])) == []


UNION_SQL = (
    "INSERT INTO mart.t SELECT u.order_id, u.pay_amount FROM ("
    "  SELECT a.order_id AS order_id, a.pay_amount AS pay_amount FROM ods.app_order a"
    "  UNION ALL"
    "  SELECT w.order_id AS order_id, w.order_amount AS pay_amount FROM ods.web_order w"
    ") u"
)


def test_o1_two_union_branches_are_siblings_aligned_by_position() -> None:
    ontology = _one([("task_a", UNION_SQL)])
    siblings = _relations(ontology, RELATION_UNION)

    assert len(siblings) == 1
    assert siblings[0]["from"] == {
        "entity": "ods.app_order",
        "columns": ["order_id", "pay_amount"],
    }
    assert siblings[0]["to"] == {
        "entity": "ods.web_order",
        "columns": ["order_id", "order_amount"],
    }
    assert siblings[0]["join_types"] == []
    assert siblings[0]["evidence"][0]["scope_id"].startswith("union:")


def test_o1_a_statement_without_a_union_publishes_no_sibling_relation() -> None:
    assert _relations(_one([("task_a", DIRECT_JOIN)]), RELATION_UNION) == []


# ---------------------------------------------------------------- O2: cardinality


AGGREGATED_RIGHT = (
    "INSERT INTO mart.t SELECT d.id, a.total FROM ods.driver d LEFT JOIN ("
    "  SELECT p.driver_id AS driver_id, SUM(p.amt) AS total FROM ods.pay p"
    "  GROUP BY p.driver_id"
    ") a ON d.id = a.driver_id"
)

RANKED_RIGHT = (
    "INSERT INTO mart.t SELECT d.id, r.amt FROM ods.driver d LEFT JOIN ("
    "  SELECT p.driver_id AS driver_id, p.amt AS amt,"
    "  ROW_NUMBER() OVER (PARTITION BY p.driver_id ORDER BY p.paid_at DESC) AS rn"
    "  FROM ods.pay p"
    ") r ON d.id = r.driver_id AND r.rn = 1"
)


def test_o2_a_right_side_grouped_by_the_join_key_proves_one_to_many() -> None:
    """Nobody aggregates a table that already holds one row per the grouping key."""
    edge = _edge(_one([("task_a", AGGREGATED_RIGHT)]), "ods.driver", "ods.pay")

    assert edge["cardinality"] == {
        "claim": CARDINALITY_ONE_TO_MANY,
        "tier": TIER_IMPLIED,
        "basis": "group_by",
    }


def test_o2_a_right_side_ranked_to_one_row_per_key_proves_one_to_many() -> None:
    edge = _edge(_one([("task_a", RANKED_RIGHT)]), "ods.driver", "ods.pay")

    assert edge["cardinality"]["claim"] == CARDINALITY_ONE_TO_MANY
    assert edge["cardinality"]["basis"] == "ranking_window"
    assert edge["cardinality"]["tier"] == TIER_IMPLIED


def test_o2_a_direct_join_onto_a_physical_table_is_only_an_assumption() -> None:
    edge = _edge(_one([("task_a", DIRECT_JOIN)]), "ods.orders", "ods.customer")

    assert edge["cardinality"] == {
        "claim": CARDINALITY_MANY_TO_ONE_ASSUMED,
        "tier": TIER_HYPOTHESIS,
        "basis": "right_side_not_deduplicated",
    }


PRODUCER_SQL = (
    "INSERT OVERWRITE TABLE mart.customer_daily PARTITION (dt = '20250101') "
    "SELECT c.id AS customer_id, MAX(c.country) AS country FROM ods.customer c "
    "GROUP BY c.id"
)

CONSUMER_SQL = (
    "INSERT INTO mart.t SELECT o.order_id, d.country FROM ods.orders o "
    "LEFT JOIN mart.customer_daily d ON o.customer_id = d.customer_id"
)


def test_o2_a_producing_task_that_proved_the_key_makes_the_join_many_to_one() -> None:
    """The one answer a single statement cannot reach: another task's proof."""
    ontology = _one([("producer", PRODUCER_SQL), ("consumer", CONSUMER_SQL)])
    edge = _edge(ontology, "ods.orders", "mart.customer_daily")

    assert edge["cardinality"]["claim"] == CARDINALITY_MANY_TO_ONE
    assert edge["cardinality"]["tier"] == TIER_PROVEN
    assert edge["cardinality"]["basis"] == "producer_key_confidence"
    assert edge["cardinality"]["producer"] == "producer"


def test_o2_a_key_the_producer_only_half_covers_stays_an_assumption() -> None:
    """Half a proven key set proves nothing: one customer may hold many countries."""
    producer = PRODUCER_SQL.replace(
        "MAX(c.country) AS country FROM ods.customer c GROUP BY c.id",
        "c.country AS country FROM ods.customer c GROUP BY c.id, c.country",
    )
    ontology = _one([("producer", producer), ("consumer", CONSUMER_SQL)])
    edge = _edge(ontology, "ods.orders", "mart.customer_daily")

    assert edge["cardinality"]["claim"] == CARDINALITY_MANY_TO_ONE_ASSUMED


# -------------------------------------------------------------- O3: multiplicity


def test_o3_grouping_a_table_by_a_key_proves_it_holds_many_rows_per_key() -> None:
    identity = _entity(_one([("task_a", AGGREGATED_RIGHT)]), "ods.pay")["identity"]

    assert identity["multiplicity"] == [
        {
            "columns": ["driver_id"],
            "tier": TIER_IMPLIED,
            "claim": "multiple_rows_per_key",
            "evidence": [
                {
                    "task": "task_a",
                    "statement_id": identity["multiplicity"][0]["evidence"][0][
                        "statement_id"
                    ],
                    "kind": "group_by",
                    "scope_id": "subq:a",
                    "logic_block_id": "logic:subq:a:group_by:001",
                }
            ],
        }
    ]


def test_o3_a_ranking_partition_is_the_same_proof_under_another_name() -> None:
    identity = _entity(_one([("task_a", RANKED_RIGHT)]), "ods.pay")["identity"]

    assert identity["multiplicity"][0]["columns"] == ["driver_id"]
    assert identity["multiplicity"][0]["evidence"][0]["kind"] == "window_partition"


def test_o3_a_group_by_spanning_two_tables_proves_nothing_about_either() -> None:
    """A GROUP BY over a join names no single table's key set, so no table is claimed."""
    sql = (
        "INSERT INTO mart.t SELECT o.customer_id, c.country, SUM(o.amount) AS total "
        "FROM ods.orders o LEFT JOIN ods.customer c ON o.customer_id = c.id "
        "GROUP BY o.customer_id, c.country"
    )
    ontology = _one([("task_a", sql)])

    assert _entity(ontology, "ods.orders")["identity"]["multiplicity"] == []
    assert _entity(ontology, "ods.customer")["identity"]["multiplicity"] == []


def test_o3_a_direct_join_publishes_the_assumed_key_as_a_hypothesis() -> None:
    keys = _entity(_one([("task_a", DIRECT_JOIN)]), "ods.customer")["identity"][
        "candidate_keys"
    ]

    assert keys == [
        {
            "columns": ["id"],
            "tier": TIER_HYPOTHESIS,
            "evidence": [
                {
                    "task": "task_a",
                    "statement_id": keys[0]["evidence"][0]["statement_id"],
                    "kind": "joined_as_right_without_dedup",
                    "logic_block_id": keys[0]["evidence"][0]["logic_block_id"],
                }
            ],
        }
    ]


# ------------------------------------------------------------------ O5: synonyms


def test_o5_a_direct_rename_is_a_proven_synonym_on_both_ends() -> None:
    sql = "INSERT INTO mart.t SELECT o.order_id AS oid FROM ods.orders o"
    ontology = _one([("task_a", sql)])

    assert _attribute(ontology, "ods.orders", "order_id")["synonyms"] == [
        {
            "entity": "mart.t",
            "column": "oid",
            "tier": TIER_PROVEN,
            "via": SYNONYM_DIRECT_RENAME,
            "evidence": [{"task": "task_a", "statement_id": "stmt:001"}],
        }
    ]
    assert _attribute(ontology, "mart.t", "oid")["synonyms"][0]["entity"] == "ods.orders"


def test_o5_a_column_carried_under_its_own_name_is_not_a_synonym() -> None:
    sql = "INSERT INTO mart.t SELECT o.order_id AS order_id FROM ods.orders o"
    ontology = _one([("task_a", sql)])

    assert _attribute(ontology, "ods.orders", "order_id")["synonyms"] == []


def test_o5_two_union_branches_align_differently_named_columns() -> None:
    ontology = _one([("task_a", UNION_SQL)])
    synonyms = _attribute(ontology, "ods.app_order", "pay_amount")["synonyms"]

    assert synonyms == [
        {
            "entity": "ods.web_order",
            "column": "order_amount",
            "tier": TIER_IMPLIED,
            "via": SYNONYM_UNION_ALIGNMENT,
            "evidence": [{"task": "task_a", "statement_id": "stmt:001"}],
        }
    ]


def test_o5_an_aligned_pair_of_equal_names_is_not_published_as_a_synonym() -> None:
    ontology = _one([("task_a", UNION_SQL)])

    assert _attribute(ontology, "ods.app_order", "order_id")["synonyms"] == []


# ---------------------------------------------------------------- O6: constraints


def test_o6_a_not_null_filter_is_a_hypothesis_with_the_reason_it_is_one() -> None:
    sql = (
        "INSERT INTO mart.t SELECT o.order_id FROM ods.orders o "
        "WHERE NOT o.customer_id IS NULL"
    )
    ontology = _one([("task_a", sql)])
    found = _constraints(ontology, CONSTRAINT_NOT_NULL)

    assert [item["target"] for item in found] == [
        {"entity": "ods.orders", "column": "customer_id"}
    ]
    assert found[0]["tier"] == TIER_HYPOTHESIS
    assert "源表本身可能仍含 NULL" in found[0]["note"]
    assert _attribute(ontology, "ods.orders", "customer_id")["not_null_observed"] is True


def test_o6_an_equality_filter_is_not_a_not_null_constraint() -> None:
    sql = "INSERT INTO mart.t SELECT o.order_id FROM ods.orders o WHERE o.state = 'NEW'"
    ontology = _one([("task_a", sql)])

    assert _constraints(ontology, CONSTRAINT_NOT_NULL) == []
    assert _attribute(ontology, "ods.orders", "state")["not_null_observed"] is False


def test_o6_a_closed_in_list_is_a_complete_and_proven_value_set() -> None:
    sql = (
        "INSERT INTO mart.t SELECT o.order_id, o.state FROM ods.orders o "
        "WHERE o.state IN ('NEW', 'PAID')"
    )
    found = _constraints(_one([("task_a", sql)]), CONSTRAINT_IN_SET, "ods.orders")

    assert found[0]["values"] == ["NEW", "PAID"]
    assert found[0]["completeness"] == "complete"
    assert found[0]["tier"] == TIER_PROVEN


def test_o6_an_observed_value_set_is_never_called_complete() -> None:
    sql = (
        "INSERT INTO mart.t SELECT o.order_id, o.state FROM ods.orders o "
        "WHERE o.state = 'NEW'"
    )
    found = _constraints(_one([("task_a", sql)]), CONSTRAINT_IN_SET, "ods.orders")

    assert found[0]["values"] == ["NEW"]
    assert found[0]["completeness"] == "unknown"
    assert found[0]["tier"] == TIER_HYPOTHESIS


def test_o6_a_partition_column_is_a_metadata_fact() -> None:
    found = _constraints(
        _one([("producer", PRODUCER_SQL)]), CONSTRAINT_PARTITION, "mart.customer_daily"
    )

    assert [item["target"]["column"] for item in found] == ["dt"]
    assert found[0]["tier"] == TIER_PROVEN


def test_o6_a_proven_producer_key_becomes_a_proven_unique_per() -> None:
    found = _constraints(
        _one([("producer", PRODUCER_SQL)]), CONSTRAINT_UNIQUE_PER, "mart.customer_daily"
    )

    assert found[0]["columns"] == ["customer_id", "dt"]
    assert found[0]["tier"] == TIER_PROVEN
    assert found[0]["evidence"][0]["basis"] == "proven"


def test_o6_a_candidate_producer_key_becomes_a_hypothesis_unique_per() -> None:
    """``key_confidence: candidate`` is the corpus's guess, and stays one here."""
    sql = (
        "INSERT INTO mart.t WITH agg AS ("
        "  SELECT s.id AS id, SUM(s.v) AS s FROM ods.side s GROUP BY s.id"
        ") SELECT m.id AS main_id, agg.s AS s FROM ods.main m LEFT JOIN agg ON m.id = agg.id"
    )
    found = _constraints(_one([("task_a", sql)]), CONSTRAINT_UNIQUE_PER, "mart.t")

    assert found[0]["columns"] == ["main_id"]
    assert found[0]["tier"] == TIER_HYPOTHESIS
    assert found[0]["evidence"][0]["basis"] == "candidate"


# The same table, written by two tasks that prove the same key set -- one 约束, proved
# twice, not two 约束. `PRODUCER_SQL` reads `ods.customer`; this one reads the mirror.
SECOND_PRODUCER_SQL = (
    "INSERT OVERWRITE TABLE mart.customer_daily PARTITION (dt = '20250102') "
    "SELECT c.id AS customer_id, MAX(c.country) AS country "
    "FROM spark_catalog.ods.customer c GROUP BY c.id"
)


def test_o6_two_producers_proving_the_same_key_set_publish_one_constraint() -> None:
    """Emitting one per producer counted the same proof twice, in the 约束 table too."""
    found = _constraints(
        _one([("producer", PRODUCER_SQL), ("second_producer", SECOND_PRODUCER_SQL)]),
        CONSTRAINT_UNIQUE_PER,
        "mart.customer_daily",
    )

    assert len(found) == 1
    assert found[0]["columns"] == ["customer_id", "dt"]
    assert [item["task"] for item in found[0]["evidence"]] == [
        "producer",
        "second_producer",
    ]


def test_o6_the_merged_constraint_keeps_the_strongest_tier_of_its_producers() -> None:
    """The same rule ``identity.candidate_keys`` follows: one weak proof is still a proof."""
    weaker = (
        "INSERT OVERWRITE TABLE mart.customer_daily PARTITION (dt = '20250102') "
        "SELECT m.id AS customer_id, agg.v AS country FROM ods.main m "
        "LEFT JOIN (SELECT s.id AS id, MAX(s.v) AS v FROM ods.side s GROUP BY s.id) agg "
        "ON m.id = agg.id"
    )
    found = _constraints(
        _one([("producer", PRODUCER_SQL), ("weaker_producer", weaker)]),
        CONSTRAINT_UNIQUE_PER,
        "mart.customer_daily",
    )

    assert len(found) == 1
    assert found[0]["tier"] == TIER_PROVEN
    assert [item["basis"] for item in found[0]["evidence"]] == ["proven", "candidate"]


def test_o6_two_producers_proving_different_key_sets_stay_two_constraints() -> None:
    """Merging is per claim, not per table: two key sets are two different claims."""
    other = (
        "INSERT OVERWRITE TABLE mart.customer_daily PARTITION (dt = '20250102') "
        "SELECT c.id AS customer_id, c.country AS country FROM ods.customer c "
        "GROUP BY c.id, c.country"
    )
    found = _constraints(
        _one([("producer", PRODUCER_SQL), ("other_producer", other)]),
        CONSTRAINT_UNIQUE_PER,
        "mart.customer_daily",
    )

    assert [item["columns"] for item in found] == [
        ["customer_id", "country", "dt"],
        ["customer_id", "dt"],
    ]


def test_o6_a_statement_that_proves_no_key_publishes_no_unique_per() -> None:
    sql = "INSERT INTO mart.t SELECT o.order_id, o.amount FROM ods.orders o"

    assert _constraints(_one([("task_a", sql)]), CONSTRAINT_UNIQUE_PER, "mart.t") == []


# ------------------------------------------------------------------ O7: conflicts


def test_o7_a_dedup_in_one_task_and_a_direct_join_in_another_is_a_conflict() -> None:
    direct = (
        "INSERT INTO mart.u SELECT d.id, p.amt FROM ods.driver d "
        "LEFT JOIN ods.pay p ON d.id = p.driver_id"
    )
    ontology = _one([("dedup_task", AGGREGATED_RIGHT), ("direct_task", direct)])
    findings = [
        item
        for item in ontology["findings"]
        if item["kind"] == FINDING_CARDINALITY_CONFLICT
    ]

    assert len(findings) == 1
    assert findings[0]["entity"] == "ods.pay"
    assert findings[0]["columns"] == ["driver_id"]
    assert findings[0]["tasks"] == {
        "multiple_rows_per_key": ["dedup_task"],
        "assumed_unique": ["direct_task"],
    }
    assert "行数放大" in findings[0]["text"]


def test_o7_two_tasks_that_both_deduplicate_are_not_a_conflict() -> None:
    ontology = _one([("task_a", AGGREGATED_RIGHT), ("task_b", RANKED_RIGHT)])

    assert ontology["findings"] == []


def test_o7_a_producer_key_conflict_is_carried_over_from_the_table_card() -> None:
    first = (
        "INSERT INTO mart.shared SELECT o.customer_id AS k, MAX(o.state) AS v "
        "FROM ods.orders o GROUP BY o.customer_id"
    )
    second = (
        "INSERT INTO mart.shared SELECT o.order_id AS k, o.state AS v "
        "FROM ods.orders o GROUP BY o.order_id, o.state"
    )
    ontology = _one([("task_a", first), ("task_b", second)])
    kinds = {item["kind"] for item in ontology["findings"]}

    assert "producer_key_conflict" in kinds
    assert all(item["entity"] == "mart.shared" for item in ontology["findings"])


def test_o7_an_ambiguous_bare_name_is_carried_over_from_the_table_card() -> None:
    bare = "INSERT INTO mart.t SELECT o.order_id FROM orders o"
    other = "INSERT INTO mart.u SELECT p.driver_id FROM dwd.orders p"
    ontology = _one(
        [("task_a", DIRECT_JOIN), ("task_b", bare), ("task_c", other)],
        schema={**SCHEMA, "orders": ["order_id"], "dwd.orders": ["driver_id"]},
    )
    kinds = {item["kind"] for item in ontology["findings"]}

    assert "ambiguous_bare_name" in kinds


# ------------------------------------------------------- honesty and determinism


CORPUS_CASES = (
    ("task_join", DIRECT_JOIN),
    ("task_agg", AGGREGATED_RIGHT),
    ("task_rank", RANKED_RIGHT),
    ("task_union", UNION_SQL),
    ("producer", PRODUCER_SQL),
    ("consumer", CONSUMER_SQL),
)


def _corpus_documents() -> list[dict]:
    return [_document(task, sql) for task, sql in CORPUS_CASES]


def _known_names(documents: list[dict]) -> tuple[set[str], set[str], set[str]]:
    """``(tables, columns, tasks)`` every contract document in the corpus names."""
    tables: set[str] = set()
    columns: set[str] = set()
    tasks: set[str] = set()
    for document in documents:
        tasks.add(str(document.get("task_id")))
        tables.update(document.get("source_tables") or [])
        if document.get("target_table"):
            tables.add(str(document["target_table"]))
        metadata = document.get("related_metadata") or {}
        for group in ("input_tables", "output_tables"):
            for item in (metadata.get(group) or {}).values():
                # A1: the metadata's declared width is named by the document too, and
                # an entity attribute may now come from a column no task read.
                for key in ("column_details", "declared_columns"):
                    columns.update(
                        str(detail.get("name")) for detail in item.get(key) or []
                    )
        columns.update(
            str(entry.get("column")) for entry in document.get("end_to_end_lineage") or []
        )
    return tables, columns, tasks


def test_the_ontology_never_names_a_table_column_or_task_the_corpus_did_not() -> None:
    documents = _corpus_documents()
    ontology = build_ontology(documents, artifact_root="corpus")
    tables, columns, tasks = _known_names(documents)

    for entity in ontology["entities"]:
        assert any(
            entity["id"] == name or name.endswith("." + entity["id"]) for name in tables
        ), f"invented entity {entity['id']!r}"
        for attribute in entity["attributes"]:
            assert attribute["column"] in columns, f"invented column {attribute['column']!r}"
    for relation in ontology["relations"]:
        for side in ("from", "to"):
            assert any(column in columns for column in relation[side]["columns"])
        for item in relation["evidence"]:
            assert item["task"] in tasks, f"invented task {item['task']!r}"


def _assertions(ontology: dict) -> list[tuple[str, dict]]:
    """Every published claim that carries a tier, with the path it was read from."""
    found = []
    for entity in ontology["entities"]:
        identity = entity["identity"]
        found.extend((f"{entity['id']}.candidate_keys", item) for item in identity["candidate_keys"])
        found.extend((f"{entity['id']}.multiplicity", item) for item in identity["multiplicity"])
        found.extend(
            (f"{entity['id']}.{attribute['column']}.synonyms", item)
            for attribute in entity["attributes"]
            for item in attribute["synonyms"]
        )
    found.extend((relation["id"], relation["cardinality"]) for relation in ontology["relations"])
    found.extend(
        (f"{item['target']['entity']}.{item['kind']}", item)
        for item in ontology["constraints"]
    )
    return found


def test_every_assertion_carries_a_tier_from_the_vocabulary() -> None:
    ontology = build_ontology(_corpus_documents(), artifact_root="corpus")
    checked = 0

    for path, assertion in _assertions(ontology):
        assert assertion["tier"] in TIERS, f"{path}: unknown tier {assertion['tier']!r}"
        checked += 1
    assert checked > 10


def test_no_assertion_weaker_than_proven_is_published_without_evidence() -> None:
    ontology = build_ontology(_corpus_documents(), artifact_root="corpus")

    for path, assertion in _assertions(ontology):
        if assertion["tier"] == TIER_PROVEN:
            continue
        evidence = assertion.get("evidence")
        basis = assertion.get("basis")
        assert evidence or basis, f"{path}: a {assertion['tier']} claim with no evidence"


def test_the_ontology_is_byte_identical_for_the_same_corpus() -> None:
    documents = _corpus_documents()
    first = build_ontology(documents, artifact_root="corpus")
    second = build_ontology(list(reversed(documents)), artifact_root="corpus")

    assert json.dumps(first, ensure_ascii=False) == json.dumps(second, ensure_ascii=False)
    assert render_ontology_index_markdown(first) == render_ontology_index_markdown(second)


def test_supplied_corpus_documents_give_the_same_answer_as_built_ones() -> None:
    """``--tables`` / ``--glossary`` are a shortcut, never a different derivation."""
    documents = _corpus_documents()
    profiles = [build_semantic_profile(document) for document in documents]
    built = build_ontology(documents, profiles, artifact_root="corpus")
    supplied = build_ontology(
        documents,
        profiles,
        tables=build_table_cards(profiles, artifact_root="corpus"),
        artifact_root="corpus",
    )

    assert built == supplied


# -------------------------------------------------------------------- golden bytes


GOLDEN_DIR = FIXTURES / "ontology"
# The same corpus the table cards' golden is built from: two contract spellings, a
# directory write that is not a table, a UNION, a ranking dedup and a shared table.
GOLDEN_CASES = (
    ("lineage_contract", "commented_insert"),
    ("lineage_contract", "directory_target"),
    ("lineage_contract", "grouped_dedup_join"),
    ("lineage_contract", "simple_insert"),
    ("task_lineage_contract", "commented_task"),
)


# The cards recorded whole: a produced table with a proven key and both constraint
# kinds, a physical table whose only identity claim is an author's assumption, and a
# UNION branch whose columns are synonyms of another table's.
GOLDEN_CARDS = ("dim.channel", "mart.metric_by_segment", "ods.events_a")


def _golden_corpus() -> tuple[dict, dict]:
    """``(ontology, table cards)`` over the fixed corpus, built exactly as the CLI does."""
    documents = []
    profiles = []
    for group, name in GOLDEN_CASES:
        case = FIXTURES / group / name
        lineage = json.loads((case / "lineage.json").read_text(encoding="utf-8"))
        diagnostics = json.loads((case / "diagnostics.json").read_text(encoding="utf-8"))
        documents.append(lineage)
        profiles.append(build_semantic_profile(lineage, diagnostics))
    cards = build_table_cards(profiles, artifact_root="corpus")
    return build_ontology(documents, profiles, tables=cards, artifact_root="corpus"), cards


def _golden_ontology() -> dict:
    return _golden_corpus()[0]


def _record_golden() -> dict[str, str]:
    """The recording path and the asserted path, deliberately one function."""
    ontology, cards = _golden_corpus()
    recorded = {
        "ontology.json": json.dumps(ontology, ensure_ascii=False, indent=2) + "\n",
        "ontology.md": render_ontology_index_markdown(ontology),
    }
    index = {str(card["table"]): card for card in cards["tables"]}
    for table in GOLDEN_CARDS:
        recorded[f"tables/{table_card_filename(table)}"] = (
            render_ontology_table_card_markdown(index[table], ontology)
        )
    return recorded


def test_golden_ontology_matches_the_baseline() -> None:
    first = _record_golden()
    second = _record_golden()

    for name, body in first.items():
        assert body == (GOLDEN_DIR / name).read_text(encoding="utf-8"), name
    assert second == first


def test_the_golden_corpus_exercises_the_shapes_the_ontology_exists_for() -> None:
    ontology = _golden_ontology()

    assert ontology["doc_format"] == DOC_FORMAT
    assert {item["kind"] for item in ontology["relations"]} == {
        RELATION_JOIN,
        RELATION_UNION,
    }
    assert {
        item["cardinality"]["claim"] for item in ontology["relations"]
    } >= {CARDINALITY_ONE_TO_MANY, CARDINALITY_MANY_TO_ONE_ASSUMED}
    assert {item["kind"] for item in ontology["constraints"]} >= {
        CONSTRAINT_IN_SET,
        CONSTRAINT_PARTITION,
        CONSTRAINT_UNIQUE_PER,
    }
    assert any(
        attribute["synonyms"]
        for entity in ontology["entities"]
        for attribute in entity["attributes"]
    )


@pytest.mark.parametrize("kind", ["entities", "relations", "constraints", "findings"])
def test_the_golden_document_keeps_its_top_level_sections(kind: str) -> None:
    assert kind in _golden_ontology()


# ------------------------------------------------- WI-12: the fifth tier, `confirmed`


CONFIRMABLE = (
    ("task_a", DIRECT_JOIN),
    ("task_b", "INSERT INTO mart.u SELECT c.name FROM ods.orders o "
               "LEFT JOIN ods.customer c ON o.customer_id = c.id"),
)


def test_an_override_raises_one_relation_to_confirmed() -> None:
    """The only tier the corpus cannot reach: somebody answered the question."""
    relation_key = "ods.orders.customer_id->ods.customer.id"
    ontology = _one(
        CONFIRMABLE,
        overrides={
            "relations": {
                relation_key: {
                    "cardinality": CARDINALITY_MANY_TO_ONE,
                    "confirmed_by": "reviewer",
                    "date": "2026-09-19",
                }
            }
        },
    )
    edge = _edge(ontology, "ods.orders", "ods.customer")

    assert relation_override_key(edge) == relation_key
    assert edge["cardinality"] == {
        "claim": CARDINALITY_MANY_TO_ONE,
        "tier": TIER_CONFIRMED,
        "basis": BASIS_HUMAN_CONFIRMATION,
        "confirmed_by": "reviewer",
        "date": "2026-09-19",
    }
    assert ontology["overrides_applied"] == {
        "relations": 1,
        "keys": 0,
        "unmatched": [],
        "ignored_fields": [],
    }


def test_an_override_raises_one_candidate_key_to_confirmed() -> None:
    ontology = _one(
        CONFIRMABLE,
        overrides={
            "keys": {"ods.customer": {"columns": ["id"], "confirmed_by": "reviewer"}}
        },
    )
    key = _entity(ontology, "ods.customer")["identity"]["candidate_keys"][0]

    assert key["columns"] == ["id"]
    assert key["tier"] == TIER_CONFIRMED
    assert {"kind": "human_confirmation", "confirmed_by": "reviewer"} in key["evidence"]
    assert ontology["overrides_applied"]["keys"] == 1


def test_a_confirmed_key_the_corpus_never_guessed_is_added_with_its_stamp() -> None:
    ontology = _one(
        CONFIRMABLE,
        overrides={"keys": {"ods.orders": {"columns": ["order_id"], "date": "2026-09-19"}}},
    )
    keys = _entity(ontology, "ods.orders")["identity"]["candidate_keys"]

    assert [item["columns"] for item in keys] == [["order_id"]]
    assert keys[0]["tier"] == TIER_CONFIRMED
    assert keys[0]["evidence"] == [{"kind": "human_confirmation", "date": "2026-09-19"}]


def test_an_override_that_matches_nothing_is_reported_rather_than_dropped() -> None:
    """A typo in a reviewed file is the one thing its reviewer cannot see."""
    ontology = _one(
        CONFIRMABLE,
        overrides={
            "relations": {"ods.orders.nope->ods.customer.id": {"cardinality": "one_to_many"}},
            "keys": {"ods.absent": {"columns": ["id"]}},
        },
    )

    assert ontology["overrides_applied"] == {
        "relations": 0,
        "keys": 0,
        "unmatched": [
            {"key": "ods.absent", "reason": "unknown_entity: ods.absent"},
            {"key": "ods.orders.nope->ods.customer.id", "reason": "unknown_column: nope"},
        ],
        "ignored_fields": [],
    }


def test_without_overrides_nothing_is_confirmed() -> None:
    ontology = _one(CONFIRMABLE)
    tiers = {
        str(key["tier"])
        for entity in ontology["entities"]
        for key in entity["identity"]["candidate_keys"]
    } | {str(item["cardinality"]["tier"]) for item in ontology["relations"]}

    assert TIER_CONFIRMED not in tiers
    assert ontology["overrides_applied"] == {
        "relations": 0,
        "keys": 0,
        "unmatched": [],
        "ignored_fields": [],
    }
