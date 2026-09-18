"""WI-2.5b: table-level metadata travels from rich JSON to the contract, semantic and cards.

Column metadata already reached every artifact; the table's own identity (its Chinese name,
what it is for, which business domain and project own it) was normalized by
``_normalize_table_detail`` and then dropped, because nothing called it for a rich JSON
document. A profile that cannot say what a table *is* leaves every downstream reader
guessing from the table name.

The privacy rule is part of the contract, not an aside: the export carries a contact email
under ``tbl_pic``, and no artifact may republish it. The exclusion is pinned here by value
(any ``@``-bearing value is refused, whatever key it arrives under), not only by key name.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.metadata.schema_metadata import (
    load_schema,
    load_schema_sources,
    normalize_schema_map,
    table_details_for_table,
)
from scope_lineage.metadata.target_table_metadata import load_target_table_metadata
from scope_lineage.render.semantic_markdown import render_semantic_markdown
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.render.table_cards import (
    build_table_cards,
    render_table_card_markdown,
    render_table_index_markdown,
)
from scope_lineage.scope.related_metadata import build_related_metadata
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.contract import to_lineage_dict

from .statement_document import build_statement_documents


RICH_DOCUMENT = {
    "table_name": "ods.customer_base",
    "full_table_name": "cat.ods.customer_base",
    "table_alias": "客户基础表",
    "table_desc": "客户主数据明细",
    "buzi_domain": "客户域",
    "buzi_domain_tree_names": "零售/客户域",
    "project_name": "客户画像",
    "project_code": "CP",
    "owner_name": "zhangsan",
    "data_level": "ODS",
    "table_physical_type": "MANAGED",
    "is_partition": 1,
    "tbl_pic": "someone@example.invalid",
    "column_comment_rate": 0.5,
    "query_time": "2026-08-15 10:00:00",
    "schema": [
        {
            "columnName": "customer_id",
            "columnType": "bigint",
            "columnComment": "客户号",
            "columnIndex": 0,
            "isPartition": 0,
        },
        {
            "columnName": "dt",
            "columnType": "string",
            "columnComment": "分区日期",
            "columnIndex": 1,
            "isPartition": 1,
        },
    ],
    "ddl": (
        "CREATE TABLE cat.ods.customer_base (customer_id BIGINT) "
        "USING iceberg PARTITIONED BY (dt STRING)"
    ),
}


def _write_rich(directory: Path, document: dict, name: str | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (name or f"{document['table_name']}_metadata.json")
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- loader


def test_rich_json_table_level_fields_reach_table_details(tmp_path: Path) -> None:
    path = _write_rich(tmp_path / "meta", RICH_DOCUMENT)

    detail = table_details_for_table(load_schema(str(path)), "ods.customer_base")

    assert detail == {
        "table_name_cn": "客户基础表",
        "table_desc": "客户主数据明细",
        "domain": "客户域",
        "domain_path": "零售/客户域",
        "project": "客户画像",
        "project_code": "CP",
        "owner": "zhangsan",
        "table_label_layer": "ODS",
        "physical_type": "MANAGED",
        "is_partitioned": True,
    }


def test_a_rich_json_directory_carries_the_same_table_details(tmp_path: Path) -> None:
    _write_rich(tmp_path / "meta", RICH_DOCUMENT)

    detail = table_details_for_table(
        load_schema(str(tmp_path / "meta")), "ods.customer_base"
    )

    assert detail["table_name_cn"] == "客户基础表"
    assert detail["domain"] == "客户域"


def test_the_contact_email_and_its_key_never_enter_table_details(tmp_path: Path) -> None:
    document = dict(RICH_DOCUMENT, owner_name="owner@example.invalid")
    path = _write_rich(tmp_path / "meta", document)

    detail = table_details_for_table(load_schema(str(path)), "ods.customer_base")

    assert "tbl_pic" not in detail
    assert "owner" not in detail
    assert not any("@" in str(value) for value in detail.values())


def test_timestamp_and_rate_keys_are_not_table_facts(tmp_path: Path) -> None:
    path = _write_rich(tmp_path / "meta", RICH_DOCUMENT)

    detail = table_details_for_table(load_schema(str(path)), "ods.customer_base")

    assert "query_time" not in detail
    assert "column_comment_rate" not in detail


def test_is_partition_zero_is_a_false_fact_not_an_absent_one(tmp_path: Path) -> None:
    path = _write_rich(tmp_path / "meta", dict(RICH_DOCUMENT, is_partition=0))

    detail = table_details_for_table(load_schema(str(path)), "ods.customer_base")

    assert detail["is_partitioned"] is False


def test_lightweight_json_table_keys_are_normalized_the_same_way(tmp_path: Path) -> None:
    path = tmp_path / "light.json"
    path.write_text(
        json.dumps(
            {
                "tables": [
                    {
                        "table_name": "ods.channel_event",
                        "table_desc": "渠道事件",
                        "domain": "渠道域",
                        "columns": [{"name": "channel_code", "type": "string"}],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    detail = table_details_for_table(load_schema(str(path)), "ods.channel_event")

    assert detail == {"table_desc": "渠道事件", "domain": "渠道域"}


def test_an_inline_schema_mapping_keeps_its_table_level_keys() -> None:
    schema = normalize_schema_map(
        {
            "ods.channel_event": {
                "table_desc": "渠道事件",
                "buzi_domain": "渠道域",
                "column_details": [{"name": "channel_code"}],
            }
        }
    )

    assert schema["ods.channel_event"] == ["channel_code"]
    assert table_details_for_table(schema, "ods.channel_event") == {
        "table_desc": "渠道事件",
        "domain": "渠道域",
    }


def test_csv_schema_loading_is_unaffected(tmp_path: Path) -> None:
    path = tmp_path / "schema.csv"
    path.write_text(
        "table_name,column_name,column_type,column_comment\n"
        "ods.channel_event,channel_code,string,渠道编码\n",
        encoding="utf-8",
    )

    schema = load_schema(str(path))

    assert schema["ods.channel_event"] == ["channel_code"]
    assert table_details_for_table(schema, "ods.channel_event") == {}


def test_fallback_fills_table_facts_the_authoritative_source_lacks(tmp_path: Path) -> None:
    authoritative = _write_rich(
        tmp_path / "a",
        {
            "table_name": "ods.customer_base",
            "table_desc": "权威描述",
            "schema": [
                {
                    "columnName": "customer_id",
                    "columnType": "bigint",
                    "columnIndex": 0,
                    "isPartition": 0,
                }
            ],
        },
    )
    fallback = _write_rich(
        tmp_path / "b",
        {
            "table_name": "ods.customer_base",
            "table_desc": "候补描述",
            "buzi_domain": "客户域",
            "schema": [
                {
                    "columnName": "customer_id",
                    "columnType": "bigint",
                    "columnIndex": 0,
                    "isPartition": 0,
                }
            ],
        },
    )

    schema = load_schema_sources([str(authoritative), str(fallback)])

    detail = table_details_for_table(schema, "ods.customer_base")
    assert detail["table_desc"] == "权威描述"
    assert detail["domain"] == "客户域"


def test_a_table_only_the_fallback_knows_brings_its_table_facts(tmp_path: Path) -> None:
    authoritative = _write_rich(tmp_path / "a", RICH_DOCUMENT)
    fallback = _write_rich(
        tmp_path / "b",
        {
            "table_name": "dim.channel",
            "table_desc": "渠道维表",
            "schema": [
                {
                    "columnName": "channel_code",
                    "columnType": "string",
                    "columnIndex": 0,
                    "isPartition": 0,
                }
            ],
        },
    )

    schema = load_schema_sources([str(authoritative), str(fallback)])

    assert table_details_for_table(schema, "dim.channel") == {"table_desc": "渠道维表"}


# ------------------------------------------------------------------ target DDL export


def test_target_table_metadata_carries_the_table_detail(tmp_path: Path) -> None:
    _write_rich(tmp_path / "meta", RICH_DOCUMENT)

    metadata = load_target_table_metadata(str(tmp_path / "meta"))

    assert metadata["ods.customer_base"].table_detail["table_name_cn"] == "客户基础表"
    assert metadata["ods.customer_base"].table_detail["project"] == "客户画像"


# ---------------------------------------------------------------- related_metadata


def _profile(sql: str, task_id: str, schema) -> dict:
    return build_semantic_profile(
        to_lineage_dict(parse_scope_lineage(sql, task_id, schema=schema))
    )


_SQL = (
    "INSERT OVERWRITE TABLE mart.customer_summary "
    "SELECT customer_id FROM ods.customer_base WHERE dt = '${bizdate}'"
)

_SCHEMA = {
    "ods.customer_base": {
        "table_desc": "客户主数据明细",
        "table_alias": "客户基础表",
        "buzi_domain": "客户域",
        "project_name": "客户画像",
        "owner_name": "zhangsan",
        "data_level": "ODS",
        "column_details": [{"name": "customer_id"}, {"name": "dt"}],
    },
    "mart.customer_summary": {
        "table_alias": "客户汇总表",
        "buzi_domain": "客户域",
        "project_name": "客户画像",
        "owner_name": "lisi",
        "column_details": [{"name": "customer_id"}],
    },
}


def test_related_metadata_publishes_table_level_facts_on_both_sides() -> None:
    schema = normalize_schema_map(_SCHEMA)
    result = parse_scope_lineage(_SQL, "wi25b", schema=schema)

    related = build_related_metadata(result, schema)

    assert related["input_tables"]["ods.customer_base"]["table_metadata"]["domain"] == "客户域"
    assert (
        related["output_tables"]["mart.customer_summary"]["table_metadata"]["table_name_cn"]
        == "客户汇总表"
    )


def test_target_ddl_table_detail_merges_the_export_facts(tmp_path: Path) -> None:
    _write_rich(
        tmp_path / "meta",
        dict(
            RICH_DOCUMENT,
            table_name="mart.customer_summary",
            full_table_name="cat.mart.customer_summary",
            schema=[
                {
                    "columnName": "customer_id",
                    "columnType": "bigint",
                    "columnComment": "客户号",
                    "columnIndex": 0,
                    "isPartition": 0,
                }
            ],
            ddl="CREATE TABLE cat.mart.customer_summary (customer_id BIGINT) USING iceberg",
        ),
    )
    target = load_target_table_metadata(str(tmp_path / "meta"))
    schema = normalize_schema_map({"ods.customer_base": ["customer_id", "dt"]})
    result = parse_scope_lineage(
        _SQL, "wi25b_ddl", schema=schema, target_metadata=target
    )

    related = build_related_metadata(
        result, schema, target.get("mart.customer_summary")
    )

    table_metadata = related["output_tables"]["mart.customer_summary"]["table_metadata"]
    assert table_metadata["table_name_cn"] == "客户基础表"
    assert table_metadata["structure_source"] == "ddl"
    assert not any("@" in str(value) for value in table_metadata.values())


# ------------------------------------------------------------------------- semantic


def test_semantic_inputs_and_task_carry_the_table_facts() -> None:
    profile = _profile(_SQL, "wi25b_semantic", _SCHEMA)

    source = profile["inputs"][0]
    assert source["comment"] == "客户基础表"
    assert source["domain"] == "客户域"
    assert source["project"] == "客户画像"
    assert source["owner"] == "zhangsan"
    assert source["layer"] == "ODS"
    assert profile["task"]["target_table_comment"] == "客户汇总表"
    assert profile["task"]["target_table_domain"] == "客户域"
    assert profile["task"]["target_table_project"] == "客户画像"
    assert profile["task"]["target_table_owner"] == "lisi"


def test_table_facts_are_null_rather_than_absent_when_unknown() -> None:
    profile = _profile(_SQL, "wi25b_null", {"ods.customer_base": ["customer_id", "dt"]})

    source = profile["inputs"][0]
    assert source["domain"] is None and source["project"] is None
    assert source["owner"] is None and source["layer"] is None
    assert profile["task"]["target_table_domain"] is None


def test_the_table_comment_key_order_prefers_the_chinese_name() -> None:
    schema = {
        "ods.customer_base": {
            "table_alias": "客户基础表",
            "table_desc": "客户主数据明细",
            "column_details": [{"name": "customer_id"}, {"name": "dt"}],
        }
    }

    profile = _profile(_SQL, "wi25b_order", schema)

    assert profile["inputs"][0]["comment"] == "客户基础表"


def test_the_markdown_overview_names_the_domain_and_project() -> None:
    profile = _profile(_SQL, "wi25b_md", _SCHEMA)

    rendered = render_semantic_markdown(profile, sections=["overview"])

    assert "表注释：客户汇总表" in rendered
    assert "业务域 客户域" in rendered
    assert "项目 客户画像" in rendered


def test_the_inputs_table_can_now_fill_its_comment_column() -> None:
    profile = _profile(_SQL, "wi25b_inputs_md", _SCHEMA)

    rendered = render_semantic_markdown(profile, sections=["overview"])

    row = next(
        line for line in rendered.splitlines() if "`ods.customer_base`" in line and "|" in line
    )
    assert "客户基础表" in row


def test_a_source_note_falls_back_to_the_table_comment() -> None:
    schema = {
        "ods.customer_base": {
            "table_desc": "客户主数据明细",
            "column_details": [{"name": "customer_id"}, {"name": "dt"}],
        }
    }

    profile = _profile(_SQL, "wi25b_note", schema)

    summaries = [field.get("summary") or "" for field in profile["fields"]]
    assert any("客户主数据明细" in text for text in summaries)


# ----------------------------------------------------------------------- table cards


def test_table_cards_carry_the_table_facts_and_real_comment_coverage() -> None:
    cards = build_table_cards([_profile(_SQL, "wi25b_cards", _SCHEMA)], artifact_root=None)

    target = next(card for card in cards["tables"] if card["table"] == "mart.customer_summary")
    source = next(card for card in cards["tables"] if card["table"] == "ods.customer_base")
    assert target["comment"] == "客户汇总表"
    assert target["domain"] == "客户域"
    assert target["owner"] == "lisi"
    assert target["coverage"]["table_comment"] is True
    assert source["comment"] == "客户基础表"
    assert source["layer"] == "ODS"
    assert source["coverage"]["table_comment"] is True


def test_a_table_without_metadata_still_reports_no_comment_coverage() -> None:
    profile = _profile(_SQL, "wi25b_cards_bare", {"ods.customer_base": ["customer_id", "dt"]})

    cards = build_table_cards([profile], artifact_root=None)

    assert all(card["coverage"]["table_comment"] is False for card in cards["tables"])
    assert all(card["domain"] is None for card in cards["tables"])


def test_the_card_index_shows_the_business_domain() -> None:
    cards = build_table_cards([_profile(_SQL, "wi25b_index", _SCHEMA)], artifact_root=None)

    rendered = render_table_index_markdown(cards)

    assert "| 表 | 生产任务数 | 消费任务数 | 表注释 | 业务域 | 键置信 |" in rendered
    assert "客户域" in rendered


def test_the_card_identity_section_names_the_business_owner() -> None:
    cards = build_table_cards([_profile(_SQL, "wi25b_identity", _SCHEMA)], artifact_root=None)

    card = next(item for item in cards["tables"] if item["table"] == "ods.customer_base")
    rendered = render_table_card_markdown(card)

    assert "- 表注释：客户基础表" in rendered
    assert "业务域 客户域" in rendered
    assert "负责人 zhangsan" in rendered


# ----------------------------------------------------------------------- statement IO


def test_the_statement_document_keeps_table_metadata(tmp_path: Path) -> None:
    result = parse_scope_lineage(_SQL, "wi25b_doc", schema=_SCHEMA)

    lineage_data, _ = build_statement_documents(result)

    related = lineage_data["related_metadata"]
    assert related["input_tables"]["ods.customer_base"]["table_metadata"]["project"] == "客户画像"


@pytest.mark.parametrize("value", ["a@b.invalid", " x@y ", "名字<a@b>"])
def test_any_email_bearing_value_is_refused_whatever_key_carries_it(value: str) -> None:
    schema = normalize_schema_map(
        {"ods.t": {"table_desc": value, "column_details": [{"name": "c"}]}}
    )

    assert table_details_for_table(schema, "ods.t") == {}


def test_the_golden_case_bait_address_reaches_no_recorded_artifact() -> None:
    """`commented_insert`'s schema carries a `tbl_pic` address; the fixtures must not.

    The unit tests above pin the rule at the normalizer. This one pins the consequence in
    the bytes a reader actually receives, which is where a regression would be noticed too
    late.
    """
    case_dir = Path(__file__).parent / "fixtures" / "lineage_contract" / "commented_insert"
    assert "demo_owner@example.invalid" in (case_dir / "case.json").read_text(encoding="utf-8")

    for name in ("lineage.json", "diagnostics.json", "mapping.md", "semantic.json", "semantic.md"):
        assert "demo_owner@example.invalid" not in (case_dir / name).read_text(encoding="utf-8")
