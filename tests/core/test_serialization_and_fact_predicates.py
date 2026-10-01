"""Unit coverage for serialization round-trips and terminal-output reasons.

Migrated from the integration repository, which held the only tests for all five functions while
Core had none: the SourceRef dict round-trip (which has to preserve `candidates`, the field that
records an ambiguous binding), display-expression stamping, terminal-output incomplete reasons,

The cross-task-trace predicate that used to be pinned here is gone: it keyed on warehouse layer
prefixes, which CLAUDE.md places downstream, and the only consumer now decides it with its own
layer policy -- one that reads more layers and can take the layer from metadata.

Fixtures are synthetic; the one real layer name the original carried was replaced with a
synthetic name that keeps the `app_` prefix the rule actually reads.
"""

from __future__ import annotations

from scope_lineage import ScopeOutputField, SourceRef
from scope_lineage.scope.source_refs import _source_ref_to_dict
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
        "logic_blocks": [{"raw_expression": "WHERE `a`.`recd_stat` = 'Ab'",
                          "normalized_expression": "where `a`.`recd_stat` = 'ab'"}],
    }
    _stamp_display_expressions(scope)
    assert scope["columns"][0]["display_expression"] == "SUM(`trn_amt`)"
    assert scope["columns"][0]["expression"] == "SUM(`a`.`trn_amt`)"   # fact untouched
    # a logic block displays its raw text, not the lower-cased comparison form
    assert scope["logic_blocks"][0]["display_expression"] == "WHERE `recd_stat` = 'Ab'"
    assert scope["logic_blocks"][0]["normalized_expression"] == "where `a`.`recd_stat` = 'ab'"
    # no bindings -> no stamping
    bare = {"columns": [{"name": "x", "expression": "`a`.`x`"}]}
    _stamp_display_expressions(bare)
    assert "display_expression" not in bare["columns"][0]


def test_logic_block_display_keeps_the_raw_text_after_a_line_comment():
    """The raw text keeps its line breaks, so a `--` comment ends at its line and an alias on
    the next line is still resolved; the collapsed comparison form ran the comment to the end."""
    from scope_lineage.contract.lineage import _stamp_display_expressions
    raw = "WHERE `a`.`x` = 1 -- note\n  AND `b`.`y` = 'Q'"
    scope = {
        "alias_source_bindings": [{"alias": "a", "physical_source_id": "src.t_a"},
                                  {"alias": "b", "physical_source_id": "src.t_b"}],
        "logic_blocks": [{"raw_expression": raw,
                          "normalized_expression": " ".join(raw.lower().split())}],
    }
    _stamp_display_expressions(scope)
    assert scope["logic_blocks"][0]["display_expression"] == (
        "WHERE `t_a`.`x` = 1 -- note\n  AND `t_b`.`y` = 'Q'"
    )


_DISPLAY_SCHEMA = {"src.t_a": ["id", "dt", "ts"], "src.t_b": ["id", "kind"], "dw.t_out": ["id", "k"]}


def _root_logic_blocks(sql: str) -> dict:
    from scope_lineage import parse_scope_lineage
    from scope_lineage.contract.lineage import to_lineage_dict
    document = to_lineage_dict(parse_scope_lineage(sql, "t", schema=_DISPLAY_SCHEMA))
    return {block["logic_type"]: block for block in document["scopes"]["ROOT"]["logic_blocks"]}


def test_parsed_logic_block_display_keeps_literal_case():
    """End to end: join, filter and CASE blocks display their string literals as written. A
    format string is case-sensitive (`MM` month vs `mm` minute), so lower-casing it changes
    what the displayed expression means."""
    blocks = _root_logic_blocks(
        "INSERT OVERWRITE TABLE dw.t_out\n"
        "SELECT a.id, CASE WHEN b.kind = 'Alpha' THEN 'X' ELSE 'y' END AS k\n"
        "FROM src.t_a a LEFT JOIN src.t_b b ON a.id = b.id AND b.kind IN ('Alpha', 'BetaGamma')\n"
        "WHERE a.dt = '20260101' AND DATE_FORMAT(a.ts, 'yyyyMMdd') = '20260101'"
    )
    assert blocks["join"]["display_expression"] == (
        "`t_a`.`id` = `t_b`.`id` AND `t_b`.`kind` IN ('Alpha', 'BetaGamma')"
    )
    assert blocks["filter"]["display_expression"] == (
        "WHERE `dt` = '20260101' AND DATE_FORMAT(`ts`, 'yyyyMMdd') = '20260101'"
    )
    assert blocks["case_when"]["display_expression"] == (
        "CASE WHEN `kind` = 'Alpha' THEN 'X' ELSE 'y' END"
    )
    # the comparison form and the fingerprint stay lower-cased: they are dedup keys
    assert blocks["filter"]["normalized_expression"] == (
        "where `a`.`dt` = '20260101' and date_format(`a`.`ts`, 'yyyymmdd') = '20260101'"
    )
    assert blocks["filter"]["fingerprint"] == "filter:" + blocks["filter"]["normalized_expression"]


def test_logic_block_with_no_bound_alias_carries_no_display():
    """Nothing to resolve -> no display_expression, exactly as before. The raw text still differs
    from its lower-cased comparison form, so reading the raw text must not turn the key into an
    always-present copy of `raw_expression`."""
    from scope_lineage.contract.lineage import _stamp_display_expressions
    scope = {
        "alias_source_bindings": [{"alias": "a", "physical_source_id": "src.t_a"}],
        "logic_blocks": [{"raw_expression": "WHERE `tmp_x`.`kind` = 'Alpha'",
                          "normalized_expression": "where `tmp_x`.`kind` = 'alpha'"}],
    }
    _stamp_display_expressions(scope)
    assert "display_expression" not in scope["logic_blocks"][0]


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


def test_the_statement_schema_declares_display_expression_where_it_is_stamped():
    """`_stamp_display_expressions` writes the key on outputs, columns and logic blocks; the
    statement schema declares it on each, as a string, the way its optional siblings are."""
    import json
    from importlib import resources

    schema = json.loads(
        resources.files("scope_lineage.schemas")
        .joinpath("lineage.schema.json")
        .read_text(encoding="utf-8")
    )
    scope = schema["properties"]["scopes"]["additionalProperties"]["properties"]
    for kind in ("outputs", "columns", "logic_blocks"):
        declared = scope[kind]["items"]["properties"]["display_expression"]
        assert declared["type"] == "string", kind
