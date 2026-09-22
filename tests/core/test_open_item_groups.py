"""Q3: the open list folded by table family, so a review round can read it.

A warehouse names one logical table many times -- a daily increment, a full snapshot, an
hourly one, a `_tmp` staging copy, a `_mid01` step -- and the ontology asks the same
question of every one of them. The flat list publishes that repetition one row at a
time, which is honest and unreadable: the same question about one table family is one
decision, and a reviewer who answers it once wants to copy the answer, not re-read it.

So the questions are folded by ``(kind, table family, question shape)``. The fold is
mechanical -- suffix stripping over the normalised name, no business vocabulary, no
guess about what the tables *mean* -- and it is lossless: ``open_items[]`` keeps every
question, ``open_item_groups[]`` says which ones are the same question, and the answers
still bind concrete tables through ``ontology.overrides.json``.

Two things a measurement over a whole warehouse settled, and they are what the relation
cases below pin. A relation's open question is **not** about the edge: it is "is the far
table unique on these columns", which is one question however many tables join it, so
the group key is the far side alone and the family fold only merges the copies of that
far table. And a group is worth what its answer unblocks, not how many rows it folded,
so every group publishes an ``impact`` and the list is ranked by it.

Every table, column and comment below is synthetic.
"""

from __future__ import annotations

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.render import ontology as ontology_module
from scope_lineage.render.ontology import (
    FINDING_KEY_HINT_CONFLICT,
    OPEN_ITEM_FINDING,
    OPEN_ITEM_KEY,
    OPEN_ITEM_RELATION,
    build_ontology,
    render_ontology_appendix_markdown,
    render_ontology_index_markdown,
    render_ontology_table_card_markdown,
    table_family,
)
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.render.table_cards import build_table_cards
from scope_lineage.scope.scope_builder import parse_scope_lineage


# --------------------------------------------------------------- the synthetic corpus

_ORDER_COLUMNS = [
    {"name": "order_id", "type": "bigint", "comment": "合成订单号"},
    {"name": "party_id", "type": "bigint", "comment": "合成客户号"},
    {"name": "channel_code", "type": "string", "comment": "合成渠道号"},
    {"name": "dt", "type": "string", "comment": "合成分区日"},
]
# A second producer that asks the same question of the same table through a differently
# named local column: same question, so the same group -- and the pattern cannot print
# this column as if the whole group shared it.
_AGENT_COLUMNS = [
    {"name": "agent_id", "type": "bigint", "comment": "合成代理号"},
    {"name": "owner_id", "type": "bigint", "comment": "合成客户号"},
    {"name": "dt", "type": "string", "comment": "合成分区日"},
]
_PARTY_COLUMNS = [
    {"name": "party_id", "type": "bigint", "comment": "合成客户号"},
    {"name": "party_code", "type": "string", "comment": "合成客户编码"},
    {"name": "party_name", "type": "string", "comment": "合成名称"},
    {"name": "dt", "type": "string", "comment": "合成分区日"},
]
# The hint lives on exactly one variant, so the finding group is the *smallest* group in
# the corpus: it still has to be ranked first, which is what "findings first" means.
_HINTED_PARTY_COLUMNS = [
    {**column, "comment": "合成主键编码"} if column["name"] == "party_code" else column
    for column in _PARTY_COLUMNS
]

VARIANTS = ("di", "df", "hi")

SCHEMA = {
    **{
        f"ods.demo_order_{variant}": {"column_details": _ORDER_COLUMNS}
        for variant in VARIANTS
    },
    **{
        f"ods.demo_party_{variant}": {
            "column_details": (
                _HINTED_PARTY_COLUMNS if variant == "hi" else _PARTY_COLUMNS
            )
        }
        for variant in VARIANTS
    },
    "ods.demo_agent_di": {"column_details": _AGENT_COLUMNS},
    "dim.demo_channel": {
        "column_details": [
            {"name": "channel_code", "type": "string", "comment": "合成渠道号"},
            {"name": "channel_name", "type": "string", "comment": "合成渠道名"},
        ]
    },
}

