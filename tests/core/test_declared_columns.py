"""A1: an entity's attributes cover the whole declared table, not only the read subset.

``related_metadata.input_tables[<table>].column_details[]`` is the *used* subset by
design, and everything derived from it inherited that narrowing: a table card listed the
four columns the corpus happened to touch, and the ontology entity built from that card
published four attributes for a table the metadata declares eighty-eight columns wide.
The ontology document already promised the other reading -- "没人读过的列是空列表" -- which
is only true if the unread column is *there* with an empty ``observed_roles``.

So the declared width travels with the used subset, additively and at every layer:

1. the contract gains ``declared_columns[]`` (DDL order, ``used`` per column) beside the
   unchanged ``column_details[]``, and absent -- not empty -- when no metadata described
   the table, because "the catalog does not know this table" and "the catalog says it has
   no columns" are two different statements;
2. a table card's ``columns[]`` is the union, each column marked ``used_in_corpus``, with
   ``coverage.columns_used`` / ``coverage.columns_declared`` saying how much of the table
   the corpus actually exercised;
3. an ontology attribute exists for every declared column, unread ones carrying the empty
   ``observed_roles`` the document always promised.

Every name here is synthetic.
"""

from __future__ import annotations

from scope_lineage.contract import to_lineage_dict
from scope_lineage.metadata.target_table_metadata import (
    TargetColumnMetadata,
    TargetMetadataMap,
    TargetTableMetadata,
)
from scope_lineage.render.ontology import (
    build_ontology,
    render_ontology_index_markdown,
    render_ontology_table_card_markdown,
)
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.render.table_cards import (
    build_table_cards,
    render_table_card_markdown,
)
from scope_lineage.scope.scope_builder import parse_scope_lineage


# A synthetic source table declared eight columns wide, of which the statement below
# reads three. The gap is the whole point: four of the five unread ones carry a comment,
# so a reader who never sees them never learns what the table holds.
WIDE_SCHEMA = {
    "ods.demo_event": {
        "table_alias": "合成事件表",
        "column_details": [
            {"name": "demo_id", "type": "bigint", "comment": "合成主键"},
            {"name": "demo_code", "type": "string", "comment": "合成编码"},
            {"name": "demo_amount", "type": "decimal(18,2)", "comment": "合成金额"},
            {"name": "unused_alpha", "type": "string", "comment": "合成未读列甲"},
            {"name": "unused_beta", "type": "string", "comment": "合成未读列乙"},
            {"name": "unused_gamma", "type": "string", "comment": None},
            {"name": "unused_delta", "type": "int", "comment": "合成未读列丁"},
            {"name": "dt", "type": "string", "comment": "合成分区日"},
        ],
    },
    "mart.demo_summary": {
        "column_details": [
            {"name": "demo_id", "type": "bigint", "comment": "合成主键"},
            {"name": "demo_amount", "type": "decimal(18,2)", "comment": "合成金额"},
            {"name": "never_written", "type": "string", "comment": "合成未写列"},
        ]
    },
}

WIDE_SQL = (
    "INSERT OVERWRITE TABLE mart.demo_summary PARTITION (dt = '20260101') "
    "SELECT e.demo_id AS demo_id, SUM(e.demo_amount) AS demo_amount "
    "FROM ods.demo_event e WHERE e.dt = '20260101' GROUP BY e.demo_id"
)

# No metadata at all: the same statement must publish no `declared_columns` rather than
# an empty one.
BLIND_SQL = (
    "INSERT OVERWRITE TABLE mart.demo_blind "
    "SELECT u.demo_id AS demo_id FROM ods.demo_unknown u"
)


def _document(sql: str = WIDE_SQL, schema=None, task: str = "demo_declared") -> dict:
    return to_lineage_dict(
        parse_scope_lineage(
            sql, task, schema=WIDE_SCHEMA if schema is None else schema
        )
    )


def _input_item(document: dict, table: str = "ods.demo_event") -> dict:
    return document["related_metadata"]["input_tables"][table]


def _output_item(document: dict, table: str = "mart.demo_summary") -> dict:
    return document["related_metadata"]["output_tables"][table]


# ------------------------------------------------------------------- 1. the contract


def test_an_input_table_declares_every_column_the_metadata_knows() -> None:
    item = _input_item(_document())

    assert [column["name"] for column in item["declared_columns"]] == [
        "demo_id",
        "demo_code",
        "demo_amount",
        "unused_alpha",
        "unused_beta",
        "unused_gamma",
        "unused_delta",
        "dt",
    ]
    assert item["table_column_count"] == 8


def test_used_marks_exactly_the_columns_the_used_subset_holds() -> None:
    item = _input_item(_document())

    used = {column["name"] for column in item["column_details"]}
    assert used == {"demo_id", "demo_amount", "dt"}
    assert {
        column["name"] for column in item["declared_columns"] if column["used"]
    } == used
    assert all(
        column["used"] is False
        for column in item["declared_columns"]
        if column["name"] not in used
    )


