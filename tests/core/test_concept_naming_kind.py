"""K2b: what a wide corpus said about the names and the kinds the concept layer proposes.

K2 ranked a concept's names off the key column's comment, the table's comment and the
stem. Run over a much wider corpus, four shapes came out at the head of that ranking
that are not names at all: a comment that only marks the column (`…ID`, `…名称`), a
comment whose "this is a key" word sits in the middle rather than at the start
(`逻辑主键`), a comment the catalog's own punctuation kept a suffix rule away from, and
a table comment that names a *filter* or a *measure* over the concept rather than the
concept (`已到期合同欠款`, `2月时段合同`). A fifth was a kind: a concept whose members are
all full snapshots of a thing came out `event` because the snapshot happened to be
rebuilt one row per row of a change log.

Every table, column, comment and name in this file is synthetic. No real corpus, table,
column or business name is reproduced here.
"""

from __future__ import annotations

import pytest

from scope_lineage.render.concepts import (
    CONCEPT_ENTITY,
    CONCEPT_EVENT,
    CONCEPT_SUMMARY,
    JUNK_FILTER,
    JUNK_MEASURE,
    JUNK_PERIOD,
    NAME_FROM_KEY_COMMENT,
    NAME_FROM_STEM,
    NAME_FROM_TABLE_COMMENT,
    SIGNAL_DIMENSION_MEMBERS,
    SIGNAL_DRIVING_LOG_SOURCE,
    TIER_HYPOTHESIS,
    TIER_IMPLIED,
    TIER_STEM_ONLY,
    key_comment_name,
)
from scope_lineage.render import concepts as concepts_module

from .test_concepts import (
    _attribute,
    _card,
    _cards,
    _concepts,
    _consumer,
    _entity,
    _ontology,
    _producer,
    _relation,
)


# --------------------------------------------------------------------- helpers


def _candidates(ontology: dict, cards: dict, concept_id: str) -> list[dict]:
    return list(_concepts(ontology, cards)[concept_id]["name_candidates"])


def _ranked(ontology: dict, cards: dict, concept_id: str) -> list[tuple[str, str]]:
    return [
        (str(item["text"]), str(item["source"]))
        for item in _candidates(ontology, cards, concept_id)
    ]


def _key_named(comment: str) -> str | None:
    """The name one key column's comment proposes as a candidate, or ``None``."""
    ontology = _ontology(
        _entity(
            "ods.cust_base",
            keys=["cust_no"],
            attributes=[_attribute("cust_no", comment=comment)],
        )
    )
    cards = _cards(_card("ods.cust_base", columns=["cust_no"]))
    found = [
        str(item["text"])
        for item in _candidates(ontology, cards, "concept:cust")
        if str(item["source"]) == NAME_FROM_KEY_COMMENT
    ]
    return found[0] if found else None


# ------------------------------------ K2b rule 1: the extended trailing key marker


@pytest.mark.parametrize(
    ("comment", "expected"),
    [
        # The marker a catalog writes in latin, whatever its case.
        ("客户ID", "客户"),
        ("客户Id", "客户"),
        ("客户id", "客户"),
        # The marker that says "this column holds the name of the thing".
        ("机构名称", "机构"),
        ("机构名", "机构"),
        # The marker that says "this column is the key".
        ("合同键", "合同"),
        # Punctuation the catalog left behind, after the marker came off.
        ("客户-编号", "客户"),
        ("机构名称：", "机构"),
    ],
)
def test_the_extended_key_marker_comes_off_a_key_comment(
    comment: str, expected: str
) -> None:
    assert key_comment_name(comment) == expected


@pytest.mark.parametrize(
    "comment",
    # Nothing survives the marker: one Chinese character is not a name.
    ["名称", "编号", "姓名", "ID"],
)
def test_a_comment_that_is_only_a_marker_still_names_nothing(comment: str) -> None:
    assert _key_named(comment) is None


@pytest.mark.parametrize(
    ("comment", "expected"),
    [
        # The K2 protections are untouched: 账号 is the word for what the column holds.
        ("贷款账号", "贷款账号"),
        ("银行卡号", "银行卡号"),
        ("设备型号", "设备型号"),
    ],
)
def test_a_whole_word_ending_in_a_marker_is_left_alone(
    comment: str, expected: str
) -> None:
    assert key_comment_name(comment) == expected


