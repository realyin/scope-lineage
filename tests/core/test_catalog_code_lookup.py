"""Where a code set's values live (``lookup``) and how a column is translated (``code_sets``).

A code set whose values sit in a dictionary table says so with ``lookup``: the table, the
code and meaning columns, and the constant condition that picks this set's rows out of a
table shared by many. A binding says which code sets translate its column, in order
(look in the first, then the next). The fixture is the demo with one synthetic
dictionary table holding two code sets, and one column translated by both.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scope_lineage.catalog import (
    build_ontology,
    check_fragment,
    digest_tables,
    load_catalog,
    merge_fragments,
    ontology_findings,
    validate_catalog,
)
from scope_lineage.cli import main
from scope_lineage.render.catalog_evidence import attach_evidence
from scope_lineage.render.catalog_gaps import concept_gaps
from scope_lineage.render.catalog_pages import render_catalog_pages
from scope_lineage.render.catalog_query import query_catalog, render_query_text
from scope_lineage.render.table_cards import DOC_FORMAT as TABLES_DOC_FORMAT
from scope_lineage.semantics import render_semantic_pages

from .catalog_demo import copy_demo, item, mutate, rules
from .table_semantics_demo import EXAMPLE, read_json
from .test_catalog_fragment import _example

DICT_TABLE = "demo_dim.dim_code_dict"
WAIVER_TABLE = "demo_dwd.dwd_collection_fee_waiver_di"
REASON = {
    "id": "code:waiver_reason",
    "name": "豁免原因",
    "values": [],
    "lookup": {
        "table": "DEMO_DIM.Dim_Code_Dict",
        "code_column": "code_val",
        "meaning_columns": [
            {"column": "code_desc", "lang": "zh"},
            {"column": "code_desc_en", "lang": "en"},
        ],
        "key_column": "dict_key",
        "filter": {"code_type": "WaiverReason"},
        "valid_from": "valid_begin",
        "valid_to": "valid_end",
    },
    "status": "drafted",
    "source": "sql",
}
CHANNEL = {
    "id": "code:waiver_channel",
    "name": "豁免渠道",
    "values": [],
    "lookup": {
        "table": DICT_TABLE,
        "code_column": "code_val",
        "meaning_columns": [{"column": "code_desc", "lang": "zh"}],
        "filter": {"code_type": "WaiverChannel"},
    },
}
REASON_ATTRIBUTE = {
    "id": "attr:fee_waiver.reason",
    "name": "豁免原因",
    "definition": "Why the waiver was granted.",
    "category": "descriptive",
    "type": "string",
    "code_set": "code:waiver_reason",
}
REASON_BINDING = {
    "column": "reason_cd",
    "to": "attribute",
    "ref": "attr:fee_waiver.reason",
    "code_sets": ["code:waiver_reason", "code:waiver_channel"],
}


def _add_lookups(root: Path) -> Path:
    """The demo, plus two dictionary code sets and one column translated by both."""
    mutate(root, "code_sets.yaml", lambda d: d["code_sets"].extend(copy.deepcopy([REASON, CHANNEL])))
    mutate(
        root, "concepts/collection.yaml",
        lambda d: item(d["concepts"], "concept:fee_waiver")["attributes"].append(
            copy.deepcopy(REASON_ATTRIBUTE)
        ),
    )
    mutate(
        root, "mapping/collection.json",
        lambda d: _waiver(d)["bindings"].insert(3, copy.deepcopy(REASON_BINDING)),
    )
    return root


def _waiver(mapping: dict) -> dict:
    return item(mapping["representations"], "table", WAIVER_TABLE)


def _binding(mapping: dict, column: str) -> dict:
    return item(_waiver(mapping)["bindings"], "column", column)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return _add_lookups(copy_demo(tmp_path))


@pytest.fixture(scope="module")
def document(tmp_path_factory) -> dict:
    return build_ontology(load_catalog(_add_lookups(copy_demo(tmp_path_factory.mktemp("lookup")))))


# ------------------------------------------------------------------ schema and checks


def test_a_lookup_and_ordered_code_sets_are_legal(root: Path) -> None:
    report = validate_catalog(load_catalog(root))

    assert report.errors == []
    assert "empty_code_set" not in rules(report.warnings), "the values live in the table"


def test_valid_from_needs_valid_to(root: Path) -> None:
    mutate(root, "code_sets.yaml", lambda d: item(d["code_sets"], "code:waiver_reason")["lookup"].pop("valid_to"))

    errors = validate_catalog(load_catalog(root)).errors

    assert [(e.rule, e.at) for e in errors] == [("schema", "code_sets[4].lookup")]


def test_a_lookup_needs_its_code_and_meaning_columns(root: Path) -> None:
    mutate(root, "code_sets.yaml", lambda d: item(d["code_sets"], "code:waiver_channel")["lookup"].pop("code_column"))

    errors = validate_catalog(load_catalog(root)).errors

    assert [(e.rule, e.at) for e in errors] == [("schema", "code_sets[5].lookup")]


def test_a_code_set_without_values_or_lookup_still_warns(root: Path) -> None:
    mutate(root, "code_sets.yaml", lambda d: item(d["code_sets"], "code:waiver_channel").pop("lookup"))

    warnings = validate_catalog(load_catalog(root)).warnings

    assert [w.at for w in warnings if w.rule == "empty_code_set"] == ["code:waiver_channel"]


def test_binding_code_sets_must_be_code_sets(root: Path) -> None:
    mutate(root, "mapping/collection.json", lambda d: _binding(d, "reason_cd")["code_sets"].append("code:nowhere"))

    errors = validate_catalog(load_catalog(root)).errors

    assert rules(errors) == ["binding_code_set"]
    assert errors[0].at == f"{WAIVER_TABLE}.reason_cd"
    assert "code:nowhere" in errors[0].message


def test_the_attributes_code_set_belongs_in_the_bindings_list(root: Path) -> None:
    mutate(root, "mapping/collection.json", lambda d: _binding(d, "reason_cd").update(code_sets=["code:waiver_channel"]))

    report = validate_catalog(load_catalog(root))

    assert report.errors == []
    found = [w for w in report.warnings if w.rule == "binding_code_sets_miss_attribute"]
    assert [w.at for w in found] == [f"{WAIVER_TABLE}.reason_cd"]
    assert "code:waiver_reason" in found[0].message


def test_a_binding_without_code_sets_is_not_asked_for_them(root: Path) -> None:
    mutate(root, "mapping/collection.json", lambda d: _binding(d, "reason_cd").pop("code_sets"))

    assert "binding_code_sets_miss_attribute" not in rules(validate_catalog(load_catalog(root)).warnings)


# ------------------------------------------------------------------------------ build


def test_build_carries_the_lookup_with_the_table_in_lower_case(document: dict) -> None:
    reason = item(document["code_sets"], "code:waiver_reason")

    assert reason["lookup"] == {
        "table": DICT_TABLE,
        "code_column": "code_val",
        "meaning_columns": [
            {"column": "code_desc", "lang": "zh"},
            {"column": "code_desc_en", "lang": "en"},
        ],
        "key_column": "dict_key",
        "filter": {"code_type": "WaiverReason"},
        "valid_from": "valid_begin",
        "valid_to": "valid_end",
    }
    assert list(reason) == ["id", "name", "values", "lookup", "status", "source", "evidence"]
    assert "lookup" not in item(document["code_sets"], "code:gender")


def test_build_carries_the_binding_code_sets_in_order(document: dict) -> None:
    rep = item(document["representations"], "table", WAIVER_TABLE)
    binding = item(rep["bindings"], "column", "reason_cd")

    assert binding["code_sets"] == ["code:waiver_reason", "code:waiver_channel"]
    assert "code_sets" not in item(rep["bindings"], "column", "waiver_type")


def test_the_built_document_fits_its_schema(document: dict) -> None:
    assert ontology_findings(document) == []


# ------------------------------------------------------------------- fragment and merge


def _fragment() -> dict:
    fragment = _example()
    fragment["code_sets"].append(copy.deepcopy(CHANNEL))
    fragment["representations"][0]["bindings"][0]["code_sets"] = ["code:waiver_channel"]
    return fragment


def test_a_fragment_may_carry_lookups_and_binding_code_sets() -> None:
    assert check_fragment(_fragment(), "f.json") == []


def test_merging_a_lookup_again_is_unchanged_and_a_different_one_conflicts(root: Path) -> None:
    same, other = _fragment(), _fragment()
    item(other["code_sets"], "code:waiver_channel")["lookup"]["filter"] = {"code_type": "Other"}

    result = merge_fragments(load_catalog(root), [("same.json", same), ("other.json", other)])

    conflicts = [c for c in result.conflicts if c.at == "code:waiver_channel"]
    assert [c.file for c in conflicts] == ["other.json"]
    assert result.added["code_set"] == 1  # the fragment's own pay_method, once


# ------------------------------------------------------------------------------ query


def test_query_table_answers_for_a_dictionary_table(document: dict) -> None:
    result = query_catalog(document, "table", "spark_catalog.DEMO_DIM.dim_code_dict")

    assert result["matches"] == [
        {
            "table": DICT_TABLE,
            "code_sets": [
                {
                    "id": "code:waiver_channel",
                    "name": "豁免渠道",
                    "code_column": "code_val",
                    "meaning_columns": [{"column": "code_desc", "lang": "zh"}],
                    "filter": {"code_type": "WaiverChannel"},
                },
                {
                    "id": "code:waiver_reason",
                    "name": "豁免原因",
                    "code_column": "code_val",
                    "meaning_columns": [
                        {"column": "code_desc", "lang": "zh"},
                        {"column": "code_desc_en", "lang": "en"},
                    ],
                    "key_column": "dict_key",
                    "filter": {"code_type": "WaiverReason"},
                    "valid_from": "valid_begin",
                    "valid_to": "valid_end",
                },
            ],
        }
    ]
    text = render_query_text(result)
    assert DICT_TABLE in text and "码值来源" in text
    assert "code_type = 'WaiverReason'" in text


def test_query_table_exits_zero_for_a_dictionary_table(tmp_path: Path, root: Path, capsys) -> None:
    out = tmp_path / "built"
    assert main(["catalog", "build", str(root), "--out", str(out)]) == 0

    code = main(["catalog", "query", str(out / "ontology.json"), "table", DICT_TABLE, "--json"])

    assert code == 0
    assert json.loads(capsys.readouterr().out.split("\n", 1)[1])["matches"]


def test_a_represented_table_that_is_also_a_source_lists_its_code_sets(root: Path) -> None:
    mutate(root, "code_sets.yaml", lambda d: item(d["code_sets"], "code:waiver_channel")["lookup"].update(table=WAIVER_TABLE))
    built = build_ontology(load_catalog(root))

    (match,) = query_catalog(built, "table", WAIVER_TABLE)["matches"]

    assert match["concept"]["id"] == "concept:fee_waiver"
    assert [s["id"] for s in match["code_sets"]] == ["code:waiver_channel"]


def test_query_column_names_the_code_sets_a_dictionary_column_serves(document: dict) -> None:
    (code,) = query_catalog(document, "column", f"{DICT_TABLE}.CODE_VAL")["matches"]
    (key,) = query_catalog(document, "column", f"{DICT_TABLE}.dict_key")["matches"]

    assert code["table"] == DICT_TABLE and code["column"] == "CODE_VAL"
    assert [(s["id"], s["role"]) for s in code["code_sets"]] == [
        ("code:waiver_channel", "code_column"),
        ("code:waiver_reason", "code_column"),
    ]
    assert [(s["id"], s["role"]) for s in key["code_sets"]] == [("code:waiver_reason", "key_column")]
    assert "豁免原因" in render_query_text(query_catalog(document, "column", f"{DICT_TABLE}.dict_key"))
    assert query_catalog(document, "column", f"{DICT_TABLE}.nothing")["matches"] == []


def test_a_bound_column_answers_with_its_code_sets_in_order(document: dict) -> None:
    (match,) = query_catalog(document, "column", f"{WAIVER_TABLE}.reason_cd")["matches"]

    assert [s["id"] for s in match["code_sets"]] == ["code:waiver_reason", "code:waiver_channel"]
    assert match["code_sets"][0]["filter"] == {"code_type": "WaiverReason"}
    text = render_query_text(query_catalog(document, "column", f"{WAIVER_TABLE}.reason_cd"))
    assert "先查 豁免原因，查不到查 豁免渠道" in text


def test_query_attribute_answers_with_the_lookup(document: dict) -> None:
    result = query_catalog(document, "attribute", "attr:fee_waiver.reason")
    (match,) = result["matches"]

    assert match["code_set"]["id"] == "code:waiver_reason"
    assert match["code_set"]["values"] == []
    assert match["code_set"]["table"] == DICT_TABLE
    assert match["code_set"]["filter"] == {"code_type": "WaiverReason"}
    text = render_query_text(result)
    assert "码值：查 demo_dim.dim_code_dict，条件 code_type = 'WaiverReason'" in text
    assert "码值：\n" not in text


def test_query_attribute_prints_no_empty_code_line(root: Path) -> None:
    mutate(root, "code_sets.yaml", lambda d: item(d["code_sets"], "code:waiver_reason").pop("lookup"))
    built = build_ontology(load_catalog(root))

    text = render_query_text(query_catalog(built, "attribute", "attr:fee_waiver.reason"))

    assert not [line for line in text.splitlines() if line.startswith("  码值：")]


# ------------------------------------------------------------------- digest and gaps


def test_digest_counts_a_dictionary_table_as_a_code_set_source(root: Path) -> None:
    dictionary = copy.deepcopy(read_json(EXAMPLE))
    dictionary["table"] = DICT_TABLE

    digest = digest_tables([dictionary], load_catalog(root))

    assert digest["catalog"]["tables_without_representation"] == []
    assert digest["catalog"]["code_set_sources"] == {
        DICT_TABLE: ["code:waiver_channel", "code:waiver_reason"]
    }
    assert digest["tables"][0]["catalog"] == {
        "represented": False,
        "code_sets": ["code:waiver_channel", "code:waiver_reason"],
    }


def test_a_code_set_with_a_lookup_is_not_a_missing_codes_gap(document: dict) -> None:
    from scope_lineage.render.catalog_view import CatalogView

    gaps = concept_gaps(CatalogView(document), "concept:fee_waiver")

    assert "attr:fee_waiver.reason" not in gaps.missing_codes


# ------------------------------------------------------------------------------ pages


def test_code_sets_page_shows_values_lookups_and_the_columns_using_them(document: dict) -> None:
    page = render_catalog_pages(document)["code_sets.md"]

    assert page.startswith("# 码值集\n")
    reason = page.split("## 豁免原因")[1].split("\n## ")[0]
    assert (
        "查 `demo_dim.dim_code_dict`，条件 `code_type = 'WaiverReason'`：码 `code_val`，"
        "含义 `code_desc`（zh）、`code_desc_en`（en），代理键 `dict_key`，"
        "有效期 `valid_begin` ~ `valid_end`"
    ) in reason
    assert f"`{WAIVER_TABLE}.reason_cd`（先查 豁免原因，查不到查 豁免渠道）" in reason
    gender = page.split("## 性别")[1].split("\n## ")[0]
    assert "F=female" in gender


def test_a_code_set_with_values_and_a_lookup_shows_the_lookup_once(root: Path) -> None:
    mutate(
        root, "code_sets.yaml",
        lambda d: item(d["code_sets"], "code:waiver_reason").update(
            values=[{"value": "A", "meaning": "hardship"}]
        ),
    )
    page = render_catalog_pages(build_ontology(load_catalog(root)))["code_sets.md"]
    reason = page.split("## 豁免原因")[1].split("\n## ")[0]

    assert reason.count("查 `demo_dim.dim_code_dict`") == 1
    assert "| 取值 | A=hardship |" in reason


def test_filter_columns_come_out_sorted(root: Path) -> None:
    mutate(
        root, "code_sets.yaml",
        lambda d: item(d["code_sets"], "code:waiver_reason")["lookup"].update(
            filter={"z_kind": "X", "code_type": "WaiverReason"}
        ),
    )

    built = build_ontology(load_catalog(root))

    assert list(item(built["code_sets"], "code:waiver_reason")["lookup"]["filter"]) == [
        "code_type",
        "z_kind",
    ]


def test_index_links_the_code_sets_page_and_names_the_source_tables(document: dict) -> None:
    index = render_catalog_pages(document)["index.md"]

    section = index.split("## 码值集\n")[1].split("\n## ")[0]
    assert "[code_sets.md](code_sets.md)" in section
    assert f"`{DICT_TABLE}`" in section


def test_the_concept_page_shows_the_lookup_and_the_fallback_order(document: dict) -> None:
    page = render_catalog_pages(document)["concepts/fee_waiver.md"]
    row = next(line for line in page.splitlines() if line.startswith("| 豁免原因 "))

    assert "查 `demo_dim.dim_code_dict`，条件 `code_type = 'WaiverReason'`" in row
    assert f"`{WAIVER_TABLE}.reason_cd`（码值：先查 豁免原因，查不到查 豁免渠道）" in row


def test_a_dictionary_tables_semantic_page_links_its_code_sets(document: dict) -> None:
    dictionary = copy.deepcopy(read_json(EXAMPLE))
    dictionary["table"] = DICT_TABLE
    dictionary.pop("concept", None)

    page = render_semantic_pages([dictionary], ontology=document)[f"{DICT_TABLE}.md"]
    header = page.splitlines()[2]

    assert "本表是码值集[豁免渠道](../code_sets.md)、[豁免原因](../code_sets.md)的码值来源" in header


# --------------------------------------------------------------------------- evidence


def test_a_table_card_without_a_lookup_column_is_reported(document: dict) -> None:
    card = {
        "table": DICT_TABLE,
        "columns": [{"name": name} for name in ("code_val", "code_desc", "code_type", "dict_key")],
    }
    tables = {"doc_format": TABLES_DOC_FORMAT, "tables": [card]}

    built = attach_evidence(document, tables=tables)

    assert built["evidence"]["code_sets"] == {
        "code:waiver_reason": {
            "table": DICT_TABLE,
            "missing_columns": ["code_desc_en", "valid_begin", "valid_end"],
        }
    }
    assert ontology_findings(built) == []


def test_a_card_spelled_in_upper_case_still_matches(document: dict) -> None:
    """Hive names ignore case: a card named ``CAT.DB.TABLE`` is the built ``db.table``."""
    cards = [
        {"table": "SPARK_CATALOG.DEMO_DIM.DIM_CODE_DICT", "columns": [{"name": "code_val"}]},
        {"table": WAIVER_TABLE.upper(), "comment": "Waivers", "columns": []},
    ]

    built = attach_evidence(document, tables={"doc_format": TABLES_DOC_FORMAT, "tables": cards})

    assert set(built["evidence"]["code_sets"]) == {"code:waiver_channel", "code:waiver_reason"}
    assert built["evidence"]["representations"][WAIVER_TABLE]["table_comment"] == "Waivers"


def test_build_warns_about_a_lookup_column_the_card_lacks(tmp_path: Path, root: Path, capsys) -> None:
    card = {"table": DICT_TABLE, "columns": [{"name": "code_val"}, {"name": "code_desc"}]}
    tables = tmp_path / "tables.json"
    tables.write_text(json.dumps({"doc_format": TABLES_DOC_FORMAT, "tables": [card]}), encoding="utf-8")

    code = main(["catalog", "build", str(root), "--out", str(tmp_path / "built"), "--tables", str(tables)])

    assert code == 0
    warnings = [line for line in capsys.readouterr().err.splitlines() if "lookup_column_missing" in line]
    assert len(warnings) == 2  # both code sets filter on code_type, which the card lacks
    assert "code:waiver_reason" in warnings[1] and "code_type" in warnings[1]


def test_without_lookups_the_evidence_has_no_code_sets_block(document: dict) -> None:
    plain = {**document, "code_sets": [s for s in document["code_sets"] if "lookup" not in s]}

    built = attach_evidence(plain, tables={"doc_format": TABLES_DOC_FORMAT, "tables": []})

    assert "code_sets" not in built["evidence"]
