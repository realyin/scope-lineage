"""A platform result pasted back for one ``question-probes/1`` item: a draft observation
confirmation, an evidence reference for an answer, or the reason there is none.

The tool never runs a query. The person who ran one hands back the result as one JSON
object, the only form read (``read_result``)::

    {"sql_id", "status", "run_on", "bizdate", "sql_executed", "columns", "rows", "note"}

(``elapsed_sec`` may be there too), ``rows`` an array of arrays, cells as the platform
prints them: strings, ``null`` (or the text ``null``) for SQL NULL.

``draft_observation`` turns a result into the confirmation entry for the item's ``lands``
target -- never stored by this module; a person confirms it -- only when every check holds:

- ``sql_id`` is the item's id and ``status`` is ``ok``;
- ``sql_executed`` is the item's SQL with each ``${name}`` placeholder replaced by one value
  (whitespace and a trailing ``;`` aside), the same value wherever the placeholder repeats;
- ``columns`` are exactly the query's own top-level output columns, in order -- so the
  output rules ``semantic probes check`` applied to the query hold for the result -- and
  the fixed columns of the item's shape: ``rows, keys, duplicate_keys`` (one row) or
  ``value, cnt`` (at most 51 rows);
- a count is a non-negative integer (a null count -- an empty table's ``SUM`` -- proves
  nothing); for uniqueness ``rows`` is at least 1, ``duplicate_keys <= keys <= rows`` and
  ``duplicate_keys`` is 0 exactly when ``rows == keys``; a value set has no value twice and
  its counts add up to at least 1;
- no cell other than an integer has a contact shape (``redaction.redact`` would change it);
- the value passes ``observed.observation_problem``.

The draft reads the partition from the item's ``partitions`` entry for the table counted
(the input of an ``input:`` target, the source table a value set reads through, otherwise
the item's table) with the placeholders put in as ``sql_executed`` has them; when the
result's ``bizdate`` is not the ``${bizdate}`` the query ran with, the partition fell back
and ``requested`` names the one first asked for (refused when the entry's ``fallback`` is
``none``). A uniqueness draft counts within each partition (all observed rows for a query
without a partition), ``unique`` is ``yes`` exactly when no key has duplicates, and its key
columns are read from the query's ``keys`` expression. A value set is ``complete`` with
fewer than 51 rows; the 51st row only says it is not, and a NULL value counts ``nulls``.
The item's ``filter`` and ``engine`` are carried. The entry's ``evidence`` is the
reference ``{probe, partition, on, sha256}`` -- the probes file's sha256 --, never rows.

``evidence_reference`` holds a result of an item that lands nothing to the same checks
short of the shapes, and gives only that reference.
"""

from __future__ import annotations

import json
import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, SqlglotError
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import build_scope

from ..redaction import redact
from .names import bare_table
from .observed import INPUT, OBSERVED_ROW, OBSERVED_VALUES, observation_problem, observed_kind
from .probe_forms import base_column, classify, output_names, projection

RESULT_KEYS = ("sql_id", "status", "run_on", "bizdate", "sql_executed", "columns", "rows", "note")
OPTIONAL_KEYS = ("elapsed_sec",)
UNIQUENESS = ("rows", "keys", "duplicate_keys")
VALUE_SET = ("value", "cnt")
VALUE_SET_ROWS = 51
MAX_VALUES = 50
BIZDATE = "${bizdate}"
_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
# A placeholder's value as the query ran with it: a date, a number, a name -- never quotes,
# spaces or anything else that could change what the query says.
_VALUE = r"[A-Za-z0-9_:./-]+"
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_INTEGER = re.compile(r"[0-9]+")


class ResultRefused(ValueError):
    """Pasted text that is not a platform result object."""


def read_result(text: str) -> dict:
    """The result object of a pasted text; ``ResultRefused`` when it is not one."""
    try:
        result = json.loads(text)
    except ValueError as error:
        raise ResultRefused(f"not a JSON result ({error}); paste the result JSON object as "
                            "it came back") from None
    if not isinstance(result, dict):
        raise ResultRefused("not a result object: paste the one JSON object a query's result is")
    problem = _shape_problem(result)
    if problem:
        raise ResultRefused(problem)
    return result


