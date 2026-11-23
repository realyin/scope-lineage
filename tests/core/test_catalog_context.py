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


def _with_two_metrics(document: dict) -> dict:
    changed = _with_metric(document)
    changed["metrics"].insert(0, {
        "id": "metric:count_repaid", "name": "还款笔数", "definition": "数还款的笔数。",
        "on": "concept:repayment", "aggregation": "count", "constraints": [], "dimensions": [],
        "status": "drafted", "source": "sql", "evidence": [],
    })
    return changed


@pytest.mark.parametrize("term", ["metric:repaid_amount", "repaid_amount", "还款金额"])
def test_a_metric_leads_to_its_concept_with_the_asked_metric_first(
    document: dict, semantics: dict, term: str
) -> None:
    pack = context_pack(_with_two_metrics(document), semantics, concepts=[term])
    (concept,) = pack["concepts"]
    assert concept["id"] == "concept:repayment"
    assert concept["via_metric"] == {"id": "metric:repaid_amount", "name": "还款金额"}
    assert [m["id"] for m in concept["metrics"]] == ["metric:repaid_amount", "metric:count_repaid"]
    assert pack["missing"] == []


def test_a_concept_reached_by_name_keeps_its_metric_order(document: dict, semantics: dict) -> None:
    (concept,) = context_pack(
        _with_two_metrics(document), semantics, concepts=["concept:repayment"]
    )["concepts"]
    assert "via_metric" not in concept
    assert [m["id"] for m in concept["metrics"]] == ["metric:count_repaid", "metric:repaid_amount"]


def test_the_text_says_which_metric_led_to_the_concept(document: dict, semantics: dict) -> None:
    text = render_context_text(
        context_pack(_with_two_metrics(document), semantics, concepts=["metric:repaid_amount"])
    )
    assert "- 由指标 还款金额（metric:repaid_amount）找到：它是下面「指标」的第一条" in text
    assert "- （所问）还款金额（metric:repaid_amount）：" in text
    assert text.index("还款金额（metric:repaid_amount）：") < text.index("还款笔数（metric:count_repaid）：")


def test_a_metric_on_no_concept_is_reported_missing(document: dict, semantics: dict) -> None:
    changed = _with_metric(document)
    changed["metrics"][0]["on"] = "concept:gone"
    pack = context_pack(changed, semantics, concepts=["metric:repaid_amount"])
    assert pack["concepts"] == []
    assert pack["missing"] == [{
        "kind": "concept", "term": "metric:repaid_amount",
        "metric": {"id": "metric:repaid_amount", "name": "还款金额"},
    }]
    assert "未找到：概念 metric:repaid_amount（指标 还款金额 没有挂在目录里的概念上）" in (
        render_context_text(pack)
    )


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


# -------------------------------------------------------------------- brief
#
# ``brief`` keeps every item that decides how to query and shortens only the parts that are
# long and do not: the one-line-per-column list becomes names, cited rules lose their SQL,
# and downstream readers are named without their tasks.

_KEPT_CATALOG = (
    "table", "concept", "kind", "grain", "time", "refresh", "scope", "time_columns", "joins",
    "constraints", "metrics", "conflicts",
)
_KEPT_SEMANTICS = (
    "present", "what", "row", "refresh", "scope", "good_for", "not_for", "watch", "questions",
)


def _conflicted(document: dict, table: str) -> dict:
    changed = copy.deepcopy(document)
    changed["evidence"]["representations"].setdefault(table, {})["conflicts"] = [
        {"rule": "grain_mismatch", "declared": ["customer_id"], "proven": ["customer_id", "dt"]}
    ]
    return changed


def test_brief_keeps_every_item_that_decides_how_to_query(document: dict, semantics: dict) -> None:
    changed = _conflicted(_with_metric(document), DEMO_TABLE)
    for table in (DEMO_TABLE, REPAYMENT, HISTORY):
        full = _table(context_pack(changed, semantics, tables=[table]), table)
        brief = _table(context_pack(changed, semantics, tables=[table], brief=True), table)
        for key in _KEPT_CATALOG:
            assert brief.get(key) == full.get(key), (table, key)
        for key in _KEPT_SEMANTICS:
            assert brief["semantics"].get(key) == full["semantics"].get(key), (table, key)
    sem = _table(context_pack(changed, semantics, tables=[DEMO_TABLE], brief=True), DEMO_TABLE)
    assert [rule["id"] for rule in sem["semantics"]["rules"]] == ["r1", "r2", "r3"]
    assert sem["semantics"]["rules"][2] == {"id": "r3", "kind": "filter", "text": "只保留编号为 1 的最新一条"}


def test_brief_shortens_columns_rules_and_downstream(document: dict, semantics: dict) -> None:
    pack = context_pack(document, semantics, tables=[DEMO_TABLE], brief=True)
    assert pack["query"]["brief"] is True
    sem = _table(pack, DEMO_TABLE)["semantics"]
    assert sem["columns"][:3] == [
        {"column": "customer_id", "category": "identifier"},
        {"column": "verified_customer_no", "category": "identifier"},
        {"column": "gender_cd", "category": "descriptive"},
    ]
    assert all("sql" not in rule for rule in sem["rules"])
    assert sem["downstream"] == [
        {"table": "demo_dwd.dwd_lending_borrower_df"},
        {"table": "demo_dws.dws_lending_loan_summary_1d"},
    ]


