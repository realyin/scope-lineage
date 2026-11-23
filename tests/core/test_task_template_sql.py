"""A task JSON may carry its scheduling template and parameter list beside the run instance.

``meta.sql`` is one run of the task: every scheduler parameter is already replaced, so a
value the scheduler filled in reads like a constant the author wrote. ``meta.task_sql``
keeps the ``${name}`` parameters and ``meta.task_parameters`` says what each one is. When
the template is there, ``parse`` reads it; only a parameter the parser finds in a table id
is bound -- token by token, never in a string or a comment -- and the binding is kept only
when every such table is still there under its bound name and the parse got no worse.
Everything else is reported as it was. ``parse --instance-sql`` keeps reading ``meta.sql``.
All names are synthetic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.cli import _load_task_input, main

TEMPLATE = (
    "-- writes cat.${db}.out\n"
    "INSERT OVERWRITE TABLE cat.${db}.out PARTITION (dt = '${dt}')\n"
    "SELECT s.id, '${db}' AS origin FROM ${db}.src s WHERE s.biz_day = '${dt}'"
)
INSTANCE = TEMPLATE.replace("${db}", "demo_mart").replace("${dt}", "20260101")
PARAMETERS = [
    {"paramKey": "dt", "paramValue": "[yyyyMMdd-1D]"},
    {"paramKey": "db", "paramValue": "demo_mart"},
]


def _write(directory: Path, meta: dict, name: str = "t.json") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps({"meta": {"task_name": "t", **meta}}), encoding="utf-8")
    return path


def _parse(tmp_path: Path, meta: dict, *flags: str, out: str = "out") -> dict:
    tasks = tmp_path / f"tasks_{out}"
    _write(tasks, meta)
    target = tmp_path / out
    assert main(["parse", "--input-dir", str(tasks), "--out", str(target), "--allow-partial", *flags]) == 0
    [lineage] = target.rglob("lineage.json")
    return {
        "lineage": json.loads(lineage.read_text(encoding="utf-8")),
        "diagnostics": json.loads((lineage.parent / "diagnostics.json").read_text(encoding="utf-8")),
        "dir": target,
    }


def _tables(lineage: dict) -> set[str]:
    found: set[str] = set()
    for statement in lineage["statement_lineage"].values():
        found.add(statement["target_table"])
        found.update(statement.get("source_tables") or [])
    return found


def _warning(diagnostics: dict, kind: str) -> list[dict]:
    return [w for w in diagnostics["warnings"] if w["type"] == kind]


def _template(sql: str, parameters, *flags: str, tmp_path: Path, out: str = "out") -> dict:
    return _parse(tmp_path, {"sql": INSTANCE, "task_sql": sql, "task_parameters": parameters},
                  *flags, out=out)


# ------------------------------------------------------------------ loading


def test_the_template_and_its_parameters_are_read_from_meta(tmp_path) -> None:
    path = _write(tmp_path, {"sql": INSTANCE, "task_sql": TEMPLATE, "task_parameters": [
        {"name": "dt", "value": "[yyyyMMdd-1D]", "description": "the business day"},
        {"paramKey": "db", "paramValue": "demo_mart"},
    ]})

    task = _load_task_input(path, tmp_path, None)

    assert task.sql == INSTANCE
    assert task.template_sql == TEMPLATE
    assert task.parameters == {"dt": "[yyyyMMdd-1D]", "db": "demo_mart"}
    assert task.parameter_descriptions == {"dt": "the business day"}


def test_an_object_of_parameters_is_read_too(tmp_path) -> None:
    path = _write(tmp_path, {"sql": INSTANCE, "task_sql": TEMPLATE,
                             "task_parameters": {"dt": "[yyyyMMdd-1D]", "db": "demo_mart"}})

    assert _load_task_input(path, tmp_path, None).parameters == {
        "dt": "[yyyyMMdd-1D]", "db": "demo_mart"}


def test_without_a_template_nothing_new_is_read(tmp_path) -> None:
    path = _write(tmp_path, {"sql": INSTANCE, "task_parameters": "not even a list"})

    task = _load_task_input(path, tmp_path, None)

    assert (task.template_sql, task.parameters, task.parameter_descriptions) == (None, {}, {})


def test_a_task_json_without_meta_does_not_read_the_new_fields(tmp_path) -> None:
    path = tmp_path / "t.json"
    path.write_text(json.dumps({"task_name": "t", "sql": INSTANCE, "task_sql": TEMPLATE,
                                "task_parameters": PARAMETERS}), encoding="utf-8")

    task = _load_task_input(path, tmp_path, None)

    assert task.template_sql is None and task.parameters == {}


@pytest.mark.parametrize(("meta", "said"), [
    ({"task_sql": 7}, "meta.task_sql"),
    ({"task_sql": TEMPLATE, "task_parameters": "dt=1"}, "meta.task_parameters"),
    ({"task_sql": TEMPLATE, "task_parameters": [["dt", "1"]]}, "meta.task_parameters"),
    ({"task_sql": TEMPLATE, "task_parameters": [{"value": "1"}]}, "meta.task_parameters"),
    ({"task_sql": TEMPLATE, "task_parameters": [{"name": "dt", "value": 1}]}, "meta.task_parameters"),
    ({"task_sql": TEMPLATE, "task_parameters": {"dt": ["1"]}}, "meta.task_parameters"),
    ({"task_sql": TEMPLATE, "task_parameters": [
        {"name": "dt", "value": "[a]"}, {"paramKey": "dt", "paramValue": "[b]"}]}, "dt"),
])
def test_a_malformed_template_or_parameter_list_is_an_input_error(tmp_path, meta, said) -> None:
    path = _write(tmp_path, {"sql": INSTANCE, **meta})

    with pytest.raises(ValueError, match=said):
        _load_task_input(path, tmp_path, None)


def test_the_same_parameter_twice_with_one_definition_is_accepted(tmp_path) -> None:
    path = _write(tmp_path, {"sql": INSTANCE, "task_sql": TEMPLATE, "task_parameters": [
        {"name": "dt", "value": "[a]"}, {"paramKey": "dt", "paramValue": "[a]"}]})

    assert _load_task_input(path, tmp_path, None).parameters == {"dt": "[a]"}


# ------------------------------------------------------------------ binding


def test_the_template_is_parsed_and_its_table_name_parameter_bound(tmp_path) -> None:
    parsed = _template(TEMPLATE, PARAMETERS, tmp_path=tmp_path)

    assert _tables(parsed["lineage"]) == {"cat.demo_mart.out", "demo_mart.src"}
    assert _warning(parsed["diagnostics"], "input_incomplete") == []
    [disclosure] = _warning(parsed["diagnostics"], "task_template_sql_used")
    assert disclosure["bound_parameters"] == {"db": 2}
    # The value parameter stays a parameter: the template, not the instance, was read.
    statement = parsed["lineage"]["statement_lineage"]["stmt:001"]
    assert "${dt}" in json.dumps(statement["target_partition_spec"])


def test_the_same_parameter_in_a_string_or_a_comment_is_left_alone(tmp_path) -> None:
    parsed = _template(TEMPLATE, PARAMETERS, tmp_path=tmp_path)
    text = json.dumps(parsed["lineage"], ensure_ascii=False)

    assert "'${db}'" in text  # the string literal
    assert "cat.${db}.out" in text  # the comment
    [disclosure] = _warning(parsed["diagnostics"], "task_template_sql_used")
    assert disclosure["bound_parameters"] == {"db": 2}


@pytest.mark.parametrize(("sql", "tables", "places"), [
    ("INSERT OVERWRITE TABLE `${db}`.out SELECT id FROM `${db}.src`",
     {"demo_mart.out", "demo_mart.src"}, 2),
    ("INSERT OVERWRITE TABLE ${db}.out_${db} SELECT id FROM ${db}.src",
     {"demo_mart.out_demo_mart", "demo_mart.src"}, 3),
])
def test_a_quoted_or_spliced_table_name_parameter_is_bound(tmp_path, sql, tables, places) -> None:
    parsed = _template(sql, PARAMETERS, tmp_path=tmp_path)

    assert _tables(parsed["lineage"]) == tables
    assert _warning(parsed["diagnostics"], "input_incomplete") == []
    [disclosure] = _warning(parsed["diagnostics"], "task_template_sql_used")
    assert disclosure["bound_parameters"] == {"db": places}


@pytest.mark.parametrize("value", ["demo.mart", "2026", None])
def test_a_value_that_is_no_plain_identifier_is_not_bound(tmp_path, value) -> None:
    parameters = [{"name": "dt", "value": "[x]"}]
    if value is not None:
        parameters.append({"name": "db", "value": value})

    parsed = _template(TEMPLATE, parameters, tmp_path=tmp_path)

    assert "cat.${db}.out" in _tables(parsed["lineage"])
    assert len(_warning(parsed["diagnostics"], "input_incomplete")) == 1
    [disclosure] = _warning(parsed["diagnostics"], "task_template_sql_used")
    assert disclosure["bound_parameters"] == {}


def test_parameter_names_are_case_sensitive(tmp_path) -> None:
    parsed = _template(TEMPLATE, {"DB": "demo_mart"}, tmp_path=tmp_path)

    assert "cat.${db}.out" in _tables(parsed["lineage"])


@pytest.mark.parametrize("sql", [
    "INSERT OVERWRITE TABLE db.out SELECT t.${col} AS v FROM db.src t",
    "INSERT OVERWRITE TABLE db.out SELECT extract(day from ${d}) AS v FROM db.src t",
    "INSERT OVERWRITE TABLE db.out SELECT t.a AS v FROM db.src t WHERE t.a is distinct from ${v}",
])
def test_a_parameter_in_no_table_id_is_never_bound(tmp_path, sql) -> None:
    parameters = {"col": "a", "d": "a", "v": "a"}

    template = _template(sql, parameters, tmp_path=tmp_path, out="template")
    instance = _parse(tmp_path, {"sql": sql}, out="plain")

    [disclosure] = _warning(template["diagnostics"], "task_template_sql_used")
    assert disclosure["bound_parameters"] == {}
    assert template["lineage"]["statement_lineage"] == instance["lineage"]["statement_lineage"]


@pytest.mark.parametrize("value", ["select", "from"])
def test_a_reserved_word_value_is_undone(tmp_path, value) -> None:
    sql = "INSERT OVERWRITE TABLE db.out SELECT s.id FROM ${db}.src s JOIN db.other o ON s.id = o.id"

    parsed = _template(sql, {"db": value}, tmp_path=tmp_path)

    assert "${db}.src" in _tables(parsed["lineage"])
    assert len(_warning(parsed["diagnostics"], "input_incomplete")) == 1
    [disclosure] = _warning(parsed["diagnostics"], "task_template_sql_used")
    assert disclosure["bound_parameters"] == {}


# ------------------------------------------------------------------ what stays as it was


def _files(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*")) if path.is_file()}


def test_the_instance_switch_parses_exactly_what_a_task_json_without_a_template_gives(tmp_path) -> None:
    switched = _template(TEMPLATE, PARAMETERS, "--instance-sql", tmp_path=tmp_path, out="switched")
    plain = _parse(tmp_path, {"sql": INSTANCE}, out="plain")

    assert _files(switched["dir"]) == _files(plain["dir"])


def test_parameters_without_a_template_change_nothing(tmp_path) -> None:
    with_list = _parse(tmp_path, {"sql": INSTANCE, "task_parameters": PARAMETERS}, out="listed")
    plain = _parse(tmp_path, {"sql": INSTANCE}, out="plain")

    assert _files(with_list["dir"]) == _files(plain["dir"])


def test_the_new_fields_do_not_reach_task_meta(tmp_path) -> None:
    parsed = _template(TEMPLATE, PARAMETERS, tmp_path=tmp_path)

    assert not {"task_sql", "task_parameters"} & set(parsed["lineage"].get("task_meta") or {})
