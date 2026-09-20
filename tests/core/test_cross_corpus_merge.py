"""P7: cross-corpus reuse of table cards (``merge_table_cards`` and its two CLI doors).

A table card answers "what is this table" out of one batch of tasks. Two batches walked
separately -- one team's warehouse jobs and another's, or last month's export and this
month's -- hold two halves of the same answer: the producer that proved the key is in
one, the consumers that read the table are in the other. Merging the two ``tables.json``
documents is the only way the ontology gets to say ``proven`` about that JOIN, and the
only honest way to say it is to keep the *corpus* on every piece of evidence, so a reader
who cannot find the producing task in the corpus in front of them is told where it lives.

The properties pinned here are the ones that make a merged card as trustworthy as a built
one: merging one document changes nothing, evidence is never anonymised, the counts are
re-derived rather than added up blindly, and a conflict between two corpora is published
exactly like a conflict inside one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.cli import main
from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.ontology import (
    BASIS_PRODUCER_KEY,
    CARDINALITY_MANY_TO_ONE,
    TIER_PROVEN,
    build_ontology,
    render_ontology_index_markdown,
    render_ontology_table_card_markdown,
)
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.render.table_cards import (
    DOC_FORMAT,
    FINDING_NEVER_CONSUMED,
    FINDING_PRODUCER_KEY_CONFLICT,
    build_table_cards,
    merge_table_cards,
)
from scope_lineage.scope.scope_builder import parse_scope_lineage

from .statement_document import write_statement_documents


SCHEMA = {
    "ods.customer_base": ["customer_id", "country_code", "dt"],
    "ods.customer_event": ["customer_id", "country_code", "event_code", "dt"],
    "mart.customer_daily": ["customer_id", "country_code", "n", "dt"],
    "mart.event_rollup": ["event_code", "n"],
    "mart.country_rollup": ["country_code", "n"],
}

# Corpus A: the task that writes the shared table, one row per customer_id.
PRODUCER_SQL = (
    "INSERT OVERWRITE TABLE mart.customer_daily PARTITION (dt = '20250101') "
    "SELECT customer_id, country_code, count(1) AS n FROM ods.customer_base "
    "GROUP BY customer_id"
)

# Corpus A also reads the shared table once, as a filter.
HOME_CONSUMER_SQL = (
    "INSERT OVERWRITE TABLE mart.country_rollup "
    "SELECT country_code, count(1) AS n FROM ods.customer_base "
    "WHERE customer_id IN (SELECT customer_id FROM mart.customer_daily) "
    "GROUP BY country_code"
)

# Corpus B: a task that joins the shared table on the whole key corpus A proved.
FOREIGN_CONSUMER_SQL = (
    "INSERT OVERWRITE TABLE mart.event_rollup "
    "SELECT e.event_code, count(1) AS n FROM ods.customer_event e "
    "LEFT JOIN mart.customer_daily d ON e.customer_id = d.customer_id "
    "GROUP BY e.event_code"
)

# Corpus B, disagreeing: the same table written by another task with another key.
RIVAL_PRODUCER_SQL = (
    "INSERT OVERWRITE TABLE mart.customer_daily PARTITION (dt = '20250101') "
    "SELECT customer_id, country_code, count(1) AS n FROM ods.customer_event "
    "GROUP BY customer_id, country_code"
)


def _profile(sql: str, task: str) -> dict:
    return build_semantic_profile(
        to_lineage_dict(parse_scope_lineage(sql, task, schema=SCHEMA))
    )


def _cards(cases, root: str) -> dict:
    return build_table_cards(
        [_profile(sql, task) for task, sql in cases], artifact_root=root
    )


def _corpus_a() -> dict:
    return _cards(
        (("producer_task", PRODUCER_SQL), ("home_task", HOME_CONSUMER_SQL)), "corpus_a"
    )


def _corpus_b() -> dict:
    return _cards((("foreign_task", FOREIGN_CONSUMER_SQL),), "corpus_b")


def _card(cards: dict, table: str) -> dict:
    return next(item for item in cards["tables"] if item["table"] == table)


def _column(card: dict, name: str) -> dict:
    return next(item for item in card["columns"] if item["name"] == name)


# ------------------------------------------------------------------------ identity


def test_merging_one_document_is_the_identity() -> None:
    cards = _corpus_a()

    merged = merge_table_cards(cards)

    assert merged == cards
    assert json.dumps(merged, ensure_ascii=False, indent=2) == json.dumps(
        cards, ensure_ascii=False, indent=2
    )


def test_merging_nothing_is_an_error() -> None:
    with pytest.raises(ValueError):
        merge_table_cards()


def test_merging_a_document_of_another_format_is_an_error() -> None:
    with pytest.raises(ValueError):
        merge_table_cards(_corpus_a(), {"doc_format": "glossary-json/1"})


# ------------------------------------------------------------------ one merged card


def test_a_table_produced_in_one_corpus_and_read_in_another_is_one_card() -> None:
    merged = merge_table_cards(_corpus_a(), _corpus_b())

    card = _card(merged, "mart.customer_daily")
    assert [item["task"] for item in card["produced_by"]] == ["producer_task"]
    assert [item["task"] for item in card["consumed_by"]] == [
        "foreign_task",
        "home_task",
    ]
    assert card["coverage"]["producers"] == 1
    assert card["coverage"]["consumers"] == 2


def test_every_producer_and_consumer_names_the_corpus_it_came_from() -> None:
    merged = merge_table_cards(_corpus_a(), _corpus_b())

    card = _card(merged, "mart.customer_daily")
    assert [item["corpus"] for item in card["produced_by"]] == ["corpus_a"]
    assert [(item["task"], item["corpus"]) for item in card["consumed_by"]] == [
        ("foreign_task", "corpus_b"),
        ("home_task", "corpus_a"),
    ]


def test_the_merged_document_says_which_corpora_it_was_merged_from() -> None:
    merged = merge_table_cards(_corpus_a(), _corpus_b())

    assert merged["doc_format"] == DOC_FORMAT
    assert merged["merged_from"] == [
        {"corpus": "corpus_a", "task_count": 2},
        {"corpus": "corpus_b", "task_count": 1},
    ]
    assert merged["corpus"]["task_count"] == 3
    assert set(merged["corpus"]["lineage_digests"]) == {
        "corpus_a/producer_task",
        "corpus_a/home_task",
        "corpus_b/foreign_task",
    }


def test_the_merged_document_is_sorted_and_order_independent() -> None:
    first = merge_table_cards(_corpus_a(), _corpus_b())
    second = merge_table_cards(_corpus_b(), _corpus_a())

    tables = [card["table"] for card in first["tables"]]
    assert tables == sorted(tables)
    assert [card["table"] for card in second["tables"]] == tables
    assert _card(first, "mart.customer_daily")["consumed_by"] == _card(
        second, "mart.customer_daily"
    )["consumed_by"]


def test_merging_a_merged_document_again_keeps_one_flat_provenance() -> None:
    once = merge_table_cards(_corpus_a(), _corpus_b())

    twice = merge_table_cards(once)

    assert twice == once


# ---------------------------------------------------------------------- the columns


def test_a_column_read_in_two_corpora_sums_its_usage_counts() -> None:
    """The same task name in two corpora is two readers, not one counted twice."""
    elsewhere = _cards((("foreign_task", FOREIGN_CONSUMER_SQL),), "corpus_c")

    merged = merge_table_cards(_corpus_a(), _corpus_b(), elsewhere)

    card = _card(merged, "mart.customer_daily")
    assert _column(card, "customer_id")["consumer_usage_counts"]["join_key"] == 2
    assert [(item["task"], item["corpus"]) for item in card["consumed_by"]] == [
        ("foreign_task", "corpus_b"),
        ("foreign_task", "corpus_c"),
        ("home_task", "corpus_a"),
    ]


def test_the_column_order_of_the_first_document_that_declared_them_is_kept() -> None:
    merged = merge_table_cards(_corpus_a(), _corpus_b())

    card = _card(merged, "mart.customer_daily")
    assert [column["name"] for column in card["columns"]] == [
        column["name"] for column in _card(_corpus_a(), "mart.customer_daily")["columns"]
    ]
    assert _column(card, "customer_id")["used_in_corpus"] is True


def test_sample_values_are_unioned_and_counted_off_the_merged_cards(
    tmp_path: Path,
) -> None:
    from scope_lineage.metadata.column_samples import load_column_samples

    def sampled(values: str, root: str) -> dict:
        source = tmp_path / f"{root}.csv"
        source.write_text(
            "table,column,value\n"
            + "".join(
                f"mart.customer_daily,country_code,{value}\n"
                for value in values.split(",")
            ),
            encoding="utf-8",
        )
        return build_table_cards(
            [_profile(PRODUCER_SQL, "producer_task")],
            artifact_root=root,
            samples=load_column_samples(str(source)),
        )

    merged = merge_table_cards(sampled("AA,BB", "corpus_a"), sampled("BB,CC", "corpus_b"))

    card = _card(merged, "mart.customer_daily")
    assert _column(card, "country_code")["samples"] == ["AA", "BB"]
    assert card["coverage"]["columns_sampled"] == 1
    assert merged["samples_applied"]["columns_sampled"] == 1
    assert len(merged["samples_applied"]["sources"]) == 2


def test_coverage_is_recomputed_rather_than_added_up() -> None:
    merged = merge_table_cards(_corpus_a(), _corpus_b())

    coverage = _card(merged, "mart.customer_daily")["coverage"]
    card = _card(merged, "mart.customer_daily")
    assert coverage["columns_used"] == sum(
        1 for column in card["columns"] if column["used_in_corpus"]
    )
    assert coverage["consumers"] == len(card["consumed_by"])


def test_a_table_the_other_corpus_reads_is_no_longer_never_consumed() -> None:
    producers_only = _cards((("producer_task", PRODUCER_SQL),), "corpus_a")
    alone = _card(producers_only, "mart.customer_daily")

    merged = _card(
        merge_table_cards(producers_only, _corpus_b()), "mart.customer_daily"
    )

    assert FINDING_NEVER_CONSUMED in {finding["kind"] for finding in alone["findings"]}
    assert FINDING_NEVER_CONSUMED not in {
        finding["kind"] for finding in merged["findings"]
    }


# --------------------------------------------------------- the foreign proof lands


def test_a_key_proven_in_one_corpus_decides_a_join_in_another() -> None:
    merged = merge_table_cards(_corpus_a(), _corpus_b())
    document = to_lineage_dict(
        parse_scope_lineage(FOREIGN_CONSUMER_SQL, "foreign_task", schema=SCHEMA)
    )

    plain = build_semantic_profile(document)
    carded = build_semantic_profile(document, None, table_cards=merged)

    assert [item["status"] for item in plain["output_shape"]["fan_out_risks"]] == [
        "unknown"
    ]
    risk = carded["output_shape"]["fan_out_risks"][0]
    assert risk["status"] == "safe"
    assert risk["basis"] == "table_card"
    assert "producer_task" in risk["reason"]


def test_the_ontology_reads_a_foreign_proof_as_proven_and_names_its_corpus() -> None:
    merged = merge_table_cards(_corpus_a(), _corpus_b())
    documents = [
        to_lineage_dict(
            parse_scope_lineage(FOREIGN_CONSUMER_SQL, "foreign_task", schema=SCHEMA)
        )
    ]

    ontology = build_ontology(documents, tables=merged, artifact_root="corpus_b")

    edge = next(
        item
        for item in ontology["relations"]
        if item["to"]["entity"] == "mart.customer_daily"
    )
    assert edge["cardinality"]["claim"] == CARDINALITY_MANY_TO_ONE
    assert edge["cardinality"]["tier"] == TIER_PROVEN
    assert edge["cardinality"]["basis"] == BASIS_PRODUCER_KEY
    foreign = [item for item in edge["evidence"] if item.get("corpus")]
    assert [(item["task"], item["corpus"]) for item in foreign] == [
        ("producer_task", "corpus_a")
    ]
    # The JOIN itself was written by one task of THIS corpus; a borrowed proof is
    # evidence, not another author.
    assert edge["task_count"] == 1


def test_a_single_corpus_ontology_carries_no_corpus_stamp() -> None:
    cards = _cards(
        (("producer_task", PRODUCER_SQL), ("foreign_task", FOREIGN_CONSUMER_SQL)),
        "corpus_a",
    )
    documents = [
        to_lineage_dict(
            parse_scope_lineage(FOREIGN_CONSUMER_SQL, "foreign_task", schema=SCHEMA)
        )
    ]

    ontology = build_ontology(documents, tables=cards, artifact_root="corpus_a")

    edge = next(
        item
        for item in ontology["relations"]
        if item["to"]["entity"] == "mart.customer_daily"
    )
    assert edge["cardinality"]["tier"] == TIER_PROVEN
    assert not [item for item in edge["evidence"] if item.get("corpus")]


# ----------------------------------------------------- what the corpus models as an entity


def _foreign_ontology() -> dict:
    """Corpus B's ontology, with corpus A's cards merged in as evidence."""
    merged = merge_table_cards(_corpus_a(), _corpus_b())
    documents = [
        to_lineage_dict(
            parse_scope_lineage(FOREIGN_CONSUMER_SQL, "foreign_task", schema=SCHEMA)
        )
    ]
    return build_ontology(documents, tables=merged, artifact_root="corpus_b")


def test_a_table_only_the_foreign_cards_know_is_not_an_entity() -> None:
    """Evidence is not scope. A card from elsewhere may decide this corpus's JOIN
    without putting its whole warehouse in this corpus's ER diagram."""
    ontology = _foreign_ontology()

    assert [entity["id"] for entity in ontology["entities"]] == [
        "mart.customer_daily",
        "mart.event_rollup",
        "ods.customer_event",
    ]
    assert "ods.customer_base" not in {entity["id"] for entity in ontology["entities"]}
    assert "mart.country_rollup" not in {entity["id"] for entity in ontology["entities"]}