def test_the_default_pack_does_not_change(document: dict, semantics: dict) -> None:
    pack = context_pack(
        document, semantics, tables=[DEMO_TABLE], columns=[f"{DEMO_TABLE}.gender_cd"]
    )
    assert set(pack["query"]) == {"tables", "columns", "concepts"}
    assert "focus" not in _table(pack, DEMO_TABLE)["semantics"]


def test_brief_text_still_says_every_kept_item(document: dict, semantics: dict) -> None:
    changed = _conflicted(document, DEMO_TABLE)
    full = context_pack(changed, semantics, tables=[DEMO_TABLE])
    text = render_context_text(context_pack(changed, semantics, tables=[DEMO_TABLE], brief=True))
    entry = _table(full, DEMO_TABLE)
    sem = entry["semantics"]
    must = [
        entry["concept"]["name"], "粒度：customer_id", "时间形态：snapshot",
        entry["conflicts"][0]["text"], sem["what"], sem["row"]["text"],
        sem["refresh"]["how_to_read"], sem["not_for"][0], sem["questions"][0]["text"],
        *[w["text"] for w in sem["watch"]], *[line["text"] for line in sem["scope"]],
        *[c["expression"] for c in entry["constraints"]], *entry["scope"],
        *[rule["text"] for rule in sem["rules"]],
        *[c["column"] for c in sem["columns"]], "demo_dwd.dwd_lending_borrower_df",
    ]
    for item in must:
        assert item in text, item
    assert "ROW_NUMBER()" not in text  # a rule's SQL
    assert "性别" not in text.split("## 字段一览", 1)[1]  # a column's meaning
    assert "--column" in text and "--brief" in text  # says how to get the rest
    joins = render_context_text(context_pack(document, semantics, tables=[REPAYMENT], brief=True))
    assert f"{REPAYMENT}.loan_no = {LOAN}.loan_no" in joins
    assert "语料中见过" in joins


def test_brief_text_is_shorter_than_the_default(document: dict, semantics: dict) -> None:
    full = render_context_text(context_pack(document, semantics, tables=[DEMO_TABLE]))
    brief = render_context_text(context_pack(document, semantics, tables=[DEMO_TABLE], brief=True))
    assert len(brief.encode("utf-8")) < len(full.encode("utf-8"))


# -------------------------------------------------------------------- focus
#
# ``focus`` narrows a table's watch items, open questions and cited rules to the ones about
# the requested columns. An item names a column by a ``column:<name>`` reference (``refs`` of a
# watch item, ``about`` of a question); one that names no column is about the whole table and
# is always kept. A rule names no column itself, so it stays when a scope line or a kept item
# cites it and leaves only with the items that cited it.


def _focus_semantics(semantics: dict) -> dict:
    changed = copy.deepcopy(semantics)
    doc = changed[DEMO_TABLE]
    doc["rules"].append(
        {"id": "r9", "kind": "derive", "text": "注册时间按秒转换", "sql": "from_unixtime(reg_ts)",
         "sources": ["sql"]}
    )
    doc["rules"].append(
        {"id": "r8", "kind": "other", "text": "整表规则", "sources": ["sql"]}
    )
    doc["summary"]["watch"][0]["refs"].append("rule:r9")
    doc["summary"]["watch"] += [
        {"kind": "coverage", "text": "整表只有一个产出任务。"},
        {"kind": "risk", "text": "整表规则要看。", "refs": ["rule:r8"]},
    ]
    doc["summary"]["questions"].append({"id": "q2", "text": "整表多久补一次数？", "status": "open"})
    return changed


def test_focus_narrows_to_the_requested_columns_and_the_whole_table(
    document: dict, semantics: dict
) -> None:
    pack = context_pack(
        document, _focus_semantics(semantics), tables=[DEMO_TABLE],
        columns=[f"{DEMO_TABLE}.GENDER_CD"], focus=True,
    )
    sem = _table(pack, DEMO_TABLE)["semantics"]
    assert [w["text"] for w in sem["watch"]] == ["整表只有一个产出任务。", "整表规则要看。"]
    assert [q["id"] for q in sem["questions"]] == ["q1", "q2"]
    assert [rule["id"] for rule in sem["rules"]] == ["r1", "r2", "r3", "r8"]
    assert sem["focus"] == {
        "columns": ["gender_cd"], "left_out": {"watch": 1, "questions": 0, "rules": 1},
    }
    # the column itself is still answered in full in the same pack
    assert [c["column"] for c in pack["columns"]] == ["gender_cd"]
    assert pack["query"]["focus"] is True


def test_focus_never_drops_an_item_about_the_whole_table(document: dict, semantics: dict) -> None:
    sems = _focus_semantics(semantics)
    full = _table(context_pack(document, sems, tables=[DEMO_TABLE]), DEMO_TABLE)["semantics"]
    table_level_watch = [w for w in full["watch"] if not any(
        r.startswith("column:") for r in w.get("refs") or [])]
    table_level_questions = [q for q in full["questions"] if not any(
        r.startswith("column:") for r in q.get("about") or [])]
    scope_rules = {r for line in full["scope"] for r in line["rule_refs"]}
    assert table_level_watch and table_level_questions
    for column in [c["column"] for c in full["columns"]] + ["no_such"]:
        for brief in (False, True):
            sem = _table(context_pack(
                document, sems, tables=[DEMO_TABLE], columns=[f"{DEMO_TABLE}.{column}"],
                focus=True, brief=brief,
            ), DEMO_TABLE)["semantics"]
            for item in table_level_watch:
                assert item in sem["watch"], (column, item)
            for item in table_level_questions:
                assert item in sem["questions"], (column, item)
            assert scope_rules <= {rule["id"] for rule in sem["rules"]}, column
            left = sem["focus"]["left_out"]
            assert len(sem["watch"]) + left["watch"] == len(full["watch"])
            assert len(sem["questions"]) + left["questions"] == len(full["questions"])
            assert len(sem["rules"]) + left["rules"] == len(full["rules"])


