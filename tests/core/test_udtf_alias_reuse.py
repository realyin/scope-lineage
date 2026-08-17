"""Two LATERAL VIEWs sharing an alias still each produce their own column.

qualify rewrites a reference to a UDTF's output column by attaching the view's alias —
``arr.unitCode`` becomes ``t.arr.unitcode``. When two views in one query block carry the
same alias it cannot tell which one owns ``arr``, so the reference is left bare, and the
expression resolver looked the qualifier up only among bound aliases and gave up. The scope
model had the answer all along: one of those views exposes a column called ``arr``.
"""

from __future__ import annotations

from scope_lineage import parse_scope_lineage
from scope_lineage.scope.end_to_end import build_end_to_end_lineage


SCHEMA = {"lods.rule_detail": ["data", "id"], "mart.t": ["unit_code"]}

_JSON_SHAPE = (
    "'array<struct<unitCode:string,detail:array<struct<subType:string>>>>'"
)


def _sql(second_alias: str) -> str:
    return f"""
    INSERT INTO mart.t
    SELECT DISTINCT arr.unitCode AS unit_code
    FROM lods.rule_detail
    LATERAL VIEW EXPLODE(from_json(data, {_JSON_SHAPE})) t AS arr
    LATERAL VIEW EXPLODE(arr.detail) {second_alias} AS d
    WHERE d.subType = 'abTest'
    """


def test_a_reused_lateral_view_alias_does_not_lose_the_output_column() -> None:
    result = parse_scope_lineage(_sql("t"), "reused_alias", schema=SCHEMA)

    assert result.diagnostics.lineage_fact_gaps == []
    assert [
        (item["column"], tuple((s["table"], s["column"]) for s in item["physical_sources"]))
        for item in build_end_to_end_lineage(result)
    ] == [("unit_code", (("lods.rule_detail", "data"),))]


def test_distinct_lateral_view_aliases_keep_working() -> None:
    """The path that already worked must not be traded away for the one that did not."""
    result = parse_scope_lineage(_sql("t2"), "distinct_alias", schema=SCHEMA)

    assert result.diagnostics.lineage_fact_gaps == []
    assert [
        (item["column"], tuple((s["table"], s["column"]) for s in item["physical_sources"]))
        for item in build_end_to_end_lineage(result)
    ] == [("unit_code", (("lods.rule_detail", "data"),))]


def test_two_views_exposing_the_same_column_name_stay_a_gap() -> None:
    """Two candidates is an ambiguity, not a choice.

    Picking one would make the answer depend on which LATERAL VIEW was written first —
    a fact about the text rather than about the data.
    """
    result = parse_scope_lineage(
        """
        INSERT INTO mart.t
        SELECT arr.unitCode AS unit_code
        FROM lods.rule_detail
        LATERAL VIEW EXPLODE(from_json(data, 'array<struct<unitCode:string>>')) t AS arr
        LATERAL VIEW EXPLODE(from_json(id, 'array<struct<unitCode:string>>')) t AS arr
        """,
        "ambiguous_alias",
        schema=SCHEMA,
    )

    assert [
        reason
        for gap in result.diagnostics.lineage_fact_gaps
        for reason in gap.get("missing_reasons") or []
    ] != []
