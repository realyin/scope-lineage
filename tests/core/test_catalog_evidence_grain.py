"""The grain a statement proves is compared by the columns it writes (audit WP2f).

``catalog_evidence`` compared the catalog's declared grain -- target columns -- with
``grain.keys[].name``, the logical keys of the scope that decides the grain. Those are a
CTE's own column names, and they include keys a WHERE pins to one value, so a write that
renames its key in the outer SELECT, or pins one grouping column, raised
``grain_mismatch`` against a catalog that was right. ``candidate_keys`` (target columns,
pins removed) is now read at every confidence, and a key that holds but is not written
(``proven_unexposed``) reports ``grain_not_exposed`` instead of ``grain_not_proven``.

Every fixture is synthetic.
"""

from __future__ import annotations

from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.catalog_evidence import _grain, grain_conflicts
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.scope.scope_builder import parse_scope_lineage

REP = {
    "grain": {"source": "proven", "identifiers": ["id:customer_id"], "extra": []},
    "bindings": [{"column": "cust_id", "ref": "id:customer_id", "to": "identifier"}],
}


def _proof(sql: str) -> dict:
    document = to_lineage_dict(parse_scope_lineage(sql, "t"))
    return _grain(build_semantic_profile(document)["output_shape"])


def test_a_key_renamed_after_its_grouping_cte_is_no_mismatch() -> None:
    proof = _proof(
        "INSERT OVERWRITE TABLE dw.g2 "
        "WITH x AS (SELECT src_id, count(*) AS cnt FROM src.a GROUP BY src_id) "
        "SELECT src_id AS cust_id, cnt FROM x"
    )
    assert proof["keys"] == ["cust_id"]
    assert grain_conflicts(REP, proof, set()) == []


def test_a_pinned_grouping_column_is_no_mismatch() -> None:
    proof = _proof(
        "INSERT OVERWRITE TABLE dw.g3 SELECT cust_id, biz_type, count(*) AS cnt FROM src.a "
        "WHERE biz_type = 'L' GROUP BY cust_id, biz_type"
    )
    assert proof["keys"] == ["cust_id"]
    assert grain_conflicts(REP, proof, set()) == []


def test_a_proven_key_the_write_does_not_expose_says_so() -> None:
    proof = _proof(
        "INSERT OVERWRITE TABLE dw.g4 SELECT cnt FROM "
        "(SELECT src_id, count(*) AS cnt FROM src.a GROUP BY src_id) x"
    )
    assert grain_conflicts(REP, proof, set()) == [
        {"rule": "grain_not_exposed", "declared_source": "proven"}
    ]


def test_sentinel_a_real_mismatch_is_still_reported() -> None:
    proof = _proof(
        "INSERT OVERWRITE TABLE dw.g5 SELECT cust_id, biz_type, count(*) AS cnt FROM src.a "
        "GROUP BY cust_id, biz_type"
    )
    assert grain_conflicts(REP, proof, set()) == [
        {"rule": "grain_mismatch", "declared": ["cust_id"], "proven": ["biz_type", "cust_id"]}
    ]


def test_sentinel_a_plain_renamed_key_is_still_clean() -> None:
    proof = _proof(
        "INSERT OVERWRITE TABLE dw.g1 SELECT src_id AS cust_id, count(*) AS cnt "
        "FROM src.a GROUP BY src_id"
    )
    assert proof == {"confidence": "proven", "keys": ["cust_id"], "basis": "group_by"}
    assert grain_conflicts(REP, proof, set()) == []