def test_focus_leaves_a_table_without_requested_columns_whole(
    document: dict, semantics: dict
) -> None:
    sems = _focus_semantics(semantics)
    full = _table(context_pack(document, sems, tables=[DEMO_TABLE]), DEMO_TABLE)
    focused = context_pack(
        document, sems, tables=[DEMO_TABLE, REPAYMENT], columns=[f"{REPAYMENT}.loan_no"],
        focus=True,
    )
    assert _table(focused, DEMO_TABLE) == full


def test_focus_text_says_what_was_left_out_and_how_to_get_it(
    document: dict, semantics: dict
) -> None:
    text = render_context_text(context_pack(
        document, _focus_semantics(semantics), tables=[DEMO_TABLE],
        columns=[f"{DEMO_TABLE}.gender_cd"], focus=True,
    ))
    assert "聚焦 gender_cd：略去只点名其他字段的注意 1 条、待确认问题 0 条、规则 1 条" in text
    assert "--focus" in text
    table_block = text.split(f"# 字段 {DEMO_TABLE}.gender_cd", 1)[0]
    assert "注册时间由秒级时间戳转换而来" not in table_block
    assert "整表只有一个产出任务。" in table_block


# ------------------------------------------------------------ columns inline


def test_columns_of_a_packed_table_come_in_full_in_the_same_pack(
    document: dict, semantics: dict
) -> None:
    pack = context_pack(
        document, semantics, tables=[DEMO_TABLE],
        columns=[f"{DEMO_TABLE}.gender_cd", f"{DEMO_TABLE}.register_time"],
    )
    assert [t["table"] for t in pack["tables"]] == [DEMO_TABLE]
    assert [c["column"] for c in pack["columns"]] == ["gender_cd", "register_time"]
    assert pack["columns"][0]["catalog"]["code_map"] == {"F": "female", "M": "male", "U": "unknown"}


def test_the_command_takes_a_comma_list_of_columns_of_one_table(capsys) -> None:
    code = main([
        "catalog", "context", str(ONTOLOGY), "--semantics", str(EXAMPLES),
        "--table", DEMO_TABLE, "--columns", "gender_cd, register_time", "--columns", "dt",
        "--brief", "--focus", "--json",
    ])
    assert code == 0
    pack = json.loads(capsys.readouterr().out)
    assert pack["query"]["columns"] == [
        f"{DEMO_TABLE}.gender_cd", f"{DEMO_TABLE}.register_time", f"{DEMO_TABLE}.dt",
    ]
    assert [c["column"] for c in pack["columns"]] == ["gender_cd", "register_time", "dt"]
    assert pack["query"]["brief"] is True and pack["query"]["focus"] is True
    assert _table(pack, DEMO_TABLE)["semantics"]["focus"]["columns"] == [
        "gender_cd", "register_time", "dt",
    ]


def test_the_command_exits_2_for_columns_without_a_table(capsys) -> None:
    assert main(["catalog", "context", str(ONTOLOGY), "--columns", "gender_cd"]) == 2
    assert "--columns" in capsys.readouterr().err


# ------------------------------------------------------ columns of several tables
#
# A bare name goes to every requested table that has the column -- a column the catalog
# binds on the table, or one its semantics document describes; ``table.col`` and
# ``db.table.col`` pin one table. One requested table keeps the old behaviour: every bare
# name is that table's.


def test_a_bare_column_goes_to_every_requested_table_that_has_it(
    document: dict, semantics: dict
) -> None:
    pack = context_pack(
        document, semantics, tables=[LOAN, REPAYMENT],
        table_columns=["loan_no", "repay_amt", "principal_amt"],
    )
    assert pack["query"]["columns"] == [
        f"{LOAN}.loan_no", f"{REPAYMENT}.loan_no", f"{REPAYMENT}.repay_amt", f"{LOAN}.principal_amt",
    ]
    assert [(c["table"], c["column"]) for c in pack["columns"]] == [
        (LOAN, "loan_no"), (REPAYMENT, "loan_no"), (REPAYMENT, "repay_amt"), (LOAN, "principal_amt"),
    ]
    assert pack["missing"] == []


def test_a_bare_column_no_requested_table_has_is_missing_once_naming_the_tables(
    document: dict, semantics: dict
) -> None:
    pack = context_pack(
        document, semantics, tables=[LOAN, REPAYMENT, "demo_dwd.nope"], table_columns=["nope_col"],
    )
    assert pack["query"]["columns"] == []
    assert pack["missing"] == [
        {"kind": "table", "term": "demo_dwd.nope"},
        {"kind": "column", "term": "nope_col", "tables": [LOAN, REPAYMENT]},
    ]
    assert f"未找到：字段 nope_col（{LOAN}、{REPAYMENT} 都没有这一列）" in render_context_text(pack)