def test_a_foreign_carded_table_this_corpus_joins_is_an_entity_with_its_proof() -> None:
    ontology = _foreign_ontology()

    entity = next(
        item for item in ontology["entities"] if item["id"] == "mart.customer_daily"
    )
    keys = entity["identity"]["candidate_keys"]
    assert [key["columns"] for key in keys] == [["customer_id"]]
    assert keys[0]["tier"] == TIER_PROVEN
    # The proof is corpus A's and says so; this corpus's own assumption stays unstamped.
    assert [
        (item["task"], item.get("corpus")) for item in keys[0]["evidence"]
    ] == [("producer_task", "corpus_a"), ("foreign_task", None)]


def test_every_relation_endpoint_has_an_entity() -> None:
    ontology = _foreign_ontology()

    published = {entity["id"] for entity in ontology["entities"]}
    endpoints = {
        relation[side]["entity"]
        for relation in ontology["relations"]
        for side in ("from", "to")
    }

    assert endpoints <= published


def test_constraints_and_findings_stay_inside_the_modelled_entities() -> None:
    ontology = _foreign_ontology()

    published = {entity["id"] for entity in ontology["entities"]}
    targets = {
        constraint["target"]["entity"] for constraint in ontology["constraints"]
    }

    assert targets <= published
    assert {finding["entity"] for finding in ontology["findings"]} <= published