def _shape_problem(result: dict) -> str | None:
    keys = set(result) - set(OPTIONAL_KEYS)
    if keys != set(RESULT_KEYS):
        return (f"a result has the keys {', '.join(RESULT_KEYS)} (and optionally "
                f"{', '.join(OPTIONAL_KEYS)}), not {', '.join(sorted(result))}")
    for name in ("sql_id", "status", "bizdate", "sql_executed"):
        if not isinstance(result[name], str):
            return f"{name} is a string"
    if not isinstance(result["run_on"], str) or not _DATE.fullmatch(result["run_on"]):
        return "run_on is the date the query ran, YYYY-MM-DD"
    if result["note"] is not None and not isinstance(result["note"], str):
        return "note is a string"
    columns = result["columns"]
    if not isinstance(columns, list) or not all(isinstance(c, str) and c for c in columns):
        return "columns is a list of column names"
    rows = result["rows"]
    if not isinstance(rows, list) or not all(isinstance(row, list) for row in rows):
        return "rows is an array of arrays"
    if any(len(row) != len(columns) for row in rows):
        return f"a row has not {len(columns)} cells, one per column"
    return None


def draft_observation(item: dict, result: dict, sha256: str, by: str,
                      date: str) -> tuple[dict | None, str | None]:
    """``(entry, None)``: the observation confirmation a person may confirm; or ``(None,
    reason)``."""
    if not item.get("lands"):
        return None, ("the item lands nothing: its result can only be evidence for an answer "
                      "(attach it to a sentence)")
    checked = _checked(item, result)
    if isinstance(checked, str):
        return None, checked
    tree, values = checked
    lands = item["lands"]
    kind = observed_kind(lands)
    wanted = UNIQUENESS if kind in (OBSERVED_ROW, INPUT) else VALUE_SET
    columns = [str(c).lower() for c in result["columns"]]
    if columns != list(wanted):
        return None, (f"the result's columns are {', '.join(result['columns'])}; {lands} "
                      f"takes exactly {', '.join(wanted)}")
    reading = _reading(tree, kind)
    if isinstance(reading, str):
        return None, reading
    if kind == OBSERVED_VALUES:
        counted = reading[0]  # the item's table, or the source table it reads through
    else:
        counted = bare_table(lands[len(INPUT):]) if kind == INPUT else bare_table(item["table"])
    place = _partition(item, counted, values, result["bizdate"])
    if isinstance(place, str):
        return None, place
    partition, requested = place
    observation = {"query": item["id"], "on": result["run_on"]}
    body = (_uniqueness(result["rows"], reading, kind, partition) if kind != OBSERVED_VALUES
            else _value_set(result["rows"], reading, item))
    if isinstance(body, str):
        return None, body
    rows, shaped = body
    observation.update(rows=rows, partition=partition)
    if requested is not None:
        observation["requested"] = requested
    for key in ("filter", "engine"):
        if item.get(key):
            observation[key] = item[key]
    observation.update(shaped)
    problem = observation_problem(kind, observation)
    if problem:
        return None, problem
    entry = {"table": bare_table(item["table"]), "target": lands, "value": observation,
             "by": by, "date": date,
             "evidence": {"probe": item["id"], "partition": partition, "on": result["run_on"],
                          "sha256": sha256}}
    return entry, None


def evidence_reference(item: dict, result: dict, sha256: str) -> tuple[dict | None, str | None]:
    """``(reference, None)`` for an item's result attached to an answer as evidence --
    ``{probe, partition, on, sha256}`` --, or ``(None, reason)``."""
    checked = _checked(item, result)
    if isinstance(checked, str):
        return None, checked
    _, values = checked
    entries = item.get("partitions") or []
    table = bare_table(item["table"])
    entry = next((e for e in entries if bare_table(e["table"]) == table),
                 entries[0] if entries else None)
    counted = bare_table(entry["table"]) if entry else table
    place = _partition(item, counted, values, result["bizdate"])
    if isinstance(place, str):
        return None, place
    return {"probe": item["id"], "partition": place[0], "on": result["run_on"],
            "sha256": sha256}, None