def test_a_table_prefix_pins_a_column_to_one_table(document: dict, semantics: dict) -> None:
    pack = context_pack(
        document, semantics, tables=[LOAN, REPAYMENT],
        table_columns=["dwd_lending_loan_df.customer_id", f"{REPAYMENT}.repay_time", "dwd_nope.x"],
    )
    assert pack["query"]["columns"] == [f"{LOAN}.customer_id", f"{REPAYMENT}.repay_time"]
    assert pack["missing"] == [{"kind": "column", "term": "dwd_nope.x", "tables": [LOAN, REPAYMENT]}]


def test_bare_columns_ignore_case_and_are_asked_once(document: dict, semantics: dict) -> None:
    pack = context_pack(
        document, semantics, tables=[LOAN, REPAYMENT],
        columns=[f"{REPAYMENT}.loan_no"],
        table_columns=["LOAN_NO", "loan_no", "dwd_lending_loan_df.Loan_No"],
    )
    assert pack["query"]["columns"] == [f"{REPAYMENT}.loan_no", f"{LOAN}.LOAN_NO"]
    assert [(c["table"], c["column"]) for c in pack["columns"]] == [
        (REPAYMENT, "loan_no"), (LOAN, "loan_no"),
    ]


def test_a_column_only_the_semantics_document_describes_counts_as_the_tables(
    document: dict, semantics: dict
) -> None:
    changed = copy.deepcopy(semantics)
    changed[DEMO_TABLE]["columns"].append({"column": "remark_txt", "meaning": "备注"})
    pack = context_pack(document, changed, tables=[DEMO_TABLE, LOAN], table_columns=["remark_txt"])
    assert pack["query"]["columns"] == [f"{DEMO_TABLE}.remark_txt"]
    assert pack["columns"][0]["semantics"]["meaning"] == "备注"


def test_one_table_takes_every_bare_column_as_before(document: dict, semantics: dict) -> None:
    pack = context_pack(document, semantics, tables=[LOAN], table_columns=["loan_no", "nope_col"])
    assert pack["query"]["columns"] == [f"{LOAN}.loan_no", f"{LOAN}.nope_col"]
    assert pack["missing"] == [{"kind": "column", "term": f"{LOAN}.nope_col"}]


def test_focus_narrows_each_table_to_its_share_of_the_bare_columns(
    document: dict, semantics: dict
) -> None:
    pack = context_pack(
        document, _focus_semantics(semantics), tables=[DEMO_TABLE, LOAN],
        table_columns=["gender_cd", "loan_no"], focus=True,
    )
    assert _table(pack, DEMO_TABLE)["semantics"]["focus"]["columns"] == ["gender_cd"]


def test_the_command_takes_bare_columns_for_several_tables(capsys) -> None:
    code = main([
        "catalog", "context", str(ONTOLOGY), "--table", LOAN, "--table", REPAYMENT,
        "--columns", "loan_no,repay_amt", "--focus", "--json",
    ])
    assert code == 0
    pack = json.loads(capsys.readouterr().out)
    assert pack["query"]["columns"] == [
        f"{LOAN}.loan_no", f"{REPAYMENT}.loan_no", f"{REPAYMENT}.repay_amt",
    ]
    assert len(pack["links"]) == 1


def test_the_command_exits_2_for_focus_without_columns(capsys) -> None:
    assert main(["catalog", "context", str(ONTOLOGY), "--table", DEMO_TABLE, "--focus"]) == 2
    assert "--focus" in capsys.readouterr().err


def test_brief_text_points_a_column_to_the_notes_its_packed_table_already_shows(
    document: dict, semantics: dict
) -> None:
    columns = [f"{DEMO_TABLE}.gender_cd", f"{DEMO_TABLE}.register_time"]
    text = render_context_text(context_pack(
        document, semantics, tables=[DEMO_TABLE], columns=columns, brief=True, focus=True,
    ))
    assert text.count("性别码值除了 F、M、U 以外") == 1
    assert text.count("注册时间由秒级时间戳转换而来") == 1
    assert f"- 点名本列的表级注意 0 条、待确认问题 1 条：见上方表 {DEMO_TABLE}" in text
    # a column whose table is not packed still carries its notes in full
    alone = render_context_text(context_pack(document, semantics, columns=columns, brief=True))
    assert "- 待确认问题 q1（open）：性别码值除了" in alone


# ------------------------------------------------------------ links between tables

CUSTOMER = "demo_dwd.dwd_party_customer_info_df"
WAIVER = "demo_dwd.dwd_collection_fee_waiver_di"
SUMMARY = "demo_dws.dws_lending_loan_summary_1d"
ACCOUNT_MAP = "demo_dwd.dwd_party_account_map_df"


@pytest.fixture(scope="module")
def partitioned(document: dict) -> dict:
    """The demo ontology with the loan snapshot's ``dt`` marked as its load partition."""
    changed = copy.deepcopy(document)
    (rep,) = [r for r in changed["representations"] if r["table"] == LOAN]
    (binding,) = [b for b in rep["bindings"] if b["column"] == "dt"]
    binding["time_role"] = "partition"
    return changed


@pytest.fixture(scope="module")
def batched(document: dict) -> dict:
    """The demo ontology with the incremental repayment table's ``dt`` marked as its
    partition and ``repay_time`` as its event time."""
    changed = copy.deepcopy(document)
    (rep,) = [r for r in changed["representations"] if r["table"] == REPAYMENT]
    roles = {"dt": "partition", "repay_time": "event_time"}
    for binding in rep["bindings"]:
        if binding["column"] in roles:
            binding["time_role"] = roles[binding["column"]]
    return changed


