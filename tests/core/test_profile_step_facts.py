"""Derivation steps that say what a projection does, and statement findings (E #20, #25, D #29).

1. **A UDF called in a SELECT list is marked a UDF black box.** The mark came only from a
   logic block's ``has_udf``, and a projection has no logic block, so ``mobile_enc(x)`` in
   a SELECT list restated as nothing; the output column's own ``has_udf`` (the function
   catalogue's verdict) now decides, still overruled by the parser for a builtin.
2. **A long inline VALUES column is summarised.** ``常量 ('k1', 'k2', ...)`` listed every
   literal of the column; past three it now reads 「内联 VALUES 的一列（N 个字面量，前 3
   个：…）」. Three or fewer stay verbatim.
3. **A positional write by schema metadata is a positional write.** ``sql_alias`` and the
   ``alias_position_mismatch`` finding knew only ``ddl_position``.
4. **One alias naming two sources in one SELECT is a finding** (``duplicate_alias``).
5. **An empty-string comparison on a non-string column is a finding**
   (``empty_string_on_non_string``); what it does depends on the engine's coercion.

Every fixture is synthetic.
"""

from __future__ import annotations

from scope_lineage import build_semantic_profile
from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {
    "ods.t_a": ["k", "name", "a", "b"],
    "dw.t_out": ["k", "v"],
}


def _profile(sql: str, schema=None, **kwargs) -> dict:
    return build_semantic_profile(
        to_lineage_dict(parse_scope_lineage(sql, "t", schema=schema or SCHEMA, **kwargs))
    )


def _steps(profile: dict, column: str) -> list[dict]:
    field = next(item for item in profile["fields"] if item["column"] == column)
    return field["derivation"]


def _texts(profile: dict, column: str) -> str:
    return " | ".join(str(step.get("text")) for step in _steps(profile, column))


# --- 1. UDF in a projection -----------------------------------------------------------


def test_a_udf_in_a_select_list_is_a_black_box():
    profile = _profile(
        "INSERT OVERWRITE TABLE dw.t_out SELECT t.k, default.mask_text(t.name) AS v FROM ods.t_a t"
    )
    assert "UDF 黑盒" in _texts(profile, "v")


def test_a_builtin_in_a_select_list_is_not():
    for call in ("md5(concat_ws('-', t.a, t.b))", "hash(t.a)"):
        profile = _profile(f"INSERT OVERWRITE TABLE dw.t_out SELECT t.k, {call} AS v FROM ods.t_a t")
        assert "UDF 黑盒" not in _texts(profile, "v")


# --- 2. VALUES summary ----------------------------------------------------------------


def _values(rows: int) -> str:
    body = ", ".join(f"('k{index}', 'L{index}')" for index in range(1, rows + 1))
    return (
        f"WITH d AS (SELECT * FROM VALUES {body} AS t(code, label)) "
        "INSERT OVERWRITE TABLE dw.t_out SELECT d.code AS k, d.label AS v FROM d"
    )


def test_a_long_values_column_is_summarised():
    text = _texts(_profile(_values(5)), "v")
    assert "5 个字面量" in text
    assert "'L1'" in text and "'L4'" not in text and "'L5'" not in text


def test_a_short_values_column_stays_verbatim():
    text = _texts(_profile(_values(3)), "v")
    assert "('L1', 'L2', 'L3')" in text
    assert "个字面量" not in text


# --- 3. schema_position -----------------------------------------------------------------


def _target_metadata(structure_source: str):
    from scope_lineage.metadata.target_table_metadata import (
        TargetColumnMetadata,
        TargetMetadataMap,
        TargetTableMetadata,
    )

    item = TargetTableMetadata(
        table_name="dw.t_paid",
        full_table_name="spark_catalog.dw.t_paid",
        columns=[
            TargetColumnMetadata(name="order_id", data_type="string", ordinal=0),
            TargetColumnMetadata(name="paid_amt", data_type="decimal(18,2)", ordinal=1),
        ],
        partition_columns=[],
        ddl="CREATE TABLE dw.t_paid(order_id STRING, paid_amt DECIMAL(18,2))"
        if structure_source == "ddl"
        else None,
        source_file="synthetic-target-metadata.json",
        structure_source=structure_source,
    )
    return TargetMetadataMap({item.table_name: item})


