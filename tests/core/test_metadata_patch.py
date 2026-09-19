"""WI-2.6: a confirmed comment written back through ``metadata-patch/1``.

The patch exists so an answer to a 待确认清单 question has somewhere to live when the
team cannot write to the warehouse's catalog. Two commands consume it -- ``parse
--metadata-patch`` (re-parse the corpus) and ``describe --metadata-patch`` (derive the
view again from artifacts already on disk) -- and the pair is only useful if they agree,
so the central test here is that the two produce the SAME ``semantic.json``, byte for
byte. The rest pins what "applied" means: the patch beats the schema, every patched entry
says so (``comment_source`` / ``patch_applied``), a key that matches nothing is reported
rather than dropped, and a run whose patch matches nothing leaves the artifact untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.cli import main
from scope_lineage.metadata.metadata_patch import (
    MetadataPatchError,
    apply_metadata_patch,
    load_metadata_patch,
)


SQL = (
    "INSERT INTO mart.orders\n"
    "SELECT o.order_id, o.pay_status, o.pay_amount\n"
    "FROM ods.app_order o\n"
    "WHERE o.pay_status = 'PAID'\n"
)

SCHEMA = {
    "ods.app_order": {
        "table_name_cn": "APP 订单",
        "columns": [
            {"name": "order_id", "type": "string", "comment": "订单号"},
            {"name": "pay_status", "type": "string", "comment": None},
            {"name": "pay_amount", "type": "decimal(18,2)", "comment": None},
        ],
    }
}

PATCH = {
    "doc_format": "metadata-patch/1",
    "tables": {
        "mart.orders": {
            "table_name_cn": "订单结果表",
            "table_desc": "每个订单一行",
            "confirmed_by": "owner",
            "date": "2026-09-19",
        }
    },
    "columns": {
        "mart.orders.pay_status": {
            "comment": "支付状态（已确认）",
            "confirmed_by": "owner",
            "date": "2026-09-19",
        },
        "ods.app_order.pay_status": {"comment": "上游支付状态（已确认）"},
    },
}


def _write(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _sql(tmp_path: Path) -> Path:
    path = tmp_path / "orders.sql"
    path.write_text(SQL, encoding="utf-8")
    return path


def _parse(tmp_path: Path, out: str, *extra: str) -> Path:
    schema = _write(tmp_path / "schema.json", SCHEMA)
    assert (
        main(
            [
                "parse",
                "--sql-file",
                str(_sql(tmp_path)),
                "--schema",
                str(schema),
                "--out",
                str(tmp_path / out),
                *extra,
            ]
        )
        == 0
    )
    return tmp_path / out / "orders"


def _statement(task_dir: Path) -> dict:
    document = json.loads((task_dir / "lineage.json").read_text(encoding="utf-8"))
    return next(iter(document["statement_lineage"].values()))


def _column(metadata: dict, group: str, table: str, column: str) -> dict:
    details = metadata[group][table]["column_details"]
    return next(item for item in details if item["name"] == column)


def _profile(task_dir: Path) -> dict:
    return json.loads((task_dir / "semantic.json").read_text(encoding="utf-8"))


def _field(profile: dict, column: str) -> dict:
    statement = profile["statements"][0]
    return next(item for item in statement["fields"] if item["column"] == column)


# ------------------------------------------------------------------- the parse path


def test_parse_writes_the_confirmed_comment_and_marks_it_as_a_patch(
    tmp_path: Path,
) -> None:
    patch = _write(tmp_path / "patch.json", PATCH)

    task = _parse(tmp_path, "out", "--metadata-patch", str(patch))

    metadata = _statement(task)["related_metadata"]
    target = _column(metadata, "output_tables", "mart.orders", "pay_status")
    assert target["comment"] == "支付状态（已确认）"
    assert target["comment_source"] == "patch"
    assert metadata["output_tables"]["mart.orders"]["table_metadata"] == {
        "table_name_cn": "订单结果表",
        "table_desc": "每个订单一行",
        "patch_applied": True,
    }


def test_a_patch_beats_the_schema_comment_for_the_same_column(tmp_path: Path) -> None:
    """The schema states what the warehouse recorded; the patch states what is true."""
    patch = _write(
        tmp_path / "patch.json",
        {"columns": {"ods.app_order.order_id": {"comment": "订单号（已确认：APP 侧）"}}},
    )

    task = _parse(tmp_path, "out", "--metadata-patch", str(patch))

    detail = _column(
        _statement(task)["related_metadata"], "input_tables", "ods.app_order", "order_id"
    )
    assert detail["comment"] == "订单号（已确认：APP 侧）"
    assert detail["comment_source"] == "patch"


def test_the_patch_also_reaches_field_usage_through_the_schema_map(
    tmp_path: Path,
) -> None:
    patch = _write(tmp_path / "patch.json", PATCH)

    task = _parse(tmp_path, "out", "--metadata-patch", str(patch))

    statement = _statement(task)
    used = [
        detail
        for scope in statement["scopes"].values()
        for block in scope.get("logic_blocks") or []
        for usage in block.get("field_usage") or []
        for detail in usage.get("used_field_details") or []
        if detail.get("name") == "pay_status"
    ]
    assert used and all(item["comment"] == "上游支付状态（已确认）" for item in used)


def test_the_target_ddl_path_takes_a_column_comment_patch(tmp_path: Path) -> None:
    """The commonest answer of all: the target's own columns, which no export describes."""
    ddl = _write(
        tmp_path / "target" / "mart.orders.json",
        {
            "table_name": "mart.orders",
            "full_table_name": "spark_catalog.mart.orders",
            "schema": [
                {"columnName": "order_id", "columnType": "string", "columnIndex": 0,
                 "isPartition": 0, "comment": "订单号"},
                {"columnName": "pay_status", "columnType": "string", "columnIndex": 1,
                 "isPartition": 0},
                {"columnName": "pay_amount", "columnType": "decimal(18,2)",
                 "columnIndex": 2, "isPartition": 0},
            ],
        },
    )
    patch = _write(tmp_path / "patch.json", PATCH)
    schema = _write(tmp_path / "schema.json", SCHEMA)

    assert (
        main(
            [
                "parse",
                "--sql-file",
                str(_sql(tmp_path)),
                "--schema",
                str(schema),
                "--target-ddl-metadata",
                str(ddl.parent),
                "--metadata-patch",
                str(patch),
                "--out",
                str(tmp_path / "out"),
            ]
        )
        == 0
    )

    metadata = _statement(tmp_path / "out" / "orders")["related_metadata"]
    assert metadata["output_tables"]["mart.orders"]["metadata_source"] == "target_ddl"
    target = _column(metadata, "output_tables", "mart.orders", "pay_status")
    assert (target["comment"], target["comment_source"]) == ("支付状态（已确认）", "patch")
    # The column the DDL did describe keeps the DDL's comment, and says so.
    untouched = _column(metadata, "output_tables", "mart.orders", "order_id")
    assert untouched["comment"] == "订单号" and "comment_source" not in untouched
    assert main(["describe", "--lineage", str(tmp_path / "out" / "orders" / "lineage.json")]) == 0
    profile = _profile(tmp_path / "out" / "orders")
    assert _field(profile, "order_id")["target_comment_source"] == "metadata"
    assert _field(profile, "pay_status")["target_comment_source"] == "patch"


