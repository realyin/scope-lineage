"""N2: one markdown file per concept, and an ``ontology.md`` that is an index.

M3 gave every concept a section of its own inside ``ontology.md``. On a wide corpus that
is the whole model in one file -- every concept's section, and the table layer under all
of them -- and a document nobody can scroll answers nothing. N2 splits it: each concept is
its own file under ``concepts/``, everything table-level moves to ``appendix.md``, and
``ontology.md`` keeps only what an index has to keep -- the counts, the diagram, one row
per concept linking to its file, one row per relation, the provisional table, and one
line per appendix section.

The claim the whole work item rests on is a size one: for *any* corpus the index is at
most a fixed overhead plus a couple of lines per concept and one per relation. That is
tested here on a synthetic 300-concept ontology, because it is the only property a
fixture corpus of nine tables can never prove.

Every table, concept, column and name in this file is synthetic. No real corpus is named.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from scope_lineage.cli import main
from scope_lineage.corpus_cache import INDEX_FILE_NAME
from scope_lineage.render.concepts import (
    CONCEPT_ENTITY,
    CONCEPT_EVENT,
    CONCEPT_SUMMARY,
    ROLE_PRIMARY,
    ROLE_REFERENCE,
    ROLE_SNAPSHOT,
    TIER_PROVISIONAL,
)
from scope_lineage.render.ontology import (
    APPENDIX_DOC_FORMAT,
    APPENDIX_FILENAME,
    CONCEPT_DOC_FORMAT,
    CONCEPTS_DIR,
    PROVISIONAL_SHOWN,
    concept_files,
    concept_filename,
    render_concept_markdown,
    render_ontology_appendix_markdown,
    render_ontology_index_markdown,
)
from scope_lineage.render.review_batches import BATCHES_DIR
from scope_lineage.scope.scope_builder import parse_scope_lineage

from .statement_document import write_statement_documents


# -------------------------------------------------------- synthetic ontology parts


def _member(table: str, role: str = ROLE_PRIMARY, basis: str = "key:proven", grain=None) -> dict:
    return {
        "table": table,
        "role": role,
        "membership_basis": basis,
        "key_columns": ["cust_no"],
        "grain": grain,
    }


def _attribute(stem: str, table: str, column: str, comment=None) -> dict:
    return {
        "stem": stem,
        "type": "string",
        "comment": comment,
        "sources": [{"table": table, "column": column}],
    }


def _concept(
    identifier: str,
    name: str,
    kind: str = CONCEPT_ENTITY,
    *,
    tables=(),
    attributes=(),
    tier="implied",
    candidates=(),
    kind_evidence=(),
) -> dict:
    return {
        "id": identifier,
        "name": name,
        "name_tier": "hypothesis",
        "name_candidates": [
            {"text": str(text), "source": "key_stem", "count": 1, "name_evidence": []}
            for text in (candidates or (name,))
        ],
        "kind": kind,
        "kind_tier": "implied",
        "kind_evidence": [dict(item) for item in kind_evidence],
        "identity": {"stem": identifier.split(":")[-1], "columns_seen": ["cust_no"]},
        "tables": [
            item if isinstance(item, dict) else _member(str(item)) for item in tables
        ],
        "attributes": [dict(item) for item in attributes],
        "tier": tier,
    }


def _provisional(table: str, name: str) -> dict:
    concept = _concept(
        f"concept:table:{table.replace('.', '_')}",
        name,
        tables=[_member(table, ROLE_PRIMARY, "table")],
        tier=TIER_PROVISIONAL,
    )
    concept["origin"] = "provisional"
    return concept


def _relation(identifier: str, source: str, target: str, *, evidence=("rel:001",)) -> dict:
    return {
        "id": identifier,
        "from": source,
        "to": target,
        "type": "association",
        "cardinality": {
            "claim": "many_to_one_assumed",
            "tier": "hypothesis",
            "basis": list(evidence),
        },
        "task_count": 2,
        "evidence": [str(item) for item in evidence],
    }


def _table_relation(identifier: str, source: str, target: str, concept_relation: str) -> dict:
    return {
        "id": identifier,
        "from": {"entity": source, "columns": ["cust_no"]},
        "to": {"entity": target, "columns": ["cust_no"]},
        "kind": "join_association",
        "cardinality": {
            "claim": "many_to_one_assumed",
            "tier": "hypothesis",
            "basis": "right_side_not_deduplicated",
        },
        "join_types": ["LEFT_OUTER"],
        "task_count": 2,
        "evidence": [{"task": "task_a", "statement_id": "stmt:001"}],
        "concept_relation": concept_relation,
    }


def _entity(table: str) -> dict:
    return {
        "id": table,
        "kind": "physical_table",
        "identity": {"candidate_keys": [], "declared_hints": [], "multiplicity": []},
        "attributes": [
            {"column": "cust_no", "type": "string", "synonyms": [], "used_in_corpus": True}
        ],
    }


def _ontology(
    *,
    concepts=(),
    relations=(),
    tables=(),
    table_relations=(),
    constraints=(),
    open_items=(),
    open_item_groups=(),
    families=(),
    findings=(),
    finding_groups=(),
    retired_stems=(),
) -> dict:
    return {
        "doc_format": "ontology-json/2",
        "corpus": {"task_count": 2},
        "concepts": [dict(item) for item in concepts],
        "provisional_count": sum(
            1 for item in concepts if str(item.get("tier")) == TIER_PROVISIONAL
        ),
        "retired_stems": [dict(item) for item in retired_stems],
        "relations": [dict(item) for item in relations],
        "representation_links": [],
        "concept_relations_unmapped": {"total": 0, "by_reason": {}},
        "tables": [dict(item) for item in tables],
        "families": [dict(item) for item in families],
        "table_relations": [dict(item) for item in table_relations],
        "constraints": [dict(item) for item in constraints],
        "findings": [dict(item) for item in findings],
        "finding_groups": [dict(item) for item in finding_groups],
        "open_items": [dict(item) for item in open_items],
        "open_item_groups": [dict(item) for item in open_item_groups],
        "overrides_applied": {
            "relations": 0,
            "keys": 0,
            "unmatched": [],
            "ignored_fields": [],
        },
    }


CUSTOMER = _concept(
    "concept:cust",
    "客户",
    CONCEPT_ENTITY,
    tables=[
        _member("ods.cust_base"),
        _member("ods.cust_snap", ROLE_SNAPSHOT, "key:hypothesis", grain="cust_no"),
        _member("ods.msg_log", ROLE_REFERENCE, "reference"),
    ],
    attributes=[
        _attribute("cust", "ods.cust_base", "cust_no", "客户编号"),
        _attribute("name", "ods.cust_base", "cust_name"),
        _attribute("city", "ods.cust_snap", "city_code"),
        _attribute("grade", "ods.cust_snap", "grade_code"),
        _attribute("open", "ods.cust_snap", "open_date"),
        _attribute("close", "ods.cust_snap", "close_date"),
        _attribute("state", "ods.cust_snap", "state_code"),
        _attribute("branch", "ods.cust_snap", "branch_no"),
        _attribute("manager", "ods.cust_snap", "manager_no"),
        _attribute("channel", "ods.cust_snap", "channel_code"),
    ],
    candidates=("客户", "客户号"),
    kind_evidence=[{"signal": "all_members_full_snapshot", "vote": CONCEPT_ENTITY}],
)

MESSAGE = _concept(
    "concept:msg",
    "消息发送",
    CONCEPT_EVENT,
    tables=[_member("ods.msg_log")],
    attributes=[_attribute("msg", "ods.msg_log", "msg_no")],
)

DAILY = _concept(
    "concept:daily",
    "客户日汇总",
    CONCEPT_SUMMARY,
    tables=[_member("mart.cust_daily")],
)


CONSTRAINT = {
    "target": {"entity": "ods.cust_base", "column": "cust_no"},
    "kind": "not_null",
    "tier": "proven",
    "evidence": [{"task": "task_a", "statement_id": "stmt:001"}],
    "concept": "concept:cust",
}

OPEN_ITEM = {
    "id": "open:key:ods.cust_base=cust_no",
    "kind": "candidate_key",
    "entity": "ods.cust_base",
    "columns": ["cust_no"],
    "tier": "hypothesis",
    "write_back": "键:ods.cust_base=cust_no",
    "text": "候选键 `cust_no`：语料没有证明它唯一。",
    "concept": "concept:cust",
}

OPEN_GROUP = {
    "group_id": "open:group:key:ods.cust_base=cust_no",
    "kind": "candidate_key",
    "family": "ods.cust_base",
    "shape": "cust_no",
    "representative": OPEN_ITEM["id"],
    "items": [OPEN_ITEM["id"]],
    "count": 1,
    "impact": 2,
    "write_back_pattern": "键:<table>=cust_no",
    "concept": "concept:cust",
}


def _corpus_ontology() -> dict:
    """Three concepts, two relations, and every per-concept section populated."""
    return _ontology(
        concepts=[CUSTOMER, MESSAGE, DAILY, _provisional("ods.audit_log", "audit_log")],
        relations=[
            _relation("crel:001", "concept:msg", "concept:cust"),
            _relation("crel:002", "concept:daily", "concept:cust", evidence=("rel:002",)),
        ],
        tables=[
            _entity(name)
            for name in (
                "mart.cust_daily",
                "ods.audit_log",
                "ods.cust_base",
                "ods.cust_snap",
                "ods.msg_log",
            )
        ],
        table_relations=[
            _table_relation("rel:001", "ods.msg_log", "ods.cust_base", "crel:001"),
            _table_relation("rel:002", "mart.cust_daily", "ods.cust_base", "crel:002"),
        ],
        constraints=[CONSTRAINT],
        open_items=[OPEN_ITEM],
        open_item_groups=[OPEN_GROUP],
        families=[{"family": "ods.cust_base", "tables": ["ods.cust_base"]}],
    )


def _concept_of(ontology: dict, identifier: str) -> dict:
    return next(item for item in ontology["concepts"] if item["id"] == identifier)


# --------------------------------------------------------------------- filenames


def test_a_concept_id_becomes_the_filename_a_reader_would_guess() -> None:
    assert concept_filename("concept:cust") == "cust.md"
    assert concept_filename("concept:table:ods_cust_base") == "table-ods_cust_base.md"


@pytest.mark.parametrize(
    "identifier",
    ["concept:cust", "concept:table:ods_cust_base", "concept:客户", "concept:a/b", "concept:."],
)
def test_a_concept_filename_holds_nothing_a_file_system_would_choke_on(
    identifier: str,
) -> None:
    name = concept_filename(identifier)

    assert name.endswith(".md")
    assert name not in {".md", "..md"}
    assert all(
        char.isascii() and (char.isalnum() or char in "_-.~") for char in name
    ), name


def test_two_concept_ids_never_reach_one_filename() -> None:
    """Collision-free by construction: the slug is reversible, not merely sanitised.

    ``concept:table:x`` and a reviewed ``new_concepts`` entry spelled ``concept:table-x``
    are two different concepts, and one file holding both would publish one of them and
    silently drop the other.
    """
    identifiers = [
        "concept:cust",
        "concept:table:cust",
        "concept:table-cust",
        "concept:cust-1",
        "concept:cust_1",
        "concept:CUST",
        "concept:客户",
        "concept:客",
        "concept:a/b",
        "concept:a_b",
        "concept:a.b",
    ]

    names = [concept_filename(item) for item in identifiers]

    assert len(set(names)) == len(identifiers), sorted(names)


def test_which_concepts_get_a_file_is_one_answer_both_writers_read() -> None:
    files = concept_files(_corpus_ontology())

    assert set(files) == {"cust.md", "msg.md", "daily.md"}
    assert files["cust.md"]["id"] == "concept:cust"


def test_a_provisional_concept_gets_no_file_of_its_own() -> None:
    """M1: it is a question, not a reading -- it stays one row of the index's table."""
    ontology = _corpus_ontology()

    files = concept_files(ontology)

    assert "table-ods_audit_log.md" not in files
    assert not any(
        str(concept.get("tier")) == TIER_PROVISIONAL for concept in files.values()
    )


