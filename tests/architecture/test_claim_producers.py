"""Every function that decides how strong a conclusion is must say by which rule (WP0).

The deep assessment's first round fixed six conclusions that had been carried to an
object they do not hold for -- a batch's key to a table, one task's IN list to a column.
Each fix landed in a private function of its own module, and nothing would remind the
author of the next inference to ask the same questions. This test is that reminder: a
function that reads or writes a strength token (``proven``, ``safe``, a tier, a key
confidence) is either a **producer**, registered here with the rule ids it applies, or a
**reader** that only reports or renders a strength someone else decided. A new function
of either kind fails until it is placed, and the rule ids must exist in
``scope_lineage.render.claims.RULES``.

See ``dev-notes/plans/2026-09-28-assertion-model-design.md`` section 4.4.
"""

from __future__ import annotations

import ast
from pathlib import Path

from scope_lineage.render.claims import RULES

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "scope_lineage"

STRENGTH_NAMES = frozenset({
    "KEY_CONFIDENCE_PROVEN",
    "KEY_CONFIDENCE_PROVEN_UNEXPOSED",
    "KEY_CONFIDENCE_CANDIDATE",
    "TIER_PROVEN",
    "TIER_IMPLIED",
    "TIER_HYPOTHESIS",
    "TIER_CONFLICT",
    "COMPLETENESS_COMPLETE",
})
STRENGTH_LITERALS = frozenset({"proven", "safe", "implied"})

# `module path:function` -> the rules it applies. A producer decides a strength.
PRODUCERS: dict[str, tuple[str, ...]] = {
    # statement level: output keys and JOIN fan-out
    "render/semantic_profile.py:_key_confidence": (
        "R-GROUPBY-KEY", "R-DISTINCT-KEY", "R-ROWNUM-FIRST", "R-EMPTY-GROUPING",
        "R-JOIN-PRESERVE",
    ),
    "render/semantic_profile.py:_split_key_risks": ("R-JOIN-BEFORE-GROUPING",),
    "render/semantic_profile.py:_fan_out_verdict": (
        "R-JOIN-PRESERVE", "R-ROWNUM-FIRST", "R-VALUES-DISTINCT",
    ),
    "render/semantic_profile.py:_grouped_uniqueness": ("R-GROUPBY-KEY", "R-PIN-DROP"),
    "render/semantic_profile.py:_grouped_key_claim": (
        "R-GROUPBY-KEY", "R-PIN-DROP", "R-EMPTY-GROUPING",
    ),
    "render/semantic_profile.py:_ranking_claim": ("R-ROWNUM-FIRST", "R-RANK-FIRST"),
    "render/semantic_profile.py:_values_key_claim": ("R-VALUES-DISTINCT",),
    "render/semantic_profile.py:_card_verdict": (
        "R-REPLACE-STATE", "R-PARTITION-STATE", "R-READ-PIN", "R-PRODUCERS-AGREE",
    ),
    "render/semantic_profile.py:_validity_verdict": ("R-VALIDITY-WINDOW",),
    "render/semantic_profile.py:_validity_claim": ("R-VALIDITY-WINDOW",),
    "render/semantic_profile.py:_capped_confidence": ("R-CANDIDATE-CAP",),
    "render/semantic_profile.py:_read_claim": ("R-READ-PIN",),
    "render/semantic_profile.py:_output_key_claim": (
        "R-GROUPBY-KEY", "R-DISTINCT-KEY", "R-ROWNUM-FIRST", "R-EMPTY-GROUPING",
        "R-DRIVING-KEYS",
    ),
    "render/semantic_profile.py:_card_key_claim": (
        "R-REPLACE-STATE", "R-PARTITION-STATE", "R-PRODUCERS-AGREE",
    ),
    # corpus level: the ontology
    "render/ontology.py:_cardinality": ("R-INTENT-DEDUP",),
    "render/ontology.py:_physical_cardinality": (
        "R-REPLACE-STATE", "R-PARTITION-STATE", "R-READ-PIN", "R-PRODUCERS-AGREE",
        "R-DIRECT-JOIN",
    ),
    "render/ontology.py:_union_edges": ("R-UNION-ALIGN",),
    "render/ontology.py:_rename_pairs": ("R-DIRECT-RENAME",),
    "render/ontology.py:_union_synonym_pairs": ("R-UNION-ALIGN",),
    "render/ontology.py:_not_null_constraints": ("R-FILTER-HINT",),
    "render/ontology.py:_in_set_constraint": ("R-CASE-OUTPUT", "R-FILTER-HINT"),
    "render/ontology.py:_value_set_claim": ("R-CASE-OUTPUT", "R-FILTER-HINT"),
    "render/glossary_values.py:_closure_claim": ("R-CASE-OUTPUT", "R-IN-FILTER"),
    "render/ontology.py:_partition_constraints": ("R-PARTITION-METADATA",),
    "render/ontology.py:_unique_per_constraints": (
        "R-REPLACE-STATE", "R-PARTITION-STATE", "R-PRODUCERS-AGREE",
    ),
    "render/ontology.py:_identity": ("R-INTENT-DEDUP",),
    "render/ontology.py:_candidate_keys": (
        "R-REPLACE-STATE", "R-PARTITION-STATE", "R-PRODUCERS-AGREE", "R-DIRECT-JOIN",
    ),
    "render/ontology.py:_agree_with_hints": ("R-HINT-AGREEMENT",),
    "render/ontology.py:_lift_relation": ("R-HINT-AGREEMENT",),
    "render/ontology.py:_hinted_relation": ("R-COMMENT-RELATION",),
    "render/ontology.py:_relations_with_hints": ("R-COMMENT-RELATION",),
    "render/ontology.py:_competing_candidate_keys": ("R-CONFLICT",),
    "render/ontology.py:_key_hint_conflicts": ("R-CONFLICT",),
    "render/ontology.py:_finding_item": ("R-CONFLICT",),
    # corpus level: concepts
    "render/concepts.py:_concept": ("R-KIND-VOTES",),
    "render/concepts.py:_kind": ("R-KIND-VOTES",),
    "render/concepts.py:_name_tier": ("R-CONCEPT-NAME",),
    "render/concepts.py:_confirm_standalone": ("R-KIND-VOTES", "R-HUMAN-CONFIRM"),
}