# --------------------------------------------------------- the two paths must agree


def test_describe_applies_the_same_patch_without_re_parsing(tmp_path: Path) -> None:
    patch = _write(tmp_path / "patch.json", PATCH)
    parsed_with_patch = _parse(tmp_path, "with", "--metadata-patch", str(patch))
    parsed_plain = _parse(tmp_path, "plain")

    assert main(["describe", "--lineage", str(parsed_with_patch / "lineage.json")]) == 0
    assert (
        main(
            [
                "describe",
                "--lineage",
                str(parsed_plain / "lineage.json"),
                "--metadata-patch",
                str(patch),
            ]
        )
        == 0
    )

    assert (parsed_plain / "semantic.json").read_text(encoding="utf-8") == (
        parsed_with_patch / "semantic.json"
    ).read_text(encoding="utf-8")
    assert (parsed_plain / "semantic.md").read_text(encoding="utf-8") == (
        parsed_with_patch / "semantic.md"
    ).read_text(encoding="utf-8")


def test_describe_does_not_rewrite_the_artifact_it_derives_from(tmp_path: Path) -> None:
    """A derived view may not edit its own contract, patch or no patch."""
    patch = _write(tmp_path / "patch.json", PATCH)
    task = _parse(tmp_path, "out")
    before = (task / "lineage.json").read_text(encoding="utf-8")

    assert (
        main(
            [
                "describe",
                "--lineage",
                str(task / "lineage.json"),
                "--metadata-patch",
                str(patch),
            ]
        )
        == 0
    )

    assert (task / "lineage.json").read_text(encoding="utf-8") == before


