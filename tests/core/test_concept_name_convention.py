"""The concept layer reads table-name suffixes only from the caller (WP11, D2).

``render/concepts.py`` read ``_df`` / ``_hf`` / ``_mf`` / ``_wf`` / ``_all`` as a full
snapshot and ``_di`` / ``_hi`` / ``_mi`` / ``_wi`` as a period increment: a member's role
(``primary`` / ``snapshot``), the ``increment_with_event_time`` kind vote, the dimension
test and the stem a comment-less table is named by all rested on them. That is one
warehouse's naming convention, so -- like ``semantic packet`` -- the concept layer now
reads it from ``domain-profile/1``'s ``table_name_convention`` and, without one, no
suffix means anything. Every name here is synthetic.
"""

from __future__ import annotations

import pytest

from scope_lineage.render import concepts as concepts_module
from scope_lineage.render.concepts import (
    ROLE_PRIMARY,
    ROLE_SNAPSHOT,
    name_convention,
)

#: The suffixes the concept layer used to ship.
OLD_CONVENTION = {
    "full": ["df", "hf", "mf", "wf", "all"],
    "incremental": ["di", "hi", "mi", "wi"],
}


def _seed(table: str) -> concepts_module._Seed:
    return concepts_module._Seed(
        table=table, entity={}, stem="gadget", tier=None, reason=None,
        key_columns=("gadget_id",), stem_columns=("gadget_id",),
    )


def test_no_suffix_names_a_copy_by_default() -> None:
    assert concepts_module._table_stem("ods.gadget_df") == "gadget_df"
    assert concepts_module._role(_seed("ods.gadget_di"), {}, None) == ROLE_PRIMARY
    assert concepts_module._demoted_role(
        {"table": "ods.gadget_di", "role": ROLE_PRIMARY}
    ) != ROLE_SNAPSHOT


def test_a_configured_convention_restores_the_old_reading() -> None:
    with name_convention(OLD_CONVENTION):
        assert concepts_module._table_stem("ods.gadget_df") == "gadget"
        assert concepts_module._table_stem("ods.gadget_hi") == "gadget"
        assert concepts_module._role(_seed("ods.gadget_di"), {}, None) == ROLE_SNAPSHOT
        assert concepts_module._role(_seed("ods.gadget_df"), {}, None) == ROLE_PRIMARY
        assert concepts_module._demoted_role(
            {"table": "ods.gadget_di", "role": ROLE_PRIMARY}
        ) == ROLE_SNAPSHOT
    assert concepts_module._table_stem("ods.gadget_df") == "gadget_df"


def test_build_concepts_takes_the_convention() -> None:
    entity = {"id": "ods.gadget_di", "columns": []}
    ontology = {"tables": [entity], "table_relations": []}
    cards = {"tables": [{"table": "ods.gadget_di"}]}

    plain = concepts_module.build_concepts(ontology, cards)
    named = concepts_module.build_concepts(ontology, cards, convention=OLD_CONVENTION)

    assert [c["name"] for c in plain["concepts"]] == ["gadget_di"]
    assert [c["name"] for c in named["concepts"]] == ["gadget"]


def test_build_ontology_holds_the_convention_through_the_concept_merges(monkeypatch) -> None:
    """A reviewed merge re-roles a folded member by its suffix, after build_concepts."""
    from scope_lineage.render import ontology as ontology_module

    class Seen(Exception):
        pass

    def spy(*_args, **_kwargs):
        raise Seen(concepts_module._CONVENTION.get().incremental)

    monkeypatch.setattr(ontology_module, "apply_concept_overrides", spy)
    with pytest.raises(Seen) as seen:
        ontology_module.build_ontology([], [], name_convention=OLD_CONVENTION)

    assert seen.value.args == (tuple(OLD_CONVENTION["incremental"]),)


def test_a_stage_suffix_is_still_read_without_a_convention() -> None:
    """Sentinel: a build-step suffix is not part of the configurable convention."""
    assert concepts_module._role(_seed("ods.gadget_tmp"), {}, None) != ROLE_PRIMARY