# ------------------------------------------------------------- one concept's file


def _customer_file() -> str:
    ontology = _corpus_ontology()
    return render_concept_markdown(_concept_of(ontology, "concept:cust"), ontology)


def test_a_concept_file_opens_with_front_matter_a_tool_can_read() -> None:
    rendered = _customer_file()

    head = rendered.split("---\n")[1]
    assert f'doc_format: "{CONCEPT_DOC_FORMAT}"' in head
    assert 'id: "concept:cust"' in head
    assert 'name: "客户"' in head
    assert 'kind: "entity"' in head
    assert 'tier: "implied"' in head
    assert 'name_tier: "hypothesis"' in head
    assert "table_count: 3" in head
    assert "relation_count: 2" in head


def test_a_concept_file_carries_every_section_the_index_used_to_carry() -> None:
    rendered = _customer_file()

    for heading in (
        "# 客户（实体）",
        "## 表现",
        "## 属性",
        "## 约束",
        "## 关系",
        "## 待人工判定",
        "## 命名与类别依据",
        "## 评审回写键",
    ):
        assert heading in rendered, heading
    assert rendered.endswith("\n")


def test_the_representations_link_back_to_the_table_cards_one_directory_over() -> None:
    rendered = _customer_file()

    assert "[`ods.cust_base`](../tables/ods.cust_base.md)" in rendered
    assert "快照" in rendered and "`key:hypothesis`" in rendered
    assert "`cust_no`" in rendered


