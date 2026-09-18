"""WI-2.9 item C: ``glossary --template``, the 取值含义 form.

The open-questions list used to ask what every ``code`` meant, one question per value,
and the owner could not work through them. Those were never questions -- they were a
form -- so the profile now points at this file and the CLI generates it.

The tests pin what the form leaves out (one case per exclusion rule), what order it asks
in, that the two files it writes say the same thing, and that two runs of one corpus
produce the same bytes.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

from scope_lineage.cli import main
from scope_lineage.render.glossary import build_glossary
from scope_lineage.render.glossary_template import (
    TEMPLATE_TOP_DEFAULT,
    build_overrides_template,
    render_overrides_template_markdown,
)
from scope_lineage.scope.scope_builder import parse_scope_lineage

from .statement_document import write_statement_documents


DAY = datetime.date(2026, 9, 19)

MIXED_SQL = (
    "INSERT INTO mart.orders SELECT o.order_id, o.pay_status, o.channel "
    "FROM ods.app_order o "
    "WHERE o.pay_status IN ('PAID', 'REFUND') AND o.channel = 'APP' "
    "AND o.dt = '20260814' AND o.rn = 1 AND o.note RLIKE 'A|B'"
)

MIXED_SCHEMA = {
    "ods.app_order": ["order_id", "pay_status", "channel", "dt", "rn", "note"]
}


def _document(sql: str, task_id: str = "corpus", schema=None) -> dict:
    from scope_lineage.contract import to_lineage_dict

    return to_lineage_dict(parse_scope_lineage(sql, task_id, schema=schema))


def _glossary(sql: str = MIXED_SQL, schema=None, **kwargs) -> dict:
    return build_glossary(
        [_document(sql, schema=schema or MIXED_SCHEMA)], artifact_root="corpus", **kwargs
    )


def _keys(template: dict) -> list[str]:
    return list(template["values"])


# ------------------------------------------------------------------ 1. exclusions


def test_a_closed_set_value_is_asked_about() -> None:
    template = build_overrides_template(_glossary(), today=DAY)

    assert "ods.app_order.pay_status=PAID" in _keys(template)
    assert "ods.app_order.pay_status=REFUND" in _keys(template)


def test_a_plain_equality_value_is_asked_about_too() -> None:
    assert "ods.app_order.channel=APP" in _keys(
        build_overrides_template(_glossary(), today=DAY)
    )


def test_a_date_shaped_literal_is_not_a_code_and_is_left_out() -> None:
    assert not [key for key in _keys(build_overrides_template(_glossary(), today=DAY))
                if key.endswith("=20260814")]


def test_a_bare_number_with_no_enumerated_context_is_left_out() -> None:
    assert not [key for key in _keys(build_overrides_template(_glossary(), today=DAY))
                if key.endswith(".rn=1")]


def test_a_number_inside_a_proven_closed_set_is_kept() -> None:
    sql = (
        "INSERT INTO mart.t SELECT s.id, s.state FROM ods.src s "
        "WHERE s.state IN (0, 1, 2)"
    )
    template = build_overrides_template(
        _glossary(sql, schema={"ods.src": ["id", "state"]}), today=DAY
    )

    assert "ods.src.state=0" in _keys(template)


def test_a_match_pattern_is_a_shape_not_a_value_and_is_left_out() -> None:
    assert not [key for key in _keys(build_overrides_template(_glossary(), today=DAY))
                if "A|B" in key]


def test_a_value_somebody_already_confirmed_is_not_asked_twice() -> None:
    overrides = {"values": {"pay_status=PAID": {"meaning": "已支付"}}}
    template = build_overrides_template(_glossary(overrides=overrides), today=DAY)

    assert "ods.app_order.pay_status=PAID" not in _keys(template)
    assert "ods.app_order.pay_status=REFUND" in _keys(template)


# -------------------------------------------------------------------- 2. ordering


TWO_TASK_SQL = (
    "INSERT INTO mart.other SELECT o.id, o.channel FROM ods.other o "
    "WHERE o.channel = 'WEB'"
)


def test_a_closed_set_outranks_a_value_used_by_more_tasks() -> None:
    """Closedness is the stronger fact: the answer completes a set rather than a guess."""
    documents = [
        _document(MIXED_SQL, "task_a", schema=MIXED_SCHEMA),
        _document(TWO_TASK_SQL, "task_b", schema={"ods.other": ["id", "channel"]}),
        _document(TWO_TASK_SQL, "task_c", schema={"ods.other": ["id", "channel"]}),
    ]
    glossary = build_glossary(documents, artifact_root="corpus")
    keys = _keys(build_overrides_template(glossary, today=DAY))

    assert keys[0].startswith("ods.app_order.pay_status=")
    assert "ods.other.channel=WEB" in keys


def test_the_values_of_one_column_are_asked_together() -> None:
    keys = _keys(build_overrides_template(_glossary(), today=DAY))
    columns = [key.rsplit("=", 1)[0] for key in keys]

    assert len(columns) == len(set(columns)) + (len(columns) - len(dict.fromkeys(columns)))
    assert columns == sorted(columns, key=lambda name: columns.index(name))


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


def test_the_markdown_says_whether_the_column_was_proven_closed() -> None:
    glossary = _glossary()
    markdown = render_overrides_template_markdown(
        build_overrides_template(glossary, today=DAY), glossary
    )

    assert "- 该列取值已被 SQL 证明封闭：是" in markdown
    assert "- 该列取值已被 SQL 证明封闭：未证明" in markdown


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


def test_no_template_flag_writes_no_template(tmp_path: Path) -> None:
    task = _artifacts(MIXED_SQL, tmp_path / "task_a", schema=MIXED_SCHEMA)
    out = tmp_path / "dict"

    assert main(["glossary", "--lineage", str(task / "lineage.json"), "--out", str(out)]) == 0
    assert not list(out.glob("*template*"))
