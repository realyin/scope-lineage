"""``describe`` consuming the value dictionary: ``fields[].value_domain`` (WI-2.4).

Two levels, and the difference between them is the whole point of the corpus layer:

- without a glossary, a field's value domain is what THIS statement proves -- the
  constants its own filters and CASE branches compare the column against, every
  ``meaning`` null because one statement cannot know one;
- with ``--glossary``, the same field carries what the corpus observed (including values
  another task pinned the column to) and the meanings a human confirmed in the overrides.

The honesty property pinned at the bottom: a ``candidate`` meaning never reaches the
one-sentence ``summary``. That sentence is where a reader stops, and a comment that
happens to contain the value is not a definition.
"""

from __future__ import annotations

import json
from pathlib import Path

from scope_lineage.cli import main
from scope_lineage.contract import to_lineage_dict
from scope_lineage.metadata.schema_metadata import SchemaMap
from scope_lineage.render.glossary import apply_glossary, build_glossary
from scope_lineage.render.glossary_values import apply_value_domains
from scope_lineage.render.semantic_markdown import render_semantic_markdown
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.scope.scope_builder import parse_scope_lineage

from .statement_document import write_statement_documents


APP_SQL = (
    "INSERT INTO mart.orders SELECT o.order_id, o.pay_status FROM ods.app_order o "
    "WHERE o.pay_status = 'PAID'"
)
WEB_SQL = (
    "INSERT INTO mart.web_orders SELECT w.order_id, w.pay_status FROM ods.web_order w "
    "WHERE w.pay_status = 'REFUND'"
)


def _schema(table: str, comment: str | None = None) -> SchemaMap:
    return SchemaMap(
        {table: ["order_id", "pay_status"]},
        column_details={
            table: [
                {"name": "order_id", "type": "bigint", "comment": None},
                {"name": "pay_status", "type": "string", "comment": comment},
            ]
        },
    )


def _document(sql: str, task_id: str, comment: str | None = None) -> dict:
    table = "ods.app_order" if "app_order" in sql else "ods.web_order"
    return to_lineage_dict(
        parse_scope_lineage(sql, task_id, schema=_schema(table, comment))
    )


def _field(profile: dict, column: str) -> dict:
    return next(item for item in profile["fields"] if item["column"] == column)


# ------------------------------------------------------ the statement's own domain


def test_a_field_carries_its_own_statements_values_without_any_glossary() -> None:
    profile = build_semantic_profile(_document(APP_SQL, "task_a"))
    field = _field(profile, "pay_status")

    assert field["value_domain"] == [
        {
            # WI-2.8 D4: one spelling for the value, the author's literal beside it.
            "value": "PAID",
            "sql_literal": "'PAID'",
            "kind": "literal",
            "seen_in": ["rule:001"],
            "closed_set": None,
            "meaning": None,
        }
    ]
    assert profile["confidence"]["metadata_coverage"]["glossary"] == {
        "values_total": 1,
        "confirmed": 0,
        "candidate": 0,
        # WI-2.12: the rule half is zero because nothing in the dictionary answers the
        # `'PAID'` this WHERE pins -- there is no dictionary at all here.
        "rule_values_total": 0,
        "rule_values_confirmed": 0,
        "field_values_total": 1,
        "field_values_confirmed": 0,
        # WI-9 legacy b: `'PAID'` is a quoted code pinned by a `=`, so it is one of the
        # values somebody can be asked to name -- and nobody has.
        "enumerable_total": 1,
        "enumerable_confirmed": 0,
    }


def test_a_field_nothing_is_compared_against_has_no_value_domain_key() -> None:
    profile = build_semantic_profile(_document(APP_SQL, "task_a"))
    assert "value_domain" not in _field(profile, "order_id")


def test_the_value_domain_key_sits_between_the_metric_card_and_the_sources() -> None:
    """Key order is part of ``semantic-json/1``; a reader diffs these files."""
    field = _field(build_semantic_profile(_document(APP_SQL, "task_a")), "pay_status")
    keys = list(field)
    assert keys.index("value_domain") < keys.index("sources")
    assert keys.index("summary") < keys.index("value_domain")


# ------------------------------------------------------------- the corpus glossary


def _corpus_glossary(overrides=None) -> dict:
    return build_glossary(
        [_document(APP_SQL, "task_a"), _document(WEB_SQL, "task_b")],
        artifact_root="corpus",
        overrides=overrides,
    )