# ----------------------------------------------------------- the derived view's keys


def test_the_profile_sources_every_comment_and_counts_what_was_answered(
    tmp_path: Path,
) -> None:
    patch = _write(tmp_path / "patch.json", PATCH)
    task = _parse(tmp_path, "out", "--metadata-patch", str(patch))
    assert main(["describe", "--lineage", str(task / "lineage.json")]) == 0

    profile = _profile(task)
    statement = profile["statements"][0]
    assert _field(profile, "pay_status")["target_comment_source"] == "patch"
    assert _field(profile, "order_id").get("target_comment_source") is None
    app_order = next(item for item in statement["inputs"] if item["table"] == "ods.app_order")
    assert app_order["comment_source"] == "metadata"
    assert statement["confidence"]["metadata_coverage"]["patch"] == {
        "tables": 1,
        "columns": 2,
    }
    assert statement["confidence"]["confirmations"] == {
        "values_confirmed": 0,
        "terms_confirmed": 0,
        "columns_patched": 2,
        "tables_patched": 1,
    }


def test_a_patched_input_table_comment_is_sourced_to_the_patch(tmp_path: Path) -> None:
    patch = _write(
        tmp_path / "patch.json",
        {"tables": {"ods.app_order": {"table_name_cn": "APP 订单（已确认）"}}},
    )
    task = _parse(tmp_path, "out", "--metadata-patch", str(patch))
    assert main(["describe", "--lineage", str(task / "lineage.json")]) == 0

    entry = next(
        item
        for item in _profile(task)["statements"][0]["inputs"]
        if item["table"] == "ods.app_order"
    )
    assert (entry["comment"], entry["comment_source"]) == ("APP 订单（已确认）", "patch")


def test_without_a_patch_the_profile_reports_no_patch_coverage(tmp_path: Path) -> None:
    task = _parse(tmp_path, "out")
    assert main(["describe", "--lineage", str(task / "lineage.json")]) == 0

    statement = _profile(task)["statements"][0]
    assert "patch" not in statement["confidence"]["metadata_coverage"]
    assert statement["confidence"]["confirmations"] == {
        "values_confirmed": 0,
        "terms_confirmed": 0,
        "columns_patched": 0,
        "tables_patched": 0,
    }
    assert "target_comment_source" not in _field(_profile(task), "order_id")


def test_the_markdown_marks_a_confirmed_comment_as_one(tmp_path: Path) -> None:
    """A reader of semantic.md must see who claims the comment, not just the text."""
    patch = _write(tmp_path / "patch.json", PATCH)
    task = _parse(tmp_path, "out", "--metadata-patch", str(patch))
    assert main(["describe", "--lineage", str(task / "lineage.json")]) == 0

    markdown = (task / "semantic.md").read_text(encoding="utf-8")
    assert "- 目标注释：支付状态（已确认）（人工确认）" in markdown
    assert "- 目标注释：注释未知" in markdown


# ------------------------------------------------------------- unmatched and misuse


def test_an_unmatched_key_is_reported_and_changes_nothing(
    tmp_path: Path, capsys
) -> None:
    patch = _write(
        tmp_path / "patch.json",
        {
            "tables": {"ods.does_not_exist": {"table_name_cn": "不存在"}},
            "columns": {"ods.app_order.no_such_column": {"comment": "不存在"}},
        },
    )
    plain = _parse(tmp_path, "plain")
    capsys.readouterr()

    patched = _parse(tmp_path, "patched", "--metadata-patch", str(patch))
    report = capsys.readouterr().out

    assert "unmatched=2" in report
    assert "ods.does_not_exist" in report and "ods.app_order.no_such_column" in report
    assert (patched / "lineage.json").read_text(encoding="utf-8") == (
        plain / "lineage.json"
    ).read_text(encoding="utf-8")