def test_the_index_counts_the_tables_that_only_supplied_evidence() -> None:
    ontology = _foreign_ontology()

    assert ontology["corpus"]["external_evidence_tables"] == 2

    rendered = render_ontology_index_markdown(ontology)

    assert "另有 2 张表仅作为外部证据参与，未建实体" in rendered


def test_a_single_corpus_ontology_models_every_card_and_counts_nothing() -> None:
    cards = _cards(
        (("producer_task", PRODUCER_SQL), ("foreign_task", FOREIGN_CONSUMER_SQL)),
        "corpus_a",
    )
    documents = [
        to_lineage_dict(parse_scope_lineage(sql, task, schema=SCHEMA))
        for task, sql in (
            ("producer_task", PRODUCER_SQL),
            ("foreign_task", FOREIGN_CONSUMER_SQL),
        )
    ]

    ontology = build_ontology(documents, tables=cards, artifact_root="corpus_a")

    assert [entity["id"] for entity in ontology["entities"]] == [
        card["table"] for card in cards["tables"]
    ]
    assert "external_evidence_tables" not in ontology["corpus"]
    assert "仅作为外部证据参与" not in render_ontology_index_markdown(ontology)


def test_section_8_of_a_card_names_the_corpus_the_proof_came_from() -> None:
    merged = merge_table_cards(_corpus_a(), _corpus_b())
    ontology = _foreign_ontology()

    rendered = render_ontology_table_card_markdown(
        _card(merged, "ods.customer_event"), ontology
    )

    assert "`corpus_a/producer_task/stmt:001`" in rendered


