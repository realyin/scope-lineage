"""One table identity for every layer (audit WP5, D1: the configuration decides).

Four modules used to answer "are these two spellings one table?" four ways: the metadata
layer kept the last two segments of any name, the table cards grouped by suffix, the
glossary bucketed by the last two segments exactly, and the catalog view kept the last
two segments without dropping quotes. The visible results were a glossary that filed one
catalog's codes under another catalog's table, a bare ``orders`` that was one card but
two glossary owners, and a metadata layer that merged two catalogs' columns without a
word. The target table was not lower-cased either, so ``SPARK_CATALOG.mart.y`` kept its
catalog and ``MART.Y`` and ``mart.y`` were two tables.

Now ``scope_lineage.table_identity`` owns both halves: normalization (quotes off, lower
case, a leading catalog dropped only when ``SCOPE_LINEAGE_CATALOG_PREFIXES`` names it)
and grouping (the dotted-suffix rule; a less qualified name joins only the one host it
could be). Every fixture is synthetic.
"""

from __future__ import annotations

import json

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.metadata.column_samples import ColumnSamples
from scope_lineage.metadata.metadata_patch import (
    apply_metadata_patch_to_document,
    load_metadata_patch,
)
from scope_lineage.metadata.schema_metadata import (
    lookup_columns,
    normalize_schema_map,
    normalize_table_name,
    strip_catalog_prefix,
)
from scope_lineage.render.catalog_view import catalog_table_name
from scope_lineage.render.glossary import build_glossary
from scope_lineage.render.semantic_profile import build_semantic_profile, card_lookup
from scope_lineage.render.table_cards import build_table_cards, table_groups
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.scope.task_lineage import parse_task_lineage
from scope_lineage.table_identity import (
    TableResolver,
    ambiguous_names,
    canonical_table_name,
    group_spellings,
)

ENV = "SCOPE_LINEAGE_CATALOG_PREFIXES"

# The four-task corpus of the audit (A §2.4): a writer of ods.orders, a reader of a bare
# orders, and two catalogs' ods.t each writing their own codes.
CORPUS = {
    "w_orders": (
        "INSERT OVERWRITE TABLE ods.orders SELECT id, "
        "CASE WHEN s = 1 THEN 'paid' ELSE 'open' END AS status FROM src.raw",
        {"src.raw": ["id", "s"]},
    ),
    "r_orders": (
        "INSERT OVERWRITE TABLE dw.o2 SELECT id, status FROM orders WHERE status = 'paid'",
        {"orders": ["id", "status"]},
    ),
    "w_cat1": (
        "INSERT OVERWRITE TABLE cat1.ods.t SELECT id, "
        "CASE WHEN k = 1 THEN 'A' ELSE 'B' END AS flag FROM src.a",
        {"src.a": ["id", "k"]},
    ),
    "w_cat2": (
        "INSERT OVERWRITE TABLE cat2.ods.t SELECT id, "
        "CASE WHEN k = 9 THEN 'X' ELSE 'Y' END AS flag FROM src.b",
        {"src.b": ["id", "k"]},
    ),
}


@pytest.fixture(autouse=True)
def _no_configured_catalogs(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)


def _document(sql: str, task: str, schema=None) -> dict:
    return to_lineage_dict(parse_scope_lineage(sql, task, schema=schema))


def _corpus() -> list[dict]:
    return [
        _document(sql, name, normalize_schema_map(schema))
        for name, (sql, schema) in CORPUS.items()
    ]


def _values(glossary: dict, column: str) -> dict[str, set]:
    found: dict[str, set] = {}
    for item in glossary["values"]:
        if item["column"] == column:
            found.setdefault(item["column_ref"], set()).add(item["value"])
    return found


# ------------------------------------------------------------------ the module itself


def test_normalization_drops_quotes_and_case_and_only_a_configured_catalog(monkeypatch):
    assert canonical_table_name("`ODS`.`Orders`") == "ods.orders"
    assert canonical_table_name(" Ods.Orders ") == "ods.orders"
    # Not configured: a three-part name is kept whole (D1).
    assert canonical_table_name("cat1.ods.t") == "cat1.ods.t"
    monkeypatch.setenv(ENV, "spark_catalog")
    assert canonical_table_name("SPARK_CATALOG.mart.y") == "mart.y"
    assert canonical_table_name("`Spark_Catalog`.`MART`.`Y`") == "mart.y"
    assert canonical_table_name("other.mart.y") == "other.mart.y"
    # Two segments are db.table, never catalog.db.
    assert canonical_table_name("spark_catalog.y") == "spark_catalog.y"


def test_an_unbound_parameter_keeps_its_spelling():
    assert canonical_table_name("ODS.${Run_Table}") == "ods.${Run_Table}"


def test_two_catalogs_are_two_groups_and_the_two_part_name_is_ambiguous():
    names = ["cat1.ods.t", "cat2.ods.t", "ods.t"]
    groups, ambiguous = group_spellings(names)
    assert sorted(groups) == [["cat1.ods.t"], ["cat2.ods.t"], ["ods.t"]]
    assert ambiguous == {"ods.t"}
    assert ambiguous_names(names) == {"ods.t"}


