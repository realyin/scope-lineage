"""In the SELECT list, a source column wins over an earlier alias of the same name.

Spark resolves a bare name in a projection against the FROM clause first and falls back to
a lateral column alias only when no input has that column: "A local column reference takes
precedence, over a lateral column alias"
(https://docs.databricks.com/en/sql/language-manual/sql-ref-name-resolution.html; lateral
column aliases arrived with SPARK-27561 in Spark 3.4 under the same rule). sqlglot's
``qualify`` expanded every matching name into the alias expression, so
``SELECT fee AS amt, amt AS fee`` read both outputs from ``fee`` with no warning. The
projection now shares the GROUP BY shield's rule: a schema-proven source column is kept,
and a name the metadata cannot settle keeps the lateral reading with a
``lateral_alias_ambiguous`` warning.
"""

from __future__ import annotations

import json

from scope_lineage import parse_task_lineage, to_task_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {
    "ods.x": ["new_code", "status", "fee", "amt", "a", "k"],
    "ods.y": ["k", "amt", "z"],
}


def _parse(sql: str, schema: dict | None = SCHEMA):
    return parse_scope_lineage(sql, task_name="t", schema=schema)


def _outputs(result) -> dict[str, str]:
    return {output.name: output.expression for output in result.scopes["ROOT"].outputs}


def _warning_types(result) -> list[str]:
    return [warning.type for warning in result.diagnostics.warnings]


def test_a_source_column_is_not_replaced_by_an_earlier_alias():
    result = _parse("INSERT INTO dw.o SELECT new_code AS status, status AS old_status FROM ods.x")

    assert _outputs(result) == {"status": "`x`.`new_code`", "old_status": "`x`.`status`"}
    assert "lateral_alias_ambiguous" not in _warning_types(result)


def test_swapped_names_keep_their_own_sources():
    result = _parse("INSERT INTO dw.o SELECT fee AS amt, amt AS fee FROM ods.x")

    assert _outputs(result) == {"amt": "`x`.`fee`", "fee": "`x`.`amt`"}


def test_the_alias_is_matched_case_insensitively():
    result = _parse("INSERT INTO dw.o SELECT fee AS AMT, amt AS fee2 FROM ods.x")

    assert _outputs(result)["fee2"] == "`x`.`amt`"


def test_a_lateral_alias_built_on_a_kept_source_column_leaks_no_placeholder():
    sql = "INSERT INTO dw.o SELECT fee AS amt, amt + 1 AS b, b * 2 AS c FROM ods.x"
    document = to_task_lineage_dict(parse_task_lineage(sql, task_name="t", schema=SCHEMA))

    assert "__lineage_where_column__" not in json.dumps(document, ensure_ascii=False)
    outputs = _outputs(_parse(sql))
    assert outputs["b"] == "`x`.`amt` + 1"
    assert outputs["c"] == "(`x`.`amt` + 1) * 2"


def test_a_derived_table_and_a_cte_with_listed_columns_prove_the_column():
    derived = _parse(
        "INSERT INTO dw.o SELECT fee AS amt, amt AS fee FROM (SELECT fee, amt FROM ods.x) s"
    )
    cte = _parse(
        "INSERT INTO dw.o WITH s AS (SELECT fee, amt FROM ods.x) "
        "SELECT fee AS amt, amt AS fee FROM s"
    )

    assert _outputs(derived) == {"amt": "`s`.`fee`", "fee": "`s`.`amt`"}
    assert _outputs(cte) == {"amt": "`s`.`fee`", "fee": "`s`.`amt`"}


def test_a_join_where_one_side_has_the_column_reads_that_side():
    result = _parse(
        "INSERT INTO dw.o SELECT x.fee AS z, z AS z2 FROM ods.x x JOIN ods.y y ON x.k = y.k"
    )

    [z2] = [output for output in result.scopes["ROOT"].outputs if output.name == "z2"]
    assert [(source.scope, source.column) for source in z2.sources] == [("ods.y", "z")]


def test_a_join_where_both_sides_have_the_column_stays_ambiguous():
    result = _parse(
        "INSERT INTO dw.o SELECT x.fee AS amt, amt AS a2 FROM ods.x x JOIN ods.y y ON x.k = y.k"
    )

    [a2] = [output for output in result.scopes["ROOT"].outputs if output.name == "a2"]
    assert [source.scope for source in a2.sources] == ["AMBIGUOUS"]
    assert "ambiguous_unqualified" in _warning_types(result)


def test_a_star_cte_source_keeps_the_alias_and_warns():
    result = _parse(
        "INSERT INTO dw.o WITH s AS (SELECT * FROM ods.x) SELECT fee AS amt, amt AS fee FROM s"
    )

    assert _outputs(result)["fee"] == "`s`.`fee`"
    assert "lateral_alias_ambiguous" in _warning_types(result)


def test_a_source_with_unknown_columns_keeps_the_alias_and_warns():
    result = _parse(
        "INSERT INTO dw.o SELECT x.fee AS q, q + 1 AS q2 FROM ods.x x JOIN ods.u u ON x.k = u.k"
    )

    assert _outputs(result)["q2"] == "`x`.`fee` + 1"
    [warning] = [w for w in result.diagnostics.warnings if w.type == "lateral_alias_ambiguous"]
    assert warning.scope == "ROOT"
    assert "'q'" in warning.msg


def test_a_name_sqlglot_leaves_unexpanded_does_not_warn():
    """An alias over an aggregate is not expanded into another aggregate, so the column
    already reads the source and there is no alias reading to report."""
    result = _parse(
        "INSERT INTO dw.o SELECT k, MAX(CASE WHEN t = 1 THEN cap END) AS cap, "
        "MAX(CASE WHEN t = 2 THEN cap END) AS cap2 FROM ods.z GROUP BY k",
        schema=None,
    )

    assert _outputs(result)["cap2"] == "MAX(CASE WHEN `z`.`t` = 2 THEN `z`.`cap` END)"
    assert "lateral_alias_ambiguous" not in _warning_types(result)


def test_a_true_lateral_alias_is_still_expanded_without_a_warning():
    """Sentinel: no source has ``b``, so Spark (and the tool) read the lateral alias."""
    result = _parse("INSERT INTO dw.o SELECT a + 1 AS b, b + 1 AS c FROM ods.x")

    assert _outputs(result)["c"] == "`x`.`a` + 1 + 1"
    assert "lateral_alias_ambiguous" not in _warning_types(result)