def test_a_glossary_widens_the_domain_to_what_other_tasks_observed() -> None:
    """``ods.web_order.pay_status`` is a different column, so it must NOT leak in."""
    profile = apply_glossary(
        build_semantic_profile(_document(APP_SQL, "task_a")), _corpus_glossary()
    )
    assert [item["value"] for item in _field(profile, "pay_status")["value_domain"]] == [
        "PAID"
    ]


def test_a_confirmed_override_reaches_the_field_and_its_summary() -> None:
    overrides = {
        "values": {
            "pay_status='PAID'": {
                "meaning": "已支付",
                "confirmed_by": "owner",
                "date": "2026-09-18",
            }
        }
    }
    profile = apply_glossary(
        build_semantic_profile(_document(APP_SQL, "task_a")), _corpus_glossary(overrides)
    )
    field = _field(profile, "pay_status")

    assert field["value_domain"][0]["meaning"] == {"text": "已支付", "status": "confirmed"}
    assert field["summary"].endswith("；取值：'PAID'（已支付）")
    assert profile["confidence"]["metadata_coverage"]["glossary"] == {
        # WI-2.12: one code, counted once. `pay_status` is pinned to `'PAID'` by the
        # WHERE and carries it into the output column of the same name -- that is one
        # business question, not two, so the union总数 stays 1 while both halves say 1.
        "values_total": 1,
        "confirmed": 1,
        "candidate": 0,
        "rule_values_total": 1,
        "rule_values_confirmed": 1,
        "field_values_total": 1,
        "field_values_confirmed": 1,
        "enumerable_total": 1,
        "enumerable_confirmed": 1,
    }


def test_a_candidate_meaning_is_published_but_kept_out_of_the_summary() -> None:
    document = _document(APP_SQL, "task_a", comment="payment state; PAID means settled")
    glossary = build_glossary([document], artifact_root="corpus")
    profile = apply_glossary(build_semantic_profile(document), glossary)
    field = _field(profile, "pay_status")

    assert field["value_domain"][0]["meaning"]["status"] == "candidate"
    assert "取值：" not in field["summary"]
    assert profile["confidence"]["metadata_coverage"]["glossary"]["candidate"] == 1


def test_applying_no_glossary_leaves_the_profile_untouched() -> None:
    document = _document(APP_SQL, "task_a")
    plain = build_semantic_profile(document)
    assert apply_glossary(build_semantic_profile(document), None) == plain


def test_applying_a_glossary_twice_does_not_double_the_summary_suffix() -> None:
    overrides = {"values": {"pay_status='PAID'": {"meaning": "已支付"}}}
    glossary = _corpus_glossary(overrides)
    once = apply_glossary(build_semantic_profile(_document(APP_SQL, "task_a")), glossary)
    twice = apply_glossary(apply_glossary(once, glossary), glossary)

    assert twice == once
    assert _field(twice, "pay_status")["summary"].count("取值：") == 1


# ---------------------------------------------------------------------- markdown


def test_the_field_section_renders_a_value_line() -> None:
    overrides = {"values": {"pay_status='PAID'": {"meaning": "已支付"}}}
    profile = apply_glossary(
        build_semantic_profile(_document(APP_SQL, "task_a")), _corpus_glossary(overrides)
    )
    rendered = render_semantic_markdown(profile, sections=["fields"])

    assert "- 取值：'PAID'（已支付）（SQL事实；证据 rule:001）" in rendered


def test_an_unconfirmed_value_renders_as_pending() -> None:
    profile = build_semantic_profile(_document(APP_SQL, "task_a"))
    rendered = render_semantic_markdown(profile, sections=["fields"])

    assert "- 取值：'PAID'（待确认）" in rendered


def test_a_closed_enum_says_so_on_the_line() -> None:
    sql = (
        "INSERT INTO mart.t SELECT o.order_id, "
        "CASE WHEN o.pay_status = 'PAID' THEN 'Y' ELSE 'N' END AS paid_flag "
        "FROM ods.app_order o"
    )
    document = to_lineage_dict(parse_scope_lineage(sql, "task_case"))
    rendered = render_semantic_markdown(
        build_semantic_profile(document), sections=["fields"]
    )

    assert "该列取值已被 SQL 证明封闭" in rendered


# ------------------------------------------------- WI-2.4b: one value, listed once

BRANCHED_SQL = (
    "INSERT INTO mart.t SELECT u.order_id, u.grp FROM ("
    " SELECT o.order_id, CASE WHEN o.pay_status IS NOT NULL THEN 'SA' ELSE 'SB' END AS grp"
    " FROM ods.app_order o"
    " UNION ALL"
    " SELECT w.order_id, CASE WHEN w.pay_status IS NOT NULL THEN 'SA' ELSE 'SC' END AS grp"
    " FROM ods.web_order w) u"
)


