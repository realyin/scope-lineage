"""M3: the ontology documents, read concept-first.

M2 renamed the keys; these are the documents that rename exists for. The main line is
the business reading -- an overview, the concept ER, the two concept tables -- and
everything table-level is marked as evidence rather than as the model. A table card
opens section 7 with what the table represents, section 8 with the concept relations its
joins fed, and the table-level joins sit under them as evidence rows.

N2 split what M3 wrote into one file: the per-concept sections became
``concepts/<file>.md`` (``render_concept_markdown``), the appendix became
``appendix.md`` (``render_ontology_appendix_markdown``), and ``ontology.md`` became the
index that links both. The claims are the same claims; each is now checked against the
document that carries it.
"""

from __future__ import annotations

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.ontology import (
    APPENDIX_FILENAME,
    APPENDIX_TITLE,
    CONCEPTS_DIR,
    OVERVIEW_TITLE,
    build_ontology,
    concept_filename,
    concept_files,
    render_concept_markdown,
    render_ontology_appendix_markdown,
    render_ontology_index_markdown,
    render_ontology_table_card_markdown,
)
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.render.table_cards import build_table_cards
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {
    "ods.orders": ["order_id", "cust_no", "amount", "state", "dt"],
    "ods.customer": ["cust_no", "cust_name", "country"],
    "ods.customer_snap": ["cust_no", "cust_name", "dt"],
}

CORPUS = (
    (
        "task_join",
        "INSERT INTO mart.order_wide SELECT o.order_id, o.cust_no, c.cust_name "
        "FROM ods.orders o LEFT JOIN ods.customer c ON o.cust_no = c.cust_no "
        "WHERE o.state IN ('NEW', 'PAID')",
    ),
    (
        "task_daily",
        "INSERT INTO mart.cust_daily SELECT c.cust_no, count(1) AS n FROM ods.customer c "
        "JOIN ods.customer_snap s ON c.cust_no = s.cust_no GROUP BY c.cust_no",
    ),
)


def _corpus() -> tuple[dict, dict]:
    documents = [
        to_lineage_dict(parse_scope_lineage(sql, task, schema=SCHEMA))
        for task, sql in CORPUS
    ]
    profiles = [build_semantic_profile(document) for document in documents]
    cards = build_table_cards(profiles, artifact_root="corpus")
    ontology = build_ontology(documents, profiles, tables=cards, artifact_root="corpus")
    return ontology, cards


def _index() -> str:
    return render_ontology_index_markdown(_corpus()[0])


def _appendix() -> str:
    return render_ontology_appendix_markdown(_corpus()[0])


def _concepts() -> dict[str, str]:
    """``<file>.md -> the concept file's markdown``, the way the CLI writes them."""
    ontology, _cards = _corpus()
    return {
        name: render_concept_markdown(concept, ontology)
        for name, concept in concept_files(ontology).items()
    }


def _card(table: str) -> str:
    ontology, cards = _corpus()
    card = next(item for item in cards["tables"] if str(item["table"]) == table)
    return render_ontology_table_card_markdown(card, ontology)


def _headings(markdown: str, level: str) -> list[str]:
    return [
        line[len(level) + 1 :]
        for line in markdown.split("\n")
        if line.startswith(f"{level} ")
    ]


# ------------------------------------------------------------------- the main line


def test_the_index_runs_overview_then_concepts_then_the_appendix_index() -> None:
    markdown = _index()

    assert _headings(markdown, "##") == [OVERVIEW_TITLE, "概念", "附录索引"]


def test_the_overview_counts_the_concepts_by_kind_and_says_how_many_are_provisional() -> None:
    ontology, _cards = _corpus()
    markdown = render_ontology_index_markdown(ontology)
    overview = markdown.split(f"## {OVERVIEW_TITLE}")[1].split("## ")[0]

    assert "实体 " in overview and "事件 " in overview and "汇总 " in overview
    assert f"{ontology['provisional_count']} 个**临时概念**" in overview
    assert "已确认" in overview


def test_the_overview_carries_the_concept_er_and_the_two_concept_tables() -> None:
    markdown = _index()
    overview = markdown.split(f"## {OVERVIEW_TITLE}")[1].split("\n## 概念\n")[0]

    assert "```mermaid" in overview and "flowchart LR" in overview
    assert "### 概念" in overview
    assert "### 关系" in overview


def test_every_folded_concept_gets_a_file_named_and_kinded(monkeypatch) -> None:
    """N2: what used to be a section of the index is now a document of its own."""
    ontology, _cards = _corpus()
    folded = [
        concept for concept in ontology["concepts"] if concept["tier"] != "provisional"
    ]
    assert folded, "this corpus is supposed to fold a concept"
    files = _concepts()

    for concept in folded:
        name = concept_filename(concept["id"])
        assert files[name].split("\n# ")[1].startswith(f"{concept['name']}（")


def test_the_index_points_at_every_one_of_those_files() -> None:
    markdown = _index()

    for name in _concepts():
        assert f"({CONCEPTS_DIR}/{name})" in markdown


@pytest.mark.parametrize(
    "block", ["## 表现", "## 属性", "## 约束", "## 关系", "## 待人工判定"]
)
def test_a_concept_file_answers_the_five_questions_about_it(block: str) -> None:
    for markdown in _concepts().values():
        assert block in markdown


