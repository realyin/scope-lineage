"""Schema column names must be case-normalized the way table names already are.

sqlglot's ``qualify`` lower-cases unquoted identifiers, so every column *reference* the
resolver sees is lower-case. Table names were normalized to match (``normalize_table_name``
says so in its own docstring), but column names were passed through verbatim — so a metadata
source that spells its columns in upper case silently matched nothing (SCHEMA-CASE-001).

The damage is not a parse error. ``SELECT *`` expansion copies schema names verbatim into a
scope's column list, so the inner scope advertises ``V1`` while the outer scope asks for
``v1``. The lookup misses, the source chain breaks to ``scope:"UNKNOWN"``, and the statement
is reported as partial — while ``metadata_coverage`` still says every table is covered,
because coverage only checks table names. On a real 5-branch MERGE this turned 0 gaps into
16,122, with no warning anywhere in the artifact.

Upper-case column names are what several metastore exports produce, so this is a supported
input shape, not a malformed one.
"""

from __future__ import annotations

import json

import pytest

from scope_lineage.metadata.schema_metadata import load_schema, normalize_schema_map
from scope_lineage.scope.scope_builder import parse_all_scope_lineage
from scope_lineage.scope.task_lineage import parse_task_lineage

UPPER = {"ods.a": ["BIZNO", "V1"], "ods.b": ["BIZNO", "V2"], "mart.tgt": ["BIZNO", "V1"]}
LOWER = {table: [c.lower() for c in cols] for table, cols in UPPER.items()}
MIXED = {table: [c.capitalize() for c in cols] for table, cols in UPPER.items()}

# A branch built with SELECT * (so schema names flow into the scope) whose columns the outer
# query then references unqualified — the shape that makes a statement lose its lineage.
MERGE_SQL = (
    "MERGE INTO mart.tgt AS t USING (\n"
    "  SELECT a.BIZNO AS BIZNO, CAST(V1 AS int) AS V1\n"
    "  FROM (SELECT * FROM ods.a) a\n"
    "  JOIN (SELECT * FROM ods.b) b ON a.BIZNO = b.BIZNO\n"
    ") s ON t.BIZNO = s.BIZNO\n"
    "WHEN MATCHED THEN UPDATE SET t.V1 = s.V1"
)


def _gaps(schema):
    result = parse_task_lineage(MERGE_SQL, task_name="t", schema=schema)
    return result.diagnostics.get("lineage_fact_gaps") or []


def _scope_columns(schema):
    for result in parse_all_scope_lineage(MERGE_SQL, task_name="t", schema=schema):
        if result.stmt_kind == "MERGE":
            return {sid: [c.name for c in sd.columns] for sid, sd in result.scopes.items()}
    return {}


@pytest.mark.parametrize("schema", [UPPER, MIXED], ids=["upper", "mixed"])
def test_case_variant_schema_produces_no_gaps(schema):
    assert _gaps(schema) == []


@pytest.mark.parametrize("schema", [UPPER, MIXED], ids=["upper", "mixed"])
def test_case_variant_schema_agrees_with_lowercase(schema):
    """The case a metadata export happens to use must not change the lineage."""
    assert _gaps(schema) == _gaps(LOWER)
    assert _scope_columns(schema) == _scope_columns(LOWER)


def test_star_expansion_does_not_leak_schema_case_into_scope_columns():
    """SELECT * copies schema names; if they keep their case, references stop matching."""
    columns = _scope_columns(UPPER)

    leaked = {sid: [c for c in names if c != c.lower()] for sid, names in columns.items()}
    assert not any(leaked.values()), leaked


def test_the_derived_column_keeps_its_real_source():
    """The concrete regression: v1 resolved to UNKNOWN instead of the branch that supplies it."""
    for result in parse_all_scope_lineage(MERGE_SQL, task_name="t", schema=UPPER):
        if result.stmt_kind != "MERGE":
            continue
        subq_s = result.scopes["subq:s"]
        v1 = next(c for c in subq_s.columns if c.name == "v1")
        assert [s.scope for s in v1.sources or []] == ["subq:a"]


def test_referenced_column_is_not_added_back_as_a_duplicate():
    """Add-back exists for columns a metastore omitted, not for ones it spelled differently."""
    names = _scope_columns(UPPER)["subq:a"]

    assert sorted(names) == sorted(set(names))
    assert len(names) == 2


def test_uppercase_target_schema_does_not_duplicate_output_rows():
    """A case-variant target table used to yield both BIZNO and bizno as separate outputs."""
    sql = "INSERT INTO mart.tgt SELECT s.BIZNO, s.V1 FROM (SELECT * FROM ods.a) s"
    result = parse_task_lineage(sql, task_name="t", schema=UPPER)

    columns = [item.get("column") for item in result.end_to_end_lineage]
    assert columns == [c.lower() for c in columns]
    assert len(columns) == len(set(columns))


def test_normalize_schema_map_lowercases_column_names():
    normalized = normalize_schema_map({"ODS.A": ["BizNo", " V1 ", "`V2`"]})

    assert normalized["ods.a"] == ["bizno", "v1", "v2"]


def test_column_details_agree_with_the_column_list(tmp_path):
    """Details feed type/comment lookups keyed by name; a mismatched key finds nothing."""
    path = tmp_path / "schema.json"
    path.write_text(
        json.dumps({"tables": [{"table_name": "ods.a",
                                "columns": [{"column_name": "BizNo", "type": "string"}]}]}),
        encoding="utf-8",
    )

    schema = load_schema(str(path))

    assert schema["ods.a"] == ["bizno"]
    assert [d["name"] for d in schema.column_details["ods.a"]] == ["bizno"]


def test_case_variants_of_one_column_collapse_to_one():
    """`ID` and `id` are the same column in Spark; keeping both invents a column."""
    normalized = normalize_schema_map({"ods.a": ["ID", "id", "Id"]})

    assert normalized["ods.a"] == ["id"]