def test_a_less_qualified_name_joins_its_one_host():
    groups, ambiguous = group_spellings(["spark_catalog.dwd.t", "dwd.t", "t"])
    assert groups == [["dwd.t", "spark_catalog.dwd.t", "t"]]
    assert ambiguous == set()


def test_the_resolver_takes_an_exact_spelling_first_and_a_unique_suffix_second():
    resolver = TableResolver(["cat1.ods.t", "cat2.ods.t", "ods.orders"])
    assert resolver.primary("CAT2.ODS.T") == "cat2.ods.t"
    assert resolver.primary("orders") == "ods.orders"
    assert resolver.primary("ods.t") is None  # two hosts: no guess
    assert resolver.primary("dwd.orders") is None


# ------------------------------------------------------------------ the glossary


def test_the_glossary_keeps_two_catalogs_apart_and_folds_the_bare_reader_in():
    glossary = build_glossary(_corpus(), artifact_root="corpus")

    flags = _values(glossary, "flag")
    assert flags == {"cat1.ods.t.flag": {"A", "B"}, "cat2.ods.t.flag": {"X", "Y"}}

    statuses = _values(glossary, "status")
    assert "orders.status" not in statuses
    assert statuses["ods.orders.status"] == {"open", "paid"}


def test_the_glossary_counts_the_bare_reader_and_its_host_as_one_table():
    glossary = build_glossary(_corpus(), artifact_root="corpus")
    term = next(item for item in glossary["terms"] if item["column"] == "status")
    assert "orders" not in term.get("tables_without_comment", [])


# ------------------------------------------------------------------ the table cards


def test_the_cards_agree_with_the_glossary():
    """Sentinel: the cards already grouped this corpus right; they must keep doing so."""
    cards = build_table_cards([build_semantic_profile(document) for document in _corpus()])
    tables = {card["table"]: card["aliases"] for card in cards["tables"]}
    assert tables["cat1.ods.t"] == []
    assert tables["cat2.ods.t"] == []
    assert tables["ods.orders"] == ["orders"]
    assert "ods.t" not in tables


def test_a_quoted_upper_case_target_and_its_lower_case_reader_are_one_card():
    writer = _document(
        "INSERT OVERWRITE TABLE `ODS`.`Orders` SELECT id, amt FROM src.a", "w"
    )
    reader = _document("INSERT OVERWRITE TABLE dw.r SELECT id, amt FROM ods.orders", "r")
    cards = build_table_cards([build_semantic_profile(writer), build_semantic_profile(reader)])
    orders = [card for card in cards["tables"] if card["table"].endswith("orders")]
    assert [card["table"] for card in orders] == ["ods.orders"]
    assert orders[0]["produced_by"] and orders[0]["consumed_by"]


def test_both_card_lookups_resolve_through_the_one_rule():
    cards = {
        "tables": [
            {"table": "cat1.ods.t", "aliases": []},
            {"table": "cat2.ods.t", "aliases": []},
            {"table": "ods.orders", "aliases": ["orders"]},
        ]
    }
    lookup = card_lookup(cards)
    assert lookup("cat2.ods.t")["table"] == "cat2.ods.t"
    assert lookup("ODS.ORDERS")["table"] == "ods.orders"
    assert lookup("ods.t") is None
    assert table_groups(["cat1.ods.t", "cat2.ods.t", "ods.t"]) == {
        "cat1.ods.t": ["cat1.ods.t"],
        "cat2.ods.t": ["cat2.ods.t"],
        "ods.t": ["ods.t"],
    }


# ------------------------------------------------------------------ the metadata layer


def test_metadata_keeps_two_catalogs_columns_apart():
    schema = normalize_schema_map({"cat1.ods.t": ["a1", "a2"], "cat2.ods.t": ["b1"]})
    document = _document("INSERT INTO mart.x SELECT b1 FROM cat2.ods.t", "t", schema)
    metadata = document["related_metadata"]["input_tables"]["cat2.ods.t"]
    assert [item["name"] for item in metadata["declared_columns"]] == ["b1"]


def test_two_configured_catalogs_folding_to_one_name_are_a_metadata_conflict(monkeypatch):
    monkeypatch.setenv(ENV, "cat1,cat2")
    schema = normalize_schema_map({"cat1.ods.t": ["a1", "a2"], "cat2.ods.t": ["b1"]})
    assert list(schema["ods.t"]) == ["a1", "a2"]  # the first spelling is kept whole
    conflicts = [item for item in schema.metadata_conflicts if item.get("table") == "ods.t"]
    assert conflicts and conflicts[0]["reason"] == "catalog_collision"

    result = parse_task_lineage(
        "INSERT INTO mart.x SELECT b1 FROM cat2.ods.t", task_name="t", schema=schema
    )
    coverage = result.diagnostics["metadata_coverage"]
    assert [item["reason"] for item in coverage["metadata_conflicts"]] == ["catalog_collision"]


