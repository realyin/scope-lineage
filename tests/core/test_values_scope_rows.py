"""A multi-row VALUES source keeps every row.

``_resolve_values_scope`` read only ``rows[0]``: each column became that one cell -- its
classification, its expression and its single source. An inline dictionary of N rows was
published as one constant, so a field reading it traced to the first row's value alone,
and two fields reading different rows of one dictionary traced to the same constant.

A column of several rows now takes every row's leaf sources (deduplicated), a
classification that does not depend on row order (the rows' shared one, else
EXPRESSION), and the expression ``(<row 1>, <row 2>, ...)`` -- a row-wise list of the
cells, not one value. A single-row VALUES is unchanged.
"""

from __future__ import annotations

import pytest

from scope_lineage import build_semantic_profile
from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {"src.t_a": ["id", "status"], "dw.t_out": ["id", "status_label"]}

DICT_VALUES = (
    "WITH dict AS ("
    " SELECT * FROM VALUES ('k1', 'TypeA', '0', 'Zero'), ('k2', 'TypeA', '1', 'One'),"
    " ('k3', 'TypeB', '0', 'Nil') AS t(id, kind, code, label)) "
)
DICT_UNION = (
    "WITH dict AS ("
    " SELECT 'k1' AS id, 'TypeA' AS kind, '0' AS code, 'Zero' AS label"
    " UNION ALL SELECT 'k2', 'TypeA', '1', 'One'"
    " UNION ALL SELECT 'k3', 'TypeB', '0', 'Nil') "
)
READ_DICT = (
    "INSERT OVERWRITE TABLE dw.t_out "
    "SELECT a.id, g.label AS status_label FROM src.t_a a "
    "LEFT JOIN dict g ON a.status = g.code AND g.kind = 'TypeA'"
)


def _document(sql: str, schema: dict | None = None) -> dict:
    return to_lineage_dict(parse_scope_lineage(sql, "t", schema=schema or SCHEMA))


def _chain_roots(document: dict, field: str) -> list[str]:
    for chain in document["field_mapping_chains"]:
        if chain["target_field"].split(".")[-1] == field:
            return chain["root_source_fields"]
    raise AssertionError(f"no chain for {field}")


def _generated(document: dict, field: str) -> list[str]:
    for row in document["end_to_end_lineage"]:
        if row["column"] == field:
            return [source["value"] for source in row.get("generated_sources") or []]
    raise AssertionError(f"no end_to_end row for {field}")


def _values_output(document: dict, column: str) -> dict:
    scope = next(s for sid, s in document["scopes"].items() if sid.startswith("udtf:"))
    return next(o for o in scope["outputs"] if o["name"] == column)


def _values_scope(document: dict) -> dict:
    return next(s for sid, s in document["scopes"].items() if sid.startswith("udtf:"))


def test_a_multi_row_dictionary_traces_to_every_row():
    document = _document(DICT_VALUES + READ_DICT)
    assert _chain_roots(document, "status_label") == [
        "CONSTANT.'Zero'", "CONSTANT.'One'", "CONSTANT.'Nil'",
    ]
    assert _generated(document, "status_label") == ["'Zero'", "'One'", "'Nil'"]


def test_a_multi_row_column_lists_its_rows_and_stays_a_constant():
    label = _values_output(_document(DICT_VALUES + READ_DICT), "label")
    assert label["transform"] == "CONSTANT"
    assert label["expression"] == "('Zero', 'One', 'Nil')"
    assert [s["column"] for s in label["sources"]] == ["'Zero'", "'One'", "'Nil'"]


def test_a_repeated_cell_is_one_source_but_keeps_its_row_in_the_expression():
    kind = _values_output(_document(DICT_VALUES + READ_DICT), "kind")
    assert kind["expression"] == "('TypeA', 'TypeA', 'TypeB')"
    assert [s["column"] for s in kind["sources"]] == ["'TypeA'", "'TypeB'"]


def test_the_values_and_union_all_spellings_trace_to_the_same_constants():
    values = _document(DICT_VALUES + READ_DICT)
    union = _document(DICT_UNION + READ_DICT)
    assert set(_chain_roots(values, "status_label")) == set(_chain_roots(union, "status_label"))


def test_a_multi_row_insert_values_keeps_every_row():
    document = _document(
        "INSERT INTO dw.t_out (id, status_label) VALUES ('k1', 'Zero'), ('k2', 'One')"
    )
    assert _generated(document, "status_label") == ["'Zero'", "'One'"]


@pytest.mark.parametrize(
    "rows",
    ["('a'), (MD5('b'))", "(MD5('b')), ('a')"],
    ids=["literal_first", "expression_first"],
)
def test_the_classification_of_mixed_rows_does_not_depend_on_their_order(rows):
    document = _document(
        f"WITH d AS (SELECT * FROM VALUES {rows} AS t(v)) "
        "INSERT OVERWRITE TABLE dw.t_out SELECT a.id, d.v AS status_label "
        "FROM src.t_a a JOIN d ON a.status = d.v"
    )
    assert _values_output(document, "v")["transform"] == "EXPRESSION"


def test_the_profile_restates_every_row_without_a_function_or_a_lost_lookup_role():
    document = _document(DICT_VALUES + READ_DICT)
    field = next(
        f for f in build_semantic_profile(document)["fields"]
        if f["column"].split(".")[-1] == "status_label"
    )
    assert all(value in field["summary"] for value in ("'Zero'", "'One'", "'Nil'"))
    assert "UDF" not in field["summary"]
    label = _values_output(document, "label")
    assert label["expression_features"]["has_udf"] is False
    assert label["expression_features"]["functions"] == []
    assert _values_scope(document)["role"] == "label"


def test_a_field_fed_by_a_multi_row_dictionary_publishes_no_value_domain():
    # the rows are not filtered by the JOIN condition (see the xfail below), so the
    # profile publishes no domain rather than an unfiltered or a first-row one
    document = _document(DICT_VALUES + READ_DICT)
    field = next(
        f for f in build_semantic_profile(document)["fields"]
        if f["column"].split(".")[-1] == "status_label"
    )
    assert field.get("value_domain") is None


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO dw.t_out (id, status_label) VALUES ('k1', 'Zero')",
        "WITH dict AS (SELECT * FROM VALUES ('k1', 'Zero') AS t(id, label)) "
        "INSERT OVERWRITE TABLE dw.t_out SELECT a.id, g.label AS status_label "
        "FROM src.t_a a LEFT JOIN dict g ON a.status = g.id",
    ],
    ids=["insert_values", "cte_values"],
)
def test_a_single_row_values_is_unchanged(sql):
    document = _document(sql)
    label = next(
        o for sid, s in document["scopes"].items() if sid.startswith("udtf:")
        for o in s["outputs"] if o["name"] in ("label", "status_label")
    )
    assert label["transform"] == "CONSTANT"
    assert label["expression"] == "'Zero'"
    assert [s["column"] for s in label["sources"]] == ["'Zero'"]


@pytest.mark.xfail(
    strict=True,
    reason="L3-b: a JOIN condition does not filter the rows of a constant row set",
)
def test_a_dictionary_read_under_a_join_filter_traces_to_the_matching_rows_only():
    document = _document(DICT_VALUES + READ_DICT)  # g.kind = 'TypeA': rows k1, k2
    assert set(_chain_roots(document, "status_label")) == {"CONSTANT.'Zero'", "CONSTANT.'One'"}