def _branched_domain() -> list[dict]:
    document = to_lineage_dict(parse_scope_lineage(BRANCHED_SQL, "task_branched"))
    return _field(build_semantic_profile(document), "grp")["value_domain"]


def test_a_value_two_branches_both_produce_is_listed_once() -> None:
    """Two CASE blocks in two branch scopes are two observations of ONE value."""
    values = [item["value"] for item in _branched_domain()]

    assert values.count("SA") == 1
    assert sorted(values) == ["SA", "SB", "SC"]


def test_the_merged_entry_keeps_every_branchs_evidence() -> None:
    entry = next(item for item in _branched_domain() if item["value"] == "SA")

    assert len(entry["seen_in"]) == 2
    assert len(set(entry["seen_in"])) == 2


def test_the_value_line_names_each_value_once() -> None:
    document = to_lineage_dict(parse_scope_lineage(BRANCHED_SQL, "task_branched"))
    rendered = render_semantic_markdown(
        build_semantic_profile(document), sections=["fields"]
    )
    line = next(item for item in rendered.splitlines() if item.startswith("- 取值："))

    assert line.count("'SA'") == 1


# ------------------------------------------------------- WI-2.4b: patterns last

PATTERN_SQL = (
    "INSERT INTO mart.t SELECT o.order_id, o.state FROM ods.app_order o "
    "WHERE o.state IN ('CN', 'US') AND o.state LIKE '%UNIT_OUT_%'"
)


def _pattern_field() -> dict:
    document = to_lineage_dict(parse_scope_lineage(PATTERN_SQL, "task_pattern"))
    return _field(build_semantic_profile(document), "state")


def test_a_pattern_is_carried_in_the_domain_with_its_own_kind() -> None:
    entry = next(
        item for item in _pattern_field()["value_domain"] if item["kind"] == "pattern"
    )

    assert entry["value"] == "%UNIT_OUT_%"
    assert entry["sql_literal"] == "'%UNIT_OUT_%'"
    assert entry["closed_set"] is None


def test_the_value_line_puts_patterns_behind_the_enumerated_values() -> None:
    document = to_lineage_dict(parse_scope_lineage(PATTERN_SQL, "task_pattern"))
    rendered = render_semantic_markdown(
        build_semantic_profile(document), sections=["fields"]
    )
    line = next(item for item in rendered.splitlines() if item.startswith("- 取值："))

    assert line.index("'CN'") < line.index("匹配模式：")
    assert line.index("匹配模式：") < line.index("'%UNIT_OUT_%'")
    # A pattern is not an enum value awaiting a business meaning, so it carries no
    # 待确认 marker of its own.
    assert "'%UNIT_OUT_%'（待确认）" not in line


def test_a_pattern_does_not_cost_the_column_its_closed_set_claim() -> None:
    """``closed_set`` is a claim about the ENUM; a LIKE beside it is ignored."""
    document = to_lineage_dict(parse_scope_lineage(PATTERN_SQL, "task_pattern"))
    rendered = render_semantic_markdown(
        build_semantic_profile(document), sections=["fields"]
    )

    assert "该列取值已被 SQL 证明封闭" in rendered


def test_a_field_whose_only_observation_is_a_pattern_still_renders_the_line() -> None:
    sql = (
        "INSERT INTO mart.t SELECT o.order_id, o.state FROM ods.app_order o "
        "WHERE o.state LIKE '%UNIT_OUT_%'"
    )
    document = to_lineage_dict(parse_scope_lineage(sql, "task_only_pattern"))
    rendered = render_semantic_markdown(
        build_semantic_profile(document), sections=["fields"]
    )
    line = next(item for item in rendered.splitlines() if item.startswith("- 取值："))

    assert line.startswith("- 取值：匹配模式：'%UNIT_OUT_%'")
    assert "该列取值已被 SQL 证明封闭" not in line


# ----------------------------------------------------- WI-2.4b: a bounded value line


def _wide_rendered(count: int) -> str:
    values = ", ".join(f"'v{index:02d}'" for index in range(1, count + 1))
    sql = (
        f"INSERT INTO mart.t SELECT o.order_id, o.state FROM ods.app_order o "
        f"WHERE o.state IN ({values})"
    )
    document = to_lineage_dict(parse_scope_lineage(sql, "task_wide"))
    return render_semantic_markdown(
        build_semantic_profile(document), sections=["fields"]
    )


def test_twelve_values_are_all_listed() -> None:
    line = next(
        item for item in _wide_rendered(12).splitlines() if item.startswith("- 取值：")
    )

    assert "'v12'" in line
    assert "等 " not in line


