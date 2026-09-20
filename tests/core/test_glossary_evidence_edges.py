"""Q1b: the four ways the fill-in form still told a review round the wrong thing.

A third real round read 候选来源 as "this row can be closed by reading" and found four
shapes where that reading was wrong, all of them invisible in the form:

1. **a label may hold only under a condition.** One CASE maps ``col = 'v'`` to one label
   under ``WHEN col = 'v' AND report_dt >= '…'`` and to another under a later plain
   ``WHEN col = 'v'``. The compound branch produces no observation, so the form printed
   the second label as a clean 1:1 translation of the code -- and it is the second half
   of a two-part rule, not a name;
2. **the comment and the CASE may disagree.** A column whose comment enumerates
   ``AA-有效`` while a CASE labels ``AA`` 作废 carries two answers, and the prompt's
   "two contradicting pieces of evidence close nothing" rule was a sentence a reviewer
   had to apply by hand across two columns of the same row;
3. **an ELSE may be a class rather than a default.** ``CASE WHEN col = 'X' THEN '自营'
   ELSE '委外' END`` sorts the column into two classes; the ELSE covers every other
   value, so 自营 is one side of a classification and not the meaning of ``X``;
4. **a family section threw its members' evidence away.** ``*.<column>`` asks one
   question for the whole family, and it used to answer it off whichever table sorted
   first -- so a code table written down on ONE of the five tables was invisible.

Each rule carries its negative: the shape that must NOT take the new route.
"""

from __future__ import annotations

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.metadata.schema_metadata import SchemaMap
from scope_lineage.render.glossary import build_glossary
from scope_lineage.render.glossary_template import (
    build_overrides_template,
    render_overrides_template_markdown,
)
from scope_lineage.scope.scope_builder import parse_scope_lineage


EVENT_TABLE = "ods.app_event"

_EVENT_COLUMNS = ("stage", "status", "report_dt")


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


def _glossary(*documents) -> dict:
    return build_glossary(list(documents), artifact_root="corpus")


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


def _row(form: str, value: str) -> str:
    """The one form row asking about ``value``, so a test reads the cells it means."""
    rows = [line for line in form.splitlines() if line.startswith(f"| `{value}` |")]
    assert len(rows) == 1, f"expected exactly one row for {value}, got {rows}"
    return rows[0]


def _select(projection: str, task_id: str, schema: SchemaMap, tail: str = "") -> dict:
    return _document(
        f"INSERT INTO mart.t SELECT e.id, {projection} AS stage_name "
        f"FROM {EVENT_TABLE} e {tail}",
        task_id,
        schema,
    )


# ======================================== 1. a label that holds only under a condition


_CONDITIONAL_CASE = (
    "CASE WHEN e.stage = 'S1' AND e.report_dt >= '20260101' THEN '自营' "
    "WHEN e.stage = 'S1' THEN '外包' "
    "WHEN e.stage = 'S2' THEN '复审' ELSE '其他' END"
)

_PLAIN_CASE = (
    "CASE WHEN e.stage = 'S1' THEN '外包' WHEN e.stage = 'S2' THEN '复审' ELSE '其他' END"
)


def _conditional_glossary() -> dict:
    return _glossary(_select(_CONDITIONAL_CASE, "task_cond", _event_schema()))


def test_a_label_from_a_case_with_a_compound_branch_is_marked_conditional() -> None:
    candidate = _candidates(_conditional_glossary(), "stage", "S1")[0]

    assert candidate["conditional"] is True
    assert candidate["text"] == "有条件：外包"


def test_the_condition_the_other_branch_added_is_published_on_the_candidate() -> None:
    candidate = _candidates(_conditional_glossary(), "stage", "S1")[0]

    assert "report_dt" in candidate["condition"]
    assert "20260101" in candidate["condition"]


def test_the_form_prints_a_conditional_label_as_conditional_and_asks_about_it() -> None:
    form = _form(_conditional_glossary())

    assert "case_label(有条件)" in _row(form, "S1")


def test_a_value_the_compound_branch_never_named_keeps_its_clean_label() -> None:
    """The negative inside the same CASE: only ``S1`` was written twice."""
    candidate = _candidates(_conditional_glossary(), "stage", "S2")[0]

    assert "conditional" not in candidate
    assert candidate["text"] == "复审"


def test_a_case_without_a_compound_branch_labels_nothing_conditionally() -> None:
    """The negative: one predicate per branch is the corpus translating codes."""
    glossary = _glossary(_select(_PLAIN_CASE, "task_plain", _event_schema()))

    assert "conditional" not in _candidates(glossary, "stage", "S1")[0]
    assert "有条件" not in _form(glossary)


# ============================== 2. the comment and the CASE disagreeing about one value


_STATUS_COMMENT = "受理状态(AA-有效，BB-无效)"

_DISAGREEING_CASE = (
    "CASE WHEN e.status = 'AA' THEN '作废' "
    "WHEN e.status = 'BB' THEN '无效' ELSE '其他' END"
)

_AGREEING_CASE = (
    "CASE WHEN e.status = 'AA' THEN '有效' "
    "WHEN e.status = 'BB' THEN '无效' ELSE '其他' END"
)


