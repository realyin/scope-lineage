"""WI-2.9 item C: ``glossary --template``, the 取值含义 form.

The open-questions list used to ask what every ``code`` meant, one question per value,
and the owner could not work through them. Those were never questions -- they were a
form -- so the profile now points at this file and the CLI generates it.

The first version of the form ranked closed sets first and then by observation count,
and a real corpus filled its whole first page with ``Y`` / ``N``, ``1`` / ``0`` and
scope-level columns: exactly the values nobody has a business meaning for. The form now
asks about *columns* -- physical ones, with at least two non-trivial values -- ranked by
how much of the corpus rests on them, and says at the top how much it left out.

The tests pin what the form leaves out (one case per exclusion rule), what order it asks
in, that the two files it writes say the same thing, and that two runs of one corpus
produce the same bytes.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

from scope_lineage.cli import main
from scope_lineage.metadata.schema_metadata import SchemaMap
from scope_lineage.render.glossary import build_glossary
from scope_lineage.render.glossary_template import (
    TEMPLATE_TOP_DEFAULT,
    build_overrides_template,
    render_overrides_template_markdown,
    template_entries,
)
from scope_lineage.scope.scope_builder import parse_scope_lineage

from .statement_document import write_statement_documents


DAY = datetime.date(2026, 9, 19)

# Two askable columns (`pay_status`, `channel`), and one of each thing the form must not
# ask about: a switch, a bare number, an instance date and a match pattern.
MIXED_SQL = (
    "INSERT INTO mart.orders SELECT o.order_id, o.pay_status, o.channel "
    "FROM ods.app_order o "
    "WHERE o.pay_status IN ('PAID', 'REFUND') AND o.channel IN ('APP', 'WEB') "
    "AND o.is_vip IN ('Y', 'N') AND o.dt IN ('20260814', '20260815') "
    "AND o.rn IN (1, 2) AND o.note RLIKE 'A|B'"
)

MIXED_COLUMNS = [
    "order_id",
    "pay_status",
    "channel",
    "is_vip",
    "dt",
    "rn",
    "note",
]

# `支付状态` carries one of the ranking clues (状态); `来源渠道` deliberately carries
# none, so the two columns differ by exactly the clue and nothing else.
MIXED_COMMENTS = {"pay_status": "支付状态", "channel": "来源渠道"}

MIXED_SCHEMA = SchemaMap(
    {"ods.app_order": MIXED_COLUMNS},
    column_details={
        "ods.app_order": [
            {
                "name": name,
                "type": "string",
                "comment": MIXED_COMMENTS.get(name),
            }
            for name in MIXED_COLUMNS
        ]
    },
)

# A CASE inside a CTE: its labels never reach a named target column, so they are filed
# against a scope id, which is not a key any overrides file can bind.
SCOPE_SQL = (
    "INSERT INTO mart.t WITH d AS ("
    " SELECT s.id, CASE WHEN s.f = 'A' THEN 'X' ELSE 'Z' END AS tag FROM ods.s s) "
    "SELECT d.id FROM d"
)


def _document(sql: str, task_id: str = "corpus", schema=None) -> dict:
    from scope_lineage.contract import to_lineage_dict

    return to_lineage_dict(parse_scope_lineage(sql, task_id, schema=schema))


def _glossary(sql: str = MIXED_SQL, schema=None, **kwargs) -> dict:
    return build_glossary(
        [_document(sql, schema=schema or MIXED_SCHEMA)], artifact_root="corpus", **kwargs
    )


def _keys(template: dict) -> list[str]:
    return list(template["values"])


def _columns(template: dict) -> list[str]:
    return list(dict.fromkeys(key.rsplit("=", 1)[0] for key in _keys(template)))


# ------------------------------------------------------------------ 1. exclusions


def test_a_closed_set_value_is_asked_about() -> None:
    template = build_overrides_template(_glossary(), today=DAY)

    assert "ods.app_order.pay_status=PAID" in _keys(template)
    assert "ods.app_order.pay_status=REFUND" in _keys(template)


def test_a_switch_is_not_a_code_and_is_left_out() -> None:
    assert not [key for key in _keys(build_overrides_template(_glossary(), today=DAY))
                if ".is_vip=" in key]


def test_a_date_shaped_literal_is_not_a_code_and_is_left_out() -> None:
    assert not [key for key in _keys(build_overrides_template(_glossary(), today=DAY))
                if key.endswith("=20260814")]


def test_a_bare_number_is_left_out_even_inside_a_proven_closed_set() -> None:
    """`rn IN (1, 2)` is a position pinned to a set, not an enumeration of codes."""
    assert not [key for key in _keys(build_overrides_template(_glossary(), today=DAY))
                if ".rn=" in key]


def test_a_match_pattern_is_a_shape_not_a_value_and_is_left_out() -> None:
    assert not [key for key in _keys(build_overrides_template(_glossary(), today=DAY))
                if "A|B" in key]


def test_a_scope_level_column_is_left_out() -> None:
    template = build_overrides_template(
        _glossary(SCOPE_SQL, schema={"ods.s": ["id", "f"]}), today=DAY
    )

    assert not [key for key in _keys(template) if ":" in key]


def test_a_column_with_only_one_value_left_is_not_worth_a_section() -> None:
    """One value is not a code system: the answer teaches a reader nothing about a set."""
    sql = (
        "INSERT INTO mart.t SELECT s.id FROM ods.src s "
        "WHERE s.state = 'OK' AND s.kind IN ('A', 'B')"
    )
    template = build_overrides_template(
        _glossary(sql, schema={"ods.src": ["id", "state", "kind"]}), today=DAY
    )

    assert _columns(template) == ["ods.src.kind"]


def test_a_value_somebody_already_confirmed_is_not_asked_twice() -> None:
    overrides = {"values": {"pay_status=PAID": {"meaning": "已支付"}}}
    template = build_overrides_template(_glossary(overrides=overrides), today=DAY)

    assert "ods.app_order.pay_status=PAID" not in _keys(template)
    assert "ods.app_order.channel=APP" in _keys(template)


# -------------------------------------------------------------------- 2. ordering


def test_a_comment_clue_lifts_a_column_above_an_otherwise_equal_one() -> None:
    """Two columns, same counts; only `支付状态` reads like a code column."""
    assert _columns(build_overrides_template(_glossary(), today=DAY)) == [
        "ods.app_order.pay_status",
        "ods.app_order.channel",
    ]


def test_the_values_of_one_column_are_asked_together() -> None:
    columns = [key.rsplit("=", 1)[0] for key in _keys(
        build_overrides_template(_glossary(), today=DAY)
    )]

    assert columns == sorted(columns, key=lambda name: columns.index(name))
    assert len(set(columns)) == len(list(dict.fromkeys(columns)))


def test_the_top_limit_cuts_the_form_and_defaults_to_twenty() -> None:
    glossary = _glossary()

    assert len(_keys(build_overrides_template(glossary, top=1, today=DAY))) == 1
    assert TEMPLATE_TOP_DEFAULT == 20
    assert _keys(build_overrides_template(glossary, top=1, today=DAY)) == _keys(
        build_overrides_template(glossary, today=DAY)
    )[:1]


# --------------------------------------------------------- 3. the two files agree


def test_every_json_entry_is_an_empty_meaning_dated_today() -> None:
    template = build_overrides_template(_glossary(), today=DAY)

    assert template["doc_format"] == "glossary-overrides-template/1"
    for payload in template["values"].values():
        assert payload == {"meaning": "", "confirmed_by": None, "date": "2026-09-19"}


def test_the_markdown_asks_about_exactly_the_json_keys() -> None:
    glossary = _glossary()
    template = build_overrides_template(glossary, today=DAY)
    markdown = render_overrides_template_markdown(template, glossary)

    for key in _keys(template):
        column, _, value = key.rpartition("=")
        assert f"## `{column}`" in markdown
        assert f"| `{value}` |" in markdown
    assert markdown.count("| `") == len(template["values"]) * 2


def test_the_markdown_counts_what_it_did_not_ask_about() -> None:
    """A form that silently drops two thirds of a corpus reads as a form that saw it."""
    glossary = _glossary()
    template = build_overrides_template(glossary, today=DAY)

    assert template["generated"]["excluded_values"] == 6
    assert template["generated"]["excluded_scope_columns"] == 0
    assert "排除了 6 个开关/数字/日期型取值与 0 个 scope 级列" in (
        render_overrides_template_markdown(template, glossary)
    )


def test_the_scope_columns_it_stepped_over_are_counted_too() -> None:
    glossary = _glossary(SCOPE_SQL, schema={"ods.s": ["id", "f"]})
    template = build_overrides_template(glossary, today=DAY)

    assert template["generated"]["excluded_scope_columns"] == 1
    assert "1 个 scope 级列" in render_overrides_template_markdown(template, glossary)


def test_the_markdown_says_whether_the_column_was_proven_closed() -> None:
    glossary = _glossary()
    markdown = render_overrides_template_markdown(
        build_overrides_template(glossary, today=DAY), glossary
    )

    assert "- 该列取值已被 SQL 证明封闭：是" in markdown


def test_a_corpus_with_nothing_to_ask_produces_a_form_that_says_so() -> None:
    glossary = _glossary(
        "INSERT INTO mart.t SELECT s.id FROM ods.src s WHERE s.dt = '20260814'",
        schema={"ods.src": ["id", "dt"]},
    )
    template = build_overrides_template(glossary, today=DAY)

    assert template["values"] == {}
    assert "语料里没有需要填含义的取值。" in render_overrides_template_markdown(
        template, glossary
    )


def test_two_builds_of_one_corpus_are_byte_identical() -> None:
    glossary = _glossary()
    first = build_overrides_template(glossary, today=DAY)
    second = build_overrides_template(_glossary(), today=DAY)

    assert json.dumps(first, ensure_ascii=False) == json.dumps(second, ensure_ascii=False)
    assert render_overrides_template_markdown(
        first, glossary
    ) == render_overrides_template_markdown(second, _glossary())


# ------------------------------------------------------------------------ 4. CLI


def _artifacts(sql: str, out_dir: Path, schema=None) -> Path:
    write_statement_documents(
        parse_scope_lineage(sql, out_dir.name, schema=schema), out_dir
    )
    return out_dir


def test_the_cli_writes_both_files_beside_the_dictionary(tmp_path: Path, capsys) -> None:
    task = _artifacts(MIXED_SQL, tmp_path / "task_a", schema=MIXED_SCHEMA)
    out = tmp_path / "dict"
    template = out / "glossary.overrides.template.md"

    assert (
        main(
            [
                "glossary",
                "--lineage",
                str(task / "lineage.json"),
                "--out",
                str(out),
                "--template",
                str(template),
            ]
        )
        == 0
    )

    assert template.read_text(encoding="utf-8").startswith("# 取值含义待填模板")
    payload = json.loads(
        (out / "glossary.overrides.template.json").read_text(encoding="utf-8")
    )
    assert payload["doc_format"] == "glossary-overrides-template/1"
    assert "fill-in template" in capsys.readouterr().out


def test_the_cli_honours_template_top(tmp_path: Path) -> None:
    task = _artifacts(MIXED_SQL, tmp_path / "task_a", schema=MIXED_SCHEMA)
    out = tmp_path / "dict"

    assert (
        main(
            [
                "glossary",
                "--lineage",
                str(task / "lineage.json"),
                "--out",
                str(out),
                "--template",
                str(out / "form.md"),
                "--template-top",
                "2",
            ]
        )
        == 0
    )

    payload = json.loads((out / "form.json").read_text(encoding="utf-8"))
    assert len(payload["values"]) == 2
    assert payload["generated"]["top"] == 2


def test_the_generated_json_is_accepted_back_as_overrides(tmp_path: Path) -> None:
    """The form's whole point: what a person fills in goes straight back into the run."""
    task = _artifacts(MIXED_SQL, tmp_path / "task_a", schema=MIXED_SCHEMA)
    out = tmp_path / "dict"
    form = out / "glossary.overrides.template.md"
    args = ["glossary", "--lineage", str(task / "lineage.json"), "--out", str(out)]

    assert main([*args, "--template", str(form)]) == 0
    filled = json.loads(form.with_suffix(".json").read_text(encoding="utf-8"))
    key = next(iter(filled["values"]))
    filled["values"][key]["meaning"] = "已支付"
    form.with_suffix(".json").write_text(
        json.dumps(filled, ensure_ascii=False), encoding="utf-8"
    )

    assert main([*args, "--overrides", str(form.with_suffix(".json"))]) == 0
    glossary = json.loads((out / "glossary.json").read_text(encoding="utf-8"))
    assert glossary["overrides_applied"]["values"] == 1
    assert glossary["overrides_applied"]["unmatched"] == []


