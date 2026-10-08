"""``grain_key_columns``: the target column each logical grain key lands on (M1).

``output_shape.grain.keys[]`` are logical keys -- a column of the scope that decides the
grain, ``subq:x.k`` -- and ``candidate_keys`` are target columns, published only when
the key is proven and never for a key that reaches the target through an expression. A
reader asking "which target columns is this batch unique by" needs the one for the
other, whatever the confidence. The facade answers per key, in order:

1. ``exposed`` -- carried to a target column by pass-through steps;
2. ``merge_on`` -- tied to a target column by a MERGE's ON equality (a bare key, and a
   matched branch to make the equality hold);
3. ``derived`` -- lifted to the ROOT output through a single-source expression;
4. ``unexposed`` -- none of these: the key is not written to the target.

Every fixture is synthetic; target and source names differ on purpose, since equal
names would hide the difference.
"""

from __future__ import annotations

from scope_lineage import build_semantic_profile
from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.render.semantic_profile import grain_key_columns
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {
    "ods.ev": ["k", "env", "v", "ts"],
    "dw.out": ["out_key", "out_env", "v"],
    "dw.same": ["k", "env", "v"],
    "dw.m": ["tk", "v"],
}


def _columns(sql: str) -> list[dict]:
    document = to_lineage_dict(parse_scope_lineage(sql, "t", schema=SCHEMA))
    grain = build_semantic_profile(document)["output_shape"]["grain"]
    return grain_key_columns(document, grain)


DEDUP = (
    "(SELECT k, env, v FROM (SELECT k, env, v, row_number() OVER (PARTITION BY k, env"
    " ORDER BY ts DESC) rn FROM ods.ev) a WHERE a.rn = 1)"
)


def test_a_renamed_key_and_a_derived_key_name_their_target_columns():
    found = _columns(
        f"INSERT OVERWRITE TABLE dw.out SELECT x.k AS out_key, concat('p_', x.env) AS out_env,"
        f" x.v FROM {DEDUP} x"
    )
    assert [(item["column"], item["via"]) for item in found] == [
        ("out_key", "exposed"),
        ("out_env", "derived"),
    ]
    assert all(item["logical"].endswith((".k", ".env")) for item in found)


def test_a_key_written_under_its_own_name_is_exposed():
    found = _columns(f"INSERT OVERWRITE TABLE dw.same SELECT x.k, x.env, x.v FROM {DEDUP} x")
    assert [(item["column"], item["via"]) for item in found] == [("k", "exposed"), ("env", "exposed")]


def test_a_key_the_write_leaves_out_is_unexposed():
    found = _columns(
        f"INSERT OVERWRITE TABLE dw.out SELECT x.k AS out_key, 'c' AS out_env, x.v FROM {DEDUP} x"
    )
    assert [(item.get("column"), item["via"]) for item in found] == [
        ("out_key", "exposed"),
        (None, "unexposed"),
    ]


def test_a_merge_key_reaches_its_target_column_through_the_on_equality():
    found = _columns(
        "MERGE INTO dw.m tgt USING (SELECT a.k AS src_k, a.v FROM (SELECT k, v, row_number()"
        " OVER (PARTITION BY k ORDER BY ts DESC) rn FROM ods.ev) a WHERE a.rn = 1) src"
        " ON tgt.tk = src.src_k WHEN MATCHED THEN UPDATE SET tgt.v = src.v"
    )
    assert [(item["column"], item["via"]) for item in found] == [("tk", "merge_on")]


def test_no_keys_is_an_empty_list():
    document = to_lineage_dict(
        parse_scope_lineage("INSERT OVERWRITE TABLE dw.same SELECT k, env, v FROM ods.ev", "t",
                            schema=SCHEMA)
    )
    grain = build_semantic_profile(document)["output_shape"]["grain"]
    assert grain_key_columns(document, grain) == []