# ------------------------------------------------------------------ the disagreement


def test_producers_that_disagree_across_corpora_are_reported() -> None:
    rival = _cards((("rival_task", RIVAL_PRODUCER_SQL),), "corpus_b")

    merged = merge_table_cards(_corpus_a(), rival)

    card = _card(merged, "mart.customer_daily")
    kinds = {finding["kind"] for finding in card["findings"]}
    assert FINDING_PRODUCER_KEY_CONFLICT in kinds
    conflict = next(
        finding
        for finding in card["findings"]
        if finding["kind"] == FINDING_PRODUCER_KEY_CONFLICT
    )
    assert {item["corpus"] for item in conflict["evidence"]} == {
        "corpus_a",
        "corpus_b",
    }


# --------------------------------------------------------------------- the markdown


def test_a_merged_card_names_the_corpus_in_its_producer_and_consumer_tables() -> None:
    from scope_lineage.render.table_cards import render_table_card_markdown

    merged = merge_table_cards(_corpus_a(), _corpus_b())

    rendered = render_table_card_markdown(_card(merged, "mart.customer_daily"))

    assert "| 语料 | 任务 | 语句 | 写入方式 | 分区 | 更新频率 |" in rendered
    assert "| 语料 | 任务 | 语句 | 角色 | 用到的列 | 怎么用 |" in rendered
    assert "`corpus_a`" in rendered and "`corpus_b`" in rendered