def test_a_thirteenth_value_turns_the_line_into_a_pointer_at_the_json() -> None:
    line = next(
        item for item in _wide_rendered(13).splitlines() if item.startswith("- 取值：")
    )

    assert "'v12'" in line
    assert "'v13'" not in line
    assert "等 13 个，完整见 semantic.json value_domain" in line


def test_the_json_still_carries_every_value_the_line_stopped_listing() -> None:
    sql = (
        "INSERT INTO mart.t SELECT o.order_id, o.state FROM ods.app_order o "
        "WHERE o.state IN (" + ", ".join(f"'v{index:02d}'" for index in range(1, 14)) + ")"
    )
    document = to_lineage_dict(parse_scope_lineage(sql, "task_wide"))
    domain = _field(build_semantic_profile(document), "state")["value_domain"]

    assert len(domain) == 13


# --------------------------------------------------------------------------- CLI


def test_describe_glossary_flag_wires_the_dictionary_through(tmp_path: Path) -> None:
    task = tmp_path / "task_a"
    write_statement_documents(
        parse_scope_lineage(APP_SQL, "task_a", schema=_schema("ods.app_order")), task
    )
    overrides = tmp_path / "glossary.overrides.json"
    overrides.write_text(
        json.dumps({"values": {"pay_status='PAID'": {"meaning": "已支付"}}}, ensure_ascii=False),
        encoding="utf-8",
    )
    out = tmp_path / "dict"
    assert main(
        [
            "glossary",
            "--lineage",
            str(task / "lineage.json"),
            "--out",
            str(out),
            "--overrides",
            str(overrides),
        ]
    ) == 0
    assert main(
        [
            "describe",
            "--lineage",
            str(task / "lineage.json"),
            "--glossary",
            str(out / "glossary.json"),
        ]
    ) == 0

    profile = json.loads((task / "semantic.json").read_text(encoding="utf-8"))
    field = next(item for item in profile["fields"] if item["column"] == "pay_status")
    assert field["value_domain"][0]["meaning"] == {"text": "已支付", "status": "confirmed"}
    assert "- 取值：'PAID'（已支付）" in (task / "semantic.md").read_text(encoding="utf-8")


def test_describe_without_the_flag_still_publishes_the_local_domain(tmp_path: Path) -> None:
    task = tmp_path / "task_a"
    write_statement_documents(
        parse_scope_lineage(APP_SQL, "task_a", schema=_schema("ods.app_order")), task
    )
    assert main(["describe", "--lineage", str(task / "lineage.json")]) == 0

    profile = json.loads((task / "semantic.json").read_text(encoding="utf-8"))
    field = next(item for item in profile["fields"] if item["column"] == "pay_status")
    assert field["value_domain"][0]["value"] == "PAID"
    assert field["value_domain"][0]["sql_literal"] == "'PAID'"
    assert field["value_domain"][0]["meaning"] is None


def test_a_missing_glossary_file_stops_describe_with_an_exit_code(
    tmp_path: Path, capsys
) -> None:
    task = tmp_path / "task_a"
    write_statement_documents(parse_scope_lineage(APP_SQL, "task_a"), task)
    assert main(
        [
            "describe",
            "--lineage",
            str(task / "lineage.json"),
            "--glossary",
            str(tmp_path / "gone.json"),
        ]
    ) == 2
    assert "--glossary path does not exist" in capsys.readouterr().err


def test_describe_rejects_a_glossary_file_of_the_wrong_document_format(
    tmp_path: Path, capsys
) -> None:
    """The predictable mistake is handing ``--glossary`` the overrides file instead.

    ``glossary --overrides`` and ``describe --glossary`` sit one line apart in every
    runbook, and the overrides document is a JSON object too -- so it used to be accepted
    silently and the task described with no value domains at all, which reads exactly
    like a corpus that observed nothing. ``--tables`` already refuses a stranger by its
    declared format; ``--glossary`` now does the same.
    """
    task = tmp_path / "task_a"
    write_statement_documents(parse_scope_lineage(APP_SQL, "task_a"), task)
    stranger = tmp_path / "glossary.overrides.json"
    stranger.write_text(
        json.dumps({"values": {"pay_status='PAID'": {"meaning": "已支付"}}}),
        encoding="utf-8",
    )

    assert main(
        [
            "describe",
            "--lineage",
            str(task / "lineage.json"),
            "--glossary",
            str(stranger),
        ]
    ) == 1
    assert "--glossary expects a glossary-json/1 document" in capsys.readouterr().err


