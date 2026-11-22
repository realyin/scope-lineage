"""D2 / 5.1: a table family folds period suffixes only when the caller's convention lists them.

``families[]`` and the grouping of open items used to strip a built-in list of period
suffixes (``_di`` / ``_df`` / ``_mi`` / ``_all`` ...) from every table name. That list is
one warehouse's naming convention, so it now comes from ``domain-profile/1``'s
``table_name_convention`` (the union of ``full`` and ``incremental``). Without one only
the generic engineering steps fold: ``_tmp`` / ``_bak`` / ``_new`` / ``_old`` and
numbered steps. All names are synthetic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.cli import main
from scope_lineage.contract import to_lineage_dict
from scope_lineage.domain_profile import load_domain_profile
from scope_lineage.render.ontology import build_ontology, table_family
from scope_lineage.render.review_batches import build_review_batches
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.render.table_cards import build_table_cards
from scope_lineage.scope.scope_builder import parse_scope_lineage

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_PROFILE = ROOT / "examples" / "domain-profile" / "domain-profile.json"
EXAMPLE_CONVENTION = load_domain_profile(EXAMPLE_PROFILE).name_convention

_COLUMNS = [
    {"name": "gadget_id", "type": "bigint", "comment": "合成编号"},
    {"name": "gadget_name", "type": "string", "comment": "合成名称"},
]
_SCHEMA = {
    name: {"column_details": _COLUMNS}
    for name in (
        "ods.gadget_di", "ods.gadget_df", "ods.gadget_tmp", "ods.gadget_mid01",
        "ods.xiao_mi", "ods.sku_all",
    )
}
_CASES = (
    ("demo_task_inc", "INSERT OVERWRITE TABLE mart.gadget_wide SELECT a.gadget_id, b.gadget_name "
     "FROM ods.gadget_di a JOIN ods.gadget_df b ON a.gadget_id = b.gadget_id"),
    ("demo_task_stage", "INSERT OVERWRITE TABLE mart.gadget_step SELECT a.gadget_id, b.gadget_name "
     "FROM ods.gadget_tmp a JOIN ods.gadget_mid01 b ON a.gadget_id = b.gadget_id"),
    ("demo_task_other", "INSERT OVERWRITE TABLE mart.other_wide SELECT a.gadget_id, b.gadget_name "
     "FROM ods.xiao_mi a JOIN ods.sku_all b ON a.gadget_id = b.gadget_id"),
)


def _ontology(name_convention=None, overrides=None) -> dict:
    documents = [
        to_lineage_dict(parse_scope_lineage(sql, task, schema=_SCHEMA)) for task, sql in _CASES
    ]
    profiles = [build_semantic_profile(document) for document in documents]
    return build_ontology(
        documents,
        profiles,
        tables=build_table_cards(profiles, artifact_root="corpus"),
        overrides=overrides,
        artifact_root="corpus",
        name_convention=name_convention,
    )


def _families(ontology: dict) -> dict[str, list[str]]:
    return {item["family"]: item["tables"] for item in ontology["families"]}


# ------------------------------------------------------------------ table_family itself


@pytest.mark.parametrize("table", ["ods.gadget_di", "ods.gadget_df", "ods.xiao_mi", "ods.sku_all"])
def test_without_a_convention_a_period_segment_is_part_of_the_name(table: str) -> None:
    assert table_family(table) == table


@pytest.mark.parametrize("table", ["ods.gadget_tmp", "ods.gadget_mid01", "ods.gadget_bak",
                                   "ods.gadget_v2", "ods.gadget_01"])
def test_without_a_convention_engineering_steps_still_fold(table: str) -> None:
    assert table_family(table) == "ods.gadget"


def test_a_listed_suffix_folds_whole_segments_only() -> None:
    assert table_family("ods.gadget_di", ("di", "df")) == "ods.gadget"
    assert table_family("ods.gadget_tmp_DI", ("di",)) == "ods.gadget"
    assert table_family("ods.gadget_dim", ("di",)) == "ods.gadget_dim"
    assert table_family("ods.di", ("di",)) == "ods.di"


# ------------------------------------------------------------------ build_ontology


def test_without_a_convention_the_copies_are_separate_families() -> None:
    families = _families(_ontology())
    assert families["ods.gadget_di"] == ["ods.gadget_di"]
    assert families["ods.gadget_df"] == ["ods.gadget_df"]
    assert families["ods.xiao_mi"] == ["ods.xiao_mi"]
    assert families["ods.sku_all"] == ["ods.sku_all"]
    assert families["ods.gadget"] == ["ods.gadget_mid01", "ods.gadget_tmp"]
    assert "ods.xiao" not in families and "ods.sku" not in families


def test_the_example_convention_folds_as_before() -> None:
    families = _families(_ontology(EXAMPLE_CONVENTION))
    assert families["ods.gadget"] == [
        "ods.gadget_df", "ods.gadget_di", "ods.gadget_mid01", "ods.gadget_tmp"]
    assert families["ods.xiao"] == ["ods.xiao_mi"]
    assert families["ods.sku"] == ["ods.sku_all"]


def test_open_item_groups_follow_the_published_family() -> None:
    for convention in (None, EXAMPLE_CONVENTION):
        ontology = _ontology(convention)
        family_of = {item["id"]: item["family"] for item in ontology["tables"]}
        items = {item["id"]: item for item in ontology["open_items"]}
        assert ontology["open_item_groups"]
        for group in ontology["open_item_groups"]:
            for item_id in group["items"]:
                item = items[item_id]
                about = item["entity"] if item["kind"] != "relation" else None
                if about is not None and about in family_of:
                    assert group["family"] == family_of[about]


def test_review_batches_read_the_published_family() -> None:
    ontology = _ontology()
    # Republish one family under a different name: the batches must follow the document,
    # not recompute it from the table name.
    for table in ontology["tables"]:
        table["family"] = "ods.relabelled"
    batches = build_review_batches(ontology, by="family")
    labels = {label for batch in batches["batches"] for label in batch["groups"]}
    assert labels == {"ods.relabelled"}


def test_the_overrides_bind_tables_whatever_the_fold() -> None:
    """The write-back keys name tables, relations and concepts -- never a family."""
    plain = _ontology()
    open_keys = [item["write_back"] for item in plain["open_items"] if item.get("write_back")]
    assert open_keys
    overrides: dict = {"keys": {}, "relations": {}}
    for key in open_keys:
        kind, _, rest = key.partition(":")
        if kind == "键":
            table, _, columns = rest.partition("=")
            overrides["keys"][table] = {"columns": columns.split("+")}
        else:
            overrides["relations"][rest] = {}
    applied = {
        name: _ontology(convention, overrides)["overrides_applied"]
        for name, convention in (("plain", None), ("named", EXAMPLE_CONVENTION))
    }
    assert applied["plain"]["keys"] + applied["plain"]["relations"] > 0
    assert applied["plain"]["unmatched"] == applied["named"]["unmatched"] == []
    for counter in ("keys", "relations"):
        assert applied["plain"][counter] == applied["named"][counter]


# ------------------------------------------------------------------ the CLI


def test_the_ontology_command_folds_families_only_with_a_profile(tmp_path: Path) -> None:
    lineage = tmp_path / "lineage"
    lineage.mkdir()
    for task, sql in _CASES:
        document = to_lineage_dict(parse_scope_lineage(sql, task, schema=_SCHEMA))
        (lineage / task).mkdir()
        (lineage / task / "lineage.json").write_text(
            json.dumps(document, ensure_ascii=False), encoding="utf-8")

    def families(out: Path, *extra) -> dict:
        assert main(["ontology", "--lineage", str(lineage), "--out", str(out),
                     "--format", "json", "--no-cache", *extra]) == 0
        document = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
        return _families(document)

    plain = families(tmp_path / "plain")
    named = families(tmp_path / "named", "--domain-profile", str(EXAMPLE_PROFILE))
    assert "ods.gadget_di" in plain and "ods.xiao_mi" in plain
    assert named["ods.gadget"] == [
        "ods.gadget_df", "ods.gadget_di", "ods.gadget_mid01", "ods.gadget_tmp"]
