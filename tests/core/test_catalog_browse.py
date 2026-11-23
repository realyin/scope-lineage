"""``catalog_browse``: the shapes a person browsing a built catalog needs, one page at a time.

A browser page over a large catalog cannot download the document. These
answers give it what one view shows: the domains, a page of concepts, tables or metrics, a
concept's neighbourhood for a graph, one table's semantics document, and the board of
open questions. Each is checked on the demo ontology and the demo table-semantics document;
the scale cases build a neutral synthetic catalog in the test.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scope_lineage import cli_catalog_answers as answers
from scope_lineage.render.catalog_browse import (
    MAX_LIMIT,
    browse_index,
    browse_list,
    concept_neighbourhood,
    questions_board,
    table_semantics,
)
from scope_lineage.render.catalog_pending import pending_line, pending_report

ROOT = Path(__file__).resolve().parents[2]
ONTOLOGY = Path(__file__).parent / "fixtures" / "catalog" / "ontology.json"
SEMANTICS = ROOT / "examples" / "table-semantics"
CUSTOMER = "demo_dwd.dwd_party_customer_info_df"
LOAN = "demo_dwd.dwd_lending_loan_df"
REPAYMENT = "demo_dwd.dwd_lending_repayment_di"


@pytest.fixture(scope="module")
def document() -> dict:
    return answers.load_ontology(str(ONTOLOGY))


@pytest.fixture(scope="module")
def semantics() -> dict:
    return answers.load_semantics(str(SEMANTICS))


def _with_metric(document: dict) -> dict:
    changed = copy.deepcopy(document)
    changed["metrics"] = [{
        "id": "metric:repaid_amount", "name": "还款金额", "definition": "把各笔还款的金额加总。",
        "on": "concept:repayment", "measure": "attr:repayment.amount", "aggregation": "sum",
        "unit": "元", "dimensions": [], "constraints": [], "status": "drafted", "source": "owner",
        "evidence": [],
    }]
    return changed


# ------------------------------------------------------------------ index


def test_the_index_lists_each_domain_with_how_much_it_holds(document) -> None:
    index = browse_index(document)

    assert index["doc_format"] == "catalog-browse-index/1"
    assert index["catalog"]["name"] == document["catalog"]["name"]
    assert index["counts"] == document["counts"]
    by_id = {domain["id"]: domain for domain in index["domains"]}
    assert sorted(by_id) == ["domain:collection", "domain:lending", "domain:party"]
    party = by_id["domain:party"]
    concepts = [c for c in document["concepts"] if c["domain"] == "domain:party"]
    assert party["concepts"] == len(concepts)
    tables = [
        r for r in document["representations"]
        if any(c["id"] == r["concept"] for c in concepts)
    ]
    assert party["tables"] == len(tables)
    assert party["name"]


# ------------------------------------------------------------------ lists


def test_concepts_of_a_domain_carry_the_index_page_columns(document) -> None:
    page = browse_list(document, "concepts", domain="domain:party")

    assert page["doc_format"] == "catalog-browse-list/1"
    ids = [item["id"] for item in page["items"]]
    assert ids == sorted(ids)
    assert set(ids) == {
        "concept:app_account", "concept:channel", "concept:customer",
        "concept:identity_verification",
    }
    customer = next(item for item in page["items"] if item["id"] == "concept:customer")
    assert set(customer) >= {"id", "name", "kind", "definition", "tables", "status"}
    assert customer["tables"] == sum(
        1 for r in document["representations"] if r["concept"] == "concept:customer"
    )
    assert page["total"] == 4 and page["offset"] == 0


def test_tables_are_paged_in_name_order_and_say_how_many_there_are(document) -> None:
    every = sorted(r["table"] for r in document["representations"])

    first = browse_list(document, "tables", limit=4)
    second = browse_list(document, "tables", offset=4, limit=4)

    assert [item["table"] for item in first["items"]] == every[:4]
    assert [item["table"] for item in second["items"]] == every[4:8]
    assert first["total"] == second["total"] == len(every)
    item = first["items"][0]
    assert set(item) >= {"table", "concept", "kind", "time", "columns"}
    assert set(item["concept"]) == {"id", "name"}


def test_tables_filter_by_concept_domain_and_text(document) -> None:
    of_loan = browse_list(document, "tables", concept="concept:loan")
    lending = browse_list(document, "tables", domain="domain:lending")
    texted = browse_list(document, "tables", text="LOAN")

    assert {item["table"] for item in of_loan["items"]} == {
        r["table"] for r in document["representations"] if r["concept"] == "concept:loan"
    }
    assert all(item["concept"]["id"] in {
        c["id"] for c in document["concepts"] if c["domain"] == "domain:lending"
    } for item in lending["items"])
    assert texted["items"] and all("loan" in item["table"] for item in texted["items"])


def test_a_concept_filter_takes_a_name_as_query_does(document) -> None:
    by_name = browse_list(document, "tables", concept="客户")
    by_id = browse_list(document, "tables", concept="concept:customer")

    assert by_name["items"] == by_id["items"]


def test_concepts_filter_by_text_over_names_and_synonyms(document) -> None:
    page = browse_list(document, "concepts", text="customer")

    assert "concept:customer" in [item["id"] for item in page["items"]]


def test_metrics_are_listed_with_their_concept(document) -> None:
    page = browse_list(_with_metric(document), "metrics", concept="concept:repayment")

    (metric,) = page["items"]
    assert metric["id"] == "metric:repaid_amount"
    assert metric["on"]["id"] == "concept:repayment"
    assert metric["aggregation"] == "sum"


def test_list_refuses_what_it_cannot_answer(document) -> None:
    with pytest.raises(ValueError):
        browse_list(document, "rows")
    with pytest.raises(ValueError):
        browse_list(document, "tables", limit=MAX_LIMIT + 1)
    with pytest.raises(ValueError):
        browse_list(document, "tables", offset=-1)


# ------------------------------------------------------------- neighbourhood


def test_the_neighbourhood_is_one_hop_with_the_edges_between_its_nodes(document) -> None:
    graph = concept_neighbourhood(document, "concept:loan")

    assert graph["doc_format"] == "catalog-neighbourhood/1"
    assert graph["centre"] == "concept:loan"
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert nodes["concept:loan"]["centre"] is True
    touching = {
        r["to"] if r["from"] == "concept:loan" else r["from"]
        for r in document["relations"] if "concept:loan" in (r["from"], r["to"])
    }
    assert set(nodes) == touching | {"concept:loan"}
    ids = {edge["id"] for edge in graph["edges"] if edge.get("id")}
    # an edge between two neighbours is drawn too: borrower -- disbursement
    assert "rel:disbursement.borrower" in ids
    assert "rel:customer_holds_app_account" not in ids
    assert graph["truncated"] == 0


def test_an_edge_carries_its_join_conditions(document) -> None:
    graph = concept_neighbourhood(document, "concept:borrower")
    owes = next(edge for edge in graph["edges"] if edge.get("id") == "rel:borrower_owes_loan")

    assert owes["kind"] == "association"
    assert owes["from"] == "concept:borrower" and owes["to"] == "concept:loan"
    assert owes["cardinality"]
    assert owes["joins"]["count"] == 1
    assert owes["joins"]["on"] == [
        "demo_dwd.dwd_lending_borrower_df.customer_id = demo_dwd.dwd_lending_loan_df.customer_id"
    ]


def test_a_foreign_key_column_is_a_join_condition_of_its_relation(document) -> None:
    graph = concept_neighbourhood(document, "concept:loan")
    edges = [edge for edge in graph["edges"] if edge.get("keys")]

    assert edges, "the demo's loan tables hold foreign keys to their neighbours"
    for edge in edges:
        for key in edge["keys"]:
            assert key["column"].count(".") == 2
            assert set(key["identifier"]) == {"id", "name"}
            assert all(target.count(".") == 2 for target in key["to"])


def test_a_column_naming_another_record_is_a_key_of_the_self_relation_only(document) -> None:
    graph = concept_neighbourhood(document, "concept:loan")
    edges = {edge.get("id"): edge for edge in graph["edges"]}

    renews = edges["rel:loan_renews_loan"]
    (key,) = renews["keys"]
    assert key["column"] == f"{LOAN}.orig_loan_no"
    assert f"{LOAN}.loan_no" in key["to"]  # its own table's key is where it points
    assert key["to_total"] == len(key["to"])
    assert edges["rel:installment_loan_is_a_loan"]["keys"] == []


def test_a_role_is_drawn_to_the_concept_that_plays_it(document) -> None:
    graph = concept_neighbourhood(document, "concept:customer")

    roles = [edge for edge in graph["edges"] if edge["kind"] == "role"]
    assert {"from": "concept:borrower", "to": "concept:customer"}.items() <= roles[0].items()


def test_the_neighbourhood_is_capped_and_says_how_many_it_left_out(document) -> None:
    graph = concept_neighbourhood(document, "concept:loan", limit=2)

    assert len(graph["nodes"]) == 3  # the centre and two neighbours
    assert graph["truncated"] >= 1
    kept = {node["id"] for node in graph["nodes"]}
    assert all({edge["from"], edge["to"]} <= kept for edge in graph["edges"])


def test_the_neighbourhood_finds_a_concept_by_name_and_says_when_none(document) -> None:
    assert concept_neighbourhood(document, "客户")["centre"] == "concept:customer"
    nothing = concept_neighbourhood(document, "no such thing")
    assert nothing["centre"] is None and nothing["nodes"] == [] and nothing["edges"] == []


# ------------------------------------------------------------------ semantics


def test_a_tables_semantics_document_is_returned_whole(document, semantics) -> None:
    answer = table_semantics(document, semantics, CUSTOMER.upper())

    assert answer["doc_format"] == "catalog-table-semantics/1"
    assert answer["table"] == CUSTOMER
    assert answer["in_catalog"] is True
    assert answer["document"] == semantics[CUSTOMER]


def test_a_table_without_a_semantics_document_has_none(document, semantics) -> None:
    answer = table_semantics(document, semantics, LOAN)

    assert answer["document"] is None and answer["in_catalog"] is True
    assert table_semantics(document, None, CUSTOMER)["document"] is None


# ------------------------------------------------------------------ questions


def _report(document, semantics, *lines) -> dict:
    entries = [{**line, "line": number} for number, line in enumerate(lines, 1)]
    return pending_report(entries, document=document, semantics=semantics)


def test_the_board_lists_the_semantics_questions_with_their_concept(document, semantics) -> None:
    board = questions_board(document, semantics)

    assert board["doc_format"] == "catalog-questions/1"
    assert board["checked"] == {"semantics": True, "pending": False}
    (question,) = board["items"]
    assert question["source"] == "semantics"
    assert question["table"] == CUSTOMER
    assert question["id"] == "q1" and question["status"] == "open"
    assert question["concept"] == {"id": "concept:customer", "name": "客户"}
    assert question["in_catalog"] is True
    assert question["columns"] == [{"column": "gender_cd", "bound": True}]


def test_pending_items_join_the_board_marked_when_the_catalog_lacks_them(
    document, semantics
) -> None:
    report = _report(
        document, semantics,
        pending_line(missing="完全没有定义的东西", question="问题一", date="2026-01-01",
                     columns=[f"{LOAN}.loan_status_cd"]),
        pending_line(missing="客户", question="问题二", date="2026-01-02"),
    )

    board = questions_board(document, semantics, report)

    pending = [item for item in board["items"] if item["source"] == "pending"]
    assert board["checked"]["pending"] is True
    missing = next(item for item in pending if item["missing"] == "完全没有定义的东西")
    assert missing["in_catalog"] is False
    assert missing["concepts"] == [{"id": "concept:loan", "name": view_name(document, "concept:loan")}]
    named = next(item for item in pending if item["missing"] == "客户")
    assert named["in_catalog"] is True
    assert board["counts"]["not_in_catalog"] == 1


def view_name(document, concept_id) -> str:
    return next(c["name"] for c in document["concepts"] if c["id"] == concept_id)


def test_the_board_filters_by_table_concept_status_source_and_text(document, semantics) -> None:
    report = _report(
        document, semantics,
        pending_line(missing="还款口径", question="q", date="2026-01-01", tables=[REPAYMENT]),
    )

    by_table = questions_board(document, semantics, report, table=REPAYMENT.upper())
    by_concept = questions_board(document, semantics, report, concept="客户")
    answered = questions_board(document, semantics, report, status="answered")
    only_pending = questions_board(document, semantics, report, source="pending")
    texted = questions_board(document, semantics, report, text="性别")

    assert [item["source"] for item in by_table["items"]] == ["pending"]
    assert [item.get("id") for item in by_concept["items"]] == ["q1"]
    assert answered["items"] == []
    assert [item["source"] for item in only_pending["items"]] == ["pending"]
    assert [item.get("id") for item in texted["items"]] == ["q1"]


def test_the_board_counts_concepts_for_its_filter_and_pages(document, semantics) -> None:
    report = _report(
        document, semantics,
        *[pending_line(missing=f"缺口 {n}", question="q", date="2026-01-01", tables=[LOAN])
          for n in range(5)],
    )

    board = questions_board(document, semantics, report, limit=2, offset=2)

    assert board["total"] == 6 and len(board["items"]) == 2 and board["offset"] == 2
    facets = {facet["id"]: facet["count"] for facet in board["concepts"]}
    assert facets["concept:loan"] == 5 and facets["concept:customer"] == 1


def test_the_board_refuses_an_unknown_status_or_source(document, semantics) -> None:
    with pytest.raises(ValueError):
        questions_board(document, semantics, status="closed")
    with pytest.raises(ValueError):
        questions_board(document, semantics, source="mail")


def test_a_question_on_a_table_the_catalog_lacks_is_marked(document, semantics) -> None:
    stray = copy.deepcopy(semantics[CUSTOMER])
    stray["table"] = "demo_ods.some_raw_table"
    board = questions_board(document, {**semantics, "demo_ods.some_raw_table": stray})

    item = next(i for i in board["items"] if i["table"] == "demo_ods.some_raw_table")
    assert item["in_catalog"] is False and item["concept"] is None


# ------------------------------------------------------------------ answers


def test_the_answers_wrap_the_shapes_with_exit_codes(document, semantics) -> None:
    assert answers.browse_index(document).exit_code == 0
    assert answers.browse_list(document, "tables").exit_code == 0
    assert answers.neighbourhood(document, "concept:loan").exit_code == 0
    assert answers.neighbourhood(document, "nothing").exit_code == 1
    assert answers.table_semantics(document, semantics, CUSTOMER).exit_code == 0
    assert answers.table_semantics(document, semantics, LOAN).exit_code == 1
    board = answers.questions(document, semantics, pending_text=None)
    assert board.exit_code == 0
    assert json.loads(board.json_text()) == board.result


def test_the_answers_refuse_bad_options_with_exit_2(document, semantics) -> None:
    for call in (
        lambda: answers.browse_list(document, "rows"),
        lambda: answers.browse_list(document, "tables", limit=0),
        lambda: answers.neighbourhood(document, "concept:loan", limit=0),
        lambda: answers.questions(document, semantics, status="closed"),
    ):
        with pytest.raises(answers.CatalogAnswerError) as caught:
            call()
        assert caught.value.exit_code == 2


def test_the_board_reads_a_pending_files_text(document, semantics) -> None:
    line = pending_line(missing="某个缺口", question="q", date="2026-01-01")
    text = json.dumps(line, ensure_ascii=False) + "\nnot json\n"

    board = answers.questions(document, semantics, pending_text=text).result

    assert [item["missing"] for item in board["items"] if item["source"] == "pending"] == ["某个缺口"]
    assert board["problems"] == [{"line": 2, "message": board["problems"][0]["message"]}]


# ------------------------------------------------------------------ scale


def synthetic_catalog(tables: int, concepts: int = 200, domains: int = 10) -> dict:
    """A neutral catalog: ``tables`` tables spread over ``concepts`` concepts in a ring."""
    concept_ids = [f"concept:c{n:04d}" for n in range(concepts)]
    document = {
        "doc_format": "ontology-json/3",
        "catalog": {"name": "synthetic"},
        "counts": {},
        "domains": [
            {"id": f"domain:d{n:02d}", "name": f"域 {n}", "status": "drafted", "source": "test",
             "evidence": []}
            for n in range(domains)
        ],
        "identifiers": [
            {"id": f"id:c{n:04d}", "name": f"标识 {n}", "identifies": concept_ids[n],
             "scope": "global", "spellings": [], "status": "drafted", "source": "test",
             "evidence": []}
            for n in range(concepts)
        ],
        "code_sets": [],
        "concepts": [
            {"id": concept_ids[n], "name": f"概念 {n}", "kind": "entity",
             "domain": f"domain:d{n % domains:02d}", "synonyms": [], "attributes": [],
             "identifiers": [f"id:c{n:04d}"], "status": "drafted", "source": "test",
             "evidence": []}
            for n in range(concepts)
        ],
        "relations": [
            {"id": f"rel:r{n:04d}", "kind": "association", "from": concept_ids[n],
             "to": concept_ids[(n + 1) % concepts], "name": "links",
             "cardinality": {"from": "0..*", "to": "1"}, "status": "drafted",
             "source": "test", "evidence": []}
            for n in range(concepts)
        ],
        "constraints": [], "metrics": [], "terms": [],
        "representations": [
            {"table": f"db.t{n:05d}", "concept": concept_ids[n % concepts], "kind": "core",
             "time": "snapshot", "table_status": "active", "scope": [], "status": "drafted",
             "source": "test", "evidence": [],
             "grain": {"identifiers": [f"id:c{n % concepts:04d}"], "source": "declared"},
             "bindings": [
                 {"column": "k", "to": "identifier", "ref": f"id:c{n % concepts:04d}"},
                 {"column": "fk", "to": "foreign_identifier",
                  "ref": f"id:c{(n + 1) % concepts:04d}"},
             ]}
            for n in range(tables)
        ],
    }
    return document


def test_a_large_catalog_answers_a_page_not_the_whole() -> None:
    document = synthetic_catalog(3000)

    page = browse_list(document, "tables", limit=50)
    graph = concept_neighbourhood(document, "concept:c0001")

    assert page["total"] == 3000 and len(page["items"]) == 50
    assert len(json.dumps(page, ensure_ascii=False)) < 20_000
    assert {node["id"] for node in graph["nodes"]} == {
        "concept:c0000", "concept:c0001", "concept:c0002"
    }
    for edge in graph["edges"]:
        assert len(edge["keys"]) <= 10 and edge["keys_total"] >= len(edge["keys"])
    assert len(json.dumps(graph, ensure_ascii=False)) < 20_000


def test_a_concept_on_very_many_tables_keeps_its_edges_short() -> None:
    document = synthetic_catalog(3000, concepts=2, domains=1)

    graph = concept_neighbourhood(document, "concept:c0000")

    for edge in graph["edges"]:
        assert len(edge["keys"]) == 10 and edge["keys_total"] >= 1500
        assert all(len(key["to"]) <= 10 and key["to_total"] >= 1500 for key in edge["keys"])
    assert len(json.dumps(graph, ensure_ascii=False)) < 20_000