def _link(pack: dict, a: str, b: str) -> dict:
    (found,) = [link for link in pack["links"] if set(link["tables"]) == {a, b}]
    return found


def _side(link: dict, table: str) -> dict:
    (found,) = [side for side in link["sides"] if side["table"] == table]
    return found


def test_a_single_table_pack_has_no_links(document: dict, semantics: dict) -> None:
    pack = context_pack(document, semantics, tables=[LOAN])
    assert "links" not in pack
    assert "# 关联" not in render_context_text(pack)


def test_two_tables_get_the_pairs_the_catalog_backs_and_which_basis(document: dict) -> None:
    pack = context_pack(document, None, tables=[LOAN, REPAYMENT])
    link = _link(pack, LOAN, REPAYMENT)
    assert link["tables"] == [LOAN, REPAYMENT]
    pairs = {(p["left"], p["right"]): p for p in link["pairs"]}
    loan_pair = pairs[(f"{LOAN}.loan_no", f"{REPAYMENT}.loan_no")]
    assert loan_pair["basis"] == "identifier"
    assert loan_pair["identifier"]["id"] == "id:loan_no"
    assert pairs[(f"{LOAN}.customer_id", f"{REPAYMENT}.customer_id")]["basis"] == "identifier"


def test_a_pair_backed_only_by_a_recorded_join_says_so(document: dict) -> None:
    changed = copy.deepcopy(document)
    # drop the shared identifier on one side: only the corpus sample still backs the pair
    (rep,) = [r for r in changed["representations"] if r["table"] == REPAYMENT]
    (binding,) = [b for b in rep["bindings"] if b["column"] == "loan_no"]
    binding["to"] = "attribute"
    binding.pop("ref")
    link = _link(context_pack(changed, None, tables=[LOAN, REPAYMENT]), LOAN, REPAYMENT)
    (pair,) = [p for p in link["pairs"] if p["left"] == f"{LOAN}.loan_no"]
    assert pair["basis"] == "seen_join"
    assert pair["relation"] == "rel:repayment.loan"


def test_each_side_says_how_many_rows_meet_a_key(document: dict) -> None:
    link = _link(context_pack(document, None, tables=[LOAN, REPAYMENT]), LOAN, REPAYMENT)
    loan = _side(link, LOAN)
    assert loan["grain"] == ["loan_no"]
    assert loan["rows_per_key"] == "one"
    assert loan["open"] == []
    repayment = _side(link, REPAYMENT)
    assert repayment["grain"] == ["repay_txn_no"]
    assert repayment["rows_per_key"] == "several"
    assert repayment["open"] == ["repay_txn_no"]


def test_a_zipper_window_left_open_must_be_pinned(document: dict) -> None:
    link = _link(context_pack(document, None, tables=[HISTORY, LOAN]), HISTORY, LOAN)
    history = _side(link, HISTORY)
    assert history["open"] == ["start_date"]
    assert history["rows_per_key"] == "one_once_filtered"
    assert history["pinned_by_filters"] == ["start_date"]
    assert {"table": HISTORY, "group": "window", "columns": [
        {"column": "start_date", "role": "valid_from"},
        {"column": "end_date", "role": "valid_to"},
    ]} in link["filters"]
    text = render_context_text(context_pack(document, None, tables=[HISTORY, LOAN]))
    assert "拉链有效期" in text
    assert "start_date" in text.split("# 关联", 1)[1]


def test_a_side_with_no_recorded_grain_is_not_guessed(document: dict) -> None:
    changed = copy.deepcopy(document)
    (rep,) = [r for r in changed["representations"] if r["table"] == REPAYMENT]
    rep.pop("grain")
    pack = context_pack(changed, None, tables=[LOAN, REPAYMENT])
    repayment = _side(_link(pack, LOAN, REPAYMENT), REPAYMENT)
    assert repayment["grain"] is None
    assert repayment["rows_per_key"] == "unknown"
    assert "没有记录粒度" in render_context_text(pack)


def test_partition_filters_come_with_the_link(partitioned: dict) -> None:
    link = _link(context_pack(partitioned, None, tables=[LOAN, REPAYMENT]), LOAN, REPAYMENT)
    assert {"table": LOAN, "group": "partition", "columns": [
        {"column": "dt", "role": "partition"},
    ]} in link["filters"]
    assert "a.dt = '<dt>'" in link["skeleton"]
    assert link["partitions"] == []


def test_an_incremental_partition_is_no_filter_and_names_the_event_time(batched: dict) -> None:
    pack = context_pack(batched, None, tables=[LOAN, REPAYMENT])
    link = _link(pack, LOAN, REPAYMENT)
    assert all(item["table"] != REPAYMENT for item in link["filters"])
    assert link["partitions"] == [{
        "table": REPAYMENT, "columns": ["dt"], "reading": "write_batch",
        "period_columns": ["repay_time"],
    }]
    skeleton = link["skeleton"]
    code = "\n".join(line.split("--")[0] for line in skeleton.splitlines())
    assert "b.dt" not in code
    assert "b.repay_time >= '<period_start>'" in code
    assert "b.repay_time < '<period_end>'" in code
    assert any(line.startswith("--") and "写入批次" in line for line in skeleton.splitlines())
    section = render_context_text(pack).split("# 关联", 1)[1]
    assert f"要过滤：{REPAYMENT}" not in section
    assert "写入批次，不是事件日期" in section and "repay_time" in section


