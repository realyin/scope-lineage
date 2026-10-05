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
