"""``semantic packet``: one material packet per target table, for a model to write from.

The packet is the deterministic half of table semantics: the target table's metadata,
every producing task with its SQL, the input tables and the lineage facts the semantic
profile already derives. Nothing in it may name an owner or carry an email address --
it is handed to a model.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from .table_semantics_demo import (
    DEMO_TABLE,
    copy_corpus,
    demo_packets,
    pack,
    packet_of,
    parse_corpus,
    read_json,
    write_json,
)

PRODUCED = {
    "demo_ads.ads_collection_overdue_loan_df",
    "demo_ads.ads_loan_status_span_df",
    "demo_dwd.dwd_lending_borrower_df",
    "demo_dwd.dwd_lending_loan_df",
    "demo_dwd.dwd_lending_repayment_di",
    "demo_dwd.dwd_party_account_map_df",
    "demo_dwd.dwd_party_customer_info_df",
    "demo_dws.dws_lending_loan_summary_1d",
}


@pytest.fixture(scope="module")
def packets(tmp_path_factory) -> Path:
    return demo_packets(tmp_path_factory.mktemp("demo"))


@pytest.fixture(scope="module")
def customer(packets: Path) -> dict:
    return packet_of(packets)


def test_every_produced_table_gets_a_readable_and_a_structured_packet(packets: Path) -> None:
    assert {path.name for path in packets.iterdir() if path.is_dir()} == PRODUCED
    for table in PRODUCED:
        assert (packets / table / "packet.md").is_file()
        assert read_json(packets / table / "packet.json")["table"] == table


def test_a_catalog_prefixed_target_is_packed_under_its_db_table_name(packets: Path) -> None:
    loan = packet_of(packets, "demo_dwd.dwd_lending_loan_df")
    assert loan["table"] == "demo_dwd.dwd_lending_loan_df"
    assert [task["name"] for task in loan["tasks"]] == ["dwd_lending_loan_daily"]


def test_the_target_table_carries_its_comment_and_every_column_in_table_order(
    customer: dict,
) -> None:
    target = customer["target"]
    assert target["comment"] == "Customer master, one row per customer"
    assert target["metadata_source"] == "schema"
    assert [column["name"] for column in target["columns"]] == [
        "customer_id", "verified_customer_no", "gender_cd", "register_time",
        "verify_status", "etl_time", "dt",
    ]
    assert target["columns"][2]["comment"] == "Gender code"
    assert [c["name"] for c in target["columns"] if c["partition"]] == ["dt"]


def test_each_producing_task_brings_its_facts_and_its_sql(customer: dict) -> None:
    (task,) = customer["tasks"]
    assert task["name"] == "dwd_party_customer_info_daily"
    assert task["description"] == "Keep the latest registration record per customer."
    assert task["schedule_cycle"] == "day"
    assert task["statements"] == ["stmt:001"]
    assert "ROW_NUMBER() OVER (PARTITION BY cust_no ORDER BY update_ts DESC)" in task["sql"]
    assert "-- F 女, M 男, U 未知" in task["sql"]
    assert task["header_comments"] == ["客户主表：每个客户号保留最新一条注册记录"]


def test_input_tables_carry_their_metadata_and_how_the_task_reads_them(
    customer: dict,
) -> None:
    (source,) = customer["inputs"]
    assert source["table"] == "demo_ods.ods_core_customer_df"
    assert source["comment"] == "Customer registrations as the core system exports them"
    assert source["driving"] is True
    assert "dedup_source" in source["roles"]
    by_name = {column["name"]: column for column in source["columns"]}
    assert by_name["gender"]["comment"] == "Gender code"
    assert by_name["update_ts"]["used"] is True
    # Time facts for check 9: one partition read by equality, a full-snapshot name.
    assert source["partition_read"] == "equality"
    assert source["name_convention"] == "full"
    assert source["full_snapshot"] is True
    assert source["date_filters"] == []


def test_a_partition_range_read_is_not_a_full_snapshot(packets: Path) -> None:
    loan = packet_of(packets, "demo_dwd.dwd_lending_loan_df")
    penalty = next(i for i in loan["inputs"] if i["table"] == "demo_ods.ods_loan_penalty_di")
    assert (penalty["partition_read"], penalty["name_convention"]) == ("range", "incremental")
    assert penalty["full_snapshot"] is False


def test_lineage_facts_come_from_the_semantic_profile(customer: dict) -> None:
    lineage = customer["lineage"]
    columns = {entry["column"]: entry for entry in lineage["columns"]}
    assert list(columns) == [c["name"] for c in customer["target"]["columns"]]
    (producer,) = columns["customer_id"]["producers"]
    assert producer["sources"] == ["demo_ods.ods_core_customer_df.cust_no"]
    assert producer["task"] == "dwd_party_customer_info_daily"
    assert columns["dt"]["producers"] == []
    assert any("FROM_UNIXTIME" in step for step in columns["register_time"]["producers"][0]["steps"])
    rn = [rule for rule in lineage["rules"] if rule["kind"] == "filter" and not rule["partition_filter"]]
    assert [rule["expression"] for rule in rn] == ["`latest`.`rn` = 1"]
    assert any(rule["kind"] == "dedup" for rule in lineage["rules"])
    (key,) = lineage["keys"]
    assert (key["key_confidence"], key["candidate_keys"], key["proven"]) == (
        "proven", ["customer_id"], True,
    )
    assert lineage["upstream_tables"] == ["demo_ods.ods_core_customer_df"]


def test_downstream_names_the_consuming_tasks_and_the_tables_they_write(customer: dict) -> None:
    downstream = {entry["task"]: entry for entry in customer["lineage"]["downstream"]}
    assert set(downstream) == {"dwd_lending_borrower_daily", "dws_lending_loan_summary_daily"}
    assert downstream["dwd_lending_borrower_daily"]["tables"] == ["demo_dwd.dwd_lending_borrower_df"]


def test_the_markdown_packet_has_every_section_and_the_sql(packets: Path, customer: dict) -> None:
    text = (packets / DEMO_TABLE / "packet.md").read_text(encoding="utf-8")
    for heading in ("## 1. 目标表", "## 2. 生产任务", "## 3. 输入表", "## 4. 血缘事实"):
        assert heading in text
    assert f"`{customer['packet_digest']}`" in text
    assert "```sql\n-- 客户主表：每个客户号保留最新一条注册记录" in text
    assert "`demo_ods.ods_core_customer_df.cust_no`" in text


def test_the_digest_is_stable_and_moves_with_the_facts(tmp_path: Path, customer: dict) -> None:
    assert re.fullmatch(r"[0-9a-f]{16}", customer["packet_digest"])
    again = packet_of(demo_packets(tmp_path / "again"))
    assert again == customer
    corpus = copy_corpus(tmp_path / "corpus")
    task = corpus / "tasks" / "dwd_party_customer_info_daily.json"
    data = read_json(task)
    data["meta"]["description"] = "Keep the newest registration per customer."
    write_json(task, data)
    lineage = parse_corpus(corpus, tmp_path / "changed-lineage")
    assert pack(corpus, lineage, tmp_path / "changed") == 0
    assert packet_of(tmp_path / "changed")["packet_digest"] != customer["packet_digest"]


# ---------------------------------------------------------------- owners and emails


EMAIL = "someone.demo@example.com"
OWNER = "demo_owner_name"


@pytest.fixture(scope="module")
def private_packets(tmp_path_factory) -> Path:
    """The demo with an owner, an owner email and an address in every free-text slot."""
    work = tmp_path_factory.mktemp("private")
    corpus = copy_corpus(work / "corpus")
    task = corpus / "tasks" / "dwd_party_customer_info_daily.json"
    data = read_json(task)
    meta = data["meta"]
    meta.update(owner=OWNER, owner_email=EMAIL, description=f"{meta['description']} Ask {EMAIL}.")
    meta["sql"] = f"-- maintainer: {EMAIL}\n{meta['sql']}"
    write_json(task, data)
    schema = read_json(corpus / "schema_info.json")
    for table in schema["tables"]:
        table["owner"] = OWNER
        if table["table_name"] == DEMO_TABLE:
            table["table_desc"] += f" (questions to {EMAIL})"
            table["schema"][0]["columnComment"] += f", see {EMAIL}"
    write_json(corpus / "schema_info.json", schema)
    lineage = parse_corpus(corpus, work / "lineage")
    assert pack(corpus, lineage, work / "packets") == 0
    return work / "packets"


def _keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_keys(item) for item in value))
    return set()


def test_a_packet_never_carries_an_owner_or_an_email(private_packets: Path) -> None:
    for path in sorted(private_packets.rglob("packet.*")):
        text = path.read_text(encoding="utf-8")
        assert "@" not in text, path
        assert OWNER not in text, path
        if path.suffix == ".json":
            assert not {key for key in _keys(json.loads(text)) if "owner" in key}, path


def test_masking_keeps_the_sentence_around_the_address(private_packets: Path) -> None:
    packet = packet_of(private_packets)
    (task,) = packet["tasks"]
    assert task["description"].endswith("Ask <email>.")
    assert task["sql"].startswith("-- maintainer: <email>\n")
    assert packet["target"]["columns"][0]["comment"] == "Customer number, see <email>"


# ---------------------------------------------------------------- selection and inputs


def test_only_packs_the_named_tables(tmp_path: Path, packets: Path) -> None:
    lineage = packets.parent / "lineage"
    from .catalog_demo import CORPUS

    out = tmp_path / "only"
    assert pack(CORPUS, lineage, out, "--only", "spark_catalog.demo_dwd.dwd_lending_loan_df", DEMO_TABLE) == 0
    assert sorted(path.name for path in out.iterdir()) == [
        "demo_dwd.dwd_lending_loan_df", DEMO_TABLE,
    ]


def test_an_unknown_only_table_is_an_error(tmp_path: Path, packets: Path) -> None:
    from .catalog_demo import CORPUS

    assert pack(CORPUS, packets.parent / "lineage", tmp_path / "x", "--only", "demo_dwd.nope") == 1


def test_without_a_schema_the_target_columns_come_from_the_lineage(
    tmp_path: Path, packets: Path
) -> None:
    from .table_semantics_demo import run
    from .catalog_demo import CORPUS

    code = run(
        "semantic", "packet", "--lineage", packets.parent / "lineage",
        "--tasks", CORPUS / "tasks", "--out", tmp_path / "bare", "--only", DEMO_TABLE,
    )
    assert code == 0
    target = packet_of(tmp_path / "bare")["target"]
    assert target["metadata_source"] == "lineage"
    assert [column["name"] for column in target["columns"]][-1] == "dt"


def test_a_task_missing_from_tasks_is_packed_without_sql(tmp_path: Path, packets: Path) -> None:
    from .catalog_demo import CORPUS

    tasks = tmp_path / "tasks"
    tasks.mkdir()
    for path in (CORPUS / "tasks").glob("*.json"):
        if path.stem != "dwd_party_customer_info_daily":
            (tasks / path.name).write_bytes(path.read_bytes())
    from .table_semantics_demo import run

    code = run(
        "semantic", "packet", "--lineage", packets.parent / "lineage", "--tasks", tasks,
        "--out", tmp_path / "out", "--only", DEMO_TABLE,
    )
    assert code == 0
    (task,) = packet_of(tmp_path / "out")["tasks"]
    assert task["sql"] is None


def test_a_tables_json_is_accepted_and_changes_nothing_it_already_knew(
    tmp_path: Path, packets: Path, customer: dict
) -> None:
    from .catalog_demo import CORPUS, demo_tables

    tables = demo_tables(packets.parent / "lineage", tmp_path / "tables")
    assert pack(CORPUS, packets.parent / "lineage", tmp_path / "out", "--tables", tables,
                "--only", DEMO_TABLE) == 0
    assert packet_of(tmp_path / "out")["lineage"]["downstream"] == customer["lineage"]["downstream"]


# ---------------------------------------------------------------- the masking helpers


def test_sql_comments_are_masked_and_quoted_text_is_left_alone() -> None:
    from scope_lineage.scope.sql_comments import redact_comments_in_sql

    sql = "SELECT '-- 13912345678' AS note, 13912345678 AS n -- call 13912345678\n/* a@b.io */"
    assert redact_comments_in_sql(sql) == (
        "SELECT '-- 13912345678' AS note, 13912345678 AS n -- call <phone>\n/* <email> */"
    )


def test_mask_emails_touches_nothing_but_the_address() -> None:
    from scope_lineage.redaction import mask_emails

    assert mask_emails("WHERE id = 13912345678 AND m = 'x.y@demo.io'") == (
        "WHERE id = 13912345678 AND m = '<email>'"
    )


# ---------------------------------------------------------------- --only reads less


@pytest.mark.parametrize("with_tables", [False, True])
def test_an_only_run_packs_the_same_facts_as_a_full_run(
    tmp_path: Path, packets: Path, with_tables: bool
) -> None:
    """``--only`` parses just the documents naming the table; the packet must not notice."""
    from .catalog_demo import CORPUS, demo_tables

    lineage = packets.parent / "lineage"
    extra = ["--tables", demo_tables(lineage, tmp_path / "tables")] if with_tables else []
    for table in sorted(PRODUCED):
        out = tmp_path / table
        assert pack(CORPUS, lineage, out, "--only", table, *extra) == 0
        assert packet_of(out, table) == packet_of(packets, table), table


def test_an_only_run_parses_only_the_documents_it_needs(
    tmp_path: Path, packets: Path, capsys
) -> None:
    from .catalog_demo import CORPUS

    assert pack(CORPUS, packets.parent / "lineage", tmp_path / "x", "--only", DEMO_TABLE) == 0
    # The producer, its two consumers; its one input has no producer in the corpus.
    assert "from 3 task(s)" in capsys.readouterr().out