def test_an_incremental_table_with_two_event_times_gets_a_comment_only(batched: dict) -> None:
    changed = copy.deepcopy(batched)
    (rep,) = [r for r in changed["representations"] if r["table"] == REPAYMENT]
    rep["bindings"].append({"column": "settle_time", "to": "technical", "time_role": "event_time"})
    link = _link(context_pack(changed, None, tables=[LOAN, REPAYMENT]), LOAN, REPAYMENT)
    code = "\n".join(line.split("--")[0] for line in link["skeleton"].splitlines())
    assert "<period_start>" not in code
    assert "repay_time" in link["skeleton"] and "settle_time" in link["skeleton"]


def test_the_table_pack_says_how_to_read_its_partition(
    document: dict, partitioned: dict, batched: dict
) -> None:
    def catalog_block(doc: dict, table: str) -> str:
        text = render_context_text(context_pack(doc, None, tables=[table]))
        return text.split("## 目录", 1)[1].split("## 怎么读", 1)[0]

    full = catalog_block(partitioned, LOAN)
    assert "每个分区一份全量，只取一个分区" in full
    batch = catalog_block(batched, REPAYMENT)
    assert "写入批次，不是事件日期" in batch and "按事件时间列 repay_time 过滤" in batch
    assert _table(context_pack(batched, None, tables=[REPAYMENT]), REPAYMENT)["partition"] == {
        "columns": ["dt"], "reading": "write_batch", "period_columns": ["repay_time"],
    }
    unknown = copy.deepcopy(partitioned)
    (rep,) = [r for r in unknown["representations"] if r["table"] == LOAN]
    rep["time"] = "unknown"
    assert "目录没记录每个分区是不是一份全量" in catalog_block(unknown, LOAN)
    assert "分区" not in catalog_block(document, LOAN)
    assert "partition" not in _table(context_pack(document, None, tables=[LOAN]), LOAN)


def test_the_skeleton_uses_plain_join_and_leaves_the_join_type_to_the_writer(
    document: dict,
) -> None:
    link = _link(context_pack(document, None, tables=[LOAN, REPAYMENT]), LOAN, REPAYMENT)
    skeleton = link["skeleton"]
    assert f"FROM {LOAN} a" in skeleton
    assert f"JOIN {REPAYMENT} b" in skeleton
    assert "a.loan_no = b.loan_no" in skeleton
    code = "\n".join(line.split("--")[0] for line in skeleton.splitlines())
    assert "LEFT" not in code and "INNER" not in code and "OUTER" not in code
    assert "-- " in skeleton and "关联方式" in skeleton
    # the open grain of the repayment side is a comment line
    assert any(
        line.startswith("--") and "repay_txn_no" in line for line in skeleton.splitlines()
    )


def _demo_pairs(document: dict) -> list[tuple[str, str]]:
    tables = [r["table"] for r in document["representations"]]
    return [(a, b) for i, a in enumerate(tables) for b in tables[i + 1:]]


@pytest.mark.parametrize("variant", ["document", "partitioned", "batched"])
def test_every_skeleton_passes_check_sql_join_and_partition_rules(request, variant) -> None:
    from scope_lineage.render.catalog_sql_check import check_sql
    from scope_lineage.scope.query_facts import query_facts

    doc = request.getfixturevalue(variant)
    checked = 0
    for a, b in _demo_pairs(doc):
        link = _link(context_pack(doc, None, tables=[a, b]), a, b)
        if link["skeleton"] is None:
            continue
        result = check_sql(doc, query_facts(link["skeleton"]))
        rules = {f["rule"] for f in result["findings"]}
        assert "join_not_recorded" not in rules, (a, b, link["skeleton"])
        assert "missing_partition_filter" not in rules, (a, b, link["skeleton"])
        checked += 1
    assert checked >= 5


def test_no_backed_pair_gives_no_skeleton_and_names_a_bridge(document: dict) -> None:
    pack = context_pack(document, None, tables=[SUMMARY, CUSTOMER])
    link = _link(pack, SUMMARY, CUSTOMER)
    assert link["pairs"] == []
    assert link["skeleton"] is None
    assert link["bridges"] == [ACCOUNT_MAP]
    text = render_context_text(pack)
    assert "目录没有支持" in text
    assert ACCOUNT_MAP in text.split("# 关联", 1)[1]


def test_no_backed_pair_and_no_bridge_says_both(document: dict) -> None:
    pack = context_pack(document, None, tables=[WAIVER, SUMMARY])
    link = _link(pack, WAIVER, SUMMARY)
    assert link["pairs"] == [] and link["bridges"] == [] and link["skeleton"] is None
    assert "也没有一张表" in render_context_text(pack)


def test_three_tables_give_one_link_a_pair(document: dict) -> None:
    pack = context_pack(document, None, tables=[LOAN, REPAYMENT, HISTORY, LOAN])
    assert [link["tables"] for link in pack["links"]] == [
        [LOAN, REPAYMENT], [LOAN, HISTORY], [REPAYMENT, HISTORY],
    ]


def test_the_link_text_comes_after_the_tables(document: dict) -> None:
    text = render_context_text(context_pack(
        document, None, tables=[LOAN, REPAYMENT], columns=[f"{LOAN}.loan_no"],
    ))
    assert text.index(f"# 表 {REPAYMENT}") < text.index(f"# 关联 {LOAN} ↔ {REPAYMENT}")
    assert text.index(f"# 关联 {LOAN} ↔ {REPAYMENT}") < text.index(f"# 字段 {LOAN}.loan_no")
    assert "```sql" in text


