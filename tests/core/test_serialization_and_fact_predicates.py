"""Unit coverage for serialization round-trips and two small fact predicates.

Migrated from the integration repository, which held the only tests for all five functions while
Core had none: the SourceRef dict round-trip (which has to preserve `candidates`, the field that
records an ambiguous binding), display-expression stamping, terminal-output incomplete reasons,
and the cross-task-trace predicate.

NOTE for whoever revisits `_cross_task_trace_required_for_fields`: it keys on warehouse layer
prefixes (`app_`, `dm`, `ads`), which CLAUDE.md says belong downstream rather than in Core. This
file pins the behaviour that exists today; it is not an endorsement of keeping that rule here.
The conflict is real and predates this migration -- see the note filed alongside it.

Fixtures are synthetic; the one real layer name the original carried was replaced with a
synthetic name that keeps the `app_` prefix the rule actually reads.
"""

from __future__ import annotations

from scope_lineage import ScopeOutputField, SourceRef
from scope_lineage.scope._shared import _source_ref_to_dict
from scope_lineage.scope.end_to_end import _output_terminal_incomplete_reasons
from scope_lineage.scope.scope_facts import _source_ref_from_dict


def _terminal_output(status, missing_reasons):
    field = ScopeOutputField(name="x", transform="EXPRESSION")
    field.expression_resolution = {"status": status, "missing_reasons": missing_reasons}
    return field


def test_phase1_serializer_stamps_display_expression():
    """Firepower: lineage.json must carry a display_expression (aliases resolved) next to the
    verbatim expression, without mutating the lineage fact. Only stamped when it actually differs."""
    from scope_lineage.contract.lineage import _stamp_display_expressions
    scope = {
        "alias_source_bindings": [{"alias": "a", "physical_source_id": "ods.ods_x"}],
        "columns": [{"name": "amt", "transform": "AGGREGATE", "expression": "SUM(`a`.`trn_amt`)"},
                    {"name": "id", "transform": "DIRECT", "expression": "`a`.`id`"}],
        "logic_blocks": [{"normalized_expression": "where `a`.`recd_stat` = 0"}],
    }
    _stamp_display_expressions(scope)
    assert scope["columns"][0]["display_expression"] == "SUM(`trn_amt`)"
    assert scope["columns"][0]["expression"] == "SUM(`a`.`trn_amt`)"   # fact untouched
    assert scope["logic_blocks"][0]["display_expression"] == "where `recd_stat` = 0"
    # no bindings -> no stamping
    bare = {"columns": [{"name": "x", "expression": "`a`.`x`"}]}
    _stamp_display_expressions(bare)
    assert "display_expression" not in bare["columns"][0]


def test_catalog_qualified_upper_layer_source_flags_cross_task_trace():
    """Layer detection reads the first segment; a catalog prefix must not hide
    an upper-layer (app_/dm/ads) source, else cross_task_trace is wrongly
    skipped (fixed incidentally by catalog normalization)."""
    from scope_lineage.scope.scope_facts import _cross_task_trace_required_for_fields

    # after catalog strip the table is app_reporting.* -> needs cross-task trace
    assert _cross_task_trace_required_for_fields([{"table": "app_reporting.daily_summary"}]) is True
    assert _cross_task_trace_required_for_fields([{"table": "ods.users"}]) is False


def test_partially_resolved_terminal_output_reports_incomplete_reasons():
    # Regression: expression_resolution.status is resolved/partially_resolved/unresolved.
    # The terminal-reasons check must match "partially_resolved" (not the stale "partial",
    # which is a trace_status value, never an expression_resolution.status value); otherwise
    # a partially-resolved terminal output is wrongly treated as fully complete.
    assert _output_terminal_incomplete_reasons(
        _terminal_output("partially_resolved", ["alias_binding_missing"])
    ) == ["alias_binding_missing"]
    # unresolved without explicit missing_reasons falls back to a generic reason.
    assert _output_terminal_incomplete_reasons(
        _terminal_output("unresolved", [])
    ) == ["output_expression_unresolved"]
    # resolved terminal outputs contribute no incomplete reasons.
    assert _output_terminal_incomplete_reasons(_terminal_output("resolved", [])) == []


def test_source_ref_dict_round_trip_preserves_candidates():
    ref = SourceRef(
        scope="AMBIGUOUS",
        column="id",
        candidates=[
            {"scope": "ods.a", "column": "id"},
            {"scope": "ods.b", "column": "id"},
        ],
        qualifier="a",
        binding_scope_id="ROOT",
        input_ref_id="input:ROOT:001",
    )

    restored = _source_ref_from_dict(_source_ref_to_dict(ref))

    assert restored == ref
    assert restored.qualifier == "a"
    assert restored.binding_scope_id == "ROOT"
    assert restored.input_ref_id == "input:ROOT:001"