def test_describe_rejects_a_glossary_file_that_is_not_json(
    tmp_path: Path, capsys
) -> None:
    task = tmp_path / "task_a"
    write_statement_documents(parse_scope_lineage(APP_SQL, "task_a"), task)
    broken = tmp_path / "glossary.json"
    broken.write_text("{not json", encoding="utf-8")

    assert main(
        [
            "describe",
            "--lineage",
            str(task / "lineage.json"),
            "--glossary",
            str(broken),
        ]
    ) == 2
    assert "not a readable JSON document" in capsys.readouterr().err


# ------------------------------------------------------ WI-2.6: counting confirmations


def test_confirmations_count_the_values_and_terms_a_human_confirmed() -> None:
    """The profile says how much of THIS task has been answered, not the corpus's total."""
    documents = [_document(APP_SQL, "task_a", "支付状态"), _document(WEB_SQL, "task_b")]
    glossary = build_glossary(
        documents,
        artifact_root="corpus",
        overrides={
            "terms": {"pay_status": {"meaning": "支付状态"}},
            "values": {"pay_status='PAID'": {"meaning": "已支付"}},
        },
    )

    profile = apply_glossary(build_semantic_profile(documents[0]), glossary)

    assert profile["confidence"]["confirmations"] == {
        "values_confirmed": 1,
        # WI-2.12: the same `'PAID'`, counted where the WHERE pins it as well as where
        # the field carries it -- two questions a reader asks in two different places.
        "rule_values_confirmed": 1,
        "terms_confirmed": 1,
        "columns_patched": 0,
        "tables_patched": 0,
    }


def test_a_confirmed_term_for_a_column_this_task_never_touches_is_not_counted() -> None:
    documents = [_document(APP_SQL, "task_a")]
    glossary = build_glossary(
        documents,
        artifact_root="corpus",
        overrides={"terms": {"pay_status": {"meaning": "支付状态"}}},
    )
    glossary["terms"].append(
        {"column": "somewhere_else", "comments": [], "tables_total": 0,
         "tables_without_comment": [], "conflict": False,
         "meaning": {"text": "别处的列", "source": "override"}}
    )

    profile = apply_glossary(build_semantic_profile(documents[0]), glossary)

    assert profile["confidence"]["confirmations"]["terms_confirmed"] == 1


def test_without_a_glossary_the_confirmation_counts_stay_zero() -> None:
    profile = build_semantic_profile(_document(APP_SQL, "task_a"))

    assert profile["confidence"]["confirmations"] == {
        "values_confirmed": 0,
        "rule_values_confirmed": 0,
        "terms_confirmed": 0,
        "columns_patched": 0,
        "tables_patched": 0,
    }


# ------------------------------- WI-2.8 D1: a CASE condition belongs to the tested column

# `amt` is projected straight out of the sub-select, so its chain-wide transform is
# DIRECT -- but the value it carries came through a CASE, and the CASE reads `flag`. The
# pre-D1 matcher followed every source of a DIRECT field, so `'N'` (the condition's
# constant) was published as a value of the amount column and marked 已证明封闭.
CASE_CONDITION_SQL = (
    "INSERT INTO mart.t SELECT m.amt, m.flag FROM ("
    "SELECT CASE WHEN o.flag = 'N' THEN o.amt ELSE 0 END AS amt, o.flag "
    "FROM ods.app_order o) m"
)

PASS_THROUGH_SQL = (
    "INSERT INTO mart.t SELECT m.flag FROM ("
    "SELECT o.flag FROM ods.app_order o WHERE o.flag = 'N') m"
)

_CASE_SCHEMA = {"ods.app_order": ["flag", "amt"], "mart.t": ["amt", "flag"]}


def _case_field(sql: str, column: str) -> dict:
    document = to_lineage_dict(parse_scope_lineage(sql, "task_case", schema=_CASE_SCHEMA))
    return _field(build_semantic_profile(document), column)


def test_a_case_conditions_constant_never_reaches_the_column_the_case_produces() -> None:
    # WI-C then took the ELSE constant too: `THEN o.amt ELSE 0` is a computation
    # default of an amount column, not a code, so the column is left with no domain
    # at all. `'N'` staying out of it is what this test is about either way.
    domain = _case_field(CASE_CONDITION_SQL, "amt").get("value_domain") or []

    assert "N" not in [item["value"] for item in domain]
    assert domain == []


def test_a_case_conditions_constant_does_not_travel_to_a_pass_through_either() -> None:
    """`flag` is read by the CASE, not compared by a filter: nothing is proven about it."""
    assert _case_field(CASE_CONDITION_SQL, "flag").get("value_domain") is None


