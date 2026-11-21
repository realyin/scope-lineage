"""``catalog search``: from the words a person uses to the catalog's own names.

``catalog query`` matches names exactly and guesses nothing, so it needs the catalog's
name for a thing. A reader starts with a business word or a whole question. ``search``
ranks concepts, metrics, attributes, identifiers, code sets and tables against that text
and returns a short list of candidates, each with its id, its name and one line, for the
reader to choose from. It ranks; it does not decide, and it never rewrites the catalog.

Every case runs on the recorded demo ontology.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scope_lineage.cli import main
from scope_lineage.render.catalog_search import SEARCH_KINDS, render_search_text, search_catalog

from .table_semantics_demo import DEMO_TABLE, EXAMPLE, EXAMPLES

ONTOLOGY = Path(__file__).parent / "fixtures" / "catalog" / "ontology.json"


@pytest.fixture(scope="module")
def document() -> dict:
    return json.loads(ONTOLOGY.read_text(encoding="utf-8"))


def _ids(result: dict) -> list[str]:
    return [hit["id"] for hit in result["hits"]]


def test_the_kinds_searched() -> None:
    assert SEARCH_KINDS == ("concept", "metric", "attribute", "identifier", "code_set", "table")


# ------------------------------------------------------------- what matches


def test_a_name_finds_its_concept_first(document: dict) -> None:
    result = search_catalog(document, "借款人")
    assert result["query"] == {"text": "借款人", "kinds": list(SEARCH_KINDS), "limit": 10}
    top = result["hits"][0]
    assert top["kind"] == "concept" and top["id"] == "concept:borrower"
    assert top["name"] == "借款人"
    assert top["summary"].startswith("A customer while they hold")
    assert "name" in top["matched_in"]


def test_a_synonym_finds_its_concept(document: dict) -> None:
    top = search_catalog(document, "对客借据")["hits"][0]
    assert top["id"] == "concept:loan"
    assert "synonym" in top["matched_in"]


def test_a_term_finds_what_it_refers_to(document: dict) -> None:
    top = search_catalog(document, "罚息", kinds=["attribute"])["hits"][0]
    assert top["id"] == "attr:loan.overdue_penalty"
    assert "term" in top["matched_in"]


def test_a_whole_question_finds_every_thing_it_names(document: dict) -> None:
    found = _ids(search_catalog(document, "每个渠道上个月的还款金额是多少", limit=5))
    assert "concept:channel" in found
    assert "concept:repayment" in found
    assert "attr:repayment.amount" in found


def test_a_word_inside_a_definition_ranks_below_a_name(document: dict) -> None:
    changed = copy.deepcopy(document)
    changed["concepts"][0]["definition"] = "渠道里的登录账户。"  # concept:app_account
    hits = search_catalog(changed, "渠道", kinds=["concept"])["hits"]
    order = [hit["id"] for hit in hits]
    assert order.index("concept:channel") < order.index("concept:app_account")
    by_id = {hit["id"]: hit for hit in hits}
    assert by_id["concept:app_account"]["matched_in"] == ["definition"]


def test_a_physical_column_name_finds_the_attribute_and_identifier_bound_to_it(
    document: dict,
) -> None:
    assert "attr:customer.gender" in _ids(search_catalog(document, "gender_cd"))
    assert search_catalog(document, "cust_no", kinds=["identifier"])["hits"][0]["id"] == (
        "id:customer_id"
    )


def test_a_code_meaning_finds_its_code_set(document: dict) -> None:
    top = search_catalog(document, "疑似核销", kinds=["code_set"])["hits"][0]
    assert top["id"] == "code:loan_status"


def test_a_table_is_found_by_its_name_its_comment_and_its_concept(document: dict) -> None:
    assert search_catalog(document, "loan_status_his", kinds=["table"])["hits"][0]["id"] == (
        "demo_dwd.dwd_lending_loan_status_his"
    )
    assert search_catalog(document, "zipper", kinds=["table"])["hits"][0]["id"] == (
        "demo_dwd.dwd_lending_loan_status_his"
    )
    assert DEMO_TABLE in _ids(search_catalog(document, "客户", kinds=["table"]))


def test_a_semantics_document_makes_its_table_findable_by_what_it_says(document: dict) -> None:
    semantics = {DEMO_TABLE: json.loads(EXAMPLE.read_text(encoding="utf-8"))}
    assert search_catalog(document, "核心系统", kinds=["table"])["hits"] == []
    top = search_catalog(document, "核心系统", semantics, kinds=["table"])["hits"][0]
    assert top["id"] == DEMO_TABLE
    assert top["matched_in"] == ["semantics"]


def test_a_metric_is_found_by_name(document: dict) -> None:
    changed = copy.deepcopy(document)
    changed["metrics"] = [
        {"id": "metric:repaid_amount", "name": "还款总额", "definition": "把各笔还款的金额加总。",
         "on": "concept:repayment", "aggregation": "sum", "status": "drafted", "source": "sql",
         "evidence": []}
    ]
    top = search_catalog(changed, "还款总额")["hits"][0]
    assert top["kind"] == "metric" and top["id"] == "metric:repaid_amount"
    assert top["where"] == "还款（concept:repayment）"


# --------------------------------------------------------- what a hit says


def test_a_hit_says_where_the_thing_lives(document: dict) -> None:
    concept = search_catalog(document, "借款人", kinds=["concept"])["hits"][0]
    assert concept["where"] == "demo_dwd.dwd_lending_borrower_df"
    attribute = search_catalog(document, "授信额度", kinds=["attribute"])["hits"][0]
    assert attribute["where"] == "借款人（concept:borrower）；demo_dwd.dwd_lending_borrower_df.credit_limit"
    table = search_catalog(document, "loan_status_his", kinds=["table"])["hits"][0]
    assert table["where"] == "借据（concept:loan）"


def test_a_summary_is_one_short_line(document: dict) -> None:
    changed = copy.deepcopy(document)
    changed["concepts"][0]["definition"] = "登录账户。\n" + "很长的说明" * 200
    hit = search_catalog(changed, "应用账户", kinds=["concept"])["hits"][0]
    assert "\n" not in hit["summary"]
    assert len(hit["summary"]) <= 120


# ------------------------------------------------------------ order, limits


def test_nothing_in_common_finds_nothing(document: dict) -> None:
    assert search_catalog(document, "火星殖民")["hits"] == []
    assert search_catalog(document, "   ")["hits"] == []


def test_kinds_and_limit_narrow_the_answer(document: dict) -> None:
    hits = search_catalog(document, "借据", kinds=["concept", "identifier"], limit=3)["hits"]
    assert len(hits) <= 3
    assert {hit["kind"] for hit in hits} <= {"concept", "identifier"}
    with pytest.raises(ValueError):
        search_catalog(document, "借据", kinds=["nonsense"])


def test_the_order_is_by_score_and_stable(document: dict) -> None:
    first = search_catalog(document, "借据状态")
    again = search_catalog(copy.deepcopy(document), "借据状态")
    assert first == again
    scores = [hit["score"] for hit in first["hits"]]
    assert scores == sorted(scores, reverse=True)
    assert all(score > 0 for score in scores)


def test_a_question_naming_two_things_lists_both_before_the_members_of_one(document: dict) -> None:
    # "Per customer, ... and the number of repayments": the customer's identifier, attributes
    # and code set all match more of the words than the repayment concept does, and used to
    # fill the first five places between them.
    question = "每个客户的客户号、性别和注册时间，以及还款的次数"
    hits = search_catalog(document, question, limit=5)["hits"]
    found = [hit["id"] for hit in hits]
    assert "concept:repayment" in found
    assert any(hit["kind"] == "attribute" and hit["id"].startswith("attr:customer.") for hit in hits)


def test_a_question_about_one_thing_keeps_the_order_of_its_scores(document: dict) -> None:
    for text in ("借款人", "借据状态", "客户", "gender_cd"):
        scores = [hit["score"] for hit in search_catalog(document, text)["hits"]]
        assert scores == sorted(scores, reverse=True), text


def test_the_members_of_a_concept_are_listed_when_asked_for_by_kind(document: dict) -> None:
    hits = search_catalog(document, "客户", kinds=["identifier"])["hits"]
    assert [hit["id"] for hit in hits][:2] == ["id:customer_id", "id:verified_customer_no"]


def test_question_scaffolding_in_the_text_matches_nothing(document: dict) -> None:
    changed = copy.deepcopy(document)
    changed["concepts"][0]["definition"] = "每个渠道是否有多少个哪些账户"  # concept:app_account
    assert search_catalog(changed, "每个是否有多少哪些")["hits"] == []
    assert search_catalog(changed, "写出统计说明")["hits"] == []
    # The words themselves still match: only the query's scaffolding is set aside.
    assert _ids(search_catalog(changed, "渠道有多少个账户", kinds=["concept"]))[0] in (
        "concept:channel", "concept:app_account"
    )


def test_a_word_with_one_scaffolding_character_still_matches(document: dict) -> None:
    # 还 and 个 are common in questions, but 还款 is a business word and stays.
    assert search_catalog(document, "有多少还款", kinds=["concept"])["hits"][0]["id"] == (
        "concept:repayment"
    )


def test_case_and_width_do_not_matter(document: dict) -> None:
    assert _ids(search_catalog(document, "LOAN_STATUS_HIS", kinds=["table"]))[0] == (
        "demo_dwd.dwd_lending_loan_status_his"
    )


# --------------------------------------------------------------- text, CLI


def test_the_text_is_one_line_a_hit(document: dict) -> None:
    text = render_search_text(search_catalog(document, "借款人", limit=3))
    lines = text.splitlines()
    assert lines[0] == "1. [概念] 借款人 concept:borrower — A customer while they hold at least one loan that is not settled."
    assert lines[1] == "   在：demo_dwd.dwd_lending_borrower_df"


def test_the_text_for_ten_hits_stays_small(document: dict) -> None:
    text = render_search_text(search_catalog(document, "每个渠道上个月的还款金额是多少"))
    assert len(text.encode("utf-8")) <= 3000


def test_the_text_says_nothing_was_found(document: dict) -> None:
    text = render_search_text(search_catalog(document, "火星殖民"))
    assert text == "没有找到与「火星殖民」相近的目录对象。\n"


def test_the_command_prints_hits_and_exits_0(capsys) -> None:
    code = main(["catalog", "search", str(ONTOLOGY), "借款人", "--json", "--limit", "2"])
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["hits"][0]["id"] == "concept:borrower" and len(result["hits"]) <= 2


def test_the_command_reads_semantics_documents(capsys) -> None:
    code = main([
        "catalog", "search", str(ONTOLOGY), "核心系统", "--semantics", str(EXAMPLES),
        "--kind", "table",
    ])
    assert code == 0
    assert DEMO_TABLE in capsys.readouterr().out


def test_the_command_exits_1_when_nothing_was_found(capsys) -> None:
    assert main(["catalog", "search", str(ONTOLOGY), "火星殖民"]) == 1
    assert "没有找到" in capsys.readouterr().out
