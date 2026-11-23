"""A column bound to an attribute shows the attribute's ``type``, wherever the column is read.

A reader writing a filter on a year or a month needs to know whether the column holds a
string or a number. The catalog records a ``type`` on every attribute; ``catalog query
attribute`` printed it, while the context pack's column answer, ``catalog query table``'s
column list and ``catalog query column`` did not. They now do, for a column bound as
``attribute`` or ``foreign_attribute``. An identifier, a technical or an unmapped column has
no type in the catalog and prints nothing extra. ``query attribute`` already shows the type
in its first line, so its column list does not repeat it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.render.catalog_context import context_pack, render_context_text
from scope_lineage.render.catalog_query import query_catalog, render_query_text

ONTOLOGY = Path(__file__).parent / "fixtures" / "catalog" / "ontology.json"
LOAN = "demo_dwd.dwd_lending_loan_df"
REPAYMENT = "demo_dwd.dwd_lending_repayment_di"


@pytest.fixture(scope="module")
def document() -> dict:
    return json.loads(ONTOLOGY.read_text(encoding="utf-8"))


def _column(document: dict, term: str) -> dict:
    (answer,) = context_pack(document, None, columns=[term])["columns"]
    return answer


def test_the_pack_gives_an_attribute_columns_type(document: dict) -> None:
    answer = _column(document, f"{LOAN}.principal_amt")
    assert answer["catalog"]["type"] == "decimal(18,2)"
    text = render_context_text(context_pack(document, None, columns=[f"{LOAN}.principal_amt"]))
    assert "  - 类型：decimal(18,2)\n" in text


def test_a_denormalised_attribute_column_has_its_type_too(document: dict) -> None:
    assert _column(document, f"{LOAN}.customer_gender_cd")["catalog"]["type"] == "string"


@pytest.mark.parametrize(
    "column", ["loan_no", "customer_id", "dt"],  # identifier, foreign identifier, technical
)
def test_a_column_with_no_type_prints_nothing_extra(document: dict, column: str) -> None:
    answer = _column(document, f"{LOAN}.{column}")
    assert "type" not in answer["catalog"]
    text = render_context_text(context_pack(document, None, columns=[f"{LOAN}.{column}"]))
    assert "类型" not in text


def test_an_unmapped_column_has_no_type(document: dict) -> None:
    term = "demo_dwd.dwd_party_customer_ext_df.ext_json"
    assert "type" not in _column(document, term)["catalog"]


def test_query_table_lists_each_attribute_columns_type(document: dict) -> None:
    result = query_catalog(document, "table", LOAN)
    columns = {c["column"]: c for c in result["matches"][0]["columns"]}
    assert columns["principal_amt"]["type"] == "decimal(18,2)"
    assert "type" not in columns["loan_no"]
    text = render_query_text(result)
    principal = next(line for line in text.splitlines() if "principal_amt →" in line)
    assert "；类型 decimal(18,2)" in principal
    loan_no = next(line for line in text.splitlines() if "  - loan_no →" in line)
    assert "类型" not in loan_no


def test_query_column_gives_the_type(document: dict) -> None:
    result = query_catalog(document, "column", f"{REPAYMENT}.repay_amt")
    assert result["matches"][0]["type"] == "decimal(18,2)"
    assert "；类型 decimal(18,2)" in render_query_text(result)
    external = query_catalog(document, "column", f"{REPAYMENT}.loan_no")
    assert "type" not in external["matches"][0]
    assert "类型" not in render_query_text(external)


def test_query_attribute_prints_the_type_once(document: dict) -> None:
    text = render_query_text(query_catalog(document, "attribute", "attr:loan.principal"))
    assert text.count("decimal(18,2)") == 1
    assert "decimal(18,2)" in text.splitlines()[0]