def test_an_equality_filter_still_travels_through_a_direct_projection() -> None:
    """The half of the rule that must keep working: a WHERE `=` IS a fact about the column."""
    domain = _case_field(PASS_THROUGH_SQL, "flag")["value_domain"]

    assert [item["value"] for item in domain] == ["N"]


def _typed_field(declared: str, transform: str = "DIRECT") -> dict:
    return {
        "column": "amount",
        "type": declared,
        "transform": transform,
        "sources": [
            {"table": "ods.app_order", "column": "amount", "transform": "DIRECT"}
        ],
    }


def _entry(value: str, literal: str) -> dict:
    return {
        "column_ref": "ods.app_order.amount",
        "column": "amount",
        "value": value,
        "sql_literal": literal,
        "kind": "literal",
        "observations": [{"context": "filter_eq", "evidence": "rule:001"}],
        "task_count": 1,
        "closed_set": None,
        "meaning_candidates": [],
        "meaning": None,
    }


def test_a_string_literal_is_not_published_as_a_value_of_an_amount_column() -> None:
    """The type guard: `'Y'` is not something a `decimal(15,2)` column ever holds."""
    field = _typed_field("decimal(15,2)")

    apply_value_domains([field], [_entry("Y", "'Y'"), _entry("0", "0")])

    assert [item["value"] for item in field["value_domain"]] == ["0"]


def test_a_quoted_number_is_still_a_value_of_a_numeric_column() -> None:
    field = _typed_field("bigint")

    apply_value_domains([field], [_entry("0", "'0'")])

    assert [item["value"] for item in field["value_domain"]] == ["0"]


def test_a_quoted_date_is_still_a_value_of_a_date_column() -> None:
    field = _typed_field("date")

    apply_value_domains([field], [_entry("2026-01-01", "'2026-01-01'"), _entry("Y", "'Y'")])

    assert [item["value"] for item in field["value_domain"]] == ["2026-01-01"]


def test_a_string_column_keeps_its_string_values() -> None:
    field = _typed_field("string")

    apply_value_domains([field], [_entry("Y", "'Y'")])

    assert [item["value"] for item in field["value_domain"]] == ["Y"]


def test_a_source_reached_through_a_case_is_not_a_pass_through_source() -> None:
    """One non-pass-through step anywhere on the chain breaks the inheritance."""
    field = _typed_field("string")
    field["sources"][0]["transform"] = "CONDITIONAL"

    apply_value_domains([field], [_entry("Y", "'Y'")])

    assert field.get("value_domain") is None


# ------------------------------------------- WI-2.8 D3: closed_set is a column's verdict

# Three CASE branches make the set closed; `0` is ALSO produced as a UNION constant, and
# the per-value merge used to withdraw the claim for that one value alone -- leaving a
# column whose three values read 待证明 / 已证明 / 已证明 out of one exhaustive CASE.
MIXED_CLOSURE_SQL = (
    "INSERT INTO mart.t SELECT CASE WHEN o.flag = 'A' THEN '1' "
    "WHEN o.flag = 'B' THEN '2' ELSE '0' END AS code FROM ods.app_order o "
    "UNION ALL SELECT '0' AS code FROM ods.web_order w"
)


def _closure_domain() -> list[dict]:
    document = to_lineage_dict(
        parse_scope_lineage(
            MIXED_CLOSURE_SQL,
            "task_closure",
            schema={
                "ods.app_order": ["flag"],
                "ods.web_order": ["flag"],
                "mart.t": ["code"],
            },
        )
    )
    return _field(build_semantic_profile(document), "code")["value_domain"]


def test_every_value_of_one_column_carries_the_same_closed_set_verdict() -> None:
    verdicts = {item["closed_set"] for item in _closure_domain()}

    assert len(verdicts) == 1
    assert verdicts == {True}


def test_the_closed_note_is_written_once_the_column_agrees() -> None:
    document = to_lineage_dict(
        parse_scope_lineage(
            MIXED_CLOSURE_SQL,
            "task_closure",
            schema={
                "ods.app_order": ["flag"],
                "ods.web_order": ["flag"],
                "mart.t": ["code"],
            },
        )
    )
    rendered = render_semantic_markdown(
        build_semantic_profile(document), sections=["fields"]
    )
    line = next(item for item in rendered.splitlines() if item.startswith("- 取值："))

    assert "该列取值已被 SQL 证明封闭" in line


# --------------------------------------------- WI-2.8 D4: one spelling, one displayed form