# Functions that only report, compare or render a strength decided elsewhere.
READERS: frozenset[str] = frozenset({
    "render/catalog_evidence.py:_grain",
    "render/catalog_evidence.py:grain_conflicts",
    "render/catalog_gaps.py:conflict_text",
    "render/ontology.py:_right_is_grouped",
    "render/ontology.py:_tier_of",
    "render/ontology.py:_contradicts",
    "render/ontology.py:_relation_items",
    "render/ontology.py:_key_items",
    "render/ontology.py:_assumed_by_key",
    "render/ontology.py:_concept_edge_label",
    "render/ontology.py:_mermaid_relation",
    "render/ontology.py:_card_identity",
    "render/ontology.py:_card_open_items",
    "render/ontology_export.py:closed_set",
    "render/ontology_export.py:_linkml_class",
    "render/ontology_export.py:_identifier_column",
    "render/ontology_export.py:_linkml_attribute",
    "render/ontology_export.py:_shacl_node_shape",
    "render/ontology_export.py:_shacl_attribute_shape",
    "render/semantic_markdown.py:_candidate_key_line",
    "render/semantic_profile.py:_driving_key_columns",
    "render/semantic_profile.py:_card_reason",
    "render/semantic_profile.py:_card_claim_level",
    "render/semantic_profile.py:_unsafe_joins",
    "semantics/checks.py:check_grain",
    "semantics/checks_meaning.py:check_fan_out",
    "semantics/checks_meaning.py:_safe_names",
    "semantics/packet_facts.py:statement_keys",
    "semantics/packet_notes.py:mark_unfiltered_rankings",
    "semantics/packet_markdown.py:_keys",
})


def strength_functions(root: Path = PACKAGE_ROOT) -> set[str]:
    """``module:function`` for every function that names a strength token."""
    found: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any(_is_strength(inner) for inner in ast.walk(node)):
                found.add(f"{path.relative_to(root).as_posix()}:{node.name}")
    return found


# A claim's status, spelt through the claims module (`claims.PROVEN`).
CLAIM_STATUS_NAMES = frozenset({"PROVEN", "CONFIRMED", "CONDITIONAL", "HYPOTHESIS"})


def _is_strength(node: ast.AST) -> bool:
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
        return node.id in STRENGTH_NAMES
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "claims"
    ):
        return node.attr in CLAIM_STATUS_NAMES
    return isinstance(node, ast.Constant) and node.value in STRENGTH_LITERALS


def test_every_function_deciding_or_reading_a_strength_is_placed() -> None:
    unplaced = sorted(strength_functions() - set(PRODUCERS) - READERS)

    assert not unplaced, (
        "functions using a strength token that are neither a registered producer "
        "(with rule ids) nor a reader:\n" + "\n".join(unplaced)
    )


def test_the_registry_names_no_function_that_is_gone() -> None:
    stale = sorted((set(PRODUCERS) | READERS) - strength_functions())

    assert not stale, "registered functions that no longer use a strength:\n" + "\n".join(
        stale
    )


def test_a_function_is_either_a_producer_or_a_reader() -> None:
    assert not set(PRODUCERS) & READERS


def test_every_rule_a_producer_names_is_declared() -> None:
    unknown = sorted(
        {rule for rules in PRODUCERS.values() for rule in rules} - set(RULES)
    )

    assert not unknown, f"rule ids not declared in claims.RULES: {unknown}"


def test_the_scan_sees_a_new_strength_function(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text(
        "def decide():\n    return 'proven'\n\n"
        "def claim():\n    return claims.PROVEN\n\n"
        "def other():\n    return 1\n",
        encoding="utf-8",
    )

    assert strength_functions(tmp_path) == {"mod.py:decide", "mod.py:claim"}