def test_a_concept_file_lists_every_attribute_rather_than_the_first_few() -> None:
    """The index summarised them because it had one paragraph; the file has a table."""
    rendered = _customer_file()

    for attribute in CUSTOMER["attributes"]:
        assert f"`{attribute['stem']}`" in rendered
    assert "`ods.cust_snap`.`grade_code`" in rendered
    assert "客户编号" in rendered


def test_the_relation_section_carries_the_joins_each_relation_was_read_off() -> None:
    rendered = _customer_file()

    assert "消息发送" in rendered and "客户日汇总" in rendered
    assert "入" in rendered
    # The table-level JOINs that fed the concept relations, as evidence rows.
    assert "`rel:001`" in rendered and "`rel:002`" in rendered
    assert "`ods.msg_log`.`cust_no`" in rendered
    assert rendered.index("## 关系") < rendered.index("`rel:001`")


def test_the_open_items_filed_under_the_concept_travel_with_it() -> None:
    rendered = _customer_file()

    assert "`open:group:key:ods.cust_base=cust_no`" in rendered
    assert "语料没有证明它唯一" in rendered


def test_the_naming_section_shows_what_voted_for_the_name_and_the_kind() -> None:
    rendered = _customer_file()

    section = rendered.split("## 命名与类别依据")[1]
    assert "客户号" in section and "key_stem" in section
    assert "all_members_full_snapshot" in section