# ------------------------------------------------------------------ the common checks


def _checked(item: dict, result: dict):
    """``(the executed query's tree, {placeholder: value})``, or the reason it is refused."""
    problem = _shape_problem(result)
    if problem:
        return problem
    if result["sql_id"] != item.get("id"):
        return f"sql_id is {result['sql_id']!r}, not this item's id {item.get('id')!r}"
    if result["status"] != "ok":
        return f"status is {result['status']!r}: only an ok result says anything"
    if item.get("class") != "data" or not item.get("sql"):
        return "the item has no query"
    values = _placeholders(item["sql"], result["sql_executed"])
    if values is None:
        return ("sql_executed is not this item's SQL with its placeholders filled in: the query "
                "that ran is not the one checked")
    for row in result["rows"]:
        for cell in row:
            if isinstance(cell, str) and not _INTEGER.fullmatch(cell) and redact(cell) != cell:
                return ("a cell has a contact shape: a result carries counts and codes, no "
                        "personal data")
    try:
        statements = [s for s in sqlglot.parse(_normal(result["sql_executed"]), read="spark")
                      if s is not None]
    except SqlglotError as error:
        return f"sql_executed does not parse ({str(error).strip().splitlines()[0]})"
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        return "sql_executed is not one SELECT"
    tree = statements[0]
    names = output_names(tree)
    if [str(c).lower() for c in result["columns"]] != names:
        return (f"the result's columns are {', '.join(result['columns'])}; the query outputs "
                f"{', '.join(names)}")
    return tree, values


