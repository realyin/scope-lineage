"""P5: the evidence-based confirmation mode of the value dictionary.

The ontology review already has it: an Agent may close an open item *by evidence the
corpus already contains*, provided it says in `basis` what closed it, and a confirmation
signed `agent:…` without a `basis` is refused rather than published. The glossary now
answers to the same discipline, over its own three kinds of evidence -- the column's own
comment enumerates the value, a CASE in the corpus maps the value to a label, or the same
value on the same column NAME is already confirmed by a human.

What the tests pin, in the order the reviewer meets it:

1. the overrides file: `basis` / `note` published beside `confirmed_by`, an unknown field
   reported rather than dropped, and an `agent:` confirmation with no `basis` rejected;
2. the CASE-label candidate route, and every shape it must NOT fire on;
3. the form: which evidence each value has, and evidence-carrying columns asked first;
4. `glossary.md`: a confirmed meaning shows what it was confirmed on.
"""

from __future__ import annotations

from scope_lineage.contract import to_lineage_dict
from scope_lineage.metadata.schema_metadata import SchemaMap
from scope_lineage.render.glossary import (
    apply_glossary,
    build_glossary,
    render_glossary_markdown,
)
from scope_lineage.render.glossary_template import (
    build_overrides_template,
    render_overrides_template_markdown,
    template_entries,
)
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.scope.scope_builder import parse_scope_lineage


DATE = "2026-09-21"


def _document(sql: str, task_id: str = "evidence_case", schema=None) -> dict:
    return to_lineage_dict(parse_scope_lineage(sql, task_id, schema=schema))


def _glossary(*documents, overrides=None) -> dict:
    return build_glossary(list(documents), artifact_root="corpus", overrides=overrides)


def _value(glossary: dict, column: str, value: str) -> dict:
    matches = [
        item
        for item in glossary["values"]
        if item["column"] == column and item["value"] == value
    ]
    assert matches, f"{column}={value} not in {[item['value'] for item in glossary['values']]}"
    return matches[0]


def _candidates(glossary: dict, column: str, value: str) -> list[dict]:
    return _value(glossary, column, value)["meaning_candidates"]


def _labels(glossary: dict) -> list[str]:
    """Every CASE label the whole dictionary offers, whichever value it hangs off."""
    return [
        item["text"]
        for entry in glossary["values"]
        for item in entry["meaning_candidates"]
        if item["source"] == "case_label"
    ]


def _order_schema(table: str, comment: str | None) -> SchemaMap:
    return SchemaMap(
        {table: ["order_id", "pay_status"]},
        column_details={
            table: [
                {"name": "order_id", "type": "bigint", "comment": None},
                {"name": "pay_status", "type": "string", "comment": comment},
            ]
        },
    )


def _order_document(table: str = "ods.app_order", task: str = "orders") -> dict:
    return _document(
        f"INSERT INTO mart.t SELECT o.order_id FROM {table} o "
        "WHERE o.pay_status IN ('PAID', 'REFUND')",
        task,
        schema=_order_schema(table, "Payment status"),
    )


def _value_override(**payload) -> dict:
    return {"values": {"ods.app_order.pay_status='PAID'": payload}}


# ------------------------------------------------- 1. basis, note and what is refused


def test_a_confirmation_publishes_its_basis_and_note_beside_who_signed_it() -> None:
    glossary = _glossary(
        _order_document(),
        overrides=_value_override(
            meaning="已支付",
            basis="列注释枚举了该取值",
            note="与上游口径一致",
            confirmed_by="agent:glossary-review",
            date=DATE,
        ),
    )

    assert _value(glossary, "pay_status", "PAID")["meaning"] == {
        "text": "已支付",
        "source": "override",
        "confirmed_by": "agent:glossary-review",
        "date": DATE,
        "confirmed_basis": "列注释枚举了该取值",
        "note": "与上游口径一致",
    }
    assert glossary["overrides_applied"]["values"] == 1
    assert glossary["overrides_applied"]["rejected"] == []


