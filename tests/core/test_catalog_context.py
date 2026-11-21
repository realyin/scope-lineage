"""``catalog context``: everything one question needs about a few tables, in one answer.

The pack joins two sources a reader otherwise opens page by page: the built ontology (what
a table carries, its keys, its time columns, where it joins, the constraints and metrics on
its concept) and the table's semantics document (how to read it, what it is not for, what
to watch, what is still an open question). It takes the parts of the semantics document a
query depends on and leaves the rest, so a pack stays a fraction of the page.

Every case runs on the recorded demo ontology and the hand-written example document.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scope_lineage.cli import main
from scope_lineage.render.catalog_context import (
    CONTEXT_FORMAT,
    context_pack,
    render_context_text,
)

from .table_semantics_demo import DEMO_TABLE, EXAMPLE, EXAMPLES

ONTOLOGY = Path(__file__).parent / "fixtures" / "catalog" / "ontology.json"
LOAN = "demo_dwd.dwd_lending_loan_df"
REPAYMENT = "demo_dwd.dwd_lending_repayment_di"
HISTORY = "demo_dwd.dwd_lending_loan_status_his"


@pytest.fixture(scope="module")
def document() -> dict:
    return json.loads(ONTOLOGY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def semantics() -> dict:
    return {DEMO_TABLE: json.loads(EXAMPLE.read_text(encoding="utf-8"))}


def _table(pack: dict, name: str) -> dict:
    (found,) = [entry for entry in pack["tables"] if entry["table"] == name]
    return found


# ------------------------------------------------------------------ a table


def test_a_table_carries_its_catalog_facts(document: dict, semantics: dict) -> None:
    pack = context_pack(document, semantics, tables=[DEMO_TABLE])
    assert pack["doc_format"] == CONTEXT_FORMAT == "catalog-context/1"
    entry = _table(pack, DEMO_TABLE)
    assert entry["concept"] == {"id": "concept:customer", "name": "客户"}
    assert entry["kind"] == "core"
    assert entry["time"] == "snapshot"
    assert entry["grain"]["columns"] == ["customer_id"]
    assert entry["grain"]["source"] == "proven"
    assert "only customers whose customer_status is active" in entry["scope"]
    constraints = {c["id"]: c for c in entry["constraints"]}
    # the concept's own rule, and the one on a relation it takes part in
    assert set(constraints) == {"cons:active_customers_only", "cons:one_account_per_channel"}
    assert constraints["cons:active_customers_only"]["expression"].startswith(
        "customer counts read only rows"
    )


def test_a_table_carries_the_parts_of_its_semantics_a_query_depends_on(
    document: dict, semantics: dict
) -> None:
    sem = _table(context_pack(document, semantics, tables=[DEMO_TABLE]), DEMO_TABLE)["semantics"]
    assert sem["present"] is True
    assert sem["what"].startswith("客户主表")
    assert sem["row"]["unique"] == "yes"
    assert "不要把多个 dt 分区相加" in sem["refresh"]["how_to_read"]
    assert sem["not_for"] == [
        "看客户注册信息的变更历史：每天只留最新一条，改动之前的值不在这张表里"
    ]
    assert sem["watch"] == [
        {"kind": "risk", "text": "注册时间由秒级时间戳转换而来，按集群默认时区解释。",
         "refs": ["column:register_time"]}
    ]
    assert sem["questions"] == [
        {"id": "q1", "text": "性别码值除了 F、M、U 以外，还会不会出现其他值？",
         "about": ["column:gender_cd"], "status": "open"}
    ]


def test_scope_lines_bring_the_rules_they_cite_with_their_sql(
    document: dict, semantics: dict
) -> None:
    sem = _table(context_pack(document, semantics, tables=[DEMO_TABLE]), DEMO_TABLE)["semantics"]
    assert [line["rule_refs"] for line in sem["scope"]] == [["r1"], ["r2", "r3"]]
    assert [rule["id"] for rule in sem["rules"]] == ["r1", "r2", "r3"]
    assert sem["rules"][2] == {
        "id": "r3", "kind": "filter", "text": "只保留编号为 1 的最新一条", "sql": "WHERE rn = 1"
    }


def test_every_column_is_listed_in_one_line_and_none_in_full(
    document: dict, semantics: dict
) -> None:
    sem = _table(context_pack(document, semantics, tables=[DEMO_TABLE]), DEMO_TABLE)["semantics"]
    assert [c["column"] for c in sem["columns"]] == [
        "customer_id", "verified_customer_no", "gender_cd", "register_time",
        "verify_status", "etl_time", "dt",
    ]
    assert sem["columns"][2] == {"column": "gender_cd", "meaning": "性别", "category": "descriptive"}


def test_provenance_and_lineage_detail_stay_out_of_the_pack(
    document: dict, semantics: dict
) -> None:
    sem = _table(context_pack(document, semantics, tables=[DEMO_TABLE]), DEMO_TABLE)["semantics"]
    text = json.dumps(sem, ensure_ascii=False)
    for left_out in ('"sources"', '"confidence"', '"upstream"', '"steps"'):
        assert left_out not in text


def test_the_tasks_and_tables_reading_a_table_are_kept_for_impact_questions(
    document: dict, semantics: dict
) -> None:
    pack = context_pack(document, semantics, tables=[DEMO_TABLE])
    assert _table(pack, DEMO_TABLE)["semantics"]["downstream"] == [
        {"task": "dwd_lending_borrower_daily", "table": "demo_dwd.dwd_lending_borrower_df"},
        {"task": "dws_lending_loan_summary_daily", "table": "demo_dws.dws_lending_loan_summary_1d"},
    ]
    text = render_context_text(pack)
    assert text.count("## 下游") == 1
    assert "- dwd_lending_borrower_daily → demo_dwd.dwd_lending_borrower_df" in text


def test_a_table_with_no_semantics_document_says_so(document: dict, semantics: dict) -> None:
    entry = _table(context_pack(document, semantics, tables=[LOAN]), LOAN)
    assert entry["semantics"] == {"present": False}
    assert entry["concept"]["id"] == "concept:loan"


def test_without_a_semantics_directory_the_pack_says_none_was_given(document: dict) -> None:
    entry = _table(context_pack(document, None, tables=[DEMO_TABLE]), DEMO_TABLE)
    assert entry["semantics"] == {"present": False}


def test_a_table_name_ignores_case_and_a_catalog_prefix(document: dict, semantics: dict) -> None:
    pack = context_pack(document, semantics, tables=["hive." + DEMO_TABLE.upper()])
    assert [entry["table"] for entry in pack["tables"]] == [DEMO_TABLE]
    assert pack["missing"] == []


def test_a_table_the_catalog_does_not_know_is_reported_missing(
    document: dict, semantics: dict
) -> None:
    pack = context_pack(document, semantics, tables=["demo_dwd.no_such_table"])
    assert pack["tables"] == []
    assert pack["missing"] == [{"kind": "table", "term": "demo_dwd.no_such_table"}]


def test_a_disagreement_between_catalog_and_corpus_is_one_sentence(
    document: dict, semantics: dict
) -> None:
    changed = copy.deepcopy(document)
    changed["evidence"]["representations"][LOAN]["conflicts"] = [
        {"rule": "grain_mismatch", "declared": ["loan_no"], "proven": ["loan_no", "dt"]}
    ]
    pack = context_pack(changed, semantics, tables=[LOAN])
    assert _table(pack, LOAN)["conflicts"] == [
        {"rule": "grain_mismatch",
         "text": f"`{LOAN}`：目录声明粒度 `loan_no`，血缘证明的是 `loan_no`、`dt`"}
    ]
    assert f"- 证据与目录矛盾：`{LOAN}`：目录声明粒度" in render_context_text(pack)
    quiet = _table(context_pack(document, semantics, tables=[DEMO_TABLE]), DEMO_TABLE)
    assert "conflicts" not in quiet


# ------------------------------------------------------- time columns, joins


def test_time_columns_carry_their_role(document: dict, semantics: dict) -> None:
    entry = _table(context_pack(document, semantics, tables=[HISTORY]), HISTORY)
    assert entry["time_columns"] == [
        {"column": "start_date", "role": "valid_from"},
        {"column": "end_date", "role": "valid_to"},
    ]


def test_a_foreign_key_names_the_tables_and_columns_it_joins_to(
    document: dict, semantics: dict
) -> None:
    entry = _table(context_pack(document, semantics, tables=[REPAYMENT]), REPAYMENT)
    joins = {join["column"]: join for join in entry["joins"]}
    assert set(joins) == {"loan_no", "customer_id"}
    loan = joins["loan_no"]
    assert loan["identifier"] == {"id": "id:loan_no", "name": "借据号"}
    assert loan["concept"]["id"] == "concept:loan"
    assert {"table": LOAN, "column": "loan_no"} in loan["to"]
    assert {"table": HISTORY, "column": "loan_no"} in loan["to"]
    assert REPAYMENT not in {target["table"] for target in loan["to"]}


def test_a_join_says_how_often_the_corpus_showed_it(document: dict, semantics: dict) -> None:
    entry = _table(context_pack(document, semantics, tables=[REPAYMENT]), REPAYMENT)
    (loan,) = [join for join in entry["joins"] if join["column"] == "loan_no"]
    assert loan["seen"] == [
        {
            "relation": "rel:repayment.loan",
            "where": "between_catalog_tables",
            "count": 1,
            "on": [f"{LOAN}.loan_no = {REPAYMENT}.loan_no"],
        },
        {
            "relation": "rel:repayment.loan",
            "where": "inside_producing_task",
            "count": 1,
            "on": [f"demo_ods.ods_repay_txn_di.loan_no = {LOAN}.loan_no"],
        },
    ]


# ------------------------------------------------------------------ columns


def test_a_column_carries_its_binding_and_its_semantics(document: dict, semantics: dict) -> None:
    pack = context_pack(document, semantics, columns=[f"{DEMO_TABLE}.gender_cd"])
    assert pack["tables"] == []
    (column,) = pack["columns"]
    assert column["table"] == DEMO_TABLE and column["column"] == "gender_cd"
    assert column["catalog"]["to"] == "attribute"
    assert column["catalog"]["ref"] == {"id": "attr:customer.gender", "name": "性别"}
    assert column["catalog"]["code_map"] == {"F": "female", "M": "male", "U": "unknown"}
    assert column["semantics"]["derivation"] == "直接取注册表的性别码。"
    assert [value["value"] for value in column["semantics"]["code_values"]] == ["F", "M", "U"]
    assert "sources" not in json.dumps(column, ensure_ascii=False)


def test_a_column_brings_the_table_notes_and_open_questions_that_name_it(
    document: dict, semantics: dict
) -> None:
    pack = context_pack(
        document, semantics,
        columns=[f"{DEMO_TABLE}.gender_cd", f"{DEMO_TABLE}.register_time"],
    )
    gender, registered = pack["columns"]
    assert [q["id"] for q in gender["questions"]] == ["q1"]
    assert gender["watch"] == []
    assert registered["questions"] == []
    assert [w["text"] for w in registered["watch"]] == [
        "注册时间由秒级时间戳转换而来，按集群默认时区解释。"
    ]


def test_a_column_the_table_does_not_have_is_reported_missing(
    document: dict, semantics: dict
) -> None:
    pack = context_pack(document, semantics, columns=[f"{DEMO_TABLE}.no_such"])
    assert pack["columns"] == []
    assert pack["missing"] == [{"kind": "column", "term": f"{DEMO_TABLE}.no_such"}]


def test_a_column_only_the_semantics_document_knows_is_still_answered(
    document: dict, semantics: dict
) -> None:
    doc = copy.deepcopy(semantics)
    doc[DEMO_TABLE]["columns"].append(
        {"column": "extra_flag", "meaning": "额外标记", "category": "descriptive",
         "derivation": "常量 0", "sources": ["sql"], "confidence": "high"}
    )
    pack = context_pack(document, doc, columns=[f"{DEMO_TABLE}.extra_flag"])
    (column,) = pack["columns"]
    assert column["catalog"] is None
    assert column["semantics"]["meaning"] == "额外标记"


# ----------------------------------------------------------------- concepts


def _with_metric(document: dict) -> dict:
    changed = copy.deepcopy(document)
    changed["metrics"] = [
        {
            "id": "metric:repaid_amount", "name": "还款金额", "definition": "把各笔还款的金额加总。",
            "on": "concept:repayment", "measure": "attr:repayment.amount", "aggregation": "sum",
            "filter": "只算成功的还款", "constraints": ["cons:repaid_after_disbursed"],
            "time_window": "按还款日", "dimensions": ["concept:loan"], "additivity": "additive",
            "unit": "元", "status": "drafted", "source": "sql", "evidence": [],
        }
    ]
    return changed


def test_a_concept_carries_its_definition_tables_and_constraints(
    document: dict, semantics: dict
) -> None:
    pack = context_pack(document, semantics, concepts=["客户"])
    (concept,) = pack["concepts"]
    assert concept["id"] == "concept:customer"
    assert [t["table"] for t in concept["tables"]] == [
        "demo_dwd.dwd_party_customer_ext_df", DEMO_TABLE,
    ]
    assert {c["id"] for c in concept["constraints"]} == {
        "cons:active_customers_only", "cons:one_account_per_channel",
    }


def test_a_concept_carries_its_metrics_spelled_out(document: dict, semantics: dict) -> None:
    pack = context_pack(_with_metric(document), semantics, concepts=["concept:repayment"])
    (metric,) = pack["concepts"][0]["metrics"]
    assert metric["name"] == "还款金额"
    assert metric["aggregation"] == "sum" and metric["unit"] == "元"
    assert metric["filter"] == "只算成功的还款"
    assert metric["measure"]["id"] == "attr:repayment.amount"
    assert metric["measure"]["columns"] == [f"{REPAYMENT}.repay_amt"]
    assert metric["constraints"] == [
        {"id": "cons:repaid_after_disbursed",
         "expression": "repaid_at is not earlier than the disbursed_at of every loan it pays"}
    ]


def test_a_table_names_the_metrics_on_its_concept(document: dict, semantics: dict) -> None:
    entry = _table(context_pack(_with_metric(document), semantics, tables=[REPAYMENT]), REPAYMENT)
    assert entry["metrics"] == [{"id": "metric:repaid_amount", "name": "还款金额"}]


def test_a_concept_is_found_by_its_id_without_the_prefix(document: dict, semantics: dict) -> None:
    pack = context_pack(document, semantics, concepts=["fee_waiver"])
    assert [concept["id"] for concept in pack["concepts"]] == ["concept:fee_waiver"]
    assert pack["missing"] == []


def test_a_concept_nothing_names_is_reported_missing(document: dict, semantics: dict) -> None:
    pack = context_pack(document, semantics, concepts=["没有这个概念"])
    assert pack["concepts"] == []
    assert pack["missing"] == [{"kind": "concept", "term": "没有这个概念"}]


# --------------------------------------------------------------------- size


def test_a_table_pack_is_smaller_than_the_document_it_reads(
    document: dict, semantics: dict
) -> None:
    pack = context_pack(document, semantics, tables=[DEMO_TABLE])
    packed = len(json.dumps(_table(pack, DEMO_TABLE)["semantics"], ensure_ascii=False))
    whole = len(json.dumps(semantics[DEMO_TABLE], ensure_ascii=False))
    assert packed < whole * 0.6


# --------------------------------------------------------------------- text


def test_the_text_names_each_part_once(document: dict, semantics: dict) -> None:
    pack = context_pack(
        document, semantics, tables=[DEMO_TABLE], columns=[f"{DEMO_TABLE}.gender_cd"]
    )
    text = render_context_text(pack)
    assert text.startswith(f"# 表 {DEMO_TABLE}\n")
    for heading in ("## 目录", "## 怎么读", "## 不适用", "## 注意", "## 待确认问题", "## 字段一览"):
        assert text.count(heading) == 1, heading
    assert f"# 字段 {DEMO_TABLE}.gender_cd" in text
    assert "q1（open）：性别码值除了 F、M、U 以外，还会不会出现其他值？" in text


def test_the_text_says_when_a_table_has_no_semantics(document: dict, semantics: dict) -> None:
    text = render_context_text(context_pack(document, semantics, tables=[LOAN]))
    assert "本表没有表语义文档" in text


def test_the_text_lists_what_was_not_found(document: dict, semantics: dict) -> None:
    text = render_context_text(context_pack(document, semantics, tables=["demo_dwd.nope"]))
    assert "未找到：表 demo_dwd.nope" in text


# ---------------------------------------------------------------------- CLI


def test_the_command_prints_the_pack(capsys) -> None:
    code = main([
        "catalog", "context", str(ONTOLOGY), "--semantics", str(EXAMPLES),
        "--table", DEMO_TABLE, "--json",
    ])
    assert code == 0
    pack = json.loads(capsys.readouterr().out)
    assert pack["doc_format"] == "catalog-context/1"
    assert _table(pack, DEMO_TABLE)["semantics"]["present"] is True


def test_the_command_prints_text_by_default(capsys) -> None:
    code = main(["catalog", "context", str(ONTOLOGY), "--table", DEMO_TABLE])
    assert code == 0
    assert capsys.readouterr().out.startswith(f"# 表 {DEMO_TABLE}\n")


def test_the_command_exits_1_when_nothing_was_found(capsys) -> None:
    code = main(["catalog", "context", str(ONTOLOGY), "--table", "demo_dwd.nope"])
    assert code == 1
    assert "未找到" in capsys.readouterr().out


def test_the_command_exits_2_without_anything_to_look_up(capsys) -> None:
    code = main(["catalog", "context", str(ONTOLOGY)])
    assert code == 2
    assert "--table" in capsys.readouterr().err


def test_the_command_exits_2_for_a_semantics_directory_that_is_not_there(
    tmp_path: Path, capsys
) -> None:
    code = main([
        "catalog", "context", str(ONTOLOGY), "--semantics", str(tmp_path / "none"),
        "--table", DEMO_TABLE,
    ])
    assert code == 2
    assert "--semantics" in capsys.readouterr().err