CASES = (
    *(
        (
            f"demo_party_task_{variant}",
            f"INSERT OVERWRITE TABLE mart.demo_wide_{variant} "
            f"SELECT o.order_id AS order_id, p.party_name AS party_name "
            f"FROM ods.demo_order_{variant} o "
            f"LEFT JOIN ods.demo_party_{variant} p ON o.party_id = p.party_id",
        )
        for variant in VARIANTS
    ),
    # Two producers, one dimension: the group's `to` side does not vary, so the pattern
    # keeps it concrete.
    *(
        (
            f"demo_channel_task_{variant}",
            f"INSERT OVERWRITE TABLE mart.demo_channel_{variant} "
            f"SELECT o.order_id AS order_id, c.channel_name AS channel_name "
            f"FROM ods.demo_order_{variant} o "
            f"LEFT JOIN dim.demo_channel c ON o.channel_code = c.channel_code",
        )
        for variant in ("di", "df")
    ),
    # A third producer onto the same party table, through its own column name.
    (
        "demo_agent_task",
        "INSERT OVERWRITE TABLE mart.demo_owner_di "
        "SELECT a.agent_id AS agent_id, p.party_name AS party_name "
        "FROM ods.demo_agent_di a "
        "LEFT JOIN ods.demo_party_di p ON a.owner_id = p.party_id",
    ),
)

PARTY_FAMILY = "ods.demo_party"
ORDER_FAMILY = "ods.demo_order"
CHANNEL_FAMILY = "dim.demo_channel"


def _ontology(*cases, overrides=None) -> dict:
    documents = [
        to_lineage_dict(parse_scope_lineage(sql, task, schema=SCHEMA))
        for task, sql in (cases or CASES)
    ]
    profiles = [build_semantic_profile(document) for document in documents]
    return build_ontology(
        documents,
        profiles,
        tables=build_table_cards(profiles, artifact_root="corpus"),
        overrides=overrides,
        artifact_root="corpus",
    )


@pytest.fixture(scope="module")
def corpus() -> dict:
    return _ontology()


def _group(ontology: dict, kind: str, family: str) -> dict:
    return next(
        group
        for group in ontology["open_item_groups"]
        if group["kind"] == kind and group["family"] == family
    )


def _card(ontology: dict, name: str) -> str:
    documents = [
        to_lineage_dict(parse_scope_lineage(sql, task, schema=SCHEMA))
        for task, sql in CASES
    ]
    cards = build_table_cards(
        [build_semantic_profile(document) for document in documents],
        artifact_root="corpus",
    )
    card = next(item for item in cards["tables"] if str(item["table"]) == name)
    return render_ontology_table_card_markdown(card, ontology)


def _section(markdown: str, title: str) -> str:
    """One `##` or `###` section's body. M3 demoted the table-level ones to `###`."""
    for level in ("## ", "### "):
        _head, marker, tail = markdown.partition(f"\n{level}{title}")
        if marker:
            body, _, _rest = tail.partition("\n## ")
            return body.partition("\n### ")[0]
    raise AssertionError(title)


# ------------------------------------------------------- 1. the family normalisation


@pytest.mark.parametrize(
    "suffix", ["di", "df", "hi", "hf", "mi", "mf", "wi", "wf", "all"]
)
def test_a_date_or_period_suffix_is_stripped(suffix: str) -> None:
    assert table_family(f"ods.demo_party_{suffix}") == PARTY_FAMILY


@pytest.mark.parametrize(
    "suffix", ["tmp", "mid01", "mid5", "step2", "stage03", "bak", "new", "old", "v2"]
)
def test_a_stage_suffix_is_stripped(suffix: str) -> None:
    assert table_family(f"ods.demo_party_{suffix}") == PARTY_FAMILY


def test_a_numeric_tail_is_stripped() -> None:
    assert table_family("ods.demo_party_01") == PARTY_FAMILY


def test_two_suffixes_are_stripped_in_one_pass() -> None:
    assert table_family("ods.demo_party_tmp_di") == PARTY_FAMILY
    assert table_family("ods.demo_party_mid02_tmp") == PARTY_FAMILY


@pytest.mark.parametrize(
    "table",
    [
        # `_dim` is not `_di`, `_info` is not `_i`: the fold compares whole segments,
        # because a prefix match would merge two tables that share three letters.
        "dim.demo_segment_dim",
        "ods.demo_party_info",
        "ods.demo_events_a",
        "ods.demo_party_daily",
    ],
)
def test_a_name_that_only_looks_like_a_suffix_is_not_folded(table: str) -> None:
    assert table_family(table) == table


def test_a_name_that_is_nothing_but_a_suffix_keeps_itself() -> None:
    """Stripping the last segment would fold every staging table into one family."""
    assert table_family("ods.tmp") == "ods.tmp"
    assert table_family("ods.di") == "ods.di"