def test_a_confirmation_without_a_basis_is_still_published_when_a_person_signed_it() -> None:
    """A human answer is the evidence. Only an Agent has to say what closed the question."""
    glossary = _glossary(
        _order_document(),
        overrides=_value_override(meaning="已支付", confirmed_by="owner", date=DATE),
    )

    meaning = _value(glossary, "pay_status", "PAID")["meaning"]
    assert meaning["text"] == "已支付"
    assert "confirmed_basis" not in meaning
    assert "note" not in meaning
    assert glossary["overrides_applied"]["rejected"] == []


def test_an_agent_confirmation_without_a_basis_is_rejected_rather_than_published() -> None:
    glossary = _glossary(
        _order_document(),
        overrides=_value_override(
            meaning="已支付", confirmed_by="agent:glossary-review", date=DATE
        ),
    )

    assert _value(glossary, "pay_status", "PAID")["meaning"] is None
    assert glossary["overrides_applied"]["values"] == 0
    assert glossary["overrides_applied"]["rejected"] == [
        {"key": "ods.app_order.pay_status='PAID'", "reason": "missing_basis"}
    ]
    # `unmatched` keeps the bare-string shape it has always had: the key is not a typo.
    assert glossary["overrides_applied"]["unmatched"] == []


def test_a_rejected_agent_term_confirmation_is_reported_the_same_way() -> None:
    glossary = _glossary(
        _order_document(),
        overrides={"terms": {"pay_status": {"meaning": "支付状态", "confirmed_by": "agent:x"}}},
    )

    assert glossary["overrides_applied"]["terms"] == 0
    assert glossary["overrides_applied"]["rejected"] == [
        {"key": "pay_status", "reason": "missing_basis"}
    ]


def test_a_field_this_release_does_not_read_is_reported_not_dropped() -> None:
    glossary = _glossary(
        _order_document(),
        overrides=_value_override(meaning="已支付", confirmed_by="owner", bassis="typo"),
    )

    assert glossary["overrides_applied"]["ignored_fields"] == [
        {"key": "ods.app_order.pay_status='PAID'", "fields": ["bassis"]}
    ]
    # The confirmation itself still takes effect: one misspelled slot is not a veto.
    assert _value(glossary, "pay_status", "PAID")["meaning"]["text"] == "已支付"


def test_an_empty_overrides_file_still_reports_both_lists() -> None:
    glossary = _glossary(_order_document())

    assert glossary["overrides_applied"] == {
        "terms": 0,
        "values": 0,
        "blank": 0,
        "unmatched": [],
        "family_expansions": [],
        "ignored_fields": [],
        "rejected": [],
    }


# ------------------------------------------------------- 2. the CASE-label candidate


_STATUS_SCHEMA = SchemaMap(
    {"ods.ticket": ["id", "status", "grade"]},
    column_details={
        "ods.ticket": [
            {"name": "id", "type": "bigint", "comment": None},
            {"name": "status", "type": "string", "comment": None},
            {"name": "grade", "type": "string", "comment": None},
        ]
    },
)


def _case_glossary(label_sql: str) -> dict:
    return _glossary(
        _document(
            "INSERT INTO mart.t SELECT t.id, "
            f"{label_sql} AS state FROM ods.ticket t",
            schema=_STATUS_SCHEMA,
        )
    )


def test_a_case_that_maps_a_value_to_a_label_offers_the_label_as_a_candidate() -> None:
    glossary = _case_glossary(
        "CASE WHEN t.status = 'AA' THEN '有效' WHEN t.status = 'BB' THEN '失效' ELSE '未知' END"
    )

    assert _candidates(glossary, "status", "AA") == [
        {
            "text": "有效",
            "source": "case_label",
            "evidence": _value(glossary, "status", "AA")["observations"][0]["evidence"],
            # P5b: one value to this label, so the label IS this value's translation.
            "fan_out": 1,
        }
    ]
    assert [item["text"] for item in _candidates(glossary, "status", "BB")] == ["失效"]
    # A candidate is not an answer: the value still has no meaning.
    assert _value(glossary, "status", "AA")["meaning"] is None