def test_the_write_back_section_names_the_key_a_reviewer_types() -> None:
    rendered = _customer_file()

    section = rendered.split("## 评审回写键")[1]
    assert "`concept:cust`" in section
    assert "concepts.overrides.json" in section
    # A folded concept is not answered with a merge slot; only a provisional one is.
    assert "merge_into" not in section


def test_a_provisional_concept_rendered_directly_is_answered_with_a_merge() -> None:
    """The renderer stays total: the CLI decides who gets a file, not the renderer."""
    ontology = _corpus_ontology()
    concept = _concept_of(ontology, "concept:table:ods_audit_log")

    rendered = render_concept_markdown(concept, ontology)

    assert "merge_into" in rendered.split("## 评审回写键")[1]


def test_rendering_one_concept_twice_writes_the_same_bytes() -> None:
    ontology = _corpus_ontology()
    concept = _concept_of(ontology, "concept:cust")

    assert render_concept_markdown(concept, ontology) == render_concept_markdown(
        concept, ontology
    )
    assert render_ontology_appendix_markdown(ontology) == render_ontology_appendix_markdown(
        ontology
    )


def test_a_concept_nothing_is_known_about_still_renders_every_section() -> None:
    ontology = _ontology(concepts=[_concept("concept:bare", "空概念")])
    concept = _concept_of(ontology, "concept:bare")

    rendered = render_concept_markdown(concept, ontology)

    for heading in ("## 表现", "## 属性", "## 约束", "## 关系", "## 待人工判定"):
        assert heading in rendered, heading