def test_the_database_is_part_of_the_family() -> None:
    assert table_family("mart.demo_party_di") == "mart.demo_party"
    assert table_family("ods.demo_party_di") != table_family("mart.demo_party_di")
    assert table_family("spark_catalog.ods.demo_party_di") == (
        "spark_catalog.ods.demo_party"
    )


def test_the_entities_and_the_family_index_agree(corpus: dict) -> None:
    families = {item["family"]: item for item in corpus["families"]}

    assert {entity["family"] for entity in corpus["tables"]} == set(families)
    assert families[PARTY_FAMILY]["tables"] == [
        f"ods.demo_party_{variant}" for variant in sorted(VARIANTS)
    ]
    assert families[PARTY_FAMILY]["size"] == len(VARIANTS)
    assert [item["family"] for item in corpus["families"]] == sorted(families)


# ------------------------------------------------------------ 2. the grouping itself


def test_one_key_question_over_a_family_is_one_group(corpus: dict) -> None:
    group = _group(corpus, OPEN_ITEM_KEY, PARTY_FAMILY)

    assert group["shape"] == "party_id"
    assert group["count"] == len(VARIANTS)
    assert sorted(group["items"]) == sorted(
        f"open:key:ods.demo_party_{variant}=party_id" for variant in VARIANTS
    )
    assert group["representative"] == group["items"][0]


def test_a_relation_group_is_the_question_about_the_far_side(corpus: dict) -> None:
    """Every edge into one table asks the same thing: is it unique on these columns?

    The producers differ, their own column names differ, the copy of the far table
    differs -- none of that changes the answer, so none of it is in the group key.
    """
    group = _group(corpus, OPEN_ITEM_RELATION, PARTY_FAMILY)

    assert group["shape"] == "party_id"
    assert group["count"] == len(VARIANTS) + 1
    assert sorted(group["items"]) == sorted(
        [
            *(
                f"open:rel:ods.demo_order_{variant}.party_id"
                f"->ods.demo_party_{variant}.party_id"
                for variant in VARIANTS
            ),
            "open:rel:ods.demo_agent_di.owner_id->ods.demo_party_di.party_id",
        ]
    )
    assert group["group_id"] == f"open:group:rel:{PARTY_FAMILY}=party_id"


def test_the_family_fold_only_merges_the_copies_of_the_far_table(corpus: dict) -> None:
    """Two far tables of one family are one group; two families stay two groups."""
    relations = [
        group
        for group in corpus["open_item_groups"]
        if group["kind"] == OPEN_ITEM_RELATION
    ]

    assert {group["family"] for group in relations} == {PARTY_FAMILY, CHANNEL_FAMILY}
    assert {
        table
        for item in _group(corpus, OPEN_ITEM_RELATION, PARTY_FAMILY)["items"]
        for table in [item.split("->")[1].rsplit(".", 1)[0]]
    } == {f"ods.demo_party_{variant}" for variant in VARIANTS}


def test_one_finding_kind_over_a_family_is_one_group(corpus: dict) -> None:
    group = _group(corpus, OPEN_ITEM_FINDING, PARTY_FAMILY)

    assert group["shape"] == FINDING_KEY_HINT_CONFLICT
    assert group["items"] == [
        "open:finding:key_hint_conflict:ods.demo_party_hi=party_code"
    ]
    assert corpus["finding_groups"] == [
        group
        for group in corpus["open_item_groups"]
        if group["kind"] == OPEN_ITEM_FINDING
    ]


def test_two_column_sets_over_one_family_stay_two_groups(corpus: dict) -> None:
    """The fold is per question, never per table: a different key is a different group."""
    shapes = {
        group["shape"]
        for group in corpus["open_item_groups"]
        if group["kind"] == OPEN_ITEM_KEY
    }

    assert {"party_id", "channel_code"} <= shapes


def test_every_open_item_is_in_exactly_one_group(corpus: dict) -> None:
    grouped = [
        item for group in corpus["open_item_groups"] for item in group["items"]
    ]

    assert sorted(grouped) == sorted(item["id"] for item in corpus["open_items"])
    assert len(grouped) == len(set(grouped))
    assert sum(group["count"] for group in corpus["open_item_groups"]) == len(
        corpus["open_items"]
    )


