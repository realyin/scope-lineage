"""Observed facts: what a platform query found, as a confirmation carries it.

Three confirmation targets carry an observation instead of a person's word:

- ``summary.row.observed`` -- the row's uniqueness by the columns the query counted;
- ``column:<c>.observed_values`` -- the values a column holds, with their counts;
- ``input:<db.table>`` -- an input table's uniqueness by some columns, under the reading
  table's own read conditions (``db.table`` as :func:`~.names.bare_table` spells it).

Each value is the matching shape of ``table-semantics/1`` (``observed_grain``,
``observed_values``, ``observed_input`` without ``table``) around one shared
``observation``: the query, the date it ran, the partitions it read and how many rows they
held. ``semantic confirm`` and the confirmed state refuse the same values here, whatever
the document:

- ``rows`` under 1: an empty table has no duplicate key and proves nothing;
- ``unique: yes`` with duplicate keys counted;
- a value off the shape (more than 50 values, a value over 64 characters or with a
  control character, a key the shape does not have -- detail rows above all);
- a value with a contact shape (:func:`~scope_lineage.redaction.redact` would mask it):
  an observation carries counts and codes, never a person's data.

What depends on the document -- an identifier column takes counts only, ``observed_on``
must be one of the column's source columns -- is ``semantic confirm``'s to refuse.
"""

from __future__ import annotations

from ..redaction import redact
from .names import bare_table
from .schema import DOC_FORMAT, packaged_schema

OBSERVED_ROW = "summary.row.observed"
INPUT = "input:"
OBSERVED_VALUES = "observed_values"
IDENTIFIER_CATEGORIES = frozenset({"identifier", "foreign_identifier"})
# A string the old ``summary.row`` target refuses to carry: an observation goes through its
# own target, so the rules above and the replay's precedence apply to it.
USE_OBSERVED_TARGET = "an observation goes through the summary.row.observed target, not summary.row"

_SHAPES = {OBSERVED_ROW: "observed_grain", OBSERVED_VALUES: "observed_values",
           INPUT: "observed_input"}


def observed_kind(target: str) -> str | None:
    """``OBSERVED_ROW``, ``OBSERVED_VALUES`` or ``INPUT`` for an observation target."""
    if target == OBSERVED_ROW:
        return OBSERVED_ROW
    if target.startswith(INPUT):
        return INPUT
    if target.startswith("column:") and target.endswith(f".{OBSERVED_VALUES}"):
        return OBSERVED_VALUES
    return None


def input_table(target: str) -> str:
    """The input table an ``input:`` target names, as ``bare_table`` spells it."""
    return bare_table(target[len(INPUT):])


def input_key(table: str, columns) -> tuple[str, tuple[str, ...]]:
    """One observed input: its table and its columns in lower case and name order."""
    return bare_table(table), tuple(sorted({str(column).lower() for column in columns}))


def partition_text(partition: dict) -> str:
    """The partitions an observation read, in words: 「分区 dt=20261119」, 「分区 dt 20261118、
    20261119」, 「分区 dt 20261116–20261122 共 7 个分区」, or 「全表」."""
    column = partition.get("column")
    if column is None:
        return "全表"
    if "from" in partition:
        count = f" 共 {partition['count']} 个分区" if partition.get("count") else ""
        return f"分区 {column} {partition['from']}–{partition['to']}{count}"
    values = [str(item) for item in partition.get("values") or []]
    if len(values) == 1:
        return f"分区 {column}={values[0]}"
    return f"分区 {column} {'、'.join(values)}" if values else f"分区 {column}"


def observation_text(value: dict) -> str:
    """Where and by which query an observation was made, for a validation message:
    「查询 probe_1，分区 dt=20261119，2026-11-20 执行」."""
    return f"查询 {value['query']}，{partition_text(value['partition'])}，{value['on']} 执行"


def observation_problem(kind: str, value) -> str | None:
    """Why ``value`` cannot be an observation of ``kind``, whatever the document; or None."""
    if not isinstance(value, dict):
        return "value must be an observation object"
    if kind == INPUT and "table" in value:
        return "value must not name table: the target names the input table"
    rows = value.get("rows")
    if not isinstance(rows, int) or isinstance(rows, bool) or rows < 1:
        return "rows must be at least 1: an observation over no rows proves nothing"
    shaped = {**value, "table": "db.table"} if kind == INPUT else value
    errors = _errors(_SHAPES[kind], shaped)
    if errors:
        return f"value does not fit an observation ({errors[0]})"
    if value.get("unique") == "yes" and value.get("duplicate_keys", 0) > 0:
        return "unique: yes, but duplicate_keys counted some"
    texts = [item["value"] for item in value.get("values") or []] + list(value.get("absent") or [])
    if any(redact(text) != text for text in texts):
        return "a value has a contact shape: an observation carries counts and codes, no personal data"
    return None


def _errors(shape: str, value: dict) -> list[str]:
    from jsonschema import Draft7Validator

    schema = packaged_schema(DOC_FORMAT)
    validator = Draft7Validator({"definitions": schema["definitions"],
                                 "$ref": f"#/definitions/{shape}"})
    errors = sorted(validator.iter_errors(value), key=lambda error: [str(part) for part in error.absolute_path])
    return [(".".join(str(part) for part in error.absolute_path) + ": " if error.absolute_path
             else "") + error.message for error in errors]
