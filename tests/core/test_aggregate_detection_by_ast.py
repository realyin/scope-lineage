"""An aggregate wrapped in another function still changes the grain (WP3p, C2.5-3).

``expression_features.has_aggregate`` fell back to a regex over eight function names
whenever the column's own transform was not AGGREGATE -- which is the case as soon as the
aggregate sits inside ``ROUND`` or ``COALESCE``. ``ROUND(STDDEV(x), 2)`` and
``COALESCE(MAX_BY(v, dt), 0)`` were published as ``grain_effect: preserved``. The test
is now the AST (any ``exp.AggFunc``), with a Spark name table only for functions sqlglot
parses as Anonymous.

Every name here is synthetic.
"""

from __future__ import annotations

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.scope.scope_facts import _has_aggregate_function

SQL = (
    "INSERT OVERWRITE TABLE m.agg2 SELECT id, ROUND(SUM(x), 2) AS s, "
    "ROUND(STDDEV(x), 2) AS sd, COALESCE(MAX_BY(v, dt), 0) AS mb, "
    "UPPER(v) AS u FROM s.a GROUP BY id, v"
)


def _outputs() -> dict[str, dict]:
    document = to_lineage_dict(
        parse_scope_lineage(SQL, "t", schema={"s.a": ["id", "x", "v", "dt"]})
    )
    return {output["name"]: output for output in document["scopes"]["ROOT"]["outputs"]}


@pytest.mark.parametrize("name", ["s", "sd", "mb"])
def test_a_wrapped_aggregate_changes_the_grain(name: str) -> None:
    output = _outputs()[name]

    assert output["expression_features"]["has_aggregate"] is True
    assert output["grain_effect"] == "changed"


@pytest.mark.parametrize("name", ["id", "u"])
def test_a_column_without_an_aggregate_keeps_the_grain(name: str) -> None:
    output = _outputs()[name]

    assert output["expression_features"]["has_aggregate"] is False
    assert output["grain_effect"] == "preserved"


@pytest.mark.parametrize("expression", [
    "ROUND(STDDEV(`a`.`x`), 2)",
    "COALESCE(MAX_BY(`a`.`v`, `a`.`dt`), 0)",
    "percentile_approx(a.x, 0.5) + 1",
    "NVL(first(a.v), 0)",
    "kurtosis(a.x) * 2",
    "WHERE a.x > (SELECT MAX(b.x) FROM b)",
])
def test_the_ast_finds_the_aggregate(expression: str) -> None:
    assert _has_aggregate_function(expression) is True


@pytest.mark.parametrize("expression", [
    "UPPER(`a`.`v`)",
    "a.maxv + a.summary",
    "'sum(' || a.v",
    "",
])
def test_names_and_text_that_only_look_like_aggregates_are_not(expression: str) -> None:
    assert _has_aggregate_function(expression) is False
