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
            "value": "'PAID'",
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
        "'PAID'"
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
        "values_total": 1,
        "confirmed": 1,
        "candidate": 0,
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

    assert values.count("'SA'") == 1
    assert sorted(values) == ["'SA'", "'SB'", "'SC'"]


def test_the_merged_entry_keeps_every_branchs_evidence() -> None:
    entry = next(item for item in _branched_domain() if item["value"] == "'SA'")

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

    assert entry["value"] == "'%UNIT_OUT_%'"
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
    assert field["value_domain"][0]["value"] == "'PAID'"
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
    assert "does not exist" in capsys.readouterr().err