# ------------------------------------------------------- 3. impact and the ranking


def test_a_relation_group_is_worth_its_producers_and_their_tasks(corpus: dict) -> None:
    """What one answer unblocks: every table that joins it and every task that does."""
    group = _group(corpus, OPEN_ITEM_RELATION, PARTY_FAMILY)

    producers = {
        f"ods.demo_order_{variant}" for variant in VARIANTS
    } | {"ods.demo_agent_di"}
    tasks = {f"demo_party_task_{variant}" for variant in VARIANTS} | {"demo_agent_task"}
    assert group["impact"] == len(producers) + len(tasks)


def test_a_key_group_is_worth_the_edges_its_answer_would_prove(corpus: dict) -> None:
    party = _group(corpus, OPEN_ITEM_KEY, PARTY_FAMILY)
    channel = _group(corpus, OPEN_ITEM_KEY, CHANNEL_FAMILY)

    # Four assumed edges land on the party family (three orders and the agent), two on
    # the channel dimension; confirming the key is what would prove them.
    assert party["impact"] == 4
    assert channel["impact"] == 2


def test_a_finding_group_is_worth_the_contradictions_it_holds(corpus: dict) -> None:
    group = _group(corpus, OPEN_ITEM_FINDING, PARTY_FAMILY)

    assert group["impact"] == group["count"]


def test_the_groups_rank_by_impact_then_size_then_the_flat_list(corpus: dict) -> None:
    ranks = {item["id"]: index for index, item in enumerate(corpus["open_items"])}
    keys = [
        (-group["impact"], -group["count"], ranks[group["representative"]])
        for group in corpus["open_item_groups"]
    ]

    assert keys == sorted(keys)


def test_a_tie_on_impact_is_broken_by_the_group_size(corpus: dict) -> None:
    """The channel edges and the party key are worth the same; the bigger one first."""
    tied = [
        group
        for group in corpus["open_item_groups"]
        if group["impact"] == 4
    ]

    assert [group["kind"] for group in tied] == [OPEN_ITEM_KEY, OPEN_ITEM_RELATION]
    assert [group["count"] for group in tied] == [len(VARIANTS), 2]


# ------------------------------------------------------------ 4. the write-back pattern


def test_the_key_pattern_leaves_the_table_for_the_reviewer(corpus: dict) -> None:
    group = _group(corpus, OPEN_ITEM_KEY, PARTY_FAMILY)

    assert group["write_back_pattern"] == "键:<table>=party_id"


def test_a_relation_pattern_keeps_the_side_the_whole_group_shares(corpus: dict) -> None:
    """`<table>` is the table the group is about; the producers' own column is shared."""
    group = _group(corpus, OPEN_ITEM_RELATION, CHANNEL_FAMILY)

    assert group["write_back_pattern"] == (
        "关系:<from_table>.channel_code-><table>.channel_code"
    )


def test_a_relation_pattern_abstracts_the_side_the_group_disagrees_on(
    corpus: dict,
) -> None:
    """One producer calls its column `owner_id`, so no concrete column is true here."""
    group = _group(corpus, OPEN_ITEM_RELATION, PARTY_FAMILY)

    assert group["write_back_pattern"] == (
        "关系:<from_table>.<from_columns>-><table>.party_id"
    )


def test_a_finding_without_a_write_back_target_has_no_pattern() -> None:
    """Two competing guesses have no single answer, so the group has no pattern."""
    conflict = _ontology(
        (
            "demo_narrow_task",
            "INSERT OVERWRITE TABLE mart.demo_narrow_di "
            "SELECT o.order_id AS order_id, p.party_name AS party_name "
            "FROM ods.demo_order_di o "
            "LEFT JOIN ods.demo_party_di p ON o.party_id = p.party_id",
        ),
        (
            "demo_wide_task",
            "INSERT OVERWRITE TABLE mart.demo_wider_di "
            "SELECT o.order_id AS order_id, p.party_name AS party_name "
            "FROM ods.demo_order_di o LEFT JOIN ods.demo_party_di p "
            "ON o.party_id = p.party_id AND o.dt = p.dt",
        ),
    )
    group = _group(conflict, OPEN_ITEM_FINDING, PARTY_FAMILY)

    assert group["shape"] == "competing_candidate_keys"
    assert group["write_back_pattern"] is None


# ------------------------------------------------------------------- 5. the markdown