def test_an_unmerged_card_renders_the_table_it_always_rendered() -> None:
    from scope_lineage.render.table_cards import render_table_card_markdown

    rendered = render_table_card_markdown(_card(_corpus_a(), "mart.customer_daily"))

    assert "| 任务 | 语句 | 写入方式 | 分区 | 更新频率 |" in rendered
    assert "语料 |" not in rendered


# -------------------------------------------------------------------------- the CLI


def _write_corpus(root: Path, cases) -> Path:
    for task, sql in cases:
        write_statement_documents(
            parse_scope_lineage(sql, task, schema=SCHEMA), root / task
        )
    return root


def _built(tmp_path: Path, name: str, cases) -> Path:
    corpus = _write_corpus(tmp_path / name, cases)
    out = tmp_path / f"{name}-out"
    assert main(["tables", "--lineage", str(corpus), "--out", str(out)]) == 0
    return out / "tables.json"


def test_merge_mode_writes_the_merged_cards(tmp_path: Path, capsys) -> None:
    first = _built(tmp_path, "a", (("producer_task", PRODUCER_SQL),))
    second = _built(tmp_path, "b", (("foreign_task", FOREIGN_CONSUMER_SQL),))
    out = tmp_path / "merged"

    assert (
        main(
            [
                "tables",
                "--merge",
                str(first),
                "--merge",
                str(second),
                "--out",
                str(out),
            ]
        )
        == 0
    )

    cards = json.loads((out / "tables.json").read_text(encoding="utf-8"))
    assert [item["corpus"] for item in _card(cards, "mart.customer_daily")["produced_by"]] == [
        str(tmp_path / "a")
    ]
    assert len(cards["merged_from"]) == 2
    assert (out / "tables.md").is_file()
    assert (out / "tables" / "mart.customer_daily.md").is_file()
    assert "Merged" in capsys.readouterr().out