def test_the_markdown_shows_the_literal_the_author_wrote() -> None:
    """The stored value lost its quotes; the line a human reads did not."""
    profile = build_semantic_profile(_document(APP_SQL, "task_a"))
    rendered = render_semantic_markdown(profile, sections=["fields"])
    line = next(item for item in rendered.splitlines() if item.startswith("- 取值："))

    assert _field(profile, "pay_status")["value_domain"][0]["value"] == "PAID"
    assert "'PAID'" in line


def test_an_unquoted_override_key_confirms_the_same_value_as_a_quoted_one() -> None:
    """`strip_quotes` runs on both sides, so a reviewer may write either spelling."""
    for key in ("pay_status=PAID", "pay_status='PAID'"):
        glossary = build_glossary(
            [_document(APP_SQL, "task_a")],
            artifact_root="corpus",
            overrides={"values": {key: "已支付"}},
        )
        assert glossary["overrides_applied"]["values"] == 1
        assert glossary["values"][0]["meaning"]["text"] == "已支付"


# ------------------------------------- WI-2.4b: an output value belongs to ONE table


ORDER_LABEL_SQL = (
    "INSERT INTO mart.orders SELECT o.id, "
    "CASE WHEN o.paid = 1 THEN 'SA' ELSE 'SB' END AS status FROM ods.app_order o"
)
TICKET_LABEL_SQL = (
    "INSERT INTO mart.tickets SELECT t.id, "
    "CASE WHEN t.opened = 1 THEN 'TA' ELSE 'TB' END AS status FROM ods.ticket t"
)


def _label_corpus() -> tuple[dict, dict, dict]:
    documents = [
        _document(ORDER_LABEL_SQL, "task_orders"),
        _document(TICKET_LABEL_SQL, "task_tickets"),
    ]
    return (
        documents[0],
        documents[1],
        build_glossary(documents, artifact_root="corpus"),
    )


def test_an_output_value_does_not_travel_to_the_same_name_in_another_table() -> None:
    """``status`` is the most reused column name a warehouse has.

    The output route used to be indexed by the bare column name, so every CASE label any
    task ever wrote into a column called ``status`` was published as a value of every
    other task's ``status`` -- a value domain that reads like an enumeration and is in
    fact a collection of unrelated codes. An output value is a fact about the column of
    ONE target table, and that is the key it is filed under.
    """
    orders, tickets, glossary = _label_corpus()

    orders_domain = _field(apply_glossary(build_semantic_profile(orders), glossary), "status")
    tickets_domain = _field(apply_glossary(build_semantic_profile(tickets), glossary), "status")

    assert [item["value"] for item in orders_domain["value_domain"]] == ["SA", "SB"]
    assert [item["value"] for item in tickets_domain["value_domain"]] == ["TA", "TB"]


def test_the_output_route_matches_under_a_different_qualification_level() -> None:
    """``spark_catalog.mart.orders`` and ``mart.orders`` are one table, here too."""
    orders, _tickets, glossary = _label_corpus()
    for entry in glossary["values"]:
        entry["column_ref"] = entry["column_ref"].replace("mart.", "spark_catalog.mart.")

    domain = _field(apply_glossary(build_semantic_profile(orders), glossary), "status")

    assert [item["value"] for item in domain["value_domain"]] == ["SA", "SB"]


def test_a_scope_level_label_still_reaches_the_column_it_produces() -> None:
    """A CASE inside a CTE names no table, so it keeps speaking to its own statement."""
    sql = (
        "INSERT INTO mart.t WITH c AS (SELECT id, "
        "CASE WHEN x = 1 THEN 'A' ELSE 'B' END AS status FROM ods.s) "
        "SELECT id, status FROM c"
    )
    document = _document(sql, "task_cte")

    domain = _field(build_semantic_profile(document), "status")["value_domain"]

    assert [item["value"] for item in domain] == ["A", "B"]


# ---------------------------------------- the enumerable half of A2 (WI-9 legacy b)


_ENUM_SCHEMA = SchemaMap(
    {"ods.ticket": ["ticket_id", "state", "level", "amount", "dt"]},
    column_details={
        "ods.ticket": [
            {"name": "ticket_id", "type": "bigint", "comment": None},
            {"name": "state", "type": "string", "comment": None},
            {"name": "level", "type": "int", "comment": None},
            {"name": "amount", "type": "decimal(18,2)", "comment": None},
            {"name": "dt", "type": "string", "comment": None},
        ]
    },
)


def _enum_schema(**comments: str) -> SchemaMap:
    """``ods.ticket`` again, with a comment written on one of its columns."""
    return SchemaMap(
        {"ods.ticket": ["ticket_id", "state", "level", "amount", "dt"]},
        column_details={
            "ods.ticket": [
                {**detail, "comment": comments.get(str(detail["name"]), detail["comment"])}
                for detail in _ENUM_SCHEMA.column_details["ods.ticket"]
            ]
        },
    )


