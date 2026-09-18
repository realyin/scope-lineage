"""WI-2.5: corpus-level table cards (``tables-json/1``) and their markdown.

A table card is the one place where what a corpus knows about a table stops being
per-task: the producing statement's grain and field summaries meet the consuming
statements' column usages under a single, normalized table name. The tests below pin the
four properties that make the card trustworthy rather than merely informative:

1. **Normalization is by suffix**, the same rule the query helper's ``_same_table`` uses,
   so one logical table written ``spark_catalog.mart.t`` by its writer and ``mart.t`` by
   its readers is one card with one primary name and the other spellings as aliases;
2. **Only physical tables get a card** -- a session-scoped relation and a ``directory:``
   target leave nothing behind for another task to read, so neither is one;
3. **Nothing is invented**: every table and column on a card can be found in one of the
   corpus's own lineage documents, and every finding names the statements it read;
4. **The same corpus builds the same bytes**, because a card is a derived view and a
   derived view that reorders itself cannot be diffed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.contract.task_lineage import to_task_lineage_dict
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.render.table_cards import (
    DOC_FORMAT,
    FINDING_KINDS,
    FINDING_MULTIPLE_PRODUCERS,
    FINDING_NEVER_CONSUMED,
    FINDING_NEVER_PRODUCED,
    FINDING_PRODUCER_KEY_CONFLICT,
    apply_table_cards,
    build_table_cards,
    render_table_card_markdown,
    render_table_index_markdown,
    table_card_filename,
)
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.scope.task_lineage import parse_task_lineage


FIXTURES = Path(__file__).parent / "fixtures"

SCHEMA = {
    "ods.customer_base": ["customer_id", "country_code", "dt"],
    "ods.customer_event": ["customer_id", "event_code", "dt"],
    "mart.customer_daily": ["customer_id", "country_code", "dt"],
    "spark_catalog.mart.customer_daily": ["customer_id", "country_code", "dt"],
}

PRODUCER_SQL = (
    "INSERT OVERWRITE TABLE mart.customer_daily PARTITION (dt = '20250101') "
    "SELECT customer_id, country_code FROM ods.customer_base GROUP BY customer_id, country_code"
)

CONSUMER_SQL = (
    "INSERT OVERWRITE TABLE mart.customer_rollup "
    "SELECT d.country_code, count(1) AS n FROM mart.customer_daily d "
    "JOIN ods.customer_event e ON d.customer_id = e.customer_id "
    "WHERE d.dt = '20250101' GROUP BY d.country_code"
)


def _statement_profile(sql: str, task: str, schema=None) -> dict:
    result = parse_scope_lineage(sql, task, schema=schema if schema is not None else SCHEMA)
    return build_semantic_profile(to_lineage_dict(result))


def _task_profile(sql: str, task: str, schema=None, task_meta=None) -> dict:
    result = parse_task_lineage(
        sql,
        task_name=task,
        schema=schema if schema is not None else SCHEMA,
        task_meta=task_meta,
    )
    return build_semantic_profile(to_task_lineage_dict(result))


def _card(cards: dict, table: str) -> dict:
    return next(item for item in cards["tables"] if item["table"] == table)


def _kinds(card: dict) -> set[str]:
    return {finding["kind"] for finding in card["findings"]}


# ------------------------------------------------------- production / consumption merge


def test_a_table_carries_its_producer_and_its_consumers_on_one_card() -> None:
    cards = build_table_cards(
        [
            _statement_profile(PRODUCER_SQL, "producer_task"),
            _statement_profile(CONSUMER_SQL, "consumer_task"),
        ]
    )

    assert cards["doc_format"] == DOC_FORMAT
    assert cards["corpus"]["task_count"] == 2
    card = _card(cards, "mart.customer_daily")
    assert [item["task"] for item in card["produced_by"]] == ["producer_task"]
    assert [item["task"] for item in card["consumed_by"]] == ["consumer_task"]
    assert card["produced_by"][0]["stmt_kind"] == "INSERT_OVERWRITE"
    assert card["produced_by"][0]["partition"]["columns"] == ["dt"]
    assert card["produced_by"][0]["grain"]["basis"] == "group_by"
    assert card["produced_by"][0]["candidate_keys"] == ["customer_id", "country_code"]
    assert card["coverage"]["producers"] == 1
    assert card["coverage"]["consumers"] == 1
    assert card["kind"] == "physical"


def test_the_producer_entry_carries_that_task_s_field_summaries() -> None:
    cards = build_table_cards([_statement_profile(PRODUCER_SQL, "producer_task")])

    fields = _card(cards, "mart.customer_daily")["produced_by"][0]["fields"]

    assert [field["column"] for field in fields] == ["customer_id", "country_code"]
    assert all(field["summary"] for field in fields)
    assert {field["structural_role"] for field in fields} == {"candidate_key"}


def test_the_consumer_entry_says_which_columns_were_read_and_how() -> None:
    cards = build_table_cards(
        [
            _statement_profile(PRODUCER_SQL, "producer_task"),
            _statement_profile(CONSUMER_SQL, "consumer_task"),
        ]
    )

    consumer = _card(cards, "mart.customer_daily")["consumed_by"][0]
    usages = {item["name"]: item["usages"] for item in consumer["columns"]}

    assert consumer["role_in_task"] == "aggregate_source"
    assert usages["customer_id"] == ["join_key"]
    assert usages["country_code"] == ["group_by", "output"]
    assert usages["dt"] == ["filter", "partition_filter"]
    # a column no logic block touched is not published as a read column
    assert all(item["usages"] for item in consumer["columns"])


def test_columns_are_the_union_of_produced_fields_and_consumed_columns() -> None:
    cards = build_table_cards(
        [
            _statement_profile(PRODUCER_SQL, "producer_task"),
            _statement_profile(CONSUMER_SQL, "consumer_task"),
        ]
    )

    columns = {item["name"]: item for item in _card(cards, "mart.customer_daily")["columns"]}

    # customer_id and country_code are written *and* read; dt is only ever read
    assert set(columns) == {"customer_id", "country_code", "dt"}
    assert columns["customer_id"]["produced_summary"]
    assert columns["dt"]["produced_summary"] is None
    assert columns["customer_id"]["consumer_usage_counts"] == {"join_key": 1}
    assert columns["dt"]["consumer_usage_counts"] == {"filter": 1, "partition_filter": 1}
    # a plain column-name schema proves no type, so the card publishes null rather
    # than a plausible one
    assert columns["country_code"]["type"] is None


def test_usage_counts_add_up_across_several_consuming_tasks() -> None:
    second = CONSUMER_SQL.replace("mart.customer_rollup", "mart.customer_rollup_two")
    cards = build_table_cards(
        [
            _statement_profile(PRODUCER_SQL, "producer_task"),
            _statement_profile(CONSUMER_SQL, "consumer_one"),
            _statement_profile(second, "consumer_two"),
        ]
    )

    columns = {item["name"]: item for item in _card(cards, "mart.customer_daily")["columns"]}

    assert columns["customer_id"]["consumer_usage_counts"] == {"join_key": 2}
    assert _card(cards, "mart.customer_daily")["coverage"]["consumers"] == 2


# --------------------------------------------------------------------- name normalization


def test_one_table_written_and_read_under_two_qualifications_is_one_card() -> None:
    producer = PRODUCER_SQL.replace(
        "mart.customer_daily", "spark_catalog.mart.customer_daily"
    )
    cards = build_table_cards(
        [
            _statement_profile(producer, "producer_task"),
            _statement_profile(CONSUMER_SQL, "consumer_task"),
        ]
    )

    tables = [item["table"] for item in cards["tables"]]

    # the most qualified spelling is the primary name; the other is recorded, not lost
    assert "spark_catalog.mart.customer_daily" in tables
    assert "mart.customer_daily" not in tables
    card = _card(cards, "spark_catalog.mart.customer_daily")
    assert card["aliases"] == ["mart.customer_daily"]
    assert len(card["produced_by"]) == 1
    assert len(card["consumed_by"]) == 1
    assert _kinds(card) == set()


def test_a_table_seen_under_one_spelling_only_has_no_aliases() -> None:
    cards = build_table_cards([_statement_profile(PRODUCER_SQL, "producer_task")])

    assert _card(cards, "mart.customer_daily")["aliases"] == []


# ------------------------------------------------------------------------- what is a table


SESSION_SCOPED_SQL = """
CREATE TEMPORARY VIEW staged AS
SELECT customer_id, country_code FROM ods.customer_base WHERE dt = '20250101';
INSERT OVERWRITE TABLE mart.customer_daily PARTITION (dt = '20250101')
SELECT customer_id, country_code FROM staged;
"""


def test_a_session_scoped_relation_never_becomes_a_table_card() -> None:
    cards = build_table_cards([_task_profile(SESSION_SCOPED_SQL, "staging_task")])

    tables = [item["table"] for item in cards["tables"]]

    assert "mart.customer_daily" in tables
    assert "staged" not in tables
    assert not any("staged" in item["aliases"] for item in cards["tables"])


def test_a_directory_write_never_becomes_a_table_card() -> None:
    sql = (
        "INSERT OVERWRITE DIRECTORY '/warehouse/export/daily' "
        "SELECT customer_id FROM ods.customer_base"
    )
    cards = build_table_cards([_statement_profile(sql, "export_task")])

    tables = [item["table"] for item in cards["tables"]]

    assert tables == ["ods.customer_base"]
    assert not any(table.startswith("directory:") for table in tables)


# -------------------------------------------------------------------------------- findings


def test_two_tasks_writing_one_table_are_reported_as_multiple_producers() -> None:
    other = PRODUCER_SQL.replace("ods.customer_base", "ods.customer_event").replace(
        "country_code", "event_code"
    )
    cards = build_table_cards(
        [
            _statement_profile(PRODUCER_SQL, "writer_one"),
            _statement_profile(other, "writer_two"),
        ]
    )

    card = _card(cards, "mart.customer_daily")

    assert FINDING_MULTIPLE_PRODUCERS in _kinds(card)
    finding = next(
        item for item in card["findings"] if item["kind"] == FINDING_MULTIPLE_PRODUCERS
    )
    assert [item["task"] for item in finding["evidence"]] == ["writer_one", "writer_two"]


def test_producers_that_disagree_about_the_key_are_reported_as_a_conflict() -> None:
    other = (
        "INSERT OVERWRITE TABLE mart.customer_daily PARTITION (dt = '20250101') "
        "SELECT customer_id, country_code FROM ods.customer_base GROUP BY customer_id"
    )
    cards = build_table_cards(
        [
            _statement_profile(PRODUCER_SQL, "writer_one"),
            _statement_profile(other, "writer_two"),
        ]
    )

    card = _card(cards, "mart.customer_daily")

    assert FINDING_PRODUCER_KEY_CONFLICT in _kinds(card)


def test_producers_that_agree_about_the_key_report_no_conflict() -> None:
    other = PRODUCER_SQL.replace("ods.customer_base", "ods.customer_event")
    cards = build_table_cards(
        [
            _statement_profile(PRODUCER_SQL, "writer_one"),
            _statement_profile(other, "writer_two"),
        ]
    )

    card = _card(cards, "mart.customer_daily")

    assert FINDING_MULTIPLE_PRODUCERS in _kinds(card)
    assert FINDING_PRODUCER_KEY_CONFLICT not in _kinds(card)


def test_a_table_nobody_reads_and_a_table_nobody_writes_are_both_reported() -> None:
    cards = build_table_cards([_statement_profile(PRODUCER_SQL, "producer_task")])

    assert _kinds(_card(cards, "mart.customer_daily")) == {FINDING_NEVER_CONSUMED}
    assert _kinds(_card(cards, "ods.customer_base")) == {FINDING_NEVER_PRODUCED}


def test_every_published_finding_kind_is_one_of_the_declared_four() -> None:
    cards = build_table_cards(
        [
            _statement_profile(PRODUCER_SQL, "producer_task"),
            _statement_profile(CONSUMER_SQL, "consumer_task"),
        ]
    )

    for card in cards["tables"]:
        for finding in card["findings"]:
            assert finding["kind"] in FINDING_KINDS
            assert finding["text"]


# ------------------------------------------------------------------------------- coverage


def test_coverage_counts_comments_rather_than_judging_them() -> None:
    cards = build_table_cards(
        [
            _statement_profile(PRODUCER_SQL, "producer_task"),
            _statement_profile(CONSUMER_SQL, "consumer_task"),
        ]
    )

    coverage = _card(cards, "mart.customer_daily")["coverage"]

    # the plain dict schema carries no comments at all: the ratio is 0.0, not absent
    assert coverage["column_comment_ratio"] == 0.0
    assert coverage["table_comment"] is False
    assert coverage["producers"] == 1
    assert coverage["consumers"] == 1


def test_a_commented_column_raises_the_ratio() -> None:
    profile = _statement_profile(PRODUCER_SQL, "producer_task")
    for item in profile["inputs"]:
        for column in item["used_columns"]:
            if column["name"] == "customer_id":
                column["comment"] = "customer id"

    coverage = _card(build_table_cards([profile]), "ods.customer_base")["coverage"]

    # the producer reads two of the table's columns; one of them now carries a comment
    assert coverage["column_comment_ratio"] == 0.5


# -------------------------------------------------------------------------- determinism


def test_the_same_corpus_builds_the_same_bytes() -> None:
    profiles = [
        _statement_profile(CONSUMER_SQL, "consumer_task"),
        _statement_profile(PRODUCER_SQL, "producer_task"),
    ]

    first = build_table_cards(profiles, artifact_root="corpus")
    second = build_table_cards(list(reversed(profiles)), artifact_root="corpus")

    assert json.dumps(first, ensure_ascii=False) == json.dumps(second, ensure_ascii=False)
    assert [item["table"] for item in first["tables"]] == sorted(
        item["table"] for item in first["tables"]
    )


# -------------------------------------------------------- anti-fabrication property test


def _known_tables(document: dict) -> set[str]:
    tables = set()
    for statement in _statements(document):
        tables |= {str(item) for item in statement.get("source_tables") or []}
        if statement.get("target_table"):
            tables.add(str(statement["target_table"]))
    return tables


def _known_columns(document: dict) -> set[str]:
    columns: set[str] = set()
    for statement in _statements(document):
        metadata = statement.get("related_metadata") or {}
        for group in ("input_tables", "output_tables"):
            for item in (metadata.get(group) or {}).values():
                for detail in item.get("column_details") or []:
                    columns.add(str(detail.get("name")))
        for entry in statement.get("end_to_end_lineage") or []:
            columns.add(str(entry.get("column")))
            for source in entry.get("physical_sources") or []:
                columns.add(str(source.get("column")))
        for scope in (statement.get("scopes") or {}).values():
            for output in scope.get("outputs") or []:
                columns.add(str(output.get("name")))
            for column in scope.get("columns") or []:
                columns.add(str(column.get("name")))
    return columns


def _statements(document: dict) -> list[dict]:
    if document.get("schema_version") == "2.0":
        return list((document.get("statement_lineage") or {}).values())
    return [document]


def _assert_no_fabricated_identifiers(cards: dict, documents: list[dict]) -> None:
    tables: set[str] = set()
    columns: set[str] = set()
    tasks: set[str] = set()
    for document in documents:
        tables |= _known_tables(document)
        columns |= _known_columns(document)
        tasks.add(str(document.get("task_id")))
    for card in cards["tables"]:
        for name in [card["table"], *card["aliases"]]:
            assert name in tables, f"table {name!r} is in no source document"
        for column in card["columns"]:
            assert column["name"] in columns, f"column {column['name']!r} is invented"
        for producer in card["produced_by"]:
            assert producer["task"] in tasks
            for field in producer["fields"]:
                assert field["column"] in columns
            for key in [*producer["grain"]["keys"], *producer["candidate_keys"]]:
                assert key in columns, f"key {key!r} is in no source document"
        for consumer in card["consumed_by"]:
            assert consumer["task"] in tasks
            for column in consumer["columns"]:
                assert column["name"] in columns
        for finding in card["findings"]:
            for item in finding["evidence"]:
                assert item["task"] in tasks


def test_the_cards_never_invent_a_table_a_column_or_a_task() -> None:
    documents = [
        to_lineage_dict(parse_scope_lineage(PRODUCER_SQL, "producer_task", schema=SCHEMA)),
        to_lineage_dict(parse_scope_lineage(CONSUMER_SQL, "consumer_task", schema=SCHEMA)),
        to_task_lineage_dict(
            parse_task_lineage(SESSION_SCOPED_SQL, task_name="staging_task", schema=SCHEMA)
        ),
    ]
    cards = build_table_cards([build_semantic_profile(document) for document in documents])

    _assert_no_fabricated_identifiers(cards, documents)


# ------------------------------------------------------------------------------- markdown


def test_a_table_card_renders_the_six_fixed_sections() -> None:
    cards = build_table_cards(
        [
            _statement_profile(PRODUCER_SQL, "producer_task"),
            _statement_profile(CONSUMER_SQL, "consumer_task"),
        ]
    )

    markdown = render_table_card_markdown(_card(cards, "mart.customer_daily"))

    for heading in (
        "## 1. 这张表是什么",
        "## 2. 一行代表什么",
        "## 3. 字段",
        "## 4. 谁生产",
        "## 5. 谁消费",
        "## 6. 治理线索",
    ):
        assert heading in markdown
    assert markdown.startswith("---\n")
    assert 'doc_format: "tables-md/1"' in markdown
    assert "producer_task" in markdown and "consumer_task" in markdown
    assert markdown.endswith("\n")


def test_a_card_without_a_table_comment_says_so_rather_than_inventing_one() -> None:
    cards = build_table_cards([_statement_profile(PRODUCER_SQL, "producer_task")])

    markdown = render_table_card_markdown(_card(cards, "mart.customer_daily"))

    assert "表注释：未知（元数据事实）" in markdown


def test_the_index_lists_every_table_with_its_counts() -> None:
    cards = build_table_cards(
        [
            _statement_profile(PRODUCER_SQL, "producer_task"),
            _statement_profile(CONSUMER_SQL, "consumer_task"),
        ]
    )

    markdown = render_table_index_markdown(cards)

    assert "| 表 | 生产任务数 | 消费任务数 | 表注释 | 业务域 | 键置信 |" in markdown
    for card in cards["tables"]:
        assert f"`{card['table']}`" in markdown


def test_the_card_filename_is_safe_for_a_directory_listing() -> None:
    assert table_card_filename("mart.customer_daily") == "mart.customer_daily.md"
    assert table_card_filename("spark_catalog.mart.t") == "spark_catalog.mart.t.md"
    assert table_card_filename("a/b c") == "a_b_c.md"


# ------------------------------------------------------------------ describe consumption


def test_describe_attaches_the_upstream_card_to_the_input_table() -> None:
    cards = build_table_cards(
        [
            _statement_profile(PRODUCER_SQL, "producer_task"),
            _statement_profile(CONSUMER_SQL, "consumer_task"),
        ]
    )
    profile = _statement_profile(CONSUMER_SQL, "consumer_task")

    enriched = apply_table_cards(profile, cards)

    inputs = {item["table"]: item for item in enriched["inputs"]}
    card = inputs["mart.customer_daily"]["card"]
    assert card["produced_by_task"] == "producer_task"
    assert card["candidate_keys"] == ["customer_id", "country_code"]
    assert card["key_confidence"] == "proven"
    assert "customer_id" in card["grain_text"]
    # a table no task in the corpus produces has no card, and says so with null
    assert inputs["ods.customer_event"]["card"] is None


def test_describe_lists_the_downstream_consumers_of_the_target_table() -> None:
    cards = build_table_cards(
        [
            _statement_profile(PRODUCER_SQL, "producer_task"),
            _statement_profile(CONSUMER_SQL, "consumer_task"),
        ]
    )
    profile = _statement_profile(PRODUCER_SQL, "producer_task")

    enriched = apply_table_cards(profile, cards)

    consumers = enriched["task"]["downstream_consumers"]
    assert [item["task"] for item in consumers] == ["consumer_task"]
    assert consumers[0]["role_in_task"] == "aggregate_source"
    assert "customer_id" in consumers[0]["columns"]


def test_describe_counts_how_much_of_the_input_side_a_card_could_answer() -> None:
    cards = build_table_cards(
        [
            _statement_profile(PRODUCER_SQL, "producer_task"),
            _statement_profile(CONSUMER_SQL, "consumer_task"),
        ]
    )

    enriched = apply_table_cards(_statement_profile(CONSUMER_SQL, "consumer_task"), cards)

    counts = enriched["confidence"]["metadata_coverage"]["table_cards"]
    assert counts == {"inputs_with_card": 1, "inputs_total": 2, "consumers": 0}


def test_a_task_profile_is_enriched_statement_by_statement() -> None:
    cards = build_table_cards(
        [
            _task_profile(SESSION_SCOPED_SQL, "staging_task"),
            _statement_profile(CONSUMER_SQL, "consumer_task"),
        ]
    )

    enriched = apply_table_cards(_task_profile(SESSION_SCOPED_SQL, "staging_task"), cards)

    statement = enriched["statements"][-1]
    assert [item["task"] for item in statement["task"]["downstream_consumers"]] == [
        "consumer_task"
    ]


def test_without_cards_the_profile_is_returned_unchanged() -> None:
    profile = _statement_profile(CONSUMER_SQL, "consumer_task")

    assert apply_table_cards(profile, None) == profile
    assert "card" not in profile["inputs"][0]


# ----------------------------------------------------------------------- golden corpus


GOLDEN_DIR = FIXTURES / "tables"
# One corpus assembled from cases the contract baseline already keeps green: two
# spellings of the contract (1.0 statement documents and a 2.0 task document), a
# directory write that must not become a table, and one table two cases both produce.
GOLDEN_CASES = (
    ("lineage_contract", "commented_insert"),
    ("lineage_contract", "directory_target"),
    ("lineage_contract", "grouped_dedup_join"),
    ("lineage_contract", "simple_insert"),
    ("task_lineage_contract", "commented_task"),
)


def _golden_corpus_profiles() -> list[dict]:
    profiles = []
    for group, name in GOLDEN_CASES:
        case = FIXTURES / group / name
        lineage = json.loads((case / "lineage.json").read_text(encoding="utf-8"))
        diagnostics = json.loads((case / "diagnostics.json").read_text(encoding="utf-8"))
        profiles.append(build_semantic_profile(lineage, diagnostics))
    return profiles


def test_golden_corpus_tables_json_matches_the_baseline() -> None:
    cards = build_table_cards(_golden_corpus_profiles(), artifact_root="corpus")

    expected = json.loads((GOLDEN_DIR / "tables.json").read_text(encoding="utf-8"))

    assert cards == expected


GOLDEN_TABLES = tuple(
    sorted(path.name[: -len(".md")] for path in (GOLDEN_DIR / "tables").glob("*.md"))
)


@pytest.mark.parametrize("table", GOLDEN_TABLES, ids=lambda name: name)
def test_golden_table_cards_match_the_baseline(table: str) -> None:
    cards = build_table_cards(_golden_corpus_profiles(), artifact_root="corpus")

    rendered = render_table_card_markdown(_card(cards, table))

    expected = (GOLDEN_DIR / "tables" / table_card_filename(table)).read_text(
        encoding="utf-8"
    )
    assert rendered == expected


def test_the_golden_directory_holds_one_card_per_table_and_no_stragglers() -> None:
    cards = build_table_cards(_golden_corpus_profiles(), artifact_root="corpus")

    assert GOLDEN_TABLES == tuple(card["table"] for card in cards["tables"])


def test_golden_index_matches_the_baseline() -> None:
    cards = build_table_cards(_golden_corpus_profiles(), artifact_root="corpus")

    rendered = render_table_index_markdown(cards)

    assert rendered == (GOLDEN_DIR / "tables.md").read_text(encoding="utf-8")


def test_the_golden_corpus_exercises_the_shapes_the_cards_exist_for() -> None:
    cards = build_table_cards(_golden_corpus_profiles(), artifact_root="corpus")

    kinds = {finding["kind"] for card in cards["tables"] for finding in card["findings"]}
    tables = [card["table"] for card in cards["tables"]]

    assert FINDING_MULTIPLE_PRODUCERS in kinds
    assert FINDING_NEVER_CONSUMED in kinds
    assert FINDING_NEVER_PRODUCED in kinds
    assert not any(table.startswith("directory:") for table in tables)
    assert len(_card(cards, "mart.channel_summary")["produced_by"]) == 2