def test_a_table_comment_keeps_no_trailing_dash_between_it_and_its_suffix() -> None:
    """「客户日志表—」 is 客户日志; the dash hid 表 from every suffix rule."""
    ontology = _ontology(_entity("ods.cust_base", keys=["cust_no"], comment="客户日志表—"))
    cards = _cards(_card("ods.cust_base", comment="客户日志表—", columns=["cust_no"]))

    assert _ranked(ontology, cards, "concept:cust") == [
        ("客户日志", NAME_FROM_TABLE_COMMENT),
        ("cust", NAME_FROM_STEM),
    ]


# -------------------------------------------- K2b rule 2: the stoplist, as a substring


@pytest.mark.parametrize(
    "comment",
    # The stoplist word sits in the middle or at the end, never at the start.
    ["逻辑主键", "原始表主键", "唯一去重键", "业务标识码"],
)
def test_a_stoplist_word_anywhere_in_a_key_comment_names_nothing(comment: str) -> None:
    assert _key_named(comment) is None


@pytest.mark.parametrize(
    ("comment", "expected"),
    [
        # A real subject in front of a trailing 流水号 / 标识 survives it.
        ("交易流水号", "交易流水"),
        ("客户标识", "客户"),
    ],
)
def test_a_subject_in_front_of_a_trailing_stoplist_word_survives(
    comment: str, expected: str
) -> None:
    assert _key_named(comment) == expected


# ----------------------------------------------- K2b rule 3: the junk-ranked candidate


def _filtered_corpus(comment: str) -> tuple[dict, dict]:
    """Three tables of one concept whose comment names a slice of it, not the concept."""
    ontology = _ontology(
        _entity(
            "ods.contr_a",
            keys=["contr_no"],
            comment=comment,
            attributes=[_attribute("contr_no", comment="合同编号")],
        ),
        _entity("ods.contr_b", keys=["contr_no"], comment=comment),
        _entity("ods.contr_c", keys=["contr_no"], comment=comment),
    )
    cards = _cards(
        _card("ods.contr_a", comment=comment, columns=["contr_no"]),
        _card("ods.contr_b", comment=comment, columns=["contr_no"]),
        _card("ods.contr_c", comment=comment, columns=["contr_no"]),
    )
    return ontology, cards


@pytest.mark.parametrize(
    ("comment", "reason"),
    [
        ("已到期合同欠款", JUNK_FILTER),
        ("未到期合同首期欠款", JUNK_FILTER),
        ("2月时段合同", JUNK_PERIOD),
        ("合同欠款", JUNK_MEASURE),
        ("合同分数据", JUNK_MEASURE),
    ],
)
def test_a_filter_or_a_measure_never_outranks_the_key_comment(
    comment: str, reason: str
) -> None:
    """Three tables agreeing on a slice still do not outvote the one key comment."""
    ontology, cards = _filtered_corpus(comment)

    candidates = _candidates(ontology, cards, "concept:contr")

    assert [str(item["text"]) for item in candidates][0] == "合同"
    junk = [item for item in candidates if str(item["source"]) == NAME_FROM_TABLE_COMMENT]
    assert [str(item["junk_reason"]) for item in junk] == [reason]
    assert str(candidates[-1]["text"]) == comment


def test_a_plain_table_comment_still_outvotes_a_single_key_comment() -> None:
    """The negative: nothing about 合同信息表 is a filter, a period or a measure."""
    ontology, cards = _filtered_corpus("合同信息表")

    candidates = _candidates(ontology, cards, "concept:contr")

    assert [str(item["text"]) for item in candidates] == ["合同", "合同", "contr"]
    assert [str(item["source"]) for item in candidates] == [
        NAME_FROM_TABLE_COMMENT,
        NAME_FROM_KEY_COMMENT,
        NAME_FROM_STEM,
    ]
    assert not any("junk_reason" in item for item in candidates)


# ------------------------------------------------- K2b rule 4: the dimension's kind


def _dimension_corpus() -> tuple[dict, dict]:
    """A 机构-like snapshot rebuilt one row per row of a change log."""
    ontology = _ontology(
        _entity(
            "dim.org_df",
            keys=["org_no"],
            comment="机构信息表",
            attributes=[_attribute("org_no", comment="机构名称")],
        )
    )
    cards = _cards(
        _card(
            "dim.org_df",
            comment="机构信息表",
            columns=["org_no"],
            produced=[_producer("task:build", basis="driving_table_rows")],
        ),
        _card(
            "ods.org_chg_flow_di",
            comment="机构变更流水",
            columns=["org_no"],
            consumed=[_consumer("task:build", role="driving")],
        ),
    )
    return ontology, cards


