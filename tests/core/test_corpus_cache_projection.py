"""The projection each corpus merge is cached through (P2).

The incremental cache used to store the whole semantic profile, which is mostly keys the
merge never looks at. Each consumer now publishes the ones its merge actually reads --
``glossary.PROFILE_FIELDS_READ``, ``table_cards.PROFILE_FIELDS_READ``,
``ontology.PROFILE_FIELDS_READ`` -- beside the code that reads them, and the cache stores
that projection instead.

A whitelist is only as good as the proof that it is complete, and there is exactly one
proof worth having: build the merge from the full profiles and from the projected ones
and compare. Run over the golden corpora, that is the guard -- a consumer that starts
reading a new key breaks here until the list beside it says so.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.corpus_cache import project_profile, union_fields
from scope_lineage.render import glossary as glossary_module
from scope_lineage.render import ontology as ontology_module
from scope_lineage.render import table_cards as table_cards_module
from scope_lineage.render.glossary import build_glossary
from scope_lineage.render.ontology import build_ontology
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.render.table_cards import build_table_cards


FIXTURES = Path(__file__).parent / "fixtures"
# Both document shapes the corpus commands accept: a 1.0 statement document, whose
# profile IS a statement profile, and a 2.0 task document, whose profile wraps a list of
# them. The projection has to answer for both, so both are golden here.
CORPORA = ("lineage_contract", "task_lineage_contract")


def _corpus(name: str) -> tuple[list[dict], list[dict], list[dict]]:
    """``(documents, profiles with diagnostics, profiles without)`` for one corpus."""
    documents, with_diagnostics, without = [], [], []
    for lineage in sorted((FIXTURES / name).rglob("lineage.json")):
        document = json.loads(lineage.read_text(encoding="utf-8"))
        diagnostics_path = lineage.parent / "diagnostics.json"
        diagnostics = (
            json.loads(diagnostics_path.read_text(encoding="utf-8"))
            if diagnostics_path.is_file()
            else None
        )
        documents.append(document)
        with_diagnostics.append(build_semantic_profile(document, diagnostics))
        without.append(build_semantic_profile(document))
    return documents, with_diagnostics, without


def _projected(profiles, fields) -> list[dict]:
    return [project_profile(profile, fields) for profile in profiles]


# --------------------------------------------- the whitelist-completeness guard


@pytest.mark.parametrize("corpus", CORPORA)
def test_the_glossary_reads_nothing_outside_its_own_field_list(corpus: str) -> None:
    documents, _, profiles = _corpus(corpus)
    fields = glossary_module.PROFILE_FIELDS_READ

    full = build_glossary(documents, artifact_root=corpus, profiles=profiles)
    trimmed = build_glossary(
        documents, artifact_root=corpus, profiles=_projected(profiles, fields)
    )

    assert trimmed == full


@pytest.mark.parametrize("corpus", CORPORA)
def test_the_table_cards_read_nothing_outside_their_own_field_list(corpus: str) -> None:
    _, profiles, _ = _corpus(corpus)
    fields = table_cards_module.PROFILE_FIELDS_READ

    full = build_table_cards(profiles, artifact_root=corpus)
    trimmed = build_table_cards(_projected(profiles, fields), artifact_root=corpus)

    assert trimmed == full


@pytest.mark.parametrize("corpus", CORPORA)
def test_the_ontology_reads_nothing_outside_its_own_field_list(corpus: str) -> None:
    """``ontology`` merges through three lists at once.

    Its runner builds the table cards and the value dictionary from the same profiles it
    collected, so the profile it caches is projected through the union of what all three
    builders read -- which is what this compares.
    """
    documents, profiles, glossary_profiles = _corpus(corpus)
    fields = union_fields(
        ontology_module.PROFILE_FIELDS_READ, table_cards_module.PROFILE_FIELDS_READ
    )

    full = _ontology(documents, profiles, glossary_profiles, corpus)
    trimmed = _ontology(
        documents,
        _projected(profiles, fields),
        _projected(glossary_profiles, glossary_module.PROFILE_FIELDS_READ),
        corpus,
    )

    assert trimmed == full


def _ontology(documents, profiles, glossary_profiles, root: str) -> dict:
    """The three layers ``run_ontology`` stacks, in the order it stacks them."""
    glossary = build_glossary(
        documents, artifact_root=root, profiles=glossary_profiles
    )
    cards = build_table_cards(profiles, artifact_root=root)
    return build_ontology(
        documents, profiles, tables=cards, glossary=glossary, artifact_root=root
    )


# ------------------------------------------------------------- the projector


def test_a_task_profile_keeps_its_own_keys_and_its_statements_keys() -> None:
    profile = {
        "artifact_kind": "task_semantic",
        "task_id": "task_one",
        "warning_counts": {"error": 0},
        "statements": [{"statement_id": "s1", "rules": [], "stages": ["dropped"]}],
    }
    fields = {"profile": ("artifact_kind", "task_id"), "statement": {"rules": None}}

    assert project_profile(profile, fields) == {
        "artifact_kind": "task_semantic",
        "task_id": "task_one",
        "statements": [{"rules": []}],
    }


def test_a_bare_statement_profile_is_projected_as_one_statement() -> None:
    """A 1.0 profile has no ``statements``: it is its own statement, and the statement
    half of the list is what applies to it."""
    profile = {"doc_format": "semantic-json/1", "rules": [{"kind": "filter"}], "stages": []}
    fields = {"profile": ("artifact_kind",), "statement": {"rules": None}}

    assert project_profile(profile, fields) == {"rules": [{"kind": "filter"}]}


def test_a_sub_key_list_narrows_every_mapping_under_that_key() -> None:
    profile = {
        "fields": [
            {"column": "order_id", "summary": "kept", "derivation": ["dropped"]},
            {"column": "amount", "derivation": ["dropped"]},
        ],
        "task": {"target_table": "mart.order_daily", "structural_summary": "dropped"},
    }
    fields = {
        "profile": (),
        "statement": {"fields": ("column", "summary"), "task": ("target_table",)},
    }

    assert project_profile(profile, fields) == {
        "fields": [{"column": "order_id", "summary": "kept"}, {"column": "amount"}],
        "task": {"target_table": "mart.order_daily"},
    }


def test_a_key_the_profile_does_not_carry_is_not_invented() -> None:
    """``statement_id`` is absent from a profile built off an AST with no script
    position, and the merge tells that apart from a null one."""
    fields = {"profile": (), "statement": {"statement_id": None, "rules": None}}

    assert project_profile({"rules": []}, fields) == {"rules": []}


def test_the_union_of_two_lists_keeps_what_either_consumer_reads() -> None:
    left = {"profile": ("artifact_kind",), "statement": {"fields": ("column",)}}
    right = {
        "profile": ("task_id",),
        "statement": {"fields": ("summary",), "rules": None},
    }

    assert union_fields(left, right) == {
        "profile": ("artifact_kind", "task_id"),
        "statement": {"fields": ("column", "summary"), "rules": None},
    }


def test_a_whole_value_wins_over_a_sub_key_list_in_a_union() -> None:
    """One consumer reading all of ``fields`` and another reading two of its sub-keys
    means the payload has to carry all of it."""
    left = {"profile": (), "statement": {"fields": ("column",)}}
    right = {"profile": (), "statement": {"fields": None}}

    assert union_fields(left, right)["statement"] == {"fields": None}
    assert union_fields(right, left)["statement"] == {"fields": None}
