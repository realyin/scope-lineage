"""N6: the value dictionary hangs its terms on CONCEPTS.

``terms[]`` merges comments by bare column NAME, which is the only thing the dictionary
alone can key on -- and it is one name short of the question a reviewer actually asks.
``ods.app_order.pay_status``, ``ods.web_order.pay_status`` and
``ods.pos_order.pay_status`` are the same *attribute of one concept* whenever the
ontology says those three tables are three representations of one order; answering the
same code three times is transcription, and answering it under one name that is not a
table is the thing that makes the answer re-usable.

So ``glossary --ontology <ontology.json>`` adds a concept layer over the same facts:

- ``concept_terms[]``: one entry per (concept, attribute), the term facts merged across
  the concept's representation tables, carrying the value entries of those columns;
- ``terms[]`` entries back-link the concept attributes they feed;
- an overrides key ``concept:<id>.<attribute>=<value>`` answers every source column of
  that attribute at once -- weaker than a key that names a table, stronger than the
  ``*.<column>`` family key, because a concept is a claim and a column name is a
  coincidence;
- the form asks one concept section instead of one family / per-table row each.

Without ``--ontology`` nothing here happens: the dictionary is the document it was.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from scope_lineage.cli import main
from scope_lineage.contract import to_lineage_dict
from scope_lineage.metadata.schema_metadata import SchemaMap
from scope_lineage.render.glossary import (
    apply_glossary,
    build_glossary,
    render_glossary_markdown,
)
from scope_lineage.render.glossary_markdown import CONFLICT_MARK
from scope_lineage.render.glossary_template import (
    build_overrides_template,
    render_overrides_template_markdown,
)
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.scope.scope_builder import parse_scope_lineage


CONFIRMATIONS = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "scope-lineage"
    / "scripts"
    / "confirmations.py"
)

# Three synthetic representations of one order, each pinning the same two codes.
TABLES = ("ods.app_order", "ods.web_order", "ods.pos_order")
TARGETS = ("mart.app_orders", "mart.web_orders", "mart.pos_orders")


def _schema(table: str, comment: str | None) -> SchemaMap:
    return SchemaMap(
        {table: ["order_id", "pay_status"]},
        column_details={
            table: [
                {"name": "order_id", "type": "bigint", "comment": None},
                {"name": "pay_status", "type": "string", "comment": comment},
            ]
        },
    )


def _document(table: str, target: str, comment: str | None, task: str) -> dict:
    sql = (
        f"INSERT INTO {target} SELECT o.order_id, o.pay_status FROM {table} o "
        "WHERE o.pay_status IN ('PAID', 'REFUND')"
    )
    return to_lineage_dict(parse_scope_lineage(sql, task, schema=_schema(table, comment)))


def _documents(comments=("Payment status", "Payment status", "Settlement state")) -> list:
    return [
        _document(table, target, comment, f"task_{index}")
        for index, (table, target, comment) in enumerate(zip(TABLES, TARGETS, comments))
    ]


def _ontology(attribute: str = "pay_status", sources=None) -> dict:
    """An ``ontology-json/2`` document, read by the dictionary as a plain dict."""
    sources = sources or [{"table": table, "column": "pay_status"} for table in TABLES]
    return {
        "doc_format": "ontology-json/2",
        "concepts": [
            {
                "id": "concept:order",
                "name": "Order",
                "kind": "event",
                "tables": [{"table": table, "role": "primary"} for table in TABLES],
                "attributes": [
                    {"stem": "order", "type": "bigint", "comment": None,
                     "sources": [{"table": TABLES[0], "column": "order_id"}]},
                    {"stem": attribute, "type": "string", "comment": None,
                     "sources": sources},
                ],
            }
        ],
        "tables": [
            {"id": table, "concepts": [{"id": "concept:order", "role": "primary"}]}
            for table in TABLES
        ],
    }


def _glossary(overrides=None, ontology=None, documents=None) -> dict:
    return build_glossary(
        documents if documents is not None else _documents(),
        artifact_root="corpus",
        overrides=overrides,
        ontology=ontology,
    )


def _attribute(glossary: dict, stem: str) -> dict:
    matches = [item for item in glossary["concept_terms"] if item["attribute"] == stem]
    assert matches, f"no concept attribute {stem}"
    return matches[0]


def _value(glossary: dict, column_ref: str, value: str) -> dict:
    return next(
        item
        for item in glossary["values"]
        if item["column_ref"] == column_ref and item["value"] == value
    )


# ------------------------------------------------------------------ concept_terms


def test_a_concept_attribute_merges_the_term_facts_of_its_three_tables() -> None:
    glossary = _glossary(ontology=_ontology())

    entry = _attribute(glossary, "pay_status")
    assert entry["concept"] == "concept:order"
    assert entry["name"] == "Order"
    assert entry["columns"] == [
        {"table": table, "column": "pay_status"} for table in sorted(TABLES)
    ]
    # Two tables say one thing and the third another: the same merge `terms[]` does,
    # taken over the attribute's own columns rather than over a bare name.
    assert [item["text"] for item in entry["comments"]] == [
        "Payment status",
        "Settlement state",
    ]
    assert entry["comments"][0]["tables"] == ["ods.app_order", "ods.web_order"]
    assert entry["conflict"] is True


def test_a_concept_attribute_carries_the_value_entries_of_its_columns() -> None:
    glossary = _glossary(ontology=_ontology())

    entry = _attribute(glossary, "pay_status")
    assert {(item["column_ref"], item["value"]) for item in entry["values"]} == {
        (f"{table}.pay_status", value) for table in TABLES for value in ("PAID", "REFUND")
    }


def test_a_term_back_links_the_concept_attributes_it_feeds() -> None:
    glossary = _glossary(ontology=_ontology())

    term = next(item for item in glossary["terms"] if item["column"] == "pay_status")
    assert term["concepts"] == [{"concept": "concept:order", "attribute": "pay_status"}]


def test_a_term_belonging_to_no_concept_stays_only_in_terms() -> None:
    # The concept's second attribute is written on a column this corpus never saw, so
    # `pay_status` feeds nothing: it keeps its entry in `terms[]` and links nowhere.
    glossary = _glossary(
        ontology=_ontology(
            attribute="settlement_state",
            sources=[{"table": "ods.ledger", "column": "settlement_state"}],
        )
    )

    term = next(item for item in glossary["terms"] if item["column"] == "pay_status")
    assert term["concepts"] == []
    assert [item["attribute"] for item in glossary["concept_terms"]] == [
        "order",
        "settlement_state",
    ]
    assert _attribute(glossary, "settlement_state")["values"] == []
    assert _attribute(glossary, "settlement_state")["comments"] == []


# ---------------------------------------------------------------------- overrides


def _concept_overrides(meaning: str = "已支付") -> dict:
    return {"values": {"concept:order.pay_status=PAID": {"meaning": meaning}}}


def test_a_concept_key_answers_every_source_that_observed_the_value() -> None:
    glossary = _glossary(overrides=_concept_overrides(), ontology=_ontology())

    for table in TABLES:
        assert _value(glossary, f"{table}.pay_status", "PAID")["meaning"]["text"] == "已支付"
    assert _value(glossary, f"{TABLES[0]}.pay_status", "REFUND")["meaning"] is None
    applied = glossary["overrides_applied"]
    assert applied["concept_expansions"] == [
        {"key": "concept:order.pay_status=PAID", "applied_to": 3}
    ]


def test_a_concept_key_beats_the_family_key_and_loses_to_an_exact_table_key() -> None:
    overrides = {
        "values": {
            "ods.app_order.pay_status=PAID": {"meaning": "这张表的口径"},
            "concept:order.pay_status=PAID": {"meaning": "概念口径"},
            "*.pay_status=PAID": {"meaning": "同名列口径"},
        }
    }
    glossary = _glossary(overrides=overrides, ontology=_ontology())

    assert _value(glossary, "ods.app_order.pay_status", "PAID")["meaning"]["text"] == (
        "这张表的口径"
    )
    assert _value(glossary, "ods.web_order.pay_status", "PAID")["meaning"]["text"] == (
        "概念口径"
    )
    applied = glossary["overrides_applied"]
    assert applied["concept_expansions"] == [
        {"key": "concept:order.pay_status=PAID", "applied_to": 2}
    ]
    # The family key reached nothing: the concept answered every table it could have.
    assert applied["family_expansions"] == []
    assert applied["unmatched"] == ["*.pay_status=PAID"]


def test_an_unknown_concept_or_attribute_is_reported_with_its_reason() -> None:
    overrides = {
        "values": {
            "concept:invoice.pay_status=PAID": {"meaning": "x"},
            "concept:order.no_such_attribute=PAID": {"meaning": "y"},
        }
    }
    applied = _glossary(overrides=overrides, ontology=_ontology())["overrides_applied"]

    assert applied["concept_unmatched"] == [
        {"key": "concept:invoice.pay_status=PAID", "reason": "unknown_concept"},
        {"key": "concept:order.no_such_attribute=PAID", "reason": "unknown_attribute"},
    ]
    # `unmatched` keeps its plain-string shape: a key that reached nothing is listed
    # there whatever kind of key it is.
    assert applied["unmatched"] == [
        "concept:invoice.pay_status=PAID",
        "concept:order.no_such_attribute=PAID",
    ]


def test_a_concept_key_without_an_ontology_reaches_nothing() -> None:
    applied = _glossary(overrides=_concept_overrides())["overrides_applied"]

    assert applied["unmatched"] == ["concept:order.pay_status=PAID"]
    assert "concept_expansions" not in applied


# --------------------------------------------------------------------- the form


def test_the_form_asks_one_concept_section_instead_of_family_or_per_table_rows() -> None:
    glossary = _glossary(ontology=_ontology())
    template = build_overrides_template(glossary, top=0)

    assert sorted(template["values"]) == [
        "concept:order.pay_status=PAID",
        "concept:order.pay_status=REFUND",
    ]
    markdown = render_overrides_template_markdown(template, glossary)
    assert "## `concept:order.pay_status`（Order·pay_status，出现在 3 张表）" in markdown
    # The family section and the per-table sections lost exactly those rows.
    assert "`*.pay_status`" not in markdown
    assert "ods.app_order.pay_status" not in markdown


def test_a_concept_section_is_asked_before_the_family_sections() -> None:
    documents = [
        *_documents(),
        *[
            to_lineage_dict(
                parse_scope_lineage(
                    f"INSERT INTO mart.q_{index} SELECT t.queue_code FROM {table} t "
                    "WHERE t.queue_code IN ('QA', 'QB')",
                    f"queue_{index}",
                    schema=SchemaMap(
                        {table: ["queue_code"]},
                        column_details={
                            table: [
                                {"name": "queue_code", "type": "string",
                                 "comment": "Queue code"}
                            ]
                        },
                    ),
                )
            )
            for index, table in enumerate(TABLES)
        ],
    ]
    glossary = _glossary(ontology=_ontology(), documents=documents)
    markdown = render_overrides_template_markdown(
        build_overrides_template(glossary, top=0), glossary
    )

    assert markdown.index("`concept:order.pay_status`") < markdown.index("`*.queue_code`")


def test_a_concept_row_unions_the_evidence_of_the_attributes_columns() -> None:
    # Only ONE representation table wrote the code table into its comment; the concept
    # row is the question about all three, so it shows that comment.
    glossary = _glossary(
        ontology=_ontology(),
        documents=_documents(comments=(None, None, "支付状态：PAID-已支付，REFUND-已退款")),
    )
    markdown = render_overrides_template_markdown(
        build_overrides_template(glossary, top=0), glossary
    )

    assert "已支付" in markdown
    assert "（来自 ods.pos_order）" in markdown


# ------------------------------------------------------------------- glossary.md


def test_the_markdown_lists_each_concept_attribute_with_its_value_counts() -> None:
    glossary = _glossary(overrides=_concept_overrides(), ontology=_ontology())
    markdown = render_glossary_markdown(glossary)

    assert "## 按概念" in markdown
    row = next(
        line for line in markdown.splitlines() if "`pay_status`" in line and "|" in line
    )
    assert "concept:order" in row and "Order" in row
    # Three tables x two codes, three of them answered by the one concept key.
    assert "3 / 6" in row
    # Two tables say one thing and the third another; the row says so rather than
    # resolving it, exactly as the column section does.
    assert CONFLICT_MARK in row


def test_without_an_ontology_the_dictionary_is_the_document_it_was() -> None:
    glossary = _glossary()

    assert list(glossary) == [
        "doc_format",
        "corpus",
        "terms",
        "values",
        "parameters",
        "overrides_applied",
    ]
    assert all("concepts" not in term for term in glossary["terms"])
    assert "按概念" not in render_glossary_markdown(glossary)


# --------------------------------------------------------------------- coverage


def test_the_glossary_coverage_block_counts_the_concept_attributes_of_this_task() -> None:
    documents = _documents()
    glossary = _glossary(overrides=_concept_overrides(), ontology=_ontology(), documents=documents)
    profile = apply_glossary(build_semantic_profile(documents[0]), glossary)

    coverage = profile["confidence"]["metadata_coverage"]["glossary"]
    assert coverage["concept_attributes_total"] == 2
    assert coverage["concept_attributes_with_confirmed_values"] == 1


def test_a_glossary_without_concepts_leaves_the_coverage_block_alone() -> None:
    documents = _documents()
    profile = apply_glossary(build_semantic_profile(documents[0]), _glossary(documents=documents))

    coverage = profile["confidence"]["metadata_coverage"]["glossary"]
    assert "concept_attributes_total" not in coverage


# ------------------------------------------------------------- the write-back key


@pytest.fixture()
def confirmations():
    spec = importlib.util.spec_from_file_location("confirmations", CONFIRMATIONS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_concept_value_target_routes_into_the_overrides_values(confirmations) -> None:
    item = {
        "回写目标": "值域:concept:order.pay_status=PAID",
        "答案": "已支付",
    }
    assert confirmations.target_of(item) == (
        "值域",
        "concept:order.pay_status=PAID",
    )
    written = confirmations.build_write_backs([item], by="owner", date="2026-09-23")
    assert written["values"]["concept:order.pay_status=PAID"] == {
        "meaning": "已支付",
        "confirmed_by": "owner",
        "date": "2026-09-23",
    }


# ------------------------------------------------------------------------- CLI


def test_the_cli_hangs_the_example_corpus_dictionary_on_its_own_ontology(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[2]
    corpus, ontology, out = tmp_path / "corpus", tmp_path / "onto", tmp_path / "dict"

    assert main([
        "parse",
        "--input-dir", str(root / "examples" / "tasks"),
        "--schema", str(root / "examples" / "metadata" / "schema_info.json"),
        "--schema-fallback",
        str(root / "examples" / "metadata" / "subscription_account_snapshot" / "source_tables"),
        "--target-ddl-metadata", str(root / "examples" / "metadata" / "target_tables"),
        "--out", str(corpus),
    ]) == 0
    assert main([
        "ontology", "--lineage", str(corpus), "--out", str(ontology), "--format", "json"
    ]) == 0
    assert main([
        "glossary",
        "--lineage", str(corpus),
        "--out", str(out),
        "--ontology", str(ontology / "ontology.json"),
    ]) == 0

    glossary = json.loads((out / "glossary.json").read_text(encoding="utf-8"))
    assert glossary["concept_terms"]
    assert all(
        entry["concept"].startswith("concept:") and entry["attribute"]
        for entry in glossary["concept_terms"]
    )
    assert "## 按概念" in (out / "glossary.md").read_text(encoding="utf-8")


def test_the_cli_rejects_an_ontology_path_that_is_not_there(tmp_path: Path, capsys) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "lineage.json").write_text(
        json.dumps(_documents()[0], ensure_ascii=False), encoding="utf-8"
    )

    assert main([
        "glossary",
        "--lineage", str(corpus / "lineage.json"),
        "--out", str(tmp_path / "dict"),
        "--ontology", str(tmp_path / "gone.json"),
    ]) == 2
    assert "--ontology" in capsys.readouterr().err