def test_merge_mode_folds_in_the_corpus_it_was_given(tmp_path: Path) -> None:
    first = _built(tmp_path, "a", (("producer_task", PRODUCER_SQL),))
    corpus = _write_corpus(tmp_path / "b", (("foreign_task", FOREIGN_CONSUMER_SQL),))
    out = tmp_path / "merged"

    assert (
        main(
            [
                "tables",
                "--lineage",
                str(corpus),
                "--merge",
                str(first),
                "--out",
                str(out),
            ]
        )
        == 0
    )

    cards = json.loads((out / "tables.json").read_text(encoding="utf-8"))
    card = _card(cards, "mart.customer_daily")
    assert [item["task"] for item in card["produced_by"]] == ["producer_task"]
    assert [item["task"] for item in card["consumed_by"]] == ["foreign_task"]
    assert [item["corpus"] for item in cards["merged_from"]] == [
        str(tmp_path / "a"),
        str(tmp_path / "b"),
    ]


def test_merge_rejects_a_file_that_is_not_a_tables_document(
    tmp_path: Path, capsys
) -> None:
    stray = tmp_path / "stray.json"
    stray.write_text('{"doc_format": "glossary-json/1"}\n', encoding="utf-8")

    assert main(["tables", "--merge", str(stray), "--out", str(tmp_path / "out")]) == 1
    assert "--merge" in capsys.readouterr().err


def test_tables_still_requires_one_of_lineage_or_merge(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit):
        main(["tables", "--out", str(tmp_path / "out")])


def test_ontology_accepts_several_tables_documents(tmp_path: Path) -> None:
    first = _built(tmp_path, "a", (("producer_task", PRODUCER_SQL),))
    second = _built(tmp_path, "b", (("foreign_task", FOREIGN_CONSUMER_SQL),))
    corpus = tmp_path / "b"
    out = tmp_path / "ontology"

    assert (
        main(
            [
                "ontology",
                "--lineage",
                str(corpus),
                "--tables",
                str(first),
                "--tables",
                str(second),
                "--out",
                str(out),
            ]
        )
        == 0
    )

    ontology = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    edge = next(
        item
        for item in ontology["relations"]
        if item["to"]["entity"] == "mart.customer_daily"
    )
    assert edge["cardinality"]["tier"] == TIER_PROVEN
    assert [item["corpus"] for item in edge["evidence"] if item.get("corpus")] == [
        str(tmp_path / "a")
    ]
    # Corpus A's own source table lent evidence and is not modelled, so no card for it.
    assert {entity["id"] for entity in ontology["entities"]} == {
        "mart.customer_daily",
        "mart.event_rollup",
        "ods.customer_event",
    }
    assert sorted(path.name for path in (out / "tables").glob("*.md")) == [
        "mart.customer_daily.md",
        "mart.event_rollup.md",
        "ods.customer_event.md",
    ]
    assert ontology["corpus"]["external_evidence_tables"] == 1
