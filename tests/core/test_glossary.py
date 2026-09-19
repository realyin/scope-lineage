"""Behavioural tests for the corpus-level term / value dictionary (glossary-json/1).

WI-2.4. The dictionary is the layer that lets a reader ask "what does ``'PAID'`` mean"
without the Core ever guessing: it collects, per column, the comments the warehouse
carries and the constants the corpus's SQL actually compares that column against, and
it attaches a *meaning* only when a human wrote one into an overrides file or when a
comment literally spells the value out.

The load-bearing properties here are the two honesty ones at the bottom: every
``column_ref`` the glossary publishes must exist in one of the source documents, and a
meaning candidate must be a substring match against a real comment -- never an
inference from the value's own spelling.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.metadata.schema_metadata import SchemaMap
from scope_lineage.render.glossary import (
    DOC_FORMAT,
    build_glossary,
    render_glossary_markdown,
)
from scope_lineage.scope.scope_builder import parse_scope_lineage


FIXTURES = Path(__file__).parent / "fixtures"
CORPUS_FIXTURE = FIXTURES / "lineage_contract"
GLOSSARY_FIXTURE = FIXTURES / "glossary"
# The recorded corpus root, written into `corpus.artifact_root`. A repo-relative string
# rather than an absolute path, so the golden bytes do not depend on the checkout.
GOLDEN_ROOT = "tests/core/fixtures/lineage_contract"


def _document(sql: str, task_id: str = "glossary_case", schema=None) -> dict:
    return to_lineage_dict(parse_scope_lineage(sql, task_id, schema=schema))


def _glossary(*documents, overrides=None, artifact_root="corpus") -> dict:
    return build_glossary(
        list(documents), artifact_root=artifact_root, overrides=overrides
    )


def _values(glossary: dict, column: str) -> list[dict]:
    return [item for item in glossary["values"] if item["column"] == column]


def _value(glossary: dict, column: str, value: str) -> dict:
    """Looked up by the SQL literal the case writes; ``value`` is stored unquoted (D4)."""
    matches = [
        item for item in _values(glossary, column) if item["sql_literal"] == value
    ]
    assert matches, f"{column}={value} not in {[item['value'] for item in _values(glossary, column)]}"
    return matches[0]


def _term(glossary: dict, column: str) -> dict:
    matches = [item for item in glossary["terms"] if item["column"] == column]
    assert matches, f"no term for {column}"
    return matches[0]


# ------------------------------------------------------------------ value collection


def test_an_equality_filter_publishes_its_literal_against_the_physical_column() -> None:
    document = _document(
        "INSERT INTO mart.t SELECT o.order_id FROM ods.app_order o "
        "WHERE o.pay_status = 'PAID'"
    )
    entry = _value(_glossary(document), "pay_status", "'PAID'")

    assert entry["column_ref"] == "ods.app_order.pay_status"
    assert "logical" not in entry
    assert entry["kind"] == "literal"
    assert entry["task_count"] == 1
    assert [item["context"] for item in entry["observations"]] == ["filter_eq"]
    assert entry["observations"][0]["evidence"].startswith("rule:")


def test_an_in_list_closes_the_value_set() -> None:
    document = _document(
        "INSERT INTO mart.t SELECT o.order_id FROM ods.app_order o "
        "WHERE o.region IN ('CN', 'US')"
    )
    glossary = _glossary(document)

    assert [item["value"] for item in _values(glossary, "region")] == ["CN", "US"]
    entry = _value(glossary, "region", "'CN'")
    assert entry["observations"][0]["context"] == "filter_in"
    assert entry["closed_set"] == {"values": ["CN", "US"], "basis": "in_list"}


def test_a_not_equal_filter_is_an_observation_but_closes_nothing() -> None:
    document = _document(
        "INSERT INTO mart.t SELECT o.order_id FROM ods.app_order o "
        "WHERE o.pay_status <> 'REFUND'"
    )
    entry = _value(_glossary(document), "pay_status", "'REFUND'")

    assert entry["observations"][0]["context"] == "filter_neq"
    assert entry["closed_set"] is None


def test_a_regex_filter_keeps_the_pattern_whole() -> None:
    """The alternation is one pattern, not three values: splitting it would invent two."""
    document = _document(
        "INSERT INTO mart.t SELECT o.order_id FROM ods.app_order o "
        "WHERE o.state RLIKE 'ACTIVE|NEW'"
    )
    entry = _value(_glossary(document), "state", "'ACTIVE|NEW'")

    assert entry["observations"][0]["context"] == "filter_rlike"
    assert entry["kind"] == "pattern"
    assert entry["closed_set"] is None


def test_a_like_pattern_is_a_pattern_and_not_an_enumerated_value() -> None:
    """WI-2.4b: ``LIKE '%UNIT_OUT_%'`` names a shape, not a value the column ever holds."""
    document = _document(
        "INSERT INTO mart.t SELECT o.order_id FROM ods.app_order o "
        "WHERE o.state LIKE '%UNIT_OUT_%'"
    )
    glossary = _glossary(document)
    entry = _value(glossary, "state", "'%UNIT_OUT_%'")

    assert entry["kind"] == "pattern"
    assert entry["closed_set"] is None
    # It stays in `values[]` -- it IS an observation about the column -- and it is not a
    # substitution, so it never reaches `parameters[]`.
    assert glossary["parameters"] == []


def test_a_pattern_in_a_join_condition_is_still_a_pattern() -> None:
    """A forced context must not overwrite what the right-hand side actually is."""
    document = _document(
        "INSERT INTO mart.t SELECT a.order_id FROM ods.app_order a "
        "LEFT JOIN dim.segment_dim d ON a.segment = d.segment AND d.name LIKE 'VIP%'"
    )
    entry = _value(_glossary(document), "name", "'VIP%'")

    assert entry["kind"] == "pattern"
    assert entry["observations"][0]["context"] == "join_condition"


def test_an_equality_against_a_percent_string_is_still_a_literal() -> None:
    """Only the matching operators make a pattern; ``=`` compares against a value."""
    document = _document(
        "INSERT INTO mart.t SELECT o.order_id FROM ods.app_order o "
        "WHERE o.state = '%UNIT_OUT_%'"
    )
    assert _value(_glossary(document), "state", "'%UNIT_OUT_%'")["kind"] == "literal"


def test_a_parameterized_pattern_stays_a_parameter() -> None:
    """``LIKE '${p}%'`` is a substitution first; the engine, not the SQL, picks the shape."""
    document = _document(
        "INSERT INTO mart.t SELECT o.order_id FROM ods.app_order o "
        "WHERE o.state LIKE '${prefix}%'"
    )
    glossary = _glossary(document)

    assert _values(glossary, "state") == []
    assert [item["kind"] for item in glossary["parameters"]] == ["parameterized"]


def test_a_pattern_does_not_take_part_in_a_closed_set() -> None:
    """An IN list closes the enum; a LIKE beside it neither joins nor breaks the claim."""
    document = _document(
        "INSERT INTO mart.t SELECT o.order_id FROM ods.app_order o "
        "WHERE o.state IN ('CN', 'US') AND o.state LIKE 'C%'"
    )
    glossary = _glossary(document)

    assert _value(glossary, "state", "'CN'")["closed_set"] == {
        "values": ["CN", "US"],
        "basis": "in_list",
    }
    assert _value(glossary, "state", "'C%'")["closed_set"] is None


def test_a_parameterized_filter_never_reaches_the_value_list() -> None:
    document = _document(
        "INSERT INTO mart.t SELECT o.order_id FROM ods.app_order o "
        "WHERE o.dt = '${bizdate}'"
    )
    glossary = _glossary(document)

    assert _values(glossary, "dt") == []
    assert glossary["parameters"] == [
        {
            "column_ref": "ods.app_order.dt",
            "expression": "dt = '${bizdate}'",
            "kind": "parameterized",
            "task_count": 1,
        }
    ]


def test_a_function_valued_filter_is_a_parameter_not_a_value() -> None:
    document = _document(
        "INSERT INTO mart.t SELECT o.order_id FROM ods.app_order o "
        "WHERE o.dt = date_sub(current_date(), 1)"
    )
    glossary = _glossary(document)

    assert _values(glossary, "dt") == []
    assert [item["kind"] for item in glossary["parameters"]] == ["function"]


def test_a_column_to_column_predicate_is_not_a_value_at_all() -> None:
    document = _document(
        "INSERT INTO mart.t SELECT o.order_id FROM ods.app_order o "
        "WHERE o.created_at = o.updated_at"
    )
    glossary = _glossary(document)

    assert glossary["values"] == []
    assert glossary["parameters"] == []


def test_case_conditions_and_labels_are_collected_under_their_own_columns() -> None:
    document = _document(
        "INSERT INTO mart.t SELECT o.order_id, "
        "CASE WHEN o.pay_status = 'PAID' THEN 'Y' ELSE 'N' END AS paid_flag "
        "FROM ods.app_order o"
    )
    glossary = _glossary(document)

    condition = _value(glossary, "pay_status", "'PAID'")
    assert condition["column_ref"] == "ods.app_order.pay_status"
    assert condition["observations"][0]["context"] == "case_condition"

    label = _value(glossary, "paid_flag", "'Y'")
    assert label["observations"][0]["context"] == "case_then"
    assert label["closed_set"] == {
        "values": ["Y", "N"],
        "basis": "case_exhaustive",
    }


def test_a_case_whose_else_returns_a_column_closes_nothing() -> None:
    document = _document(
        "INSERT INTO mart.t SELECT o.order_id, "
        "CASE WHEN o.pay_status = 'PAID' THEN 'Y' ELSE o.pay_status END AS paid_flag "
        "FROM ods.app_order o"
    )
    glossary = _glossary(document)

    assert _value(glossary, "paid_flag", "'Y'")["closed_set"] is None


def test_a_case_without_else_closes_nothing() -> None:
    document = _document(
        "INSERT INTO mart.t SELECT o.order_id, "
        "CASE WHEN o.pay_status = 'PAID' THEN 'Y' END AS paid_flag "
        "FROM ods.app_order o"
    )
    glossary = _glossary(document)

    assert _value(glossary, "paid_flag", "'Y'")["closed_set"] is None


def test_a_union_branch_constant_is_recorded_against_the_target_column() -> None:
    document = _document(
        "INSERT INTO mart.t SELECT o.order_id, 'APP' AS channel FROM ods.app_order o "
        "UNION ALL SELECT w.order_id, 'WEB' AS channel FROM ods.web_order w"
    )
    glossary = _glossary(document)

    entry = _value(glossary, "channel", "'APP'")
    assert entry["column_ref"] == "mart.t.channel"
    assert entry["observations"][0]["context"] == "union_constant"
    assert [item["value"] for item in _values(glossary, "channel")] == ["APP", "WEB"]


def test_a_plain_constant_projection_is_recorded_as_such() -> None:
    document = _document("INSERT INTO mart.t SELECT o.order_id, 'APP' AS channel FROM ods.app_order o")
    entry = _value(_glossary(document), "channel", "'APP'")

    assert entry["observations"][0]["context"] == "constant_projection"


def test_a_joins_extra_condition_constant_is_recorded_on_the_scope_column() -> None:
    document = _document(
        "INSERT INTO mart.t WITH d AS ("
        " SELECT segment, ROW_NUMBER() OVER (PARTITION BY segment ORDER BY updated_at DESC) AS rn"
        " FROM dim.segment_dim)"
        " SELECT a.segment FROM ods.app_order a LEFT JOIN d ON a.segment = d.segment AND d.rn = 1"
    )
    entry = _value(_glossary(document), "rn", "1")

    assert entry["logical"] is True
    assert entry["column_ref"] == "cte:d.rn"
    assert entry["observations"][0]["context"] == "join_condition"


# -------------------------------------------------------------------- normalisation


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


def test_the_same_table_under_two_catalog_prefixes_is_one_table() -> None:
    short = _document(
        "INSERT INTO mart.t SELECT o.order_id, o.pay_status FROM ods.app_order o "
        "WHERE o.pay_status = 'PAID'",
        "task_short",
        schema=_order_schema("ods.app_order", "Payment status"),
    )
    long = _document(
        "INSERT INTO mart.t SELECT o.order_id, o.pay_status FROM hive.ods.app_order o "
        "WHERE o.pay_status = 'PAID'",
        "task_long",
        schema=_order_schema("hive.ods.app_order", "Payment status"),
    )
    glossary = _glossary(short, long)

    entry = _value(glossary, "pay_status", "'PAID'")
    assert entry["column_ref"] == "hive.ods.app_order.pay_status"  # longest spelling wins
    assert entry["task_count"] == 2
    # One source table under two spellings, plus the target both tasks write.
    assert _term(glossary, "pay_status")["tables_total"] == 2


# --------------------------------------------------------------------------- terms


def test_terms_merge_identical_comments_and_flag_conflicting_ones() -> None:
    same = _document(
        "INSERT INTO mart.t SELECT o.order_id, o.pay_status FROM ods.app_order o",
        "task_a",
        schema=_order_schema("ods.app_order", "Payment status"),
    )
    other = _document(
        "INSERT INTO mart.u SELECT w.order_id, w.pay_status FROM ods.web_order w",
        "task_b",
        schema=_order_schema("ods.web_order", "Payment status"),
    )
    different = _document(
        "INSERT INTO mart.v SELECT p.order_id, p.pay_status FROM ods.pos_order p",
        "task_c",
        schema=_order_schema("ods.pos_order", "Settlement state"),
    )
    term = _term(_glossary(same, other, different), "pay_status")

    merged = next(item for item in term["comments"] if item["text"] == "Payment status")
    assert merged["count"] == 2
    assert merged["tables"] == ["ods.app_order", "ods.web_order"]
    assert term["conflict"] is True
    # Three source tables plus the three targets they write: an output table's column
    # comment is a comment on this name too, and a missing one is a real gap.
    assert term["tables_total"] == 6


def test_a_column_nobody_commented_is_still_a_term_with_its_tables_listed() -> None:
    document = _document(
        "INSERT INTO mart.t SELECT o.order_id, o.pay_status FROM ods.app_order o",
        schema=_order_schema("ods.app_order", None),
    )
    term = _term(_glossary(document), "pay_status")

    assert term["comments"] == []
    assert term["conflict"] is False
    assert term["tables_without_comment"] == ["mart.t", "ods.app_order"]
    assert term["meaning"] is None


# --------------------------------------------------------------- meaning candidates


def _commented_schema(comment: str, table_comment: str | None = None) -> SchemaMap:
    return SchemaMap(
        {"ods.app_order": ["order_id", "pay_status"]},
        column_details={
            "ods.app_order": [
                {"name": "order_id", "type": "bigint", "comment": None},
                {"name": "pay_status", "type": "string", "comment": comment},
            ]
        },
        table_details=(
            {"ods.app_order": {"comment": table_comment}} if table_comment else None
        ),
    )


def test_a_column_comment_that_spells_the_value_out_becomes_a_candidate() -> None:
    document = _document(
        "INSERT INTO mart.t SELECT o.order_id FROM ods.app_order o WHERE o.pay_status = 'PAID'",
        schema=_commented_schema("payment state, PAID means settled"),
    )
    entry = _value(_glossary(document), "pay_status", "'PAID'")

    assert entry["meaning_candidates"] == [
        {
            "text": "payment state, PAID means settled",
            "source": "column_comment",
            "evidence": "column:ods.app_order.pay_status",
        }
    ]
    assert entry["meaning"] is None  # a candidate is not a confirmed meaning


def test_a_comment_that_does_not_contain_the_value_is_not_a_candidate() -> None:
    document = _document(
        "INSERT INTO mart.t SELECT o.order_id FROM ods.app_order o WHERE o.pay_status = 'PAID'",
        schema=_commented_schema("payment state"),
    )
    assert _value(_glossary(document), "pay_status", "'PAID'")["meaning_candidates"] == []


def test_a_sql_comment_on_the_condition_is_a_candidate() -> None:
    document = _document(
        "INSERT INTO mart.t SELECT o.order_id FROM ods.app_order o\n"
        "WHERE o.pay_status = 'PAID' -- PAID is the settled state\n"
    )
    entry = _value(_glossary(document), "pay_status", "'PAID'")

    assert [item["source"] for item in entry["meaning_candidates"]] == ["sql_comment"]
    assert entry["meaning_candidates"][0]["text"] == "PAID is the settled state"


def test_a_one_character_value_never_matches_a_comment() -> None:
    """``0`` occurs inside almost any sentence; one accidental hit poisons the layer."""
    document = _document(
        "INSERT INTO mart.t SELECT o.order_id FROM ods.app_order o WHERE o.pay_status = '0'",
        schema=_commented_schema("state code, 0 means new"),
    )
    assert _value(_glossary(document), "pay_status", "'0'")["meaning_candidates"] == []


# ----------------------------------------------------------------------- overrides


def _override_document() -> dict:
    return _document(
        "INSERT INTO mart.t SELECT o.order_id FROM ods.app_order o WHERE o.pay_status = 'PAID'",
        schema=_order_schema("ods.app_order", "Payment status"),
    )


def test_a_qualified_override_key_confirms_one_value() -> None:
    overrides = {
        "values": {
            "ods.app_order.pay_status='PAID'": {
                "meaning": "已支付",
                "confirmed_by": "owner",
                "date": "2026-09-18",
            }
        }
    }
    glossary = _glossary(_override_document(), overrides=overrides)

    assert _value(glossary, "pay_status", "'PAID'")["meaning"] == {
        "text": "已支付",
        "source": "override",
        "confirmed_by": "owner",
        "date": "2026-09-18",
    }
    assert glossary["overrides_applied"] == {
        "terms": 0,
        "values": 1,
        "blank": 0,
        "unmatched": [],
    }


def test_a_key_left_blank_is_counted_rather_than_confirmed_as_empty() -> None:
    """WI-2.9 item C: `glossary --template` ships every entry blank, and a half-filled
    form comes back with the rest unanswered. "Nobody has said" must not become
    "somebody said nothing"."""
    overrides = {
        "terms": {"pay_status": {"meaning": ""}},
        "values": {"ods.app_order.pay_status='PAID'": {"meaning": ""}},
    }
    glossary = _glossary(_override_document(), overrides=overrides)

    assert _value(glossary, "pay_status", "'PAID'")["meaning"] is None
    assert glossary["overrides_applied"] == {
        "terms": 0,
        "values": 0,
        "blank": 2,
        "unmatched": [],
    }


def test_a_bare_column_override_key_confirms_every_same_named_column() -> None:
    other = _document(
        "INSERT INTO mart.u SELECT w.order_id FROM ods.web_order w WHERE w.pay_status = 'PAID'",
        "task_b",
        schema=_order_schema("ods.web_order", "Payment status"),
    )
    overrides = {"values": {"pay_status='PAID'": {"meaning": "已支付"}}}
    glossary = _glossary(_override_document(), other, overrides=overrides)

    entries = _values(glossary, "pay_status")
    assert len(entries) == 2
    assert all(item["meaning"]["text"] == "已支付" for item in entries)
    assert all(item["meaning"]["confirmed_by"] is None for item in entries)
    assert glossary["overrides_applied"]["values"] == 2


def test_a_term_override_confirms_the_column_meaning() -> None:
    overrides = {
        "terms": {"pay_status": {"meaning": "支付状态", "confirmed_by": "owner", "date": "2026-09-18"}}
    }
    glossary = _glossary(_override_document(), overrides=overrides)

    assert _term(glossary, "pay_status")["meaning"] == {
        "text": "支付状态",
        "source": "override",
        "confirmed_by": "owner",
        "date": "2026-09-18",
    }
    assert glossary["overrides_applied"]["terms"] == 1


def test_an_override_key_that_matches_nothing_is_reported_not_swallowed() -> None:
    overrides = {
        "terms": {"nonexistent_column": {"meaning": "x"}},
        "values": {"ods.app_order.pay_status='GONE'": {"meaning": "y"}},
    }
    glossary = _glossary(_override_document(), overrides=overrides)

    assert glossary["overrides_applied"]["unmatched"] == [
        "nonexistent_column",
        "ods.app_order.pay_status='GONE'",
    ]


# ------------------------------------------------------------- honesty properties


def _corpus_documents() -> list[dict]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(CORPUS_FIXTURE.glob("*/lineage.json"))
    ]


def _statement_documents(document: dict) -> list[dict]:
    if document.get("schema_version") == "2.0":
        return list((document.get("statement_lineage") or {}).values())
    return [document]


def _known_refs(documents: list[dict]) -> tuple[set, set]:
    """``(tables, scopes)`` every source document names, catalog prefixes included."""
    tables: set = set()
    scopes: set = set()
    for document in documents:
        for statement in _statement_documents(document):
            tables.update(statement.get("source_tables") or [])
            if statement.get("target_table"):
                tables.add(str(statement["target_table"]))
            scopes.update(statement.get("scopes") or {})
    return tables, scopes


def test_every_published_column_ref_exists_in_a_source_document() -> None:
    documents = _corpus_documents()
    glossary = build_glossary(documents, artifact_root=GOLDEN_ROOT)
    tables, scopes = _known_refs(documents)

    for entry in glossary["values"] + glossary["parameters"]:
        owner = str(entry["column_ref"]).rsplit(".", 1)[0]
        assert owner in tables or owner in scopes, f"invented owner {owner!r}"


def test_every_meaning_candidate_is_a_literal_substring_of_a_real_comment() -> None:
    documents = _corpus_documents()
    glossary = build_glossary(documents, artifact_root=GOLDEN_ROOT)

    for entry in glossary["values"]:
        for candidate in entry["meaning_candidates"]:
            value = entry["value"].strip().strip("'\"")
            assert value.lower() in candidate["text"].lower()


def test_the_glossary_is_byte_identical_for_the_same_corpus() -> None:
    documents = _corpus_documents()
    first = build_glossary(documents, artifact_root=GOLDEN_ROOT)
    second = build_glossary(list(reversed(documents)), artifact_root=GOLDEN_ROOT)

    assert json.dumps(first, ensure_ascii=False, sort_keys=False) == json.dumps(
        second, ensure_ascii=False, sort_keys=False
    )
    assert render_glossary_markdown(first) == render_glossary_markdown(second)


def test_the_corpus_block_counts_what_it_read() -> None:
    documents = _corpus_documents()
    glossary = build_glossary(documents, artifact_root=GOLDEN_ROOT)

    assert glossary["doc_format"] == DOC_FORMAT == "glossary-json/1"
    assert glossary["corpus"]["artifact_root"] == GOLDEN_ROOT
    assert glossary["corpus"]["task_count"] == len(documents)
    assert glossary["corpus"]["statement_count"] == sum(
        len(_statement_documents(document)) for document in documents
    )
    assert set(glossary["corpus"]["lineage_digests"]) == {
        str(document.get("task_id")) for document in documents
    }


# -------------------------------------------------------------------- golden bytes


def _record_golden() -> tuple[str, str]:
    """The recording path and the asserted path, deliberately one function."""
    documents = _corpus_documents()
    glossary = build_glossary(documents, artifact_root=GOLDEN_ROOT)
    return (
        json.dumps(glossary, ensure_ascii=False, indent=2) + "\n",
        render_glossary_markdown(glossary),
    )


def test_glossary_artifacts_match_golden_bytes() -> None:
    first_json, first_md = _record_golden()
    second_json, second_md = _record_golden()

    assert first_json == (GLOSSARY_FIXTURE / "glossary.json").read_text(encoding="utf-8")
    assert first_md == (GLOSSARY_FIXTURE / "glossary.md").read_text(encoding="utf-8")
    assert second_json == first_json
    assert second_md == first_md


def test_the_markdown_gives_every_documented_column_a_section() -> None:
    glossary = build_glossary(_corpus_documents(), artifact_root=GOLDEN_ROOT)
    rendered = render_glossary_markdown(glossary)

    for entry in glossary["values"]:
        assert f"## {entry['column']}" in rendered


@pytest.mark.parametrize("payload", [{}, {"terms": {}, "values": {}}])
def test_an_empty_overrides_file_changes_nothing(payload) -> None:
    document = _override_document()
    assert build_glossary([document], artifact_root="corpus", overrides=payload) == (
        build_glossary([document], artifact_root="corpus")
    )