def test_a_full_snapshot_of_a_thing_is_an_entity_however_it_was_built() -> None:
    """The rebuild reads a change log; what the table *holds* is still the 机构."""
    ontology, cards = _dimension_corpus()

    concept = _concepts(ontology, cards)["concept:org"]

    signals = [str(vote["signal"]) for vote in concept["kind_evidence"]]

    assert concept["kind"] == CONCEPT_ENTITY
    assert concept["kind_tier"] == TIER_IMPLIED
    assert SIGNAL_DIMENSION_MEMBERS in signals
    assert SIGNAL_DRIVING_LOG_SOURCE not in signals


def test_an_increment_carrying_an_event_time_is_still_an_event() -> None:
    """The negative: the dimension signal never speaks for a period of events."""
    ontology = _ontology(
        _entity(
            "dwd.pay_flow_di",
            keys=["pay_no", "paid_time"],
            comment="回款",
            attributes=[
                _attribute("pay_no", comment="回款编号"),
                _attribute("paid_time", type_="timestamp"),
            ],
        )
    )
    cards = _cards(
        _card("dwd.pay_flow_di", comment="回款", columns=["pay_no", "paid_time"])
    )

    concept = _concepts(ontology, cards)["concept:pay"]

    assert concept["kind"] == CONCEPT_EVENT
    assert SIGNAL_DIMENSION_MEMBERS not in {
        str(vote["signal"]) for vote in concept["kind_evidence"]
    }


def test_a_reference_member_never_casts_a_kind_vote() -> None:
    """A JOIN lends a concept a member, never the member's words."""
    ontology = _ontology(
        _entity("dim.org_df", keys=["org_no"], comment="机构"),
        _entity(
            "dwd.pay_flow_di",
            keys=["pay_no"],
            comment="回款流水",
            attributes=[_attribute("pay_no"), _attribute("org_no")],
        ),
        relations=[_relation("dwd.pay_flow_di", ["org_no"], "dim.org_df", ["org_no"])],
    )
    cards = _cards(
        _card("dim.org_df", comment="机构", columns=["org_no"]),
        _card("dwd.pay_flow_di", comment="回款流水", columns=["pay_no", "org_no"]),
    )

    concept = _concepts(ontology, cards)["concept:org"]

    assert concept["kind"] == CONCEPT_ENTITY
    assert "dwd.pay_flow_di" not in {
        str(vote.get("table")) for vote in concept["kind_evidence"]
    }


# =============================================================== K2c: three residuals
#
# The same wide corpus, run again after K2b. A table comment whose storage suffix hides
# behind a latin tail the `_` convention never marked; a dimension whose only word about
# itself is latin, so K2b's "at least one member calls itself a dimension" half never
# fired and a change-log rebuild carried the kind; and a concept whose every candidate
# was junk-ranked, so the *stem* won and was published as a name with nothing saying it
# is not one.


# ------------------------------------------- K2c rule 1: the latin tail after the dash


def _table_named(comment: str) -> str:
    """The name one table comment proposes, whatever its rank."""
    ontology = _ontology(_entity("ods.cust_base", keys=["cust_no"], comment=comment))
    cards = _cards(_card("ods.cust_base", comment=comment, columns=["cust_no"]))
    found = [
        str(item["text"])
        for item in _candidates(ontology, cards, "concept:cust")
        if str(item["source"]) == NAME_FROM_TABLE_COMMENT
    ]
    return found[0] if found else ""


@pytest.mark.parametrize(
    ("comment", "expected"),
    [
        # K2b already reached these; they stay locked down.
        ("UBS流量日志表-", "UBS流量日志"),
        ("ABC客户信息表—", "ABC客户"),
        # The residual: a `-` marks a segment as surely as a `_` does.
        ("UBS流量日志表-DF", "UBS流量日志"),
        ("ABC客户信息表-df", "ABC客户"),
        ("UBS流量日志表-id", "UBS流量日志"),
    ],
)
def test_a_latin_tail_never_hides_the_storage_suffix(comment: str, expected: str) -> None:
    assert _table_named(comment) == expected


@pytest.mark.parametrize(
    "comment",
    # The negative: a latin tail nobody declared a storage marker stays where it is,
    # and with it the 表 it is standing in front of.
    ["客户信息表-v2", "客户信息表-2024"],
)
def test_an_undeclared_latin_tail_is_left_alone(comment: str) -> None:
    assert _table_named(comment) == comment


# ------------------------------------------ K2c rule 2: the dimension that says `agent`