def _status_form(case: str, comment: str = _STATUS_COMMENT) -> str:
    return _form(
        _glossary(_select(case, "task_status", _event_schema(status=comment)))
    )


def test_a_comment_and_a_case_label_that_disagree_are_marked_a_contradiction() -> None:
    assert "⚠ 矛盾" in _row(_status_form(_DISAGREEING_CASE), "AA")


def test_the_value_both_sources_agree_on_stays_clean_in_the_same_column() -> None:
    assert "⚠ 矛盾" not in _row(_status_form(_DISAGREEING_CASE), "BB")


def test_an_agreeing_comment_and_case_label_leave_the_row_untouched() -> None:
    """The negative: the same answer written twice is not a disagreement."""
    row = _row(_status_form(_AGREEING_CASE), "AA")

    assert "⚠ 矛盾" not in row
    assert "comment_enum、case_label" in row


def test_a_label_the_comment_spells_out_at_greater_length_agrees() -> None:
    """The negative: ``有效`` inside ``已受理有效`` is the same answer, said longer."""
    row = _row(_status_form(_AGREEING_CASE, "受理状态(AA-已受理有效，BB-无效)"), "AA")

    assert "⚠ 矛盾" not in row


# ========================================= 3. an ELSE that is a class, not a default


_OBSERVED_TAIL = "WHERE e.stage IN ('X1', 'X2', 'X3')"

_CLASSIFYING_CASE = "CASE WHEN e.stage = 'X1' THEN '自营' ELSE '委外' END"

_EXHAUSTIVE_CASE = (
    "CASE WHEN e.stage = 'X1' THEN '自营' WHEN e.stage = 'X2' THEN '代理' ELSE '其他' END"
)

_NULL_ELSE_CASE = "CASE WHEN e.stage = 'X1' THEN '自营' ELSE NULL END"


def _stage_glossary(case: str, tail: str = _OBSERVED_TAIL) -> dict:
    return _glossary(_select(case, "task_stage", _event_schema(), tail))


def test_a_case_whose_else_is_a_label_classifies_rather_than_translates() -> None:
    glossary = _stage_glossary(_CLASSIFYING_CASE)

    assert _candidates(glossary, "stage", "X1")[0]["single_branch"] is True
    assert "case_label(单值分支)" in _row(_form(glossary), "X1")


def test_a_case_that_gives_every_observed_value_its_own_branch_stays_a_mapping() -> None:
    """The negative: an ELSE nobody's value reaches is a default, not a class."""
    glossary = _stage_glossary(_EXHAUSTIVE_CASE, "WHERE e.stage IN ('X1', 'X2')")

    assert "single_branch" not in _candidates(glossary, "stage", "X1")[0]
    assert "| case_label |" in _row(_form(glossary), "X1")


def test_a_null_else_classifies_nothing() -> None:
    """The negative: ``ELSE NULL`` says the other values have no label at all."""
    glossary = _stage_glossary(_NULL_ELSE_CASE)

    assert "single_branch" not in _candidates(glossary, "stage", "X1")[0]
    assert "单值分支" not in _form(glossary)


# ================================= 4. a family section reading every member's evidence


_FAMILY_TABLES = ("ods.order_a", "ods.order_b", "ods.order_c")

_PAY_COMMENT = "支付状态(PAID-已支付，REFUND-已退款)"


def _family_schema(table: str, comment: str | None) -> SchemaMap:
    return SchemaMap(
        {table: ["id", "pay_status"]},
        column_details={
            table: [
                {"name": "id", "type": "bigint", "comment": None},
                {"name": "pay_status", "type": "string", "comment": comment},
            ]
        },
    )


def _family_form(*comments: str | None) -> str:
    return _form(
        _glossary(
            *[
                _document(
                    f"INSERT INTO mart.t_{index} SELECT o.id FROM {table} o "
                    "WHERE o.pay_status IN ('PAID', 'REFUND')",
                    f"task_{index}",
                    _family_schema(table, comment),
                )
                for index, (table, comment) in enumerate(zip(_FAMILY_TABLES, comments))
            ]
        )
    )


@pytest.fixture()
def documented_family() -> str:
    """The family, with the code table written down on exactly one of its tables."""
    return _family_form(None, _PAY_COMMENT, None)


def test_a_family_row_carries_the_evidence_any_member_table_supplied(
    documented_family: str,
) -> None:
    assert "## `*.pay_status`（出现在 3 张表）" in documented_family
    assert "comment_enum" in _row(documented_family, "PAID")


def test_a_family_row_names_the_member_table_the_evidence_came_from(
    documented_family: str,
) -> None:
    assert _FAMILY_TABLES[1] in _row(documented_family, "PAID")


def test_a_family_row_shows_the_comment_clue_of_the_member_that_has_one(
    documented_family: str,
) -> None:
    assert "已支付" in _row(documented_family, "PAID")


def test_a_family_nobody_documented_still_says_it_has_no_evidence() -> None:
    """The negative: a union of nothing is nothing, and the row says so."""
    form = _family_form(None, None, None)

    assert "## `*.pay_status`（出现在 3 张表）" in form
    assert _row(form, "PAID").endswith("| — |  |")
