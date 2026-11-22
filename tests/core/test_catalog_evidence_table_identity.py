"""Two table identities folded onto one catalog table are a conflict, not one table.

The catalog names a table ``db.table`` and a corpus name is matched by its last two
segments. With no catalog configured (D1), ``cat1.ods.t`` and ``cat2.ods.t`` are two
tables, yet both folded onto the catalog's ``ods.t`` and their writers were merged: a key
one of them proved was published as the catalog table's ``grain_proof``. The merge now
groups the names folded onto each catalog table with the table identity; more than one
group is the conflict ``table_identity_ambiguous`` and no lineage evidence.

Every fixture is synthetic.
"""

from __future__ import annotations

import pytest

from scope_lineage.catalog import build_ontology, load_catalog, validate_ontology_document
from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.catalog_evidence import attach_evidence, lineage_facts
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.table_identity import CATALOG_PREFIXES_ENV

from .catalog_demo import DEMO

TABLE = "demo_dwd.dwd_party_customer_info_df"
CUSTOMER = "demo_dwd.dwd_party_account_map_df"


def _write(target: str, *, grouped: bool) -> str:
    if grouped:
        return (
            f"INSERT OVERWRITE TABLE {target} SELECT customer_id, gender_cd, count(*) AS c "
            "FROM src.b GROUP BY customer_id, gender_cd"
        )
    return f"INSERT OVERWRITE TABLE {target} SELECT customer_id, gender_cd FROM src.a"


def _evidence(sqls: dict) -> dict:
    pairs = [(to_lineage_dict(parse_scope_lineage(sql, task)), None) for task, sql in sqls.items()]
    document = attach_evidence(build_ontology(load_catalog(DEMO)), lineage=lineage_facts(pairs))
    validate_ontology_document(document)
    return document["evidence"]


def test_two_catalogs_writing_one_catalog_table_are_a_conflict_without_evidence() -> None:
    evidence = _evidence({
        "t1": _write(f"cat1.{TABLE}", grouped=False),
        "t2": _write(f"cat2.{TABLE}", grouped=True),
    })

    entry = evidence["representations"][TABLE]
    assert entry == {
        "conflicts": [
            {
                "rule": "table_identity_ambiguous",
                "names": [f"cat1.{TABLE}", f"cat2.{TABLE}"],
            }
        ]
    }
    assert not [key for key in evidence["bindings"] if key.startswith(f"{TABLE}.")]


def test_a_reader_of_the_other_catalog_is_ambiguous_too() -> None:
    evidence = _evidence({
        "t1": _write(f"cat1.{TABLE}", grouped=True),
        "t2": f"INSERT OVERWRITE TABLE dw.x SELECT customer_id FROM cat2.{TABLE}",
    })

    entry = evidence["representations"][TABLE]
    assert "grain_proof" not in entry
    assert entry["conflicts"][0]["names"] == [f"cat1.{TABLE}", f"cat2.{TABLE}"]


def test_configured_catalogs_are_one_table_and_merge_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CATALOG_PREFIXES_ENV, "cat1,cat2")
    evidence = _evidence({
        "t1": _write(f"cat1.{TABLE}", grouped=False),
        "t2": _write(f"cat2.{TABLE}", grouped=True),
    })

    entry = evidence["representations"][TABLE]
    assert entry["producing_tasks"] == ["t1", "t2"]
    assert entry["grain_proof"]["task"] == "t2"
    assert all(c["rule"] != "table_identity_ambiguous" for c in entry.get("conflicts", []))


def test_sentinel_one_catalog_and_its_unqualified_spelling_are_one_table() -> None:
    evidence = _evidence({
        "t1": _write(f"spark_catalog.{TABLE}", grouped=True),
        "t2": _write(TABLE, grouped=False),
    })

    entry = evidence["representations"][TABLE]
    assert entry["producing_tasks"] == ["t1", "t2"]
    assert entry["grain_proof"]["task"] == "t1"
    assert all(c["rule"] != "table_identity_ambiguous" for c in entry.get("conflicts", []))


def test_sentinel_another_table_keeps_its_evidence() -> None:
    evidence = _evidence({
        "t1": _write(f"cat1.{TABLE}", grouped=False),
        "t2": _write(f"cat2.{TABLE}", grouped=True),
        "t3": f"INSERT OVERWRITE TABLE {CUSTOMER} SELECT customer_id FROM src.c",
    })

    assert evidence["representations"][CUSTOMER]["producing_tasks"] == ["t3"]


def test_the_governance_text_names_both_tables_and_the_way_out() -> None:
    from scope_lineage.render.catalog_gaps import concept_gaps, conflict_text
    from scope_lineage.render.catalog_view import CatalogView

    pairs = [
        (to_lineage_dict(parse_scope_lineage(_write(f"{c}.{TABLE}", grouped=True), c)), None)
        for c in ("cat1", "cat2")
    ]
    document = attach_evidence(build_ontology(load_catalog(DEMO)), lineage=lineage_facts(pairs))
    view = CatalogView(document)
    gaps = concept_gaps(view, "concept:customer")

    texts = [conflict_text(view, table, c) for table, c in gaps.conflicts if table == TABLE]
    assert len(texts) == 1
    assert f"cat1.{TABLE}" in texts[0] and f"cat2.{TABLE}" in texts[0]
    assert "SCOPE_LINEAGE_CATALOG_PREFIXES" in texts[0]