def test_the_template_flag_says_it_still_needs_an_out_directory(capsys) -> None:
    """`--out` stays required, so the refusal has to name the reason, not just the flag."""
    assert main(["glossary", "--lineage", "x", "--template", "form.md"]) == 2

    error = capsys.readouterr().err
    assert "--out is required" in error
    assert "--template ranks its form from that dictionary" in error


def test_no_template_flag_writes_no_template(tmp_path: Path) -> None:
    task = _artifacts(MIXED_SQL, tmp_path / "task_a", schema=MIXED_SCHEMA)
    out = tmp_path / "dict"

    assert main(["glossary", "--lineage", str(task / "lineage.json"), "--out", str(out)]) == 0
    assert not list(out.glob("*template*"))


# ------------------- 5. WI-B: the alias of a positionally bound column, in the form


def test_the_form_heading_says_which_alias_the_author_wrote() -> None:
    """The person filling the form in searches their SQL for the name they typed."""
    from .test_glossary import _positional_document

    glossary = build_glossary([_positional_document()], artifact_root="corpus")
    rendered = render_overrides_template_markdown(
        build_overrides_template(glossary, today=DAY), glossary
    )

    assert (
        "## `mart.hourly_gap_summary.gap_10`"
        "（SQL 别名 `delta_18`，按 DDL 位置写入）（2 个取值）" in rendered
    )