def _enum_coverage(sql: str, schema: SchemaMap | None = None) -> dict:
    document = to_lineage_dict(
        parse_scope_lineage(sql, "enum_case", schema=schema or _ENUM_SCHEMA)
    )
    profile = build_semantic_profile(document)
    return profile["confidence"]["metadata_coverage"].get("glossary") or {}


def test_a_batch_date_is_observed_but_is_not_an_enumerable_code() -> None:
    coverage = _enum_coverage(
        "INSERT INTO mart.t SELECT t.ticket_id, t.dt FROM ods.ticket t "
        "WHERE t.dt = '20250115'"
    )

    assert coverage["values_total"] == 1
    assert coverage["enumerable_total"] == 0


def test_a_bare_number_pinned_by_equals_is_not_an_enumerable_code() -> None:
    """`= 0` is as likely a guard or a threshold as a code, and nobody can name it."""
    coverage = _enum_coverage(
        "INSERT INTO mart.t SELECT t.ticket_id, t.level FROM ods.ticket t "
        "WHERE t.level = 0"
    )

    assert coverage["values_total"] == 1
    assert coverage["enumerable_total"] == 0


_IN_LIST_SQL = (
    "INSERT INTO mart.t SELECT t.ticket_id, t.level FROM ods.ticket t "
    "WHERE t.level IN (0, 1)"
)


def test_a_bare_number_in_an_in_list_is_still_nothing_anybody_can_name() -> None:
    """Q1: the denominator asks the FORM's question, and the form does not ask this one.

    An ``IN`` list proves ``0`` and ``1`` are alternatives; it does not turn them into
    business vocabulary, and the fill-in form has always stepped over a bare number.
    The count used to admit them anyway, so a reader saw a ratio taken over rows the
    form would never print -- a form asking nothing beside "2 codes unexplained".
    """
    coverage = _enum_coverage(_IN_LIST_SQL)

    assert coverage["values_total"] == 2
    assert coverage["enumerable_total"] == 0


def test_a_bare_number_the_column_comment_enumerates_is_counted() -> None:
    """The positive half: once somebody wrote down which is which, it is a code table."""
    coverage = _enum_coverage(_IN_LIST_SQL, _enum_schema(level="0-未生效，1-生效"))

    assert coverage["values_total"] == 2
    assert coverage["enumerable_total"] == 2


def test_a_case_label_is_enumerable_and_a_case_condition_alone_is_not() -> None:
    coverage = _enum_coverage(
        "INSERT INTO mart.t SELECT t.ticket_id, "
        "CASE WHEN t.amount > 100 THEN 'BIG' ELSE 'SMALL' END AS band FROM ods.ticket t"
    )

    assert coverage["enumerable_total"] == 2


def test_a_renamed_pass_through_keeps_its_code_enumerable() -> None:
    """The dictionary files the code under the source column; the field renames it."""
    coverage = _enum_coverage(
        "INSERT INTO mart.t SELECT t.ticket_id, t.state AS ticket_state "
        "FROM ods.ticket t WHERE t.state = 'OPEN'"
    )

    assert coverage["values_total"] == 1
    assert coverage["enumerable_total"] == 1


def test_a_match_shape_is_never_an_enumerable_code() -> None:
    coverage = _enum_coverage(
        "INSERT INTO mart.t SELECT t.ticket_id, t.state FROM ods.ticket t "
        "WHERE t.state RLIKE 'OPEN|CLOSED'"
    )

    assert coverage["values_total"] == 1
    assert coverage["enumerable_total"] == 0


def test_the_enumerable_count_never_exceeds_the_observed_total() -> None:
    """Anti-fabrication: the narrowed denominator is a subset, never a second list."""
    for sql in (
        "INSERT INTO mart.t SELECT t.ticket_id, t.state FROM ods.ticket t "
        "WHERE t.state = 'OPEN'",
        "INSERT INTO mart.t SELECT t.ticket_id, t.level FROM ods.ticket t "
        "WHERE t.level IN (0, 1)",
        "INSERT INTO mart.t SELECT t.ticket_id, 'X' AS src FROM ods.ticket t",
    ):
        coverage = _enum_coverage(sql)
        assert coverage["enumerable_total"] <= coverage["values_total"]
        assert coverage["enumerable_confirmed"] <= coverage["enumerable_total"]
        assert coverage["enumerable_confirmed"] <= coverage["confirmed"]