def test_a_declared_column_carries_the_type_and_comment_the_metadata_gave_it() -> None:
    item = _input_item(_document())

    unread = next(
        column for column in item["declared_columns"] if column["name"] == "unused_alpha"
    )
    assert unread == {
        "name": "unused_alpha",
        "type": "string",
        "comment": "合成未读列甲",
        "used": False,
    }


def test_the_used_subset_itself_is_untouched() -> None:
    """``column_details[]`` is the contract's answer to "what does this task read"."""
    item = _input_item(_document())

    assert item["column_details"] == [
        {"name": "demo_id", "type": "bigint", "comment": "合成主键"},
        {"name": "demo_amount", "type": "decimal(18,2)", "comment": "合成金额"},
        {"name": "dt", "type": "string", "comment": "合成分区日"},
    ]


def test_a_table_no_metadata_describes_declares_nothing_rather_than_an_empty_list() -> None:
    item = _input_item(_document(BLIND_SQL, schema={}), "ods.demo_unknown")

    assert "declared_columns" not in item
    assert "table_column_count" not in item


def test_the_written_target_declares_its_whole_width_too() -> None:
    item = _output_item(_document())

    assert [
        (column["name"], column["used"]) for column in item["declared_columns"]
    ] == [
        ("demo_id", True),
        ("demo_amount", True),
        ("never_written", False),
    ]
    assert [column["name"] for column in item["column_details"]] == [
        "demo_id",
        "demo_amount",
    ]


DDL_SQL = (
    "INSERT OVERWRITE TABLE mart.demo_ddl "
    "SELECT e.demo_id AS demo_id FROM ods.demo_event e"
)


def _target_metadata() -> TargetMetadataMap:
    item = TargetTableMetadata(
        table_name="mart.demo_ddl",
        full_table_name="demo_catalog.mart.demo_ddl",
        columns=[
            TargetColumnMetadata("demo_id", "bigint", 0, False, "合成主键"),
            TargetColumnMetadata("demo_label", "string", 1, False, "合成标签"),
            TargetColumnMetadata("dt", "string", 2, True, "合成分区日"),
        ],
        partition_columns=["dt"],
        ddl="CREATE TABLE mart.demo_ddl(demo_id BIGINT, demo_label STRING, dt STRING)",
        source_file="demo_ddl_metadata.json",
        structure_source="ddl",
    )
    return TargetMetadataMap({item.table_name: item})


def test_the_targets_own_ddl_declares_the_columns_this_statement_does_not_write() -> None:
    result = parse_scope_lineage(
        DDL_SQL,
        "demo_declared_ddl",
        schema={"ods.demo_event": WIDE_SCHEMA["ods.demo_event"]},
        target_metadata=_target_metadata(),
    )
    item = result.related_metadata["output_tables"]["mart.demo_ddl"]

    assert item["metadata_source"] == "target_ddl"
    assert [
        (column["name"], column["used"]) for column in item["declared_columns"]
    ] == [("demo_id", True), ("demo_label", False), ("dt", False)]


# ------------------------------------------------------- 2. the semantic profile input


def test_the_profile_input_carries_the_declared_width_for_the_corpus_to_read() -> None:
    profile = build_semantic_profile(_document())

    item = next(
        entry for entry in profile["inputs"] if entry["table"] == "ods.demo_event"
    )
    assert [column["name"] for column in item["declared_columns"]] == [
        column["name"] for column in _input_item(_document())["declared_columns"]
    ]
    assert [column["name"] for column in item["used_columns"]] == [
        "demo_id",
        "demo_amount",
        "dt",
    ]


# --------------------------------------------------------------------- 3. table cards


def _cards(*documents: dict) -> dict:
    return build_table_cards(
        [build_semantic_profile(document) for document in documents],
        artifact_root="corpus",
    )


def _card(cards: dict, table: str) -> dict:
    return next(card for card in cards["tables"] if card["table"] == table)


def test_a_card_lists_the_columns_nobody_read_in_ddl_order() -> None:
    card = _card(_cards(_document()), "ods.demo_event")

    assert [column["name"] for column in card["columns"]] == [
        "demo_id",
        "demo_code",
        "demo_amount",
        "unused_alpha",
        "unused_beta",
        "unused_gamma",
        "unused_delta",
        "dt",
    ]


def test_an_unread_column_says_so_and_claims_no_usage() -> None:
    card = _card(_cards(_document()), "ods.demo_event")

    unread = next(column for column in card["columns"] if column["name"] == "unused_beta")
    assert unread["used_in_corpus"] is False
    assert unread["consumer_usage_counts"] == {}
    assert unread["produced_summary"] is None
    assert unread["comment"] == "合成未读列乙"

    read = next(column for column in card["columns"] if column["name"] == "demo_id")
    assert read["used_in_corpus"] is True