def test_the_appendix_prints_one_row_per_group_with_the_counts(corpus: dict) -> None:
    markdown = render_ontology_appendix_markdown(corpus)
    title = (
        f"待人工判定清单（{len(corpus['open_items'])} 条，"
        f"折叠为 {len(corpus['open_item_groups'])} 组）"
    )
    body = _section(markdown, title)

    for group in corpus["open_item_groups"]:
        assert group["group_id"] in body, group["group_id"]
        assert group["representative"] in body, group["group_id"]
    assert "键:<table>=party_id" in body
    # The column the ranking is on has to be readable, or the order looks arbitrary.
    assert "影响" in body
    for group in corpus["open_item_groups"]:
        assert f"| {group['impact']} |" in body, group["group_id"]
    # The flat list is the JSON's job now: the markdown says the question once, and the
    # copies of the table it also applies to are not printed at all.
    assert "open:key:ods.demo_party_hi=party_id" not in body


def test_the_headline_counts_the_groups_as_well_as_the_items(corpus: dict) -> None:
    """The headline is the index's: the counts stayed there when the rows left (N2)."""
    markdown = render_ontology_index_markdown(corpus)

    assert (
        f"待人工判定 {len(corpus['open_items'])} 条 / "
        f"{len(corpus['open_item_groups'])} 组"
    ) in markdown


def test_the_findings_table_is_folded_and_stands_above_the_open_list(
    corpus: dict,
) -> None:
    markdown = render_ontology_appendix_markdown(corpus)
    title = (
        f"矛盾发现（{len(corpus['findings'])} 条，"
        f"折叠为 {len(corpus['finding_groups'])} 组）"
    )
    body = _section(markdown, title)

    assert corpus["finding_groups"][0]["group_id"] in body
    assert markdown.index(f"### {title}") < markdown.index("### 待人工判定清单（")


def test_only_the_first_groups_are_printed_and_the_rest_are_counted(
    corpus: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ontology_module, "OPEN_ITEM_GROUPS_SHOWN", 2)
    groups = corpus["open_item_groups"]
    hidden = groups[2:]
    body = _section(
        render_ontology_appendix_markdown(corpus),
        f"待人工判定清单（{len(corpus['open_items'])} 条，"
        f"折叠为 {len(groups)} 组）",
    )

    for group in groups[:2]:
        assert group["group_id"] in body
    for group in hidden:
        assert group["group_id"] not in body
    assert (
        f"另有 {len(hidden)} 组 {sum(group['count'] for group in hidden)} 条"
    ) in body
    assert "open_item_groups[]" in body


def test_an_empty_list_still_says_so(corpus: dict) -> None:
    empty = {**corpus, "open_items": [], "open_item_groups": [], "findings": [],
             "finding_groups": []}

    assert "本语料没有待人工判定项。" in render_ontology_appendix_markdown(empty)


def test_a_card_cites_the_group_beside_the_item(corpus: dict) -> None:
    body = _section(_card(corpus, "ods.demo_party_di"), "11. 待人工判定")
    group = _group(corpus, OPEN_ITEM_KEY, PARTY_FAMILY)

    assert "open:key:ods.demo_party_di=party_id" in body
    assert group["group_id"] in body


# --------------------------------------------------------------------- 6. stability


def test_the_group_ids_are_the_same_in_two_builds_of_the_same_corpus() -> None:
    first = _ontology(*CASES)
    second = _ontology(*reversed(CASES))

    assert [group["group_id"] for group in first["open_item_groups"]] == [
        group["group_id"] for group in second["open_item_groups"]
    ]
    assert first["open_item_groups"] == second["open_item_groups"]
    assert first["families"] == second["families"]
    assert all(
        group["group_id"].startswith("open:group:")
        for group in first["open_item_groups"]
    )


def test_answering_one_table_shrinks_its_group_without_moving_the_others(
    corpus: dict,
) -> None:
    """An override still binds one concrete table: the fold is a view, not a merge."""
    after = _ontology(
        *CASES,
        overrides={"keys": {"ods.demo_party_di": {"columns": ["party_id"]}}},
    )
    before = _group(corpus, OPEN_ITEM_KEY, PARTY_FAMILY)
    now = _group(after, OPEN_ITEM_KEY, PARTY_FAMILY)

    assert now["count"] == before["count"] - 1
    assert "open:key:ods.demo_party_di=party_id" not in now["items"]
    assert now["group_id"] == before["group_id"]