def test_a_concept_file_lists_its_tables_with_role_basis_and_grain() -> None:
    ontology, _cards = _corpus()
    files = _concepts()

    for concept in concept_files(ontology).values():
        markdown = files[concept_filename(concept["id"])]
        assert "| 表 | 角色 | 依据 | 粒度 |" in markdown
        for member in concept["tables"]:
            assert f"../tables/{member['table']}.md" in markdown


def test_the_provisional_concepts_are_one_table_at_the_end_of_the_concept_part() -> None:
    markdown = _index()
    concepts = markdown.split("\n## 概念\n")[1].split("\n## 附录索引")[0]

    assert "### 临时概念（每表一个，待归并）" in concepts


# --------------------------------------------------------------------- the appendix


@pytest.mark.parametrize(
    "heading",
    [
        "表级关系（证据）",
        "表",
        "表级关系",
        "表族",
        "矛盾发现",
    ],
)
def test_the_appendix_holds_the_table_layer(heading: str) -> None:
    assert f"### {heading}" in _appendix()


def test_the_appendix_holds_the_full_folded_open_item_list() -> None:
    ontology, _cards = _corpus()
    appendix = render_ontology_appendix_markdown(ontology)

    assert "### 待人工判定清单" in appendix
    for group in ontology["open_item_groups"]:
        assert f"`{group['group_id']}`" in appendix


def test_the_table_level_er_is_marked_as_evidence_not_as_the_model() -> None:
    appendix = _appendix()

    assert _headings(appendix, "#") == [APPENDIX_TITLE]
    assert "### 表级关系（证据）" in appendix
    assert "erDiagram" in appendix
    assert "erDiagram" not in _index()


def test_the_index_says_how_much_is_in_the_appendix_and_where_it_is() -> None:
    ontology, _cards = _corpus()
    entry = render_ontology_index_markdown(ontology).split("## 附录索引")[1]

    assert f"[`{APPENDIX_FILENAME}`]({APPENDIX_FILENAME})" in entry
    assert f"**表** {len(ontology['tables'])} 张" in entry
    assert f"**表级关系** {len(ontology['table_relations'])} 条" in entry


# ------------------------------------------------------------------------- the size


def _wide(ontology: dict, concepts: int) -> dict:
    """One corpus's ontology with ``concepts`` folded concepts, for the size bound."""
    template = next(
        item for item in ontology["concepts"] if item["tier"] != "provisional"
    )
    grown = [
        {**template, "id": f"concept:wide_{index:03d}", "name": f"概念{index:03d}"}
        for index in range(concepts)
    ]
    return {**ontology, "concepts": grown, "provisional_count": 0}


def test_a_wide_corpus_grows_the_index_by_a_row_a_concept_and_nothing_else() -> None:
    """N2 replaced M3's caps with a bound: no concept is summarised away any more."""
    ontology, _cards = _corpus()
    wide = _wide(ontology, 47)

    markdown = render_ontology_index_markdown(wide)

    assert "未展开" not in markdown
    assert len(markdown.split("\n")) <= 200 + 2 * 47 + len(wide["relations"])
    assert len(concept_files(wide)) == 47


# ---------------------------------------------------------------- the table cards


def test_section_seven_opens_with_the_concept_then_the_sibling_representations() -> None:
    card = _card("ods.customer")

    identity = card.split("## 7. 身份（本体）")[1].split("## 8.")[0]
    assert identity.index("本表是") < identity.index("**概念中的其他表现**")
    assert identity.index("**概念中的其他表现**") < identity.index("**候选键**")


def test_the_sibling_block_names_the_other_tables_of_the_concept_with_their_roles() -> None:
    card = _card("ods.customer")
    identity = card.split("## 7. 身份（本体）")[1].split("## 8.")[0]

    assert "ods.customer_snap" in identity or "ods.orders" in identity


def test_section_eight_shows_the_concept_relations_with_the_joins_as_evidence() -> None:
    card = _card("ods.orders")
    relations = card.split("## 8. 关系")[1].split("## 9.")[0]

    assert relations.index("**概念关系**") < relations.index("**表级 JOIN（证据）**")


def test_a_card_whose_concept_has_no_relation_says_so_rather_than_printing_a_table() -> None:
    ontology, cards = _corpus()
    lonely = {**ontology, "relations": []}
    card = next(item for item in cards["tables"] if str(item["table"]) == "ods.orders")

    body = render_ontology_table_card_markdown(card, lonely)

    assert "本表所属概念没有可发布的概念关系。" in body


@pytest.mark.parametrize("section", ["9. 约束", "10. 属性同义", "11. 待人工判定"])
def test_the_later_sections_still_stand_and_cite_the_concept(section: str) -> None:
    ontology, cards = _corpus()
    card = next(item for item in cards["tables"] if str(item["table"]) == "ods.customer")
    concept = next(
        item
        for item in ontology["concepts"]
        for member in item["tables"]
        if member["table"] == "ods.customer" and member["membership_basis"] != "reference"
    )

    body = render_ontology_table_card_markdown(card, ontology)
    section_body = body.split(f"## {section}")[1].split("\n## ")[0]

    assert section_body.strip()
    assert f"`{concept['id']}`" in section_body