def _latin_dimension_corpus() -> tuple[dict, dict]:
    """The 机构 shape again, except the only word about the table is latin."""
    ontology = _ontology(
        _entity(
            "ods.agent_df",
            keys=["agent_no"],
            comment="agent",
            attributes=[_attribute("agent_no", comment="机构名称")],
        )
    )
    cards = _cards(
        _card(
            "ods.agent_df",
            comment="agent",
            columns=["agent_no"],
            produced=[_producer("task:build", basis="driving_table_rows")],
        ),
        _card(
            "ods.agent_chg_flow_di",
            comment="机构变更流水",
            columns=["agent_no"],
            consumed=[_consumer("task:build", role="driving")],
        ),
    )
    return ontology, cards


def test_a_dimension_that_only_says_agent_is_still_an_entity() -> None:
    """`agent` is the corpus calling the table a dimension, in the words it had."""
    ontology, cards = _latin_dimension_corpus()

    concept = _concepts(ontology, cards)["concept:agent"]
    signals = [str(vote["signal"]) for vote in concept["kind_evidence"]]

    assert concept["kind"] == CONCEPT_ENTITY
    assert concept["kind_tier"] == TIER_IMPLIED
    assert SIGNAL_DIMENSION_MEMBERS in signals
    assert SIGNAL_DRIVING_LOG_SOURCE not in signals


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ods.agent_df agent", [CONCEPT_ENTITY]),
        ("dwd.click_di click stream", [CONCEPT_EVENT]),
        ("ODS.ORG_DF ORG", [CONCEPT_ENTITY]),
        ("dws.cust_agg_df report", [CONCEPT_SUMMARY]),
        # The negative a whole-word match exists for: a word that merely *contains* one.
        ("ods.catalogue_df catalogue", []),
        ("ods.diagnostics_df diagnostics", []),
    ],
)
def test_a_latin_word_hint_matches_whole_words_only(text: str, expected: list) -> None:
    assert concepts_module._word_votes(text) == expected


# ---------------------------------- K2c rule 3: the stem is not a name, and says so


def _junk_only_corpus(comment: str) -> tuple[dict, dict]:
    ontology = _ontology(
        _entity("ods.queue_a", keys=["queue_no"], comment=comment),
        _entity("ods.queue_b", keys=["queue_no"], comment=comment),
    )
    cards = _cards(
        _card("ods.queue_a", comment=comment, columns=["queue_no"]),
        _card("ods.queue_b", comment=comment, columns=["queue_no"]),
    )
    return ontology, cards


@pytest.mark.parametrize(
    ("comment", "expected"),
    [
        ("2月时段队列欠款", "队列"),
        ("已到期队列欠款", "队列"),
        ("未到期队列首期金额", "队列"),
        ("2024年队列统计", "队列"),
    ],
)
def test_a_clean_phrase_inside_a_junk_comment_beats_the_bare_stem(
    comment: str, expected: str
) -> None:
    """`queue` is the warehouse's spelling; 队列 was in the comment all along."""
    ontology, cards = _junk_only_corpus(comment)

    concept = _concepts(ontology, cards)["concept:queue"]

    assert concept["name"] == expected
    assert concept["name_tier"] == TIER_HYPOTHESIS
    assert str(concept["name_candidates"][0]["source"]) == NAME_FROM_TABLE_COMMENT
    # The comment it was recovered from stays in the evidence, junk reason and all.
    assert comment in {str(item["text"]) for item in concept["name_candidates"]}


def test_a_concept_no_comment_named_says_its_name_is_only_the_stem() -> None:
    """The negative of the rescue: nothing to recover, so the tier says so."""
    ontology = _ontology(_entity("ods.queue_a", keys=["queue_no"]))
    cards = _cards(_card("ods.queue_a", columns=["queue_no"]))

    concept = _concepts(ontology, cards)["concept:queue"]

    assert concept["name"] == "queue"
    assert concept["name_tier"] == TIER_STEM_ONLY
    assert [str(item["source"]) for item in concept["name_candidates"]] == [
        NAME_FROM_STEM
    ]


def test_a_junk_comment_with_no_chinese_left_keeps_the_stem_tier() -> None:
    """The negative again: 欠款 alone recovers nothing, so the stem stands and says so."""
    ontology, cards = _junk_only_corpus("2月欠款")

    concept = _concepts(ontology, cards)["concept:queue"]

    assert concept["name"] == "queue"
    assert concept["name_tier"] == TIER_STEM_ONLY


def test_a_named_concept_is_still_a_hypothesis() -> None:
    """The negative for the tier: a comment named it, so nothing changed."""
    ontology, cards = _junk_only_corpus("队列信息表")

    concept = _concepts(ontology, cards)["concept:queue"]

    assert concept["name"] == "队列"
    assert concept["name_tier"] == TIER_HYPOTHESIS