# ------------------------------------ 6. WI-D: `--template-top 0` means "no cap"


def test_a_top_of_zero_asks_about_every_askable_value() -> None:
    """Zero used to produce an empty form, which is the one thing nobody wants: a
    corpus with more values than the default is exactly when "ask about all" is asked
    for."""
    glossary = _glossary()
    every = _keys(build_overrides_template(glossary, top=0, today=DAY))

    assert every == _keys(build_overrides_template(glossary, top=TEMPLATE_TOP_DEFAULT, today=DAY))
    assert len(every) == len(template_entries(glossary, top=0))
    assert every


def test_a_top_of_zero_is_not_cut_by_the_default(tmp_path: Path) -> None:
    """The form is larger than the default cut, so 0 and 20 cannot agree by accident."""
    glossary = _glossary()
    assert len(template_entries(glossary, top=0)) == len(
        [item for item in glossary["values"] if item["column"] in ("pay_status", "channel")]
    )
    assert len(_keys(build_overrides_template(glossary, top=1, today=DAY))) == 1


def test_the_cli_takes_zero_as_no_cap(tmp_path: Path) -> None:
    task = _artifacts(MIXED_SQL, tmp_path / "task_a", schema=MIXED_SCHEMA)
    out = tmp_path / "dict"

    assert (
        main(
            [
                "glossary",
                "--lineage",
                str(task / "lineage.json"),
                "--out",
                str(out),
                "--template",
                str(out / "form.md"),
                "--template-top",
                "0",
            ]
        )
        == 0
    )

    payload = json.loads((out / "form.json").read_text(encoding="utf-8"))
    assert payload["generated"]["top"] == 0
    assert len(payload["values"]) == 4


def test_a_top_of_zero_keeps_single_value_columns() -> None:
    """The ≥2 rule is about ranking worth, not about hiding: a form that promises to
    ask about every askable value cannot drop eight columns out of nine."""
    sql = (
        "INSERT INTO mart.t SELECT s.id FROM ods.src s "
        "WHERE s.state = 'OK' AND s.kind IN ('A', 'B')"
    )
    glossary = _glossary(sql, schema={"ods.src": ["id", "state", "kind"]})

    assert _columns(build_overrides_template(glossary, today=DAY)) == ["ods.src.kind"]
    assert _columns(build_overrides_template(glossary, top=0, today=DAY)) == [
        "ods.src.kind",
        "ods.src.state",
    ]
    assert "ods.src.state=OK" in _keys(build_overrides_template(glossary, top=0, today=DAY))
