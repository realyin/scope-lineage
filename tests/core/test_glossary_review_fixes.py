"""Q1: the three things two review rounds spent their budget working around.

The 候选来源 column told a reviewer which rows could be closed by reading. Two rounds
over a corpus said it was still telling them the wrong thing, in three ways:

1. **a CASE label is only a translation inside its own labelling system.** One column
   may carry two CASEs at once -- one bucketing its values into ownership classes,
   another into stage classes -- and a value that happens to be alone in one of them
   read as a 1:1 translation of the code. The same column also gets "labels" that are
   themselves codes from another coding system (``CU_OS_S1_1_1 → S1_1_1``), which
   re-code the value rather than define it;
2. **one code table repeated across many tables was asked once per table.** The same
   ``(column name, value)`` pair is one business question however many tables observed
   it, and answering it per table is the same sentence typed again and again;
3. **the form and the coverage denominator disagreed about what is askable.** The form
   stopped asking about switches, bare numbers and Chinese prose; ``enumerable_code``
   kept counting them, so the ratio a reader saw beside the form was taken over a
   larger set than the form's own questions.

Each section carries its negative: the shape that must NOT take the new route.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.metadata.schema_metadata import SchemaMap
from scope_lineage.render.glossary import build_glossary
from scope_lineage.render.glossary_template import (
    _is_askable,
    build_overrides_template,
    render_overrides_template_markdown,
    template_entries,
)
from scope_lineage.render.glossary_values import askable_value, enumerable_code
from scope_lineage.scope.scope_builder import parse_scope_lineage


EVENT_TABLE = "ods.app_event"

_EVENT_COLUMNS = ("stage", "pay_status", "vip", "channel")


def _event_schema(**comments: str | None) -> SchemaMap:
    """``ods.app_event`` with the columns these tests pin, each with its own comment."""
    return SchemaMap(
        {EVENT_TABLE: ["id", *_EVENT_COLUMNS]},
        column_details={
            EVENT_TABLE: [
                {"name": "id", "type": "bigint", "comment": None},
                *[
                    {"name": name, "type": "string", "comment": comments.get(name)}
                    for name in _EVENT_COLUMNS
                ],
            ]
        },
    )


def _document(sql: str, task_id: str, schema: SchemaMap | None = None) -> dict:
    return to_lineage_dict(parse_scope_lineage(sql, task_id, schema=schema))


def _glossary(*documents, overrides: dict | None = None) -> dict:
    return build_glossary(list(documents), artifact_root="corpus", overrides=overrides)


def _value(glossary: dict, column: str, value: str) -> dict:
    matches = [
        item
        for item in glossary["values"]
        if item["column"] == column and item["value"] == value
    ]
    assert matches, f"{column}={value} missing from the dictionary"
    return matches[0]


def _candidates(glossary: dict, column: str, value: str) -> list[dict]:
    return _value(glossary, column, value)["meaning_candidates"]


def _form(glossary: dict) -> str:
    return render_overrides_template_markdown(
        build_overrides_template(glossary, top=0), glossary
    )


def _case_document(label_sql: str, task_id: str, target: str = "mart.t") -> dict:
    return _document(
        f"INSERT INTO {target} SELECT e.id, {label_sql} AS stage_name "
        f"FROM {EVENT_TABLE} e",
        task_id,
        _event_schema(),
    )


# =============================== 1. label systems and code-shaped labels


_OWNER_CASE = (
    "CASE WHEN e.stage = 'S1' THEN '自营' WHEN e.stage = 'S2' THEN '外包' ELSE '其他' END"
)
_STEP_CASE = (
    "CASE WHEN e.stage = 'S1' THEN '初审' WHEN e.stage = 'S2' THEN '复审' ELSE '其他' END"
)


def _two_system_glossary() -> dict:
    """One column, two CASEs, two different label sets -- the P5c defect itself."""
    return _glossary(
        _case_document(_OWNER_CASE, "task_owner", target="mart.owner"),
        _case_document(_STEP_CASE, "task_step", target="mart.step"),
    )


def test_two_case_rules_with_different_label_sets_are_two_label_systems() -> None:
    glossary = _two_system_glossary()

    assert _value(glossary, "stage", "S1")["label_systems"] == 2
    assert _value(glossary, "stage", "S2")["label_systems"] == 2


def test_each_candidate_names_the_case_rule_it_came_from() -> None:
    candidates = _candidates(_two_system_glossary(), "stage", "S1")
    systems = [str(item["label_system"]) for item in candidates]

    assert len(set(systems)) == 2
    assert all(item.endswith("rule:001") for item in systems)
    assert {item.split("/")[0] for item in systems} == {"task_owner", "task_step"}


def test_the_form_warns_the_column_carries_two_label_systems() -> None:
    form = _form(_two_system_glossary())

    assert f"## `{EVENT_TABLE}.stage`（2 个取值）⚠ 2 套标签体系" in form
    assert "case_label(体系 1/2)" in form


def test_one_case_rule_written_twice_is_still_one_label_system() -> None:
    """The negative: two tasks running the same code table do not disagree."""
    glossary = _glossary(
        _case_document(_OWNER_CASE, "task_a", target="mart.a"),
        _case_document(_OWNER_CASE, "task_b", target="mart.b"),
    )

    assert "label_systems" not in _value(glossary, "stage", "S1")
    assert "label_system" not in _candidates(glossary, "stage", "S1")[0]
    assert "套标签体系" not in _form(glossary)
    assert "| 自营 | case_label |" in _form(glossary)


def test_a_lone_value_inside_a_bucketing_case_is_not_a_translation() -> None:
    glossary = _glossary(
        _case_document(
            "CASE WHEN e.stage = 'S1' THEN '自营' "
            "WHEN e.stage IN ('S2', 'S3') THEN '外包' ELSE '其他' END",
            "task_owner",
        )
    )

    assert _candidates(glossary, "stage", "S1")[0]["single_branch"] is True
    assert "case_label(单值分支)" in _form(glossary)


def test_a_case_that_buckets_nothing_leaves_its_labels_alone() -> None:
    """The negative: every branch one value wide is the corpus translating codes."""
    glossary = _glossary(_case_document(_OWNER_CASE, "task_owner"))

    assert "single_branch" not in _candidates(glossary, "stage", "S1")[0]
    assert "单值分支" not in _form(glossary)


def test_a_label_that_is_itself_a_code_is_published_as_a_synonym() -> None:
    glossary = _glossary(
        _case_document(
            "CASE WHEN e.stage = 'CU_OS_S1_1_1' THEN 'S1_1_1' "
            "WHEN e.stage = 'CU_OS_S2' THEN '已完成' ELSE '其他' END",
            "task_code",
        )
    )
    candidate = _candidates(glossary, "stage", "CU_OS_S1_1_1")[0]

    assert candidate["source"] == "code_alias"
    assert candidate["text"] == "同义码：S1_1_1"
    assert "code_alias" in _form(glossary)


def test_a_label_that_repeats_another_value_of_the_column_is_a_synonym_too() -> None:
    glossary = _glossary(
        _document(
            "INSERT INTO mart.t SELECT e.id, "
            "CASE WHEN e.stage = 'done' THEN 'paid' ELSE '其他' END AS stage_name "
            f"FROM {EVENT_TABLE} e WHERE e.stage IN ('done', 'paid')",
            "task_alias",
            _event_schema(),
        )
    )

    assert _candidates(glossary, "stage", "done")[0]["source"] == "code_alias"


def test_a_capitalised_word_is_a_label_and_not_a_code() -> None:
    """The negative: ``ONLINE`` and ``Paid`` are words somebody chose, not codes."""
    glossary = _glossary(
        _case_document(
            "CASE WHEN e.stage = 'C1' THEN 'ONLINE' "
            "WHEN e.stage = 'C2' THEN 'Paid' ELSE '其他' END",
            "task_word",
        )
    )

    assert _candidates(glossary, "stage", "C1")[0]["source"] == "case_label"
    assert _candidates(glossary, "stage", "C2")[0]["source"] == "case_label"
    assert "code_alias" not in _form(glossary)


# =================================== 2. the column family write-back


_FAMILY_TABLES = ("ods.order_a", "ods.order_b", "ods.order_c")


def _family_schema(table: str) -> SchemaMap:
    return SchemaMap(
        {table: ["id", "pay_status"]},
        column_details={
            table: [
                {"name": "id", "type": "bigint", "comment": None},
                {"name": "pay_status", "type": "string", "comment": None},
            ]
        },
    )


def _family_glossary(*tables: str, overrides: dict | None = None) -> dict:
    return _glossary(
        *[
            _document(
                f"INSERT INTO mart.t_{index} SELECT o.id FROM {table} o "
                "WHERE o.pay_status IN ('PAID', 'REFUND')",
                f"task_{index}",
                _family_schema(table),
            )
            for index, table in enumerate(tables or _FAMILY_TABLES)
        ],
        overrides=overrides,
    )


def _meanings(glossary: dict, value: str) -> dict[str, str]:
    return {
        str(entry["column_ref"]): str((entry.get("meaning") or {}).get("text") or "")
        for entry in glossary["values"]
        if entry["value"] == value
    }


def test_a_family_key_answers_every_table_that_observed_the_value() -> None:
    glossary = _family_glossary(
        overrides={"values": {"*.pay_status=PAID": {"meaning": "已支付"}}}
    )

    assert glossary["overrides_applied"]["values"] == 3
    assert glossary["overrides_applied"]["family_expansions"] == [
        {"key": "*.pay_status=PAID", "applied_to": 3}
    ]
    assert set(_meanings(glossary, "PAID").values()) == {"已支付"}


def test_a_qualified_key_wins_over_the_family_key_for_its_own_table() -> None:
    glossary = _family_glossary(
        overrides={
            "values": {
                "*.pay_status=PAID": {"meaning": "已支付"},
                "ods.order_a.pay_status=PAID": {"meaning": "甲表已支付"},
            }
        }
    )

    assert _meanings(glossary, "PAID")["ods.order_a.pay_status"] == "甲表已支付"
    assert _meanings(glossary, "PAID")["ods.order_b.pay_status"] == "已支付"
    assert glossary["overrides_applied"]["family_expansions"] == [
        {"key": "*.pay_status=PAID", "applied_to": 2}
    ]


def test_a_family_key_that_matches_nothing_is_reported_and_never_dropped() -> None:
    """The negative: a typo in a reviewed file is what the reviewer cannot see."""
    glossary = _family_glossary(
        overrides={"values": {"*.pay_statuz=PAID": {"meaning": "已支付"}}}
    )

    assert glossary["overrides_applied"]["unmatched"] == ["*.pay_statuz=PAID"]
    assert glossary["overrides_applied"]["family_expansions"] == []


def test_the_form_asks_a_repeated_code_table_once_for_the_whole_family() -> None:
    form = _form(_family_glossary())
    template = build_overrides_template(_family_glossary(), top=0)

    assert "## `*.pay_status`（出现在 3 张表）" in form
    assert f"## `{_FAMILY_TABLES[0]}.pay_status`" not in form
    assert set(template["values"]) == {"*.pay_status=PAID", "*.pay_status=REFUND"}


def test_a_pair_seen_in_two_tables_keeps_its_per_table_rows() -> None:
    """The negative: two tables is not a family -- the answers may legitimately differ."""
    form = _form(_family_glossary(*_FAMILY_TABLES[:2]))

    assert "## `*.pay_status`" not in form
    assert f"## `{_FAMILY_TABLES[0]}.pay_status`" in form
    assert f"## `{_FAMILY_TABLES[1]}.pay_status`" in form


# ------------------------------------------- the skill's write-back script


_CONFIRMATIONS = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "scope-lineage"
    / "scripts"
    / "confirmations.py"
)


@pytest.fixture()
def confirmations_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("confirmations", _CONFIRMATIONS)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_the_write_back_script_accepts_a_family_target(confirmations_module) -> None:
    items = confirmations_module.parse_items(
        "Q1. `*.pay_status` 的这两个码分别是什么？\n"
        "- 回写目标：值域:*.pay_status=PAID\n"
        "- 答案：已支付\n"
    )
    write_backs = confirmations_module.build_write_backs(
        items, by="owner", date="2026-09-21"
    )

    assert write_backs["values"] == {
        "*.pay_status=PAID": {
            "meaning": "已支付",
            "confirmed_by": "owner",
            "date": "2026-09-21",
        }
    }


def test_the_write_back_script_still_refuses_a_value_wildcard(
    confirmations_module,
) -> None:
    """The negative: ``=*`` names no value, and the dictionary cannot bind it."""
    items = confirmations_module.parse_items(
        "Q1. `*.pay_status` 的码表是什么？\n"
        "- 回写目标：值域:*.pay_status=*\n"
        "- 答案：已支付\n"
    )
    glossary = _family_glossary(
        overrides={
            "values": dict(
                confirmations_module.build_write_backs(
                    items, by="owner", date="2026-09-21"
                )["values"]
            )
        }
    )

    assert glossary["overrides_applied"]["unmatched"] == ["*.pay_status=*"]


# ======================= 3. ranking and the coverage denominator


_RANK_TABLE = "ods.rank_src"

_RANK_SCHEMA = SchemaMap(
    {_RANK_TABLE: ["id", "enum_code", "mention_code", "plain_code"]},
    column_details={
        _RANK_TABLE: [
            {"name": "id", "type": "bigint", "comment": None},
            {"name": "enum_code", "type": "string", "comment": "AA-已受理，BB-已完成"},
            {
                "name": "mention_code",
                "type": "string",
                "comment": "由上游每日刷新，AA 之后才会有下游动作",
            },
            {"name": "plain_code", "type": "string", "comment": None},
        ]
    },
)


def _rank_glossary() -> dict:
    return _glossary(
        _document(
            f"INSERT INTO mart.t SELECT r.id FROM {_RANK_TABLE} r "
            "WHERE r.enum_code IN ('AA', 'BB') "
            "AND r.mention_code IN ('AA', 'BB') "
            "AND r.plain_code IN ('PA', 'PB', 'PC')",
            "task_rank",
            _RANK_SCHEMA,
        )
    )


def _ranked_columns(glossary: dict) -> list[str]:
    ordered: list[str] = []
    for entry in template_entries(glossary, top=0):
        if entry["column"] not in ordered:
            ordered.append(str(entry["column"]))
    return ordered


def test_a_column_whose_only_clue_is_a_mention_ranks_with_the_unanswered_ones() -> None:
    assert _ranked_columns(_rank_glossary()) == [
        "enum_code",
        "plain_code",
        "mention_code",
    ]


def test_a_bucket_label_does_not_lift_a_column_over_a_larger_one() -> None:
    """The negative half of the same rule, on the other kind of non-evidence."""
    glossary = _glossary(
        _document(
            "INSERT INTO mart.t SELECT e.id, "
            "CASE WHEN e.stage IN ('S1', 'S2') THEN '进行中' ELSE '未知' END AS stage_name "
            f"FROM {EVENT_TABLE} e WHERE e.channel IN ('CA', 'CB', 'CC')",
            "task_bucket",
            _event_schema(),
        )
    )
    ordered = [name for name in _ranked_columns(glossary) if name in ("stage", "channel")]

    assert ordered == ["channel", "stage"]


def test_a_column_the_comment_enumerates_still_comes_first() -> None:
    """The positive: evidence somebody can act on is still the cheapest part."""
    assert _ranked_columns(_rank_glossary())[0] == "enum_code"


def _ranked_column_refs(glossary: dict) -> list[str]:
    ordered: list[str] = []
    for entry in template_entries(glossary, top=0):
        if entry["column_ref"] not in ordered:
            ordered.append(str(entry["column_ref"]))
    return ordered


def _same_name_glossary() -> dict:
    """One value answered by a PERSON on one table; the same value open on another."""
    return _glossary(
        _document(
            "INSERT INTO mart.t_a SELECT o.id FROM ods.order_a o "
            "WHERE o.pay_status IN ('PAID', 'REFUND')",
            "task_a",
            _family_schema("ods.order_a"),
        ),
        _document(
            "INSERT INTO mart.t_b SELECT o.id FROM ods.order_b o "
            "WHERE o.pay_status IN ('PAID', 'REFUND') "
            "AND o.plain_code IN ('PA', 'PB', 'PC')",
            "task_b",
            SchemaMap(
                {"ods.order_b": ["id", "pay_status", "plain_code"]},
                column_details={
                    "ods.order_b": [
                        {"name": "id", "type": "bigint", "comment": None},
                        {"name": "pay_status", "type": "string", "comment": None},
                        {"name": "plain_code", "type": "string", "comment": None},
                    ]
                },
            ),
        ),
        overrides={
            "values": {
                "ods.order_a.pay_status=PAID": {
                    "meaning": "已支付",
                    "confirmed_by": "owner",
                }
            }
        },
    )


def test_a_value_a_person_confirmed_on_a_same_named_column_is_still_evidence() -> None:
    """The third route of the review prompt keeps its place at the front of the form.

    A human answer on `ods.order_a.pay_status` is what the same-name rule rests on, so
    the identically named column of another table is a row a reviewer closes by reading
    -- it outranks a larger column that carries nothing, exactly as an enumeration does.
    """
    ordered = _ranked_column_refs(_same_name_glossary())

    assert ordered[0] == "ods.order_b.pay_status"
    assert ordered.index("ods.order_b.plain_code") > 0


# ------------------------------- the coverage denominator and the form agree


def _askable_glossary(comment: str | None, column: str, *values: str) -> dict:
    listed = ", ".join(f"'{value}'" for value in values)
    return _glossary(
        _document(
            f"INSERT INTO mart.t SELECT e.id FROM {EVENT_TABLE} e "
            f"WHERE e.{column} IN ({listed})",
            "task_askable",
            _event_schema(**{column: comment}),
        )
    )


@pytest.mark.parametrize(
    "comment, column, values, expected",
    [
        (None, "vip", ("Y", "N"), False),
        ("Y-是，N-否", "vip", ("Y", "N"), True),
        (None, "channel", ("委外", "触达成功"), False),
        (None, "stage", ("AA", "BB"), True),
    ],
)
def test_the_denominator_counts_exactly_what_the_form_asks_about(
    comment, column, values, expected
) -> None:
    glossary = _askable_glossary(comment, column, *values)

    for entry in glossary["values"]:
        if entry["column"] != column:
            continue
        assert askable_value(entry) is expected
        assert _is_askable(entry) is expected
        assert enumerable_code(entry) is expected


def test_the_published_coverage_moves_with_the_form(tmp_path: Path) -> None:
    """A switch nobody defined is no longer counted in the ratio beside the form."""
    from scope_lineage.render.glossary import apply_glossary
    from scope_lineage.render.semantic_profile import build_semantic_profile

    document = json.loads(
        json.dumps(
            _document(
                f"INSERT INTO mart.t SELECT e.id FROM {EVENT_TABLE} e "
                "WHERE e.vip IN ('Y', 'N')",
                "task_cover",
                _event_schema(),
            )
        )
    )
    glossary = _glossary(document)
    profile = apply_glossary(build_semantic_profile(document), glossary)
    coverage = profile["confidence"]["metadata_coverage"]["glossary"]

    assert coverage["enumerable_total"] == 0
    assert build_overrides_template(glossary, top=0)["values"] == {}