def test_coverage_counts_the_used_columns_against_the_declared_width() -> None:
    card = _card(_cards(_document()), "ods.demo_event")

    assert card["coverage"]["columns_used"] == 3
    assert card["coverage"]["columns_declared"] == 8


def test_a_table_nothing_declared_leaves_the_declared_count_null() -> None:
    card = _card(_cards(_document(BLIND_SQL, schema={})), "mart.demo_blind")

    assert card["coverage"]["columns_declared"] is None
    assert card["coverage"]["columns_used"] == len(card["columns"])


def test_the_card_markdown_says_how_much_of_the_table_the_corpus_uses() -> None:
    rendered = render_table_card_markdown(_card(_cards(_document()), "ods.demo_event"))

    assert "本语料用到 3/8 个字段" in rendered


def test_a_card_for_an_undeclared_table_keeps_the_line_off() -> None:
    rendered = render_table_card_markdown(
        _card(_cards(_document(BLIND_SQL, schema={})), "mart.demo_blind")
    )

    assert "本语料用到" not in rendered


def test_an_unread_column_is_a_row_with_a_dash_for_its_usage() -> None:
    rendered = render_table_card_markdown(_card(_cards(_document()), "ods.demo_event"))

    row = next(
        line for line in rendered.split("\n") if line.startswith("| `unused_alpha`")
    )
    assert row.endswith("| — |")
    assert "合成未读列甲" in row


WIDE_TABLE = "ods.demo_many"


def _many_column_schema(width: int) -> dict:
    return {
        WIDE_TABLE: {
            "column_details": [
                {"name": f"demo_col_{index:02d}", "type": "string", "comment": None}
                for index in range(width)
            ]
        }
    }


def test_a_long_tail_of_unread_columns_is_grouped_after_the_used_ones() -> None:
    """Twenty-odd unread rows in the middle of the table hide the two that matter."""
    schema = _many_column_schema(30)
    document = _document(
        "INSERT OVERWRITE TABLE mart.demo_many_out "
        f"SELECT m.demo_col_00 AS demo_col_00 FROM {WIDE_TABLE} m",
        schema=schema,
        task="demo_many",
    )

    rendered = render_table_card_markdown(_card(_cards(document), WIDE_TABLE))
    body = rendered.split("## 3. 字段")[1].split("## 4.")[0]
    note = next(line for line in body.split("\n") if "本语料没有读写" in line)

    assert "29" in note
    assert body.index("| `demo_col_00`") < body.index(note)
    assert body.index(note) < body.index("| `demo_col_01`")


# ----------------------------------------------------------------------- 4. ontology


def _ontology(*documents: dict) -> dict:
    profiles = [build_semantic_profile(document) for document in documents]
    return build_ontology(
        documents,
        profiles,
        tables=build_table_cards(profiles, artifact_root="corpus"),
        artifact_root="corpus",
    )


def _entity(ontology: dict, table: str) -> dict:
    return next(item for item in ontology["tables"] if item["id"] == table)


def test_an_entity_has_one_attribute_per_declared_column() -> None:
    entity = _entity(_ontology(_document()), "ods.demo_event")

    assert [attribute["column"] for attribute in entity["attributes"]] == [
        "demo_id",
        "demo_code",
        "demo_amount",
        "unused_alpha",
        "unused_beta",
        "unused_gamma",
        "unused_delta",
        "dt",
    ]


def test_an_unread_attribute_carries_the_empty_observed_roles_the_doc_promises() -> None:
    entity = _entity(_ontology(_document()), "ods.demo_event")

    unread = next(
        item for item in entity["attributes"] if item["column"] == "unused_gamma"
    )
    assert unread["observed_roles"] == []
    assert unread["used_in_corpus"] is False

    read = next(item for item in entity["attributes"] if item["column"] == "demo_id")
    assert read["used_in_corpus"] is True
    assert read["observed_roles"]


def test_the_entity_table_counts_attributes_against_the_used_ones() -> None:
    rendered = render_ontology_index_markdown(_ontology(_document()))

    row = next(
        line
        for line in rendered.split("## 附录：表与证据")[1].split("\n")
        if line.startswith("| [`ods.demo_event`]")
    )
    assert "8（语料用到 3）" in row


def test_the_entity_card_repeats_the_attribute_count_in_its_identity_section() -> None:
    ontology = _ontology(_document())
    cards = _cards(_document())

    rendered = render_ontology_table_card_markdown(
        _card(cards, "ods.demo_event"), ontology
    )
    section = rendered.split("## 7. 身份（本体）")[1].split("## 8.")[0]

    assert "属性 8（语料用到 3）" in section