def _normal(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip().rstrip(";").strip()


def _placeholders(template: str, executed: str) -> dict[str, str] | None:
    """``{"${name}": value}`` when ``executed`` is ``template`` with its placeholders
    filled in, whitespace aside; None otherwise."""
    pattern, seen, position = [], set(), 0
    text = _normal(template)
    for match in _PLACEHOLDER.finditer(text):
        pattern.append(re.escape(text[position:match.start()]))
        name = match.group(1)
        pattern.append(f"(?P={name})" if name in seen else f"(?P<{name}>{_VALUE})")
        seen.add(name)
        position = match.end()
    pattern.append(re.escape(text[position:]))
    # the template's own spaces match any run of whitespace in what ran
    regex = "".join(pattern).replace(r"\ ", r"\s+")
    found = re.fullmatch(regex, _normal(executed))
    if found is None:
        return None
    return {f"${{{name}}}": value for name, value in found.groupdict().items()}


def _partition(item: dict, table: str, values: dict, bizdate: str):
    """``(observed partition, requested or None)`` of the table counted, or the reason."""
    entry = next((e for e in item.get("partitions") or [] if bare_table(e["table"]) == table),
                 None)
    if entry is None:
        if item.get("full_scan"):
            return {"column": None}, None
        return f"partitions names no partition of {table}, and the item is no full scan"
    filled = dict(values)
    filled.setdefault(BIZDATE, bizdate)
    read = _fill(entry["want"], filled)
    if read is None:
        return f"the partition wanted ({entry['want']}) has a placeholder the query does not fill"
    requested = None
    if BIZDATE in values and bizdate and values[BIZDATE] != bizdate:
        if entry["fallback"] != "latest_available":
            return (f"the query read {read}, not the batch date {bizdate}, and the item's "
                    "fallback is none")
        requested = _fill(entry["want"], {**values, BIZDATE: bizdate})
    return {"column": entry["column"], "values": [read]}, requested


def _fill(text: str, values: dict) -> str | None:
    def put(match):
        return values.get(match.group(0), match.group(0))
    filled = _PLACEHOLDER.sub(put, text)
    return None if _PLACEHOLDER.search(filled) else filled


# ------------------------------------------------------------------ the two shapes


def _reading(tree: exp.Select, kind: str):
    """The key columns a uniqueness query counts, or ``(table, column)`` a value set reads;
    or the reason they cannot be read."""
    tree = tree.copy()
    for table in tree.find_all(exp.Table):
        table.set("catalog", None)
    try:
        tree = qualify(tree, dialect="spark", validate_qualify_columns=False,
                       quote_identifiers=False)
        root = build_scope(tree)
    except (OptimizeError, SqlglotError) as error:
        return f"the query's columns cannot be read ({str(error).strip().splitlines()[0]})"
    if root is None:
        return "the query's columns cannot be read"
    select = root.expression
    if kind == OBSERVED_VALUES:
        value = projection(select, "value")
        base = base_column(value, root) if isinstance(value, exp.Column) else None
        return base or "the value column's source cannot be read from the query"
    keys = classify(projection(select, "keys"), root)
    if keys is None or keys.kind != "keys" or not keys.keys:
        return "the key columns the query counts cannot be read from its keys expression"
    return keys.keys


def _count(cell, name: str):
    if cell is None or cell == "null":
        return None, f"{name} is null: an empty table's count proves nothing"
    if isinstance(cell, bool):
        return None, f"{name} is not an integer"
    if isinstance(cell, int):
        number = cell
    elif isinstance(cell, str) and re.fullmatch(r"-?[0-9]+", cell.strip()):
        number = int(cell.strip())
    else:
        return None, f"{name} is not an integer ({cell!r})"
    if number < 0:
        return None, f"{name} is negative"
    return number, None


def _uniqueness(rows: list, keys: tuple, kind: str, partition: dict):
    if len(rows) != 1:
        return f"a uniqueness count returns one row, not {len(rows)}"
    counts = {}
    for name, cell in zip(UNIQUENESS, rows[0]):
        number, problem = _count(cell, name)
        if problem:
            return problem
        counts[name] = number
    total, distinct, duplicates = counts["rows"], counts["keys"], counts["duplicate_keys"]
    if total < 1:
        return "rows must be at least 1: an observation over no rows proves nothing"
    if distinct > total:
        return f"keys ({distinct}) is more than rows ({total})"
    if duplicates > distinct:
        return f"duplicate_keys ({duplicates}) is more than keys ({distinct})"
    if (duplicates == 0) != (total == distinct):
        return (f"duplicate_keys ({duplicates}) does not fit rows ({total}) and keys "
                f"({distinct}): no key repeats exactly when rows equals keys")
    columns = "grain_columns" if kind == OBSERVED_ROW else "columns"
    within = "all_observed" if partition.get("column") is None else "each_partition"
    return total, {columns: list(keys), "unique": "yes" if duplicates == 0 else "no",
                   "within": within, "keys": distinct, "duplicate_keys": duplicates}


def _value_set(rows: list, source: tuple[str, str], item: dict):
    if len(rows) > VALUE_SET_ROWS:
        return f"a value set returns at most {VALUE_SET_ROWS} rows, not {len(rows)}"
    if not rows:
        return "the result has no row: an observation over no rows proves nothing"
    seen, values, nulls, total = set(), [], None, 0
    for at, (value, cell) in enumerate(rows):
        count, problem = _count(cell, "cnt")
        if problem:
            return problem
        null = value is None or value == "null"
        key = None if null else (str(value) if isinstance(value, (str, int)) and not isinstance(
            value, bool) else ...)
        if key is ...:
            return f"a value is not text ({value!r})"
        if key in seen:
            return f"the value {'NULL' if null else key!r} is listed twice"
        seen.add(key)
        total += count
        if at >= MAX_VALUES:
            continue  # the 51st row only says the list is not complete
        if null:
            nulls = count
        else:
            values.append({"value": key, "count": count})
    shaped = {"values": values, "complete": len(rows) < VALUE_SET_ROWS}
    if nulls is not None:
        shaped["nulls"] = nulls
    table, column = source
    if table != bare_table(item["table"]):
        shaped["observed_on"] = f"{table}.{column}"
    return total, shaped