# ------------------------------------------------------------------- the index


def test_the_index_links_every_folded_concept_to_its_own_file() -> None:
    rendered = render_ontology_index_markdown(_corpus_ontology())

    for name, file in (("客户", "cust.md"), ("消息发送", "msg.md"), ("客户日汇总", "daily.md")):
        assert f"[{name}]({CONCEPTS_DIR}/{file})" in rendered, name


def test_the_index_no_longer_expands_a_concept_into_a_section() -> None:
    """The whole point of N2: the per-concept prose moved out of the index."""
    rendered = render_ontology_index_markdown(_corpus_ontology())

    assert "### 客户（实体）" not in rendered
    assert "**属性摘要**" not in rendered
    assert "## 附录：表与证据" not in rendered


def test_the_index_keeps_a_provisional_summary_and_the_ones_worth_answering() -> None:
    """Under the cap the index still shows them all -- and always says where the rest is."""
    rendered = render_ontology_index_markdown(_corpus_ontology())

    section = rendered.split("### 临时概念（每表一个，待归并）")[1]
    assert "1 个临时概念" in section
    assert "`concept:table:ods_audit_log` 的 `merge_into`" in section
    assert f"({APPENDIX_FILENAME}" in section


def test_the_index_replaces_the_appendix_with_one_line_per_section() -> None:
    rendered = render_ontology_index_markdown(_corpus_ontology())

    section = rendered.split("## 附录索引")[1]
    assert f"({APPENDIX_FILENAME}" in section
    assert "tables/" in section
    for text in ("5", "2", "1"):  # tables, table relations, constraints
        assert text in section


def _wide_ontology(count: int, provisional: int = 0) -> dict:
    concepts = [
        _concept(f"concept:c{index:04d}", f"概念{index}", tables=[f"ods.t{index:04d}"])
        for index in range(count)
    ] + [_provisional(f"ods.p{index:04d}", f"p{index:04d}") for index in range(provisional)]
    relations = [
        _relation(f"crel:{index:04d}", f"concept:c{index:04d}", "concept:c0000")
        for index in range(1, count)
    ]
    return _ontology(
        concepts=concepts,
        relations=relations,
        tables=[_entity(f"ods.t{index:04d}") for index in range(count)],
    )


def _bound(ontology: Mapping) -> int:
    """200 fixed + 2 lines per real concept + 1 per relation + the provisional cap."""
    real = [
        item for item in ontology["concepts"] if str(item["tier"]) != TIER_PROVISIONAL
    ]
    return 200 + 2 * len(real) + len(ontology["relations"]) + PROVISIONAL_SHOWN


def test_the_index_stays_an_index_however_wide_the_corpus_is() -> None:
    """The size claim N2 exists for, on a corpus no fixture could hold."""
    ontology = _wide_ontology(300)

    lines = render_ontology_index_markdown(ontology).split("\n")

    assert len(lines) <= _bound(ontology), len(lines)


def test_a_pile_of_provisional_concepts_does_not_grow_the_index() -> None:
    """The failure this change exists for: one row per unplaced table was the index."""
    ontology = _wide_ontology(30, provisional=420)

    lines = render_ontology_index_markdown(ontology).split("\n")

    assert len(lines) <= _bound(ontology), len(lines)
    # The cap is a cap, not a fold: every one of them is in the appendix.
    appendix = render_ontology_appendix_markdown(ontology)
    for index in range(420):
        assert f"`concept:table:ods_p{index:04d}` 的 `merge_into`" in appendix, index