def test_the_command_prints_links_for_two_tables(capsys) -> None:
    code = main([
        "catalog", "context", str(ONTOLOGY), "--table", LOAN, "--table", REPAYMENT, "--json",
    ])
    assert code == 0
    pack = json.loads(capsys.readouterr().out)
    assert pack["doc_format"] == "catalog-context/1"
    assert _link(pack, LOAN, REPAYMENT)["skeleton"]


def _code_lines(skeleton: str) -> list[str]:
    return [line.split("--")[0].strip() for line in skeleton.splitlines() if not line.startswith("--")]


def test_other_backed_pairs_are_alternatives_not_anded_into_on(document: dict) -> None:
    # loan_no = loan_no and orig_loan_no = loan_no are two different paths (a loan, the
    # loan it renews); AND-ing them would ask for a loan that renews itself
    link = _link(context_pack(document, None, tables=[LOAN, HISTORY]), LOAN, HISTORY)
    code = _code_lines(link["skeleton"])
    assert "ON  a.loan_no = b.loan_no" in code or "ON a.loan_no = b.loan_no" in code
    assert not any("orig_loan_no" in line for line in code)
    assert any(
        line.startswith("--") and "a.orig_loan_no = b.loan_no" in line
        for line in link["skeleton"].splitlines()
    )
    on = {(p["left"], p["right"]) for p in link["pairs"] if p["in_skeleton"]}
    assert on == {(f"{LOAN}.loan_no", f"{HISTORY}.loan_no")}
    # a pair that is no grain column of either side is not AND-ed in either
    link = _link(context_pack(document, None, tables=[LOAN, REPAYMENT]), LOAN, REPAYMENT)
    assert not any("customer_id" in line for line in _code_lines(link["skeleton"]))


def test_a_pair_that_completes_a_composite_grain_joins_the_on(document: dict) -> None:
    changed = copy.deepcopy(document)
    (rep,) = [r for r in changed["representations"] if r["table"] == SUMMARY]
    rep["bindings"].append({"column": "account_id", "to": "foreign_identifier",
                            "ref": "id:app_account_id"})
    # the map's grain names id:channel_code; bind it as the map's own key so the grain resolves
    (rep,) = [r for r in changed["representations"] if r["table"] == ACCOUNT_MAP]
    (binding,) = [b for b in rep["bindings"] if b["column"] == "channel_code"]
    binding["to"] = "identifier"
    link = _link(context_pack(changed, None, tables=[ACCOUNT_MAP, SUMMARY]), ACCOUNT_MAP, SUMMARY)
    on = {(p["left"], p["right"]) for p in link["pairs"] if p["in_skeleton"]}
    assert on == {
        (f"{ACCOUNT_MAP}.account_id", f"{SUMMARY}.account_id"),
        (f"{ACCOUNT_MAP}.channel_code", f"{SUMMARY}.channel_code"),
    }
    assert _side(link, ACCOUNT_MAP)["rows_per_key"] == "one"


def test_check_sql_lists_the_same_pairs_the_link_shows(document: dict) -> None:
    from scope_lineage.render.catalog_sql_check import check_sql
    from scope_lineage.scope.query_facts import query_facts

    sql = f"SELECT * FROM {LOAN} a JOIN {REPAYMENT} b ON a.dt = b.dt"
    (finding,) = [
        f for f in check_sql(document, query_facts(sql))["findings"]
        if f["rule"] == "join_not_recorded"
    ]
    link = _link(context_pack(document, None, tables=[LOAN, REPAYMENT]), LOAN, REPAYMENT)
    assert [(p["left"], p["right"]) for p in finding["catalog"]["recorded"]] == [
        (p["left"], p["right"]) for p in link["pairs"]
    ]


# -------------------------------------------------------------------- units
#
# A measure's unit in the catalog may have been filled in by the drafter while the table
# semantics give none. With the semantics documents the pack can tell the two apart: a unit
# none of the attribute's bound columns has in the material is marked as unconfirmed, and
# an attribute with no unit says whether the material gives one. Without them nothing is
# marked and the pack is what it always was.

PRINCIPAL = f"{LOAN}.principal_amt"
UNSUPPORTED = "（材料未给，目录所填未经确认）"


def _material(unit: str | None = None, column: str = "principal_amt", table: str = LOAN) -> dict:
    """A table-semantics document for ``table`` describing one measure column."""
    described = {"column": column, "meaning": "金额", "category": "measure"}
    if unit:
        described["unit"] = unit
    return {table: {"table": table, "columns": [described]}}


def _principal(document: dict, **fields) -> dict:
    """The document with ``attr:loan.principal`` changed (a field given as None is removed)."""
    changed = copy.deepcopy(document)
    for concept in changed["concepts"]:
        for attribute in concept.get("attributes") or []:
            if attribute["id"] == "attr:loan.principal":
                attribute.update(fields)
                for key in [k for k, v in fields.items() if v is None]:
                    del attribute[key]
    return changed


def _column_pack(document: dict, semantics, column: str = PRINCIPAL) -> tuple[dict, str]:
    pack = context_pack(document, semantics, columns=[column])
    return pack["columns"][0]["catalog"], render_context_text(pack)


def test_a_unit_the_material_does_not_give_is_marked_unconfirmed(document: dict) -> None:
    catalog, text = _column_pack(document, _material())
    assert catalog["unit"] == "CNY"
    assert catalog["material_unit"] == {"given": False}
    assert f"  - 单位：CNY{UNSUPPORTED}\n" in text