def test_metadata_for_db_table_still_describes_an_unconfigured_catalog_read():
    """Sentinel: an export keyed ``db.table`` must keep matching ``catalog.db.table`` SQL."""
    schema = normalize_schema_map({"ods.t": ["id", "amt"]})
    assert lookup_columns(schema, "lake.ods.t") == ["id", "amt"]
    document = _document("INSERT INTO mart.x SELECT * FROM lake.ods.t", "t", schema)
    assert document["related_metadata"]["input_tables"]["lake.ods.t"]["declared_columns"]


def test_metadata_for_one_catalog_still_describes_its_db_table_read():
    schema = normalize_schema_map({"lake.ods.t": ["id", "amt"]})
    assert lookup_columns(schema, "ods.t") == ["id", "amt"]
    two = normalize_schema_map({"cat1.ods.t": ["a"], "cat2.ods.t": ["b"]})
    assert lookup_columns(two, "ods.t") is None


def test_metadata_helpers_go_through_the_module(monkeypatch):
    assert normalize_table_name("cat1.ods.t") == "cat1.ods.t"
    assert normalize_table_name("`ODS`.`Orders`") == "ods.orders"
    monkeypatch.setenv(ENV, "spark_catalog")
    assert strip_catalog_prefix("SPARK_CATALOG.ods.t") == "ods.t"
    assert normalize_table_name("SPARK_CATALOG.ods.t") == "ods.t"
    # A db.table.column reference keeps its three parts when nothing is configured to drop.
    assert strip_catalog_prefix("ods.t.col") == "ods.t.col"


# ------------------------------------------------------------------ the target table


def test_an_upper_case_configured_catalog_is_dropped_from_the_target(monkeypatch):
    monkeypatch.setenv(ENV, "spark_catalog")
    document = _document("INSERT OVERWRITE TABLE SPARK_CATALOG.mart.y SELECT id FROM ods.t", "t")
    assert document["target_table"] == "mart.y"


def test_upper_and_lower_case_spellings_of_a_target_are_one_state():
    result = parse_task_lineage(
        "INSERT OVERWRITE TABLE MART.Y SELECT id FROM ods.t;\n"
        "INSERT INTO TABLE mart.y SELECT id FROM ods.u;",
        task_name="t",
    )
    assert list(result.final_table_states) == ["mart.y"]


# ------------------------------------------------------------------ the catalog view


def test_the_catalog_match_key_drops_quotes_and_case():
    assert catalog_table_name("`ODS`.`Orders`") == "ods.orders"
    assert catalog_table_name("demo_dwd.t") == "demo_dwd.t"
    assert catalog_table_name("t") == "t"


def test_the_catalog_match_key_drops_a_configured_catalog(monkeypatch):
    monkeypatch.setenv(ENV, "spark_catalog")
    assert catalog_table_name("SPARK_CATALOG.demo_dwd.t") == "demo_dwd.t"


# ------------------------------------------------------------------ the other lookups


def test_a_patch_for_db_table_answers_an_unconfigured_catalog_read(tmp_path):
    """Sentinel: the patch key follows the same rule as the metadata lookup."""
    path = tmp_path / "patch.json"
    path.write_text(
        json.dumps(
            {"doc_format": "metadata-patch/1", "columns": {"ods.t.amt": {"comment": "amount"}}}
        ),
        encoding="utf-8",
    )
    patch = load_metadata_patch([str(path)])
    schema = normalize_schema_map({"ods.t": ["id", "amt"]})
    document = _document("INSERT INTO mart.x SELECT id, amt FROM lake.ods.t", "t", schema)
    apply_metadata_patch_to_document(document, patch)
    assert patch.unmatched() == []


def test_samples_for_two_catalogs_stay_with_their_own_tables():
    samples = ColumnSamples()
    samples.add("cat1.ods.t", "flag", "A")
    samples.add("cat2.ods.t", "flag", "X")
    assert samples.values(["CAT2.ods.t"], "flag") == ["X"]
    assert samples.values(["ods.t"], "flag") == []  # either catalog: neither
    single = ColumnSamples()
    single.add("ods.t", "flag", "A")
    assert single.values(["spark_catalog.ods.t"], "flag") == ["A"]


# The skill script `query.py` is stdlib-only (a skill bundle may not import the package), so
# it keeps its own copy of the suffix rule; this pins the copy to the package's answer.
_SPELLINGS = ["t", "ods.t", "dwd.t", "cat.ods.t", "cat2.ods.t", "ods.t2", "s", "ods.st", ""]


def test_the_skill_query_script_s_suffix_rule_is_the_package_s():
    import importlib.util
    from pathlib import Path

    from scope_lineage.table_identity import same_table

    script = Path(__file__).resolve().parents[2] / "skills/scope-lineage/scripts/query.py"
    spec = importlib.util.spec_from_file_location("skill_query", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    disagree = [
        (left, right)
        for left in _SPELLINGS
        for right in _SPELLINGS
        if module._same_table(left, right) != same_table(left, right)
    ]
    assert disagree == []