def test_the_index_shows_the_provisional_concepts_worth_answering_first() -> None:
    """Ranked by what an answer unblocks -- the order ``--review-batches`` works them in."""
    ontology = _wide_ontology(2, provisional=40)
    # Two of the last ones carry edges, so the ranking has something to rank on.
    ontology["relations"].extend(
        [
            _relation("crel:9001", "concept:table:ods_p0039", "concept:c0000"),
            _relation("crel:9002", "concept:table:ods_p0039", "concept:c0001"),
            _relation("crel:9003", "concept:table:ods_p0038", "concept:c0000"),
        ]
    )

    section = render_ontology_index_markdown(ontology).split(
        "### 临时概念（每表一个，待归并）"
    )[1]
    rows = [
        line
        for line in section.split("\n")
        if line.startswith("| ") and "`merge_into` |" in line
    ]

    assert len(rows) == PROVISIONAL_SHOWN
    assert "ods.p0039" in rows[0]
    assert "ods.p0038" in rows[1]
    assert f"另有 {40 - PROVISIONAL_SHOWN} 个" in section


def test_a_concept_the_index_does_not_expand_is_still_reachable() -> None:
    """Nothing is hidden behind a cap any more -- every concept has a row and a file."""
    ontology = _wide_ontology(300)
    rendered = render_ontology_index_markdown(ontology)

    files = concept_files(ontology)

    assert len(files) == 300
    assert "未展开" not in rendered
    for name in ("c0000.md", "c0299.md"):
        assert f"({CONCEPTS_DIR}/{name})" in rendered


# ----------------------------------------------------------------- the appendix


def test_the_appendix_holds_the_tables_the_index_dropped() -> None:
    ontology = _corpus_ontology()

    rendered = render_ontology_appendix_markdown(ontology)

    assert f'doc_format: "{APPENDIX_DOC_FORMAT}"' in rendered.split("---\n")[1]
    for heading in (
        "### 表级关系（证据）",
        "### 表",
        "### 表级关系",
        "### 约束",
        "### 表族",
        "### 退役键词根",
        "### 矛盾发现",
    ):
        assert heading in rendered, heading
    assert "待人工判定清单" in rendered
    assert rendered.endswith("\n")


def test_the_full_provisional_table_lives_in_the_appendix() -> None:
    """One row per unplaced table is a list, and a list belongs where the lists are."""
    ontology = _corpus_ontology()

    rendered = render_ontology_appendix_markdown(ontology)

    section = rendered.split("### 临时概念（每表一个，待归并）")[1]
    assert "`concept:table:ods_audit_log` 的 `merge_into`" in section
    assert "`ods.audit_log`" in section


def test_a_corpus_that_placed_every_table_says_so_in_both_documents() -> None:
    ontology = _ontology(concepts=[CUSTOMER])

    for rendered in (
        render_ontology_index_markdown(ontology),
        render_ontology_appendix_markdown(ontology),
    ):
        section = rendered.split("### 临时概念（每表一个，待归并）")[1]
        assert "每张表都归到了某个业务键长出来的概念上" in section


def test_the_appendix_links_the_cards_and_the_index_beside_it() -> None:
    rendered = render_ontology_appendix_markdown(_corpus_ontology())

    assert "[`ods.cust_base`](tables/ods.cust_base.md)" in rendered
    assert "ontology.md" in rendered


# ----------------------------------------------------------------------- the CLI


SCHEMA = {
    "ods.customer_base": ["customer_id", "country_code", "state", "dt"],
    "mart.customer_daily": ["customer_id", "country_code", "dt"],
}

PRODUCER_SQL = (
    "INSERT OVERWRITE TABLE mart.customer_daily PARTITION (dt = '20250101') "
    "SELECT customer_id, max(country_code) AS country_code FROM ods.customer_base "
    "WHERE state IN ('NEW', 'PAID') GROUP BY customer_id"
)

CONSUMER_SQL = (
    "INSERT OVERWRITE TABLE mart.customer_rollup "
    "SELECT b.country_code, count(1) AS n FROM ods.customer_base b "
    "LEFT JOIN mart.customer_daily d ON b.customer_id = d.customer_id "
    "WHERE d.dt = '20250101' GROUP BY b.country_code"
)