PAID_SCHEMA = {"ods.o": ["order_id", "amount"], "dw.t_paid": ["order_id", "paid_amt"]}


def test_a_positional_write_by_either_metadata_publishes_the_sql_alias():
    for source, method in (("schema", "schema_position"), ("ddl", "ddl_position")):
        document = to_lineage_dict(parse_scope_lineage(
            "INSERT OVERWRITE TABLE dw.t_paid SELECT a.order_id, a.amount AS total_amt FROM ods.o a",
            "t",
            schema=PAID_SCHEMA,
            target_metadata=_target_metadata(source),
        ))
        assert document["target_field_binding"]["method"] == method
        profile = build_semantic_profile(document)
        field = next(item for item in profile["fields"] if item["column"] == "paid_amt")
        assert field["sql_alias"] == "total_amt"
        kinds = [item["kind"] for item in profile["confidence"]["findings"]]
        assert "alias_position_mismatch" in kinds


def test_a_write_by_column_list_publishes_no_alias():
    profile = _profile(
        "INSERT OVERWRITE TABLE dw.t_paid (order_id, paid_amt) "
        "SELECT a.order_id, a.amount AS total_amt FROM ods.o a",
        schema=PAID_SCHEMA,
        target_metadata=_target_metadata("schema"),
    )
    field = next(item for item in profile["fields"] if item["column"] == "paid_amt")
    assert "sql_alias" not in field


# --- 4. duplicate_alias -----------------------------------------------------------------

ALIAS_SCHEMA = {
    "ods.buyer": ["k", "app_code"],
    "ods.region": ["k", "region_name"],
    "dw.t_out": ["k", "v"],
}


def _findings(profile: dict, kind: str) -> list[dict]:
    return [item for item in profile["confidence"]["findings"] if item["kind"] == kind]


def test_one_alias_for_two_sources_in_one_select_is_a_finding():
    profile = _profile(
        "INSERT OVERWRITE TABLE dw.t_out SELECT b.k, b.region_name AS v FROM ods.buyer b "
        "LEFT JOIN ods.region b ON b.k = b.k",
        schema=ALIAS_SCHEMA,
    )
    (finding,) = _findings(profile, "duplicate_alias")
    assert finding["severity"] == "warn"
    assert "ods.buyer" in finding["text"] and "ods.region" in finding["text"]
    assert finding["evidence"] == ["ROOT"]


def test_one_alias_in_two_scopes_is_not():
    profile = _profile(
        "INSERT OVERWRITE TABLE dw.t_out SELECT b.k, b.v FROM ("
        " SELECT b.k, b.region_name AS v FROM ods.region b) b",
        schema=ALIAS_SCHEMA,
    )
    assert _findings(profile, "duplicate_alias") == []


# --- 5. empty string on a non-string column ---------------------------------------------

TYPED_SCHEMA = {
    "tables": [
        {"table_name": "ods.x", "schema": [
            {"columnName": "k", "columnType": "bigint", "columnIndex": 0},
            {"columnName": "s", "columnType": "string", "columnIndex": 1},
        ]},
    ]
}


def _typed_profile(sql: str, tmp_path) -> dict:
    import json as _json

    from scope_lineage.metadata.schema_metadata import load_schema

    path = tmp_path / "schema.json"
    path.write_text(_json.dumps(TYPED_SCHEMA), encoding="utf-8")
    return _profile(sql, schema=load_schema(str(path)))


def test_an_empty_string_test_on_a_bigint_column_is_a_finding(tmp_path):
    profile = _typed_profile(
        "INSERT OVERWRITE TABLE dw.t_out SELECT if(x.k = '', NULL, x.k) AS k, "
        "if(x.s = '', NULL, x.s) AS v FROM ods.x x",
        tmp_path,
    )
    (finding,) = _findings(profile, "empty_string_on_non_string")
    assert "ods.x.k" in finding["text"] and "bigint" in finding["text"]
    assert "取决于引擎" in finding["text"]
    assert finding["severity"] == "warn"


def test_an_empty_string_test_on_a_string_column_is_not(tmp_path):
    profile = _typed_profile(
        "INSERT OVERWRITE TABLE dw.t_out SELECT x.k, x.s AS v FROM ods.x x WHERE x.s <> ''",
        tmp_path,
    )
    assert _findings(profile, "empty_string_on_non_string") == []