def test_an_in_list_branch_labels_every_value_it_tests() -> None:
    """One column, one label: the CASE puts each of the values it lists in one bucket.

    P5b: the label reaches every value, as it always did, and now says how many values
    it reached -- 有效 is what this branch calls the pair, not what either code means.
    """
    glossary = _case_glossary(
        "CASE WHEN t.status IN ('AA', 'BB') THEN '有效' ELSE '未知' END"
    )
    bucket = "分类桶：有效（同桶 2 个值）"

    assert [item["text"] for item in _candidates(glossary, "status", "AA")] == [bucket]
    assert [item["text"] for item in _candidates(glossary, "status", "BB")] == [bucket]


def test_a_branch_that_returns_a_column_says_nothing_about_the_value() -> None:
    glossary = _case_glossary(
        "CASE WHEN t.status = 'AA' THEN t.grade WHEN t.status = 'BB' THEN '失效' ELSE '未知' END"
    )

    assert _candidates(glossary, "status", "AA") == []
    assert _labels(glossary) == ["失效"]


def test_a_branch_that_returns_an_expression_says_nothing_about_the_value() -> None:
    glossary = _case_glossary(
        "CASE WHEN t.status = 'AA' THEN CONCAT(t.grade, '级') "
        "WHEN t.status = 'BB' THEN '失效' ELSE '未知' END"
    )

    assert _candidates(glossary, "status", "AA") == []
    assert _labels(glossary) == ["失效"]


def test_a_branch_testing_two_columns_at_once_labels_neither_of_them() -> None:
    """`WHEN a = 'AA' AND b = 'GG' THEN '有效'` labels the pair, and a pair is not a value."""
    glossary = _case_glossary(
        "CASE WHEN t.status = 'AA' AND t.grade = 'GG' THEN '有效' "
        "WHEN t.status = 'BB' THEN '失效' ELSE '未知' END"
    )

    assert _labels(glossary) == ["失效"]


def test_a_branch_whose_label_is_code_shaped_is_not_read_as_a_meaning() -> None:
    """`THEN 'X'` re-codes the value; a one-character label defines nothing."""
    glossary = _case_glossary(
        "CASE WHEN t.status = 'AA' THEN 'X' WHEN t.status = 'BB' THEN 'Y' ELSE 'Z' END"
    )

    assert _labels(glossary) == []


def test_a_branch_that_relabels_a_value_as_itself_adds_nothing() -> None:
    glossary = _case_glossary(
        "CASE WHEN t.status = 'AA' THEN 'AA' WHEN t.status = 'BB' THEN '失效' ELSE '未知' END"
    )

    assert _candidates(glossary, "status", "AA") == []
    assert _labels(glossary) == ["失效"]


def test_a_case_label_reaches_the_rule_that_tests_the_value() -> None:
    """The describe side of the route: the code is written in the CASE's own condition."""
    document = _document(
        "INSERT INTO mart.t SELECT t.id, CASE WHEN t.status = 'AA' THEN '有效' "
        "ELSE '未知' END AS state FROM ods.ticket t",
        schema=_STATUS_SCHEMA,
    )
    profile = apply_glossary(build_semantic_profile(document), _glossary(document))
    rule = next(
        item for item in profile["rules"] if "CASE" in str(item.get("expression"))
    )

    assert rule["value_meanings"][0]["meaning"] == {"text": "有效", "status": "candidate"}


def test_a_comment_candidate_and_a_case_label_are_both_offered() -> None:
    schema = SchemaMap(
        {"ods.ticket": ["id", "status"]},
        column_details={
            "ods.ticket": [
                {"name": "id", "type": "bigint", "comment": None},
                {"name": "status", "type": "string", "comment": "AA-生效，BB-失效"},
            ]
        },
    )
    glossary = _glossary(
        _document(
            "INSERT INTO mart.t SELECT t.id, "
            "CASE WHEN t.status = 'AA' THEN '有效' ELSE '未知' END AS state FROM ods.ticket t",
            schema=schema,
        )
    )

    assert [
        (item["source"], item["text"]) for item in _candidates(glossary, "status", "AA")
    ] == [("comment_enum", "生效"), ("case_label", "有效")]


# ------------------------------------------------------------- 3. the form's evidence