def _corpus(root: Path) -> Path:
    for name, sql in (("producer_task", PRODUCER_SQL), ("consumer_task", CONSUMER_SQL)):
        write_statement_documents(parse_scope_lineage(sql, name, schema=SCHEMA), root / name)
    return root


def _run(corpus: Path, out: Path, *extra: str) -> int:
    return main(["ontology", "--lineage", str(corpus), "--out", str(out), *extra])


def test_the_cli_writes_one_file_per_concept_and_the_appendix(tmp_path: Path, capsys) -> None:
    out = tmp_path / "out"

    assert _run(_corpus(tmp_path / "corpus"), out) == 0

    ontology = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    expected = concept_files(ontology)
    written = sorted(item.name for item in (out / CONCEPTS_DIR).glob("*.md"))
    assert written == sorted(expected)
    assert (out / APPENDIX_FILENAME).read_text(encoding="utf-8").startswith("---\n")
    assert f"concept files {len(expected)}" in capsys.readouterr().out


def test_a_card_links_the_concept_file_of_the_concept_it_represents(tmp_path: Path) -> None:
    """A reader told 「本表是客户的主表视图」 is one click from the concept, not one search."""
    out = tmp_path / "out"
    assert _run(_corpus(tmp_path / "corpus"), out) == 0

    ontology = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    folded = next(iter(concept_files(ontology).items()), None)
    assert folded is not None
    name, concept = folded
    table = str(concept["tables"][0]["table"])

    card = (out / "tables" / f"{table}.md").read_text(encoding="utf-8")

    assert f"(../{CONCEPTS_DIR}/{name})" in card


def test_the_index_links_the_review_batches_when_the_run_cut_them(tmp_path: Path) -> None:
    """A reviewer told there are N questions asks where the queue is; the answer is a link."""
    out = tmp_path / "out"
    corpus = _corpus(tmp_path / "corpus")

    assert _run(corpus, out, "--review-batches", str(out)) == 0

    section = (out / "ontology.md").read_text(encoding="utf-8").split(
        "### 临时概念（每表一个，待归并）"
    )[1]
    assert f"({BATCHES_DIR}/)" in section
    assert (out / BATCHES_DIR / "index.md").exists()


def test_without_the_flag_the_index_names_no_batch_directory(tmp_path: Path) -> None:
    """The negative: a link to a directory this run never wrote is a broken promise."""
    out = tmp_path / "out"

    assert _run(_corpus(tmp_path / "corpus"), out) == 0

    section = (out / "ontology.md").read_text(encoding="utf-8").split(
        "### 临时概念（每表一个，待归并）"
    )[1]
    assert f"({BATCHES_DIR}/)" not in section
    assert "--review-batches" in section


def test_a_json_only_run_writes_neither_the_concept_files_nor_the_appendix(
    tmp_path: Path,
) -> None:
    out = tmp_path / "out"

    assert _run(_corpus(tmp_path / "corpus"), out, "--format", "json") == 0

    assert not (out / CONCEPTS_DIR).exists()
    assert not (out / APPENDIX_FILENAME).exists()


def test_the_incremental_bookkeeping_counts_the_concept_files(tmp_path: Path) -> None:
    """A file a run wrote and the cache never heard of is a file nothing cleans up."""
    out = tmp_path / "out"

    assert _run(_corpus(tmp_path / "corpus"), out, "--incremental") == 0

    cache = json.loads((out / INDEX_FILE_NAME).read_text(encoding="utf-8"))
    written = cache["written"]
    ontology = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    for name in concept_files(ontology):
        assert f"{CONCEPTS_DIR}/{name}" in written, name
    assert APPENDIX_FILENAME in written


def test_an_incremental_second_run_rewrites_the_same_concept_files(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path / "corpus")
    first, second = tmp_path / "first", tmp_path / "second"

    assert _run(corpus, first, "--incremental") == 0
    assert _run(corpus, second, "--incremental") == 0
    assert _run(corpus, second, "--incremental") == 0

    def published(root: Path) -> dict[str, str]:
        return {
            str(path.relative_to(root)): path.read_text(encoding="utf-8")
            for path in sorted(root.rglob("*.md"))
        }

    assert published(second) == published(first)
