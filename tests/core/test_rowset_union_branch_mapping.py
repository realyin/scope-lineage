"""Rowset expressions inside a UNION branch must not be reported as unresolved.

A UNION branch whose projection is a row-count aggregate or a bare window
function has a determinate source -- the rowset itself -- and the resolver
already says so (``source_kind: 'rowset'``). The branch *mapping*, however, used
to be built one pass before ``_normalize_scope_expression_resolutions`` ran, so
it never carried the synthesized ``rowset_sources``; the gap detector then
re-derived ``unresolved`` from three empty lists and raised a root-impact gap
for an expression nothing was actually missing from.
"""
from __future__ import annotations

from scope_lineage import parse_scope_lineage


def _union_sql(expression: str) -> str:
    return f"""
INSERT OVERWRITE TABLE db.tgt
SELECT k, cnt FROM (
  SELECT k, {expression} AS cnt FROM db.a GROUP BY k
  UNION ALL
  SELECT k, {expression} AS cnt FROM db.b GROUP BY k
) u
"""


def _branch_mappings(result, output_name: str) -> list[dict]:
    mappings: list[dict] = []
    for scope_data in result.scopes.values():
        for output in scope_data.outputs or []:
            if output.name != output_name:
                continue
            resolution = output.expression_resolution or {}
            mappings.extend(resolution.get("union_branch_mappings") or [])
    return mappings


def test_row_count_aggregate_in_union_branch_emits_no_gap():
    result = parse_scope_lineage(_union_sql("COUNT(1)"), task_name="t")
    assert result.diagnostics.lineage_fact_gaps == []


def test_bare_window_function_in_union_branch_emits_no_gap():
    # Deliberately bare OVER (): a windowed function that references a column
    # picks that column up as a physical source and never reproduced the bug.
    result = parse_scope_lineage(_union_sql("ROW_NUMBER() OVER ()"), task_name="t")
    assert result.diagnostics.lineage_fact_gaps == []


def test_windowed_function_with_column_still_resolves():
    """Reverse guard: the case that already resolved must keep resolving.

    If a fix widened the early return to "never report a branch mapping", this
    test would still pass -- so it also pins the resolution_type, which a
    blanket suppression would leave untouched while breaking the classification.
    """
    result = parse_scope_lineage(
        _union_sql("ROW_NUMBER() OVER (PARTITION BY k ORDER BY k)"), task_name="t"
    )
    assert result.diagnostics.lineage_fact_gaps == []
    types = {mapping.get("resolution_type") for mapping in _branch_mappings(result, "cnt")}
    assert types == {"rowset_window_function"}


def test_rowset_branch_mapping_carries_rowset_sources():
    """The mapping must record the rowset source, not merely stop gapping.

    Scoped to the aggregate column: the ``k`` mappings are physical projections
    and legitimately carry no rowset source.
    """
    result = parse_scope_lineage(_union_sql("COUNT(1)"), task_name="t")
    mappings = _branch_mappings(result, "cnt")
    assert mappings, "expected union branch mappings for the aggregate output"
    for mapping in mappings:
        assert mapping.get("rowset_sources"), mapping