def test_describe_reports_unmatched_patch_keys_too(tmp_path: Path, capsys) -> None:
    patch = _write(
        tmp_path / "patch.json", {"columns": {"ods.app_order.nope": {"comment": "x"}}}
    )
    task = _parse(tmp_path, "out")
    capsys.readouterr()

    assert (
        main(
            [
                "describe",
                "--lineage",
                str(task / "lineage.json"),
                "--metadata-patch",
                str(patch),
            ]
        )
        == 0
    )

    assert "patch_unmatched=1" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["parse", "describe"])
def test_an_unreadable_patch_file_stops_the_run_with_exit_code_two(
    tmp_path: Path, command: str
) -> None:
    task = _parse(tmp_path, "out")
    missing = str(tmp_path / "nope.json")
    argv = (
        ["parse", "--sql-file", str(_sql(tmp_path)), "--out", str(tmp_path / "again")]
        if command == "parse"
        else ["describe", "--lineage", str(task / "lineage.json")]
    )

    assert main([*argv, "--metadata-patch", missing]) == 2


def test_a_document_declaring_another_format_is_refused(tmp_path: Path) -> None:
    patch = _write(tmp_path / "patch.json", {"doc_format": "glossary-json/1"})
    task = _parse(tmp_path, "out")

    assert (
        main(
            [
                "describe",
                "--lineage",
                str(task / "lineage.json"),
                "--metadata-patch",
                str(patch),
            ]
        )
        == 2
    )


# --------------------------------------------------------------------- the loader


def test_two_patch_files_merge_with_the_later_one_winning(tmp_path: Path) -> None:
    first = _write(
        tmp_path / "a.json",
        {"columns": {"mart.orders.pay_status": {"comment": "第一轮"}},
         "tables": {"mart.orders": {"table_name_cn": "第一轮"}}},
    )
    second = _write(
        tmp_path / "b.json", {"columns": {"mart.orders.pay_status": {"comment": "第二轮"}}}
    )

    patch = load_metadata_patch([str(first), str(second)])

    assert patch.column_comment("mart.orders", "pay_status") == "第二轮"
    assert patch.table_detail("mart.orders")["table_name_cn"] == "第一轮"


def test_the_loader_normalizes_case_and_catalog_qualified_names(tmp_path: Path) -> None:
    patch = load_metadata_patch(
        [
            str(
                _write(
                    tmp_path / "a.json",
                    {"columns": {"MART.Orders.PAY_STATUS": {"comment": "大小写无关"}}},
                )
            )
        ]
    )

    assert patch.column_comment("mart.orders", "pay_status") == "大小写无关"


def test_a_two_part_column_key_is_not_a_column_reference(tmp_path: Path) -> None:
    """``orders.pay_status`` could be a table or a column; guessing would patch a table."""
    patch = load_metadata_patch(
        [str(_write(tmp_path / "a.json", {"columns": {"orders.pay_status": {"comment": "x"}}}))]
    )

    assert not patch


def test_apply_counts_related_metadata_and_mirrors_it_into_field_usage() -> None:
    """One answer, counted once -- field_usage is the same comment seen from a scope."""
    statement = {
        "related_metadata": {
            "input_tables": {
                "ods.app_order": {
                    "column_details": [{"name": "pay_status", "type": None, "comment": None}]
                }
            },
            "output_tables": {},
        },
        "scopes": {
            "ROOT": {
                "field_usage": [
                    {
                        "source_id": "ods.app_order",
                        "source_type": "physical_table",
                        "used_field_details": [
                            {"name": "pay_status", "type": None, "comment": None}
                        ],
                    }
                ]
            }
        },
    }
    patch = load_metadata_patch([])
    patch.columns[("ods.app_order", "pay_status")] = "已确认"

    assert apply_metadata_patch(statement, patch) == {"tables": 0, "columns": 1}
    usage = statement["scopes"]["ROOT"]["field_usage"][0]["used_field_details"][0]
    assert (usage["comment"], usage["comment_source"]) == ("已确认", "patch")


def test_load_metadata_patch_refuses_a_non_object_document(tmp_path: Path) -> None:
    path = _write(tmp_path / "a.json", ["not", "an", "object"])

    with pytest.raises(MetadataPatchError):
        load_metadata_patch([str(path)])
