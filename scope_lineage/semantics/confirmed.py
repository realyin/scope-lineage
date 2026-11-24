"""What an owner confirmed, read from ``semantic-confirmations/1`` files, apart from any document.

The confirmations files of a run are the source of truth for the facts a person gave:
``semantic confirm`` writes them into the documents, ``semantic validate`` (checks 3 and
4) holds every document to them, and ``semantic facts`` prints them for a writer. All
three read them here, so one document gets one verdict whichever command looks at it.

A path is one confirmations file, or a directory: every ``*.json`` directly in it whose
``doc_format`` is ``semantic-confirmations/1``, in file-name order, its entries in order.
Other JSON documents and other files are passed over; a file that is not readable JSON,
or a confirmations file its schema refuses, is an error -- a half-written confirmations
file must not drop a confirmation unnoticed.

Per table (``bare_table``) the entries build the state ``apply_confirmations`` would leave
in a document, later entries winning:

- ``column:<c>.code_values``: a list replaces the column's confirmed values, one
  ``{value, meaning}`` object is merged into them (a value already confirmed takes the
  new meaning in place);
- ``column:<c>.meaning``: the column's confirmed meaning;
- ``summary.row``: an object is merged into the confirmed row fields, a string is the
  row text (``grain_source`` is the one the entry set: ``semantic confirm`` also turns a
  document's ``inferred`` grain into ``declared`` under a confirmed ``grain_columns`` or
  ``unique``, which is what check 4 asks of the document);
- ``question:<id>``: the answer, with the question's text when the entry carries
  ``asked``;
- the observations (:mod:`.observed`): ``summary.row.observed`` the row's, one
  ``column:<c>.observed_values`` per column, one ``input:<db.table>`` per input table
  (``bare_table``) and set of columns, its value with ``table`` added. They are kept
  apart from the row fields: an observation is no owner's word.

An entry whose value ``apply_confirmations`` would refuse whatever the document (a code
value without a meaning, a row field the schema does not have, an empty answer, a
``summary.row`` object that sets ``observed`` or ``grain_source: observed``, an
observation over no rows) adds nothing. Each fact keeps who confirmed it and when.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .names import bare_table
from .observed import (
    INPUT,
    OBSERVED_ROW,
    OBSERVED_VALUES,
    input_key,
    input_table,
    observation_problem,
)
from .schema import CONFIRMATIONS_FORMAT, DOC_FORMAT, packaged_schema, schema_errors

_COLUMN_TARGET = re.compile(
    r"column:(?P<column>[^.\s]+)\.(?P<slot>meaning|code_values|observed_values)")
# The row fields `semantic facts` prints first, in this order; any other confirmed row
# field follows in name order.
_ROW_ORDER = ("grain_columns", "grain_source", "unique", "text", "note")
# The row's enum values in words for a writer, each followed by the field's own value.
_ROW_VALUES = {
    "unique": {"yes": "是", "no": "否", "unknown": "未知"},
    "grain_source": {"declared": "声明", "inferred": "推断", "proven": "血缘证明"},
}
_ROW_WORDS = {
    "grain_columns": "行粒度列",
    "grain_source": "行粒度来源",
    "unique": "按粒度列唯一",
    "text": "一行是什么",
    "note": "行的说明",
}


class ConfirmationsError(Exception):
    """A confirmations path that cannot be read; ``messages`` say where and why."""

    def __init__(self, messages: list[str]):
        super().__init__("\n".join(messages))
        self.messages = messages


@dataclass(frozen=True)
class Fact:
    """One confirmed value, who confirmed it and when."""

    value: object
    by: str
    date: str
    asked: str | None = None


@dataclass
class TableConfirmed:
    """The confirmed state of one table."""

    row: dict[str, Fact] = field(default_factory=dict)
    meanings: dict[str, Fact] = field(default_factory=dict)
    codes: dict[str, dict[str, Fact]] = field(default_factory=dict)
    answers: dict[str, Fact] = field(default_factory=dict)
    # What platform queries observed, apart from what a person said.
    observed_row: Fact | None = None
    observed_values: dict[str, Fact] = field(default_factory=dict)
    # (input table, its observed columns in lower case and name order) -> the observation
    observed_inputs: dict[tuple[str, tuple[str, ...]], Fact] = field(default_factory=dict)

    def code_meanings(self, column: str) -> dict[str, str]:
        """``value -> meaning`` confirmed on one column, in confirmed order."""
        return {value: str(fact.value) for value, fact in self.codes.get(column, {}).items()}

    def row_fields(self) -> dict[str, object]:
        """The confirmed row fields, ``field -> value``."""
        return {name: fact.value for name, fact in self.row.items()}

    def __bool__(self) -> bool:
        return bool(self.row or self.meanings or self.codes or self.answers
                    or self.observed_row or self.observed_values or self.observed_inputs)


@dataclass
class Confirmations:
    """The confirmations read from one path: the files, their entries, the state per table."""

    path: str
    files: list[str]
    entries: list[dict]
    tables: dict[str, TableConfirmed]

    def for_table(self, table: object) -> TableConfirmed | None:
        return self.tables.get(bare_table(table))


def read_confirmations(path: str | Path) -> Confirmations | None:
    """The confirmations at ``path`` (a file or a directory); None when a directory holds
    no confirmations file. Raises :class:`ConfirmationsError` when ``path`` does not exist
    or a file cannot be read or fits no schema."""
    root = Path(path)
    if root.is_dir():
        candidates = sorted(item for item in root.glob("*.json") if item.is_file())
        explicit = False
    elif root.is_file():
        candidates, explicit = [root], True
    else:
        raise ConfirmationsError([f"--confirmations does not exist: {root}"])
    files, entries, messages = [], [], []
    for file in candidates:
        try:
            document = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            messages.append(f"--confirmations {file}: not a readable JSON document ({error})")
            continue
        if not explicit and not (
            isinstance(document, dict) and document.get("doc_format") == CONFIRMATIONS_FORMAT
        ):
            continue
        errors = schema_errors(document, CONFIRMATIONS_FORMAT)
        if errors:
            messages += [f"--confirmations {file} {error['at'] or '(document)'}: {error['message']}"
                         for error in errors]
            continue
        files.append(str(file))
        entries += document["confirmations"]
    if messages:
        raise ConfirmationsError(messages)
    if not files:
        return None
    return Confirmations(path=str(root), files=files, entries=entries,
                         tables=confirmed_state(entries))


def confirmed_state(entries: list[dict]) -> dict[str, TableConfirmed]:
    """``db.table -> TableConfirmed`` built from ``entries`` in order; later entries win."""
    tables: dict[str, TableConfirmed] = {}
    for entry in entries:
        state = tables.setdefault(bare_table(entry.get("table")), TableConfirmed())
        _take(state, entry)
    return {table: state for table, state in tables.items() if state}


def _take(state: TableConfirmed, entry: dict) -> None:
    target, value = str(entry.get("target")), entry.get("value")
    by, date = str(entry.get("by")), str(entry.get("date"))
    if target.startswith("question:"):
        if isinstance(value, str) and value.strip():
            state.answers[target.split(":", 1)[1]] = Fact(value, by, date, entry.get("asked"))
        return
    if target == "summary.row":
        fields = _row_fields(value)
        for name, item in (fields or {}).items():
            state.row[name] = Fact(item, by, date)
        return
    if target == OBSERVED_ROW:
        if observation_problem(OBSERVED_ROW, value) is None:
            state.observed_row = Fact(value, by, date)
        return
    if target.startswith(INPUT):
        if observation_problem(INPUT, value) is None:
            table = input_table(target)
            state.observed_inputs[input_key(table, value["columns"])] = Fact(
                {"table": table, **value}, by, date)
        return
    match = _COLUMN_TARGET.fullmatch(target)
    if match is None:
        return
    column = match["column"]
    if match["slot"] == "meaning":
        if isinstance(value, str) and value.strip():
            state.meanings[column] = Fact(value, by, date)
        return
    if match["slot"] == OBSERVED_VALUES:
        if observation_problem(OBSERVED_VALUES, value) is None:
            state.observed_values[column] = Fact(value, by, date)
        return
    items = value if isinstance(value, list) else [value] if isinstance(value, dict) else None
    if not items or not all(_is_code(item) for item in items):
        return
    if isinstance(value, list):
        state.codes[column] = {}
    codes = state.codes.setdefault(column, {})
    for item in items:
        codes[item["value"]] = Fact(item["meaning"], by, date)


def _is_code(item) -> bool:
    return (isinstance(item, dict) and isinstance(item.get("value"), str)
            and isinstance(item.get("meaning"), str) and bool(item["meaning"].strip()))


def _row_fields(value) -> dict | None:
    """The row fields a ``summary.row`` value sets, or None when ``apply_confirmations``
    would refuse it: a string is the text; an object must fit the row's schema, and may not
    set ``observed`` or ``grain_source: observed`` (an observation has its own target)."""
    if isinstance(value, str):
        return {"text": value} if value.strip() else None
    if not isinstance(value, dict) or not value:
        return None
    if "observed" in value or value.get("grain_source") == "observed":
        return None
    schema = packaged_schema(DOC_FORMAT)
    row = schema["definitions"]["row"]
    fields_schema = {
        "definitions": schema["definitions"], "type": "object",
        "properties": row["properties"], "additionalProperties": False,
    }
    from jsonschema import Draft7Validator

    if any(True for _ in Draft7Validator(fields_schema).iter_errors(value)):
        return None
    return dict(value)


# ------------------------------------------------------------------ facts text


def render_facts(confirmations: Confirmations | None, tables: list[str], *,
                 grains: dict[str, list[str]] | None = None) -> str:
    """The confirmed facts of each table as plain lines, the text a writing prompt's
    ``{FACTS}`` takes.

    Per table a header line, then one fact per line -- the row fields, the column
    meanings, the code values, the answered questions that carry ``asked`` (one without
    it cannot say which question it answers, and is left out) -- each ending with who confirmed
    it and when (``unique`` and ``grain_source`` in words, the field's value after them); ``无`` when the table has none. Line breaks inside a confirmed text are
    folded to spaces, so one line is always one fact. When none of the tables has a fact
    the whole text is ``无``: the prompt reads as it did before there were confirmations.

    The observations follow, one line each (:func:`_observed_lines`): the row's, then each
    column's, then each input table's. ``grains`` (``db.table -> grain columns``, read from
    the documents) lets the row's line say when the columns the query counted are not the
    document's grain columns; it changes nothing else.
    """
    lines: list[str] = []
    found = False
    for table in tables:
        name = bare_table(table)
        state = confirmations.for_table(name) if confirmations else None
        lines.append(f"表 {name} 已确认的事实：")
        grain = {bare_table(key): value for key, value in (grains or {}).items()}.get(name)
        facts = _fact_lines(state) + _observed_lines(state, grain) if state else []
        found = found or bool(facts)
        lines += facts or ["无"]
    return "\n".join(lines) + "\n" if found else "无\n"


def _fact_lines(state: TableConfirmed) -> list[str]:
    lines = []
    names = [name for name in _ROW_ORDER if name in state.row]
    names += sorted(name for name in state.row if name not in _ROW_ORDER)
    for name in names:
        fact = state.row[name]
        word = _ROW_WORDS.get(name, f"行字段 {name}")
        lines.append(f"- {word}：{_row_value(name, fact.value)}{_by(fact)}")
    for column, fact in state.meanings.items():
        lines.append(f"- 列 {column} 的含义：{_one_line(fact.value)}{_by(fact)}")
    for column, codes in state.codes.items():
        for value, fact in codes.items():
            lines.append(f"- 列 {column} 的码值「{_one_line(value)}」：{_one_line(fact.value)}"
                         f"{_by(fact)}")
    # An answer without the question's text is left out: after a rewrite its id may name
    # another question, and a writer told "qN: answer" would pin it on the wrong one.
    for question_id in sorted(state.answers, key=_question_order):
        fact = state.answers[question_id]
        if not fact.asked:
            continue
        lines.append(f"- 问题 {question_id}（问：{_one_line(fact.asked)}）的回答："
                     f"{_one_line(fact.value)}{_by(fact)}")
    return lines


def _observed_lines(state: TableConfirmed, grain: list[str] | None) -> list[str]:
    """One line per observation, each 「观测：<对象>在分区 … 内（查询 …，… 执行，N 行）…」.

    An observation is no definition, so no line says 「唯一」: a row or an input table is
    "counted by (columns) without a duplicate", within the partitions read; a column's
    values come with their counts, and the line says they are no code list."""
    lines = []
    if state.observed_row:
        fact = state.observed_row
        value = fact.value
        counted = list(value["grain_columns"])
        text = f"本表{_where(value)}{_counted(value, counted)}"
        if grain is not None and set(grain) != set(counted):
            text += f"；计数列 {_columns(counted)} 不是文档的行粒度列 {_columns(grain)}"
        lines.append(f"- 观测：{text}；只说明这些分区，不是定义{_noted(fact)}")
    for column, fact in state.observed_values.items():
        lines.append(f"- 观测：列 {column} {_where(fact.value)}{_values_text(fact.value)}"
                     f"；观测不给含义，不是码值表{_noted(fact)}")
    for fact in state.observed_inputs.values():
        value = fact.value
        if value["unique"] == "yes":
            effect = "按这几列关联它时在该分区内不放大，别的分区没观测"
        else:
            effect = "按这几列关联它时会放大行数"
        lines.append(f"- 观测：输入表 {value['table']} {_where(value)}"
                     f"{_counted(value, value['columns'])}；{effect}{_noted(fact)}")
    return lines


def _where(value: dict) -> str:
    """「在分区 … 内（查询 …，… 执行，N 行）」: where and by which query an observation was made."""
    partition = value["partition"]
    column = partition.get("column")
    if column is None:
        place = "在全表内"
    elif "from" in partition:
        count = f" 共 {partition['count']} 个分区" if partition.get("count") else ""
        place = f"在分区 {column} {partition['from']}–{partition['to']}{count}内"
    else:
        values = [str(item) for item in partition.get("values") or []]
        place = (f"在分区 {column}={values[0]} 内" if len(values) == 1
                 else f"在分区 {column} {'、'.join(values)} 内" if values
                 else f"在分区 {column} 内")
    parts = [f"查询 {_one_line(value['query'])}"]
    if value.get("requested"):
        parts.append(f"原定 {_one_line(value['requested'])}，回退到最近可用分区")
    if value.get("filter"):
        parts.append(f"条件 {_one_line(value['filter'])}")
    parts.append(f"{value['on']} 执行")
    parts.append(f"{value['rows']} 行")
    if value.get("observed_on"):
        parts.append(f"取自 {_one_line(value['observed_on'])}")
    return f"{place}（{'，'.join(parts)}）"


def _counted(value: dict, columns) -> str:
    """「按 (a, b) 计数无重复（N 个键）」, or with duplicates; how the partitions were counted
    when there were several."""
    keys = value.get("keys")
    if value["unique"] == "yes":
        text = f"按 {_columns(columns)} 计数无重复" + (f"（{keys} 个键）" if keys is not None else "")
    else:
        duplicates = value.get("duplicate_keys")
        counts = [f"{keys} 个键里" if keys is not None else None,
                  f"{duplicates} 个重复" if duplicates is not None else None]
        detail = " ".join(item for item in counts if item)
        text = f"按 {_columns(columns)} 计数有重复" + (f"（{detail}）" if detail else "")
    partition = value["partition"]
    several = "from" in partition or len(partition.get("values") or []) > 1
    if several:
        text += ("，每个分区内分别计数" if value["within"] == "each_partition"
                 else "，所有观测分区合起来计数")
    return text


def _values_text(value: dict) -> str:
    """The values a column was seen to hold, with counts; the values not seen; the counts."""
    parts = []
    items = value.get("values") or []
    if items:
        seen = "、".join(f"{_one_line(item['value'])}（{item['count']} 行）" for item in items)
        parts.append(f"出现 {seen}，{'已列全' if value['complete'] else '未列全'}")
    absent = value.get("absent") or []
    if absent:
        parts.append(f"没有出现 {'、'.join(_one_line(item) for item in absent)}")
    counts = [f"去重 {value['distinct']} 个" if value.get("distinct") is not None else "",
              f"空值 {value['nulls']} 个" if value.get("nulls") is not None else ""]
    counts = "、".join(item for item in counts if item)
    if not items:
        parts.append(f"只给计数：{counts}" if counts else "只给计数")
    elif counts:
        parts.append(counts)
    return "；".join(parts)


def _columns(columns) -> str:
    return f"({', '.join(str(column) for column in columns)})"


def _noted(fact: Fact) -> str:
    return f"（{_one_line(fact.by)} 于 {fact.date} 记录）"


def _question_order(question_id: str) -> tuple:
    digits = question_id.lstrip("q")
    return (0, int(digits), question_id) if digits.isdigit() else (1, 0, question_id)


def _row_value(name: str, value) -> str:
    """A row field's value as a writer reads it: an enum in words, with the field's value."""
    words = _ROW_VALUES.get(name, {})
    if isinstance(value, str) and value in words:
        return f"{words[value]}（{name}: {value}）"
    return _value_text(value)


def _value_text(value) -> str:
    if isinstance(value, list):
        return "、".join(_one_line(item) for item in value) or "（无）"
    if isinstance(value, str):
        return _one_line(value)
    return _one_line(json.dumps(value, ensure_ascii=False))


def _one_line(text) -> str:
    return " ".join(str(text if text is not None else "").split())


def _by(fact: Fact) -> str:
    return f"（{_one_line(fact.by)} 于 {fact.date} 确认）"