def test_a_unit_the_material_gives_carries_no_mark(document: dict) -> None:
    catalog, text = _column_pack(document, _material("元"))
    assert "material_unit" not in catalog
    assert "  - 单位：CNY\n" in text
    assert "材料未给" not in text and "目录未填" not in text


def test_notes_about_something_else_leave_a_supported_unit_unchanged(document: dict) -> None:
    noted = _principal(document, notes="待 owner 确认：是否含税")
    for semantics in (_material("元"), None):
        assert context_pack(noted, semantics, columns=[PRINCIPAL]) == context_pack(
            document, semantics, columns=[PRINCIPAL]
        )
        assert render_context_text(context_pack(noted, semantics, columns=[PRINCIPAL])) == (
            render_context_text(context_pack(document, semantics, columns=[PRINCIPAL]))
        )


def test_without_semantics_nothing_is_marked(document: dict) -> None:
    for changed in (document, _principal(document, unit=None)):
        pack = context_pack(changed, None, columns=[PRINCIPAL])
        assert "material_unit" not in json.dumps(pack, ensure_ascii=False)
        text = render_context_text(pack)
        assert "材料未给" not in text and "目录未填" not in text
    assert "  - 单位：CNY\n" in render_context_text(context_pack(document, None, columns=[PRINCIPAL]))
    assert "单位" not in render_context_text(
        context_pack(_principal(document, unit=None), None, columns=[PRINCIPAL])
    )


def test_no_unit_and_none_in_the_material_says_the_material_gives_none(document: dict) -> None:
    catalog, text = _column_pack(_principal(document, unit=None), _material())
    assert "unit" not in catalog
    assert catalog["material_unit"] == {"given": False}
    assert "  - 单位：材料未给\n" in text


def test_no_unit_while_the_material_gives_one_shows_the_materials_unit(document: dict) -> None:
    catalog, text = _column_pack(_principal(document, unit=None), _material("元"))
    assert "unit" not in catalog
    assert catalog["material_unit"] == {"given": True, "units": ["元"]}
    assert "  - 单位：元（目录未填）\n" in text


def test_one_bound_column_with_a_unit_in_the_material_supports_the_attribute(document: dict) -> None:
    changed = copy.deepcopy(document)
    for rep in changed["representations"]:
        if rep["table"] == REPAYMENT:
            rep["bindings"].append(
                {"column": "principal_copy", "to": "attribute", "ref": "attr:loan.principal"}
            )
    semantics = {**_material(), **_material("元", column="principal_copy", table=REPAYMENT)}
    catalog, text = _column_pack(changed, semantics)
    assert "material_unit" not in catalog
    assert "材料未给" not in text


def test_a_unit_whose_columns_no_document_describes_is_not_judged(
    document: dict, semantics: dict
) -> None:
    """Semantics were given, but none for the attribute's table: the material says nothing."""
    catalog, text = _column_pack(document, semantics)
    assert "material_unit" not in catalog
    assert "  - 单位：CNY\n" in text


def test_a_non_measure_attribute_is_not_judged(document: dict) -> None:
    catalog, _ = _column_pack(_principal(document, category="descriptive"), _material())
    assert "material_unit" not in catalog


def _repayment_material(unit: str | None = None) -> dict:
    return _material(unit, column="repay_amt", table=REPAYMENT)


@pytest.mark.parametrize("term", ["metric:repaid_amount", "concept:repayment"])
def test_a_metric_over_a_measure_the_material_gives_no_unit_for_is_marked(
    document: dict, term: str
) -> None:
    pack = context_pack(_with_two_metrics(document), _repayment_material(), concepts=[term])
    metrics = {m["id"]: m for m in pack["concepts"][0]["metrics"]}
    assert metrics["metric:repaid_amount"]["material_unit"] == {"given": False}
    assert "material_unit" not in metrics["metric:count_repaid"]   # no measure to compare
    assert f"  - 单位：元{UNSUPPORTED}\n" in render_context_text(pack)


def test_a_metric_over_a_supported_measure_carries_no_mark(document: dict) -> None:
    pack = context_pack(
        _with_metric(document), _repayment_material("元"), concepts=["metric:repaid_amount"]
    )
    assert "material_unit" not in pack["concepts"][0]["metrics"][0]
    assert "  - 单位：元\n" in render_context_text(pack)


def test_a_metric_with_no_unit_says_what_the_material_gives(document: dict) -> None:
    changed = _with_metric(document)
    del changed["metrics"][0]["unit"]
    for unit, line in ((None, "  - 单位：材料未给\n"), ("元", "  - 单位：元（目录未填）\n")):
        pack = context_pack(changed, _repayment_material(unit), concepts=["metric:repaid_amount"])
        assert line in render_context_text(pack)


def test_a_metric_without_semantics_is_not_marked(document: dict) -> None:
    for semantics in (None, {}):
        pack = context_pack(_with_metric(document), semantics, concepts=["metric:repaid_amount"])
        assert "material_unit" not in json.dumps(pack, ensure_ascii=False)
        assert "  - 单位：元\n" in render_context_text(pack)


def test_the_answers_facade_marks_the_same_way(document: dict) -> None:
    from scope_lineage.cli_catalog_answers import context

    answer = context(document, _material(), columns=[PRINCIPAL])
    assert answer.result["columns"][0]["catalog"]["material_unit"] == {"given": False}
    assert UNSUPPORTED in answer.text()