_EVIDENCE_COLUMNS = ["id", "channel", "queue"]

_EVIDENCE_SCHEMA = SchemaMap(
    {"ods.event": _EVIDENCE_COLUMNS},
    column_details={
        "ods.event": [
            {"name": "id", "type": "bigint", "comment": None},
            {"name": "channel", "type": "string", "comment": "AA-线上，BB-线下"},
            {"name": "queue", "type": "string", "comment": None},
        ]
    },
)

# `queue` has three values to `channel`'s two, so the old ranking puts it first; only
# `channel` carries evidence anybody could confirm from.
_EVIDENCE_SQL = (
    "INSERT INTO mart.t SELECT e.id FROM ods.event e "
    "WHERE e.channel IN ('AA', 'BB') AND e.queue IN ('Q1', 'Q2', 'Q3')"
)


def _evidence_glossary() -> dict:
    return _glossary(_document(_EVIDENCE_SQL, schema=_EVIDENCE_SCHEMA))


def test_the_form_asks_the_columns_that_carry_evidence_first() -> None:
    entries = template_entries(_evidence_glossary())

    assert [item["column"] for item in entries][:2] == ["channel", "channel"]
    assert {item["column"] for item in entries} == {"channel", "queue"}


def test_the_form_names_the_evidence_each_value_has() -> None:
    glossary = _evidence_glossary()
    rendered = render_overrides_template_markdown(
        build_overrides_template(glossary, top=0), glossary
    )

    assert "| 注释线索 | 候选来源 |" in rendered
    assert "| 线上 | comment_enum |" in rendered
    assert "| — | — |" in rendered


def test_the_form_marks_a_case_label_as_the_evidence_it_is() -> None:
    glossary = _glossary(
        _document(
            "INSERT INTO mart.t SELECT t.id, CASE WHEN t.status = 'AA' THEN '有效' "
            "WHEN t.status = 'BB' THEN '失效' ELSE '未知' END AS state FROM ods.ticket t",
            schema=_STATUS_SCHEMA,
        )
    )
    rendered = render_overrides_template_markdown(
        build_overrides_template(glossary, top=0), glossary
    )

    assert "| 有效 | case_label |" in rendered


def test_a_value_a_human_confirmed_on_a_same_named_column_is_evidence_elsewhere() -> None:
    glossary = _glossary(
        _order_document(),
        _order_document("ods.web_order", "web_orders"),
        overrides=_value_override(meaning="已支付", confirmed_by="owner", date=DATE),
    )
    rendered = render_overrides_template_markdown(
        build_overrides_template(glossary, top=0), glossary
    )

    assert "| — | same_name_confirmed |" in rendered
    # The confirmed value itself is not asked again, so it never reaches the form.
    assert "ods.app_order.pay_status=PAID" not in rendered


def test_an_agent_confirmation_is_not_evidence_for_the_same_name_elsewhere() -> None:
    """Otherwise one Agent answer spreads itself across the corpus unreviewed."""
    glossary = _glossary(
        _order_document(),
        _order_document("ods.web_order", "web_orders"),
        overrides=_value_override(
            meaning="已支付", basis="列注释枚举了该取值", confirmed_by="agent:x", date=DATE
        ),
    )
    rendered = render_overrides_template_markdown(
        build_overrides_template(glossary, top=0), glossary
    )

    assert "same_name_confirmed" not in rendered


# ------------------------------------------------------------------- 4. glossary.md


def test_the_dictionary_shows_what_a_confirmed_meaning_was_confirmed_on() -> None:
    glossary = _glossary(
        _order_document(),
        overrides=_value_override(
            meaning="已支付",
            basis="列注释枚举了该取值",
            confirmed_by="agent:glossary-review",
            date=DATE,
        ),
    )

    assert "（依据：列注释枚举了该取值）" in render_glossary_markdown(glossary)


def test_a_rejected_confirmation_is_visible_in_the_dictionary() -> None:
    glossary = _glossary(
        _order_document(),
        overrides=_value_override(meaning="已支付", confirmed_by="agent:x"),
    )

    assert "missing_basis" in render_glossary_markdown(glossary)
