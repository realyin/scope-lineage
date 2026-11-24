"""``semantic probes check``: static checks of a ``question-probes/1`` file.

A probes file holds, per open question of a table, its sub-questions; each sub-question
the data can answer (``class: data``) carries one SELECT a person runs on the platform.
Nothing here runs SQL or connects anywhere: every check reads the query's syntax tree
(sqlglot, Spark dialect), the material packets and, when given, the table-semantics
documents.

- C1 the query parses, with each ``${name}`` placeholder replaced by its example value
  from ``placeholders``;
- C2 it is exactly one read-only SELECT (or a set operation of SELECTs): no DML, DDL or
  command anywhere in it;
- C3 every table it reads is the item's table or one of that table's inputs in the packet
  (a catalog prefix ignored), and every column resolves against them;
- C4 every partitioned table is filtered on a partition column in the SELECT that reads it
  (WHERE or the join's ON) and named in ``partitions``, or the item says why it does not
  in ``full_scan``; every ``partitions`` item names a partition column of a table read;
- C5 no top-level output column shows a sensitive column's values -- traced through
  derived tables and CTEs; inside ``COUNT`` / ``COUNT_IF``, a comparison or a window's
  ``PARTITION BY`` / ``ORDER BY`` a column shows no value -- and no ``SELECT *`` at the
  top. Sensitive are the identifier columns (``identifier``, ``foreign_identifier``) of
  the documents with their source columns, and every name in the run's sensitive-column
  list (one column name, or ``db.table.column``, per line);
- C6 a query that returns more than one row (grouped, ``DISTINCT``, or detail rows) has a
  ``LIMIT`` of at most 50 -- 51 for a ``value_set``, whose 51st row says the list is not
  complete;
- C7 the item's question is in the table's document and still reads as ``asked`` (NFKC
  and whitespace folded); one already answered warns;
- C8 ids are unique; a data item has ``sql``, ``shape`` and ``how_to_read``; a human or
  corpus item has a ``note`` and neither ``sql`` nor ``lands``;
- C9 an item with ``lands`` has the fixed output columns of its shape, and their
  expressions have the forms :mod:`.probe_forms` lists: ``uniqueness`` -> exactly
  ``rows, keys, duplicate_keys`` counted over the table the target names (the item's
  table for ``summary.row.observed``, the input for ``input:<db.table>``);
  ``value_set`` -> exactly ``value`` (the one ``GROUP BY`` column: the target column, or
  one of its source columns) and ``cnt`` (``COUNT(*)``), no ``HAVING``, ``LIMIT 51``.

A data item without ``engine`` warns: a platform may route a query to another engine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, SqlglotError
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import Scope, build_scope

from .names import bare_column, bare_table, folded_text
from .observed import IDENTIFIER_CATEGORIES, INPUT, OBSERVED_ROW
from .probe_forms import (
    base_column,
    classify,
    output_names,
    projection,
    single_row,
    table_name,
)
from .schema import PROBES_FORMAT, schema_errors

CHECK_FORMAT = "question-probes-check/1"
SENSITIVE_FILE = "sensitive-columns.txt"
ALL_CHECKS = ("C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9")
LIMIT = 50
VALUE_SET_LIMIT = 51
UNIQUENESS = ("rows", "keys", "duplicate_keys")
VALUE_SET = ("value", "cnt")
NO_LIST = (
    f"no sensitive-column list (--sensitive, or {SENSITIVE_FILE} in the run directory): "
    "only the identifier columns of the documents are blocked from the output"
)
NO_LIST_NO_DOCS = (
    f"no sensitive-column list (--sensitive, or {SENSITIVE_FILE} in the run directory) and "
    "no --docs: no column is blocked from the output"
)

_PLACEHOLDER = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")
_COLUMN_LANDS = re.compile(r"^column:(?P<column>[^.\s]+)\.observed_values$")
_FORBIDDEN = tuple(
    getattr(exp, name) for name in (
        "Insert", "Create", "Drop", "Delete", "Update", "Merge", "Alter", "Command",
        "TruncateTable", "Use", "Set", "Cache", "Uncache", "LoadData", "Into",
    ) if hasattr(exp, name)
)
_SET_OPERATION = getattr(exp, "SetOperation", exp.Union)


@dataclass
class Sensitive:
    """Column names blocked from a query's output: bare names, and ``db.table.column``."""

    names: frozenset[str] = frozenset()
    columns: frozenset[str] = frozenset()

    def why(self, table: str, column: str, identifiers: dict[str, str]) -> str | None:
        reference = f"{table}.{column}"
        if column in self.names or reference in self.columns:
            return "is in the sensitive-column list"
        if reference in identifiers:
            return identifiers[reference]
        return None


@dataclass
class _Item:
    data: dict
    findings: list[dict] = field(default_factory=list)

    def fail(self, check: str, message: str) -> None:
        self.findings.append({"check": check, "level": "FAIL", "message": message})

    def warn(self, check: str, message: str) -> None:
        self.findings.append({"check": check, "level": "WARN", "message": message})


def parse_sensitive(text: str) -> tuple[Sensitive, list[str]]:
    """A sensitive-column list: one name per line, ``#`` comments and blank lines skipped.
    A line is a column name or ``[catalog.]db.table.column``; problems by line."""
    names, columns, problems = set(), set(), []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = [part.strip("`") for part in line.split(".")]
        if not all(re.fullmatch(r"[A-Za-z0-9_$]+", part) for part in parts) or len(parts) == 2:
            problems.append(f"line {number}: {raw.strip()!r} is not a column name or "
                            "db.table.column")
        elif len(parts) == 1:
            names.add(parts[0].lower())
        else:
            columns.add(bare_column(line))
    return Sensitive(frozenset(names), frozenset(columns)), problems


def check_probes(
    document, packets: dict[str, dict | None], documents: dict[str, dict] | None,
    sensitive: Sensitive | None,
) -> dict:
    """The ``question-probes-check/1`` report body (without where the inputs came from).

    ``packets`` maps a bare table to its packet (None when there is none); ``documents``
    maps a bare table to its table-semantics document, or is None when none were given.
    """
    errors = schema_errors(document, PROBES_FORMAT)
    checks = [check for check in ALL_CHECKS if documents is not None or check != "C7"]
    warnings = []
    if sensitive is None:
        warnings.append(NO_LIST if documents is not None else NO_LIST_NO_DOCS)
    if errors:
        return _report([], errors, warnings, checks, 0)
    identifiers = _identifiers(documents or {})
    placeholders = document.get("placeholders") or {}
    items = [_Item(item) for item in document["items"]]
    seen: dict[str, int] = {}
    full_scans = 0
    for item in items:
        id_ = item.data["id"]
        seen[id_] = seen.get(id_, 0) + 1
        if seen[id_] == 2:
            item.fail("C8", f"id {id_} is used by more than one item")
        runnable = _shape_of_class(item)
        if documents is not None:
            _question(item, documents)
        if runnable:
            full_scans += _query(item, placeholders, packets, documents, sensitive or Sensitive(),
                                 identifiers)
    return _report(items, [], warnings, checks, full_scans)


def _report(items, errors, warnings, checks, full_scans) -> dict:
    findings = [f for item in items for f in item.findings]
    classes = [item.data["class"] for item in items]
    return {
        "doc_format": CHECK_FORMAT,
        "summary": {
            "items": len(items),
            "data": classes.count("data"),
            "human": classes.count("human"),
            "corpus": classes.count("corpus"),
            "failures": len(errors) + sum(f["level"] == "FAIL" for f in findings),
            "warnings": len(warnings) + sum(f["level"] == "WARN" for f in findings),
            "full_scans": full_scans,
            "checks": checks,
        },
        "warnings": warnings,
        "schema_errors": errors,
        "items": [
            {key: item.data[key] for key in ("id", "table", "question", "part", "class")}
            | {"findings": item.findings}
            for item in items
        ],
    }


def _identifiers(documents: dict[str, dict]) -> dict[str, str]:
    """``db.table.column`` -> why it is blocked, for every identifier column of the
    documents and every source column of one."""
    found = {}
    for table, document in sorted(documents.items()):
        for column in document.get("columns") or []:
            if not isinstance(column, dict) or column.get("category") not in IDENTIFIER_CATEGORIES:
                continue
            name = str(column.get("column") or "").lower()
            why = f"is an identifier column ({table}.{name} is {column['category']})"
            found.setdefault(f"{table}.{name}", why)
            for source in column.get("source_columns") or []:
                found.setdefault(bare_column(source),
                                 f"is a source column of the identifier column {table}.{name}")
    return found


# ------------------------------------------------------------------ C7, C8


def _shape_of_class(item: _Item) -> bool:
    """C8: what the item's class needs; False when the query checks cannot run."""
    data, ok = item.data, True
    if data["class"] == "data":
        for key in ("sql", "shape", "how_to_read"):
            if not data.get(key):
                item.fail("C8", f"a data item needs {key}")
                ok = ok and key != "sql"
        if not data.get("engine"):
            item.warn("engine", "no engine: say which engine runs the query (a platform may "
                                "route it to another one)")
        return ok
    if not data.get("note"):
        item.fail("C8", f"a {data['class']} item needs a note saying who or what answers it")
    for key in ("sql", "lands"):
        if data.get(key):
            item.fail("C8", f"a {data['class']} item has no {key}; only a data item does")
    return False


def _question(item: _Item, documents: dict[str, dict]) -> None:
    table = bare_table(item.data["table"])
    document = documents.get(table)
    if document is None:
        item.fail("C7", f"no document for {table} under --docs")
        return
    questions = (document.get("summary") or {}).get("questions") or []
    question = next((q for q in questions
                     if isinstance(q, dict) and q.get("id") == item.data["question"]), None)
    if question is None:
        item.fail("C7", f"{table} has no question {item.data['question']}")
        return
    if folded_text(question.get("text")) != folded_text(item.data["asked"]):
        item.fail("C7", f"{item.data['question']} no longer reads as asked; it now reads "
                        f"{question.get('text')!r}")
    elif question.get("status") == "answered":
        item.warn("C7", f"{item.data['question']} is already answered")


# ------------------------------------------------------------------ the query: C1-C6, C9


def _query(item: _Item, placeholders: dict, packets: dict, documents, sensitive: Sensitive,
           identifiers: dict[str, str]) -> int:
    """Run C1-C6 and C9 on a data item's query; 1 when it is a flagged full scan."""
    data = item.data
    sql = data["sql"]
    missing = sorted(set(_PLACEHOLDER.findall(sql)) - set(placeholders))
    if missing:
        item.fail("C1", f"placeholder(s) {', '.join(missing)} have no example value in "
                        "placeholders")
        return 0
    for name, value in placeholders.items():
        sql = sql.replace(name, value)
    try:
        statements = [s for s in sqlglot.parse(sql, read="spark") if s is not None]
    except SqlglotError as error:
        item.fail("C1", f"does not parse as Spark SQL: {_first_line(error)}")
        return 0
    if len(statements) != 1:
        item.fail("C2", f"{len(statements)} statements; one SELECT only")
        return 0
    tree = statements[0]
    if not isinstance(tree, (exp.Select, _SET_OPERATION)):
        item.fail("C2", f"the statement is {type(tree).__name__}, not a SELECT")
        return 0
    forbidden = sorted({type(node).__name__ for node in tree.walk()
                        if isinstance(node, _FORBIDDEN)})
    if forbidden:
        item.fail("C2", f"{', '.join(forbidden)} inside the query; read-only SELECT only")
        return 0
    if _star_output(tree):
        item.fail("C5", "SELECT * in the output: name the columns (counts, not detail rows)")
    target = bare_table(data["table"])
    packet = packets.get(target)
    if packet is None:
        item.fail("C3", f"no packet for {target} under --packets")
        return 0
    tables = _packet_tables(packet)
    read = _tables_read(tree)
    outside = sorted(name for name in read if name not in tables)
    if outside:
        item.fail("C3", f"{', '.join(outside)} is neither {target} nor one of its inputs in "
                        "the packet")
        return 0
    for table in tree.find_all(exp.Table):
        table.set("catalog", None)
    try:
        tree = qualify(tree, schema=_schema(tables), dialect="spark",
                       validate_qualify_columns=True, infer_schema=False,
                       quote_identifiers=False)
        root = build_scope(tree)
    except (OptimizeError, SqlglotError) as error:
        item.fail("C3", f"{_first_line(error)} against the packet's tables")
        return 0
    if root is None:
        item.fail("C3", "the query reads nothing the packet knows")
        return 0
    full_scan = _partitions(item, root, tables)
    _outputs(item, root, sensitive, identifiers)
    _bounded(item, root)
    if data.get("lands"):
        _lands(item, root, packet, documents)
    return full_scan


def _first_line(error: Exception) -> str:
    return str(error).strip().splitlines()[0] if str(error).strip() else type(error).__name__


def _star_output(tree: exp.Expression) -> bool:
    selects = _top_selects(tree)
    return any(isinstance(item, exp.Star) or (isinstance(item, exp.Column)
                                              and isinstance(item.this, exp.Star))
               for select in selects for item in select.expressions)


def _top_selects(node: exp.Expression) -> list[exp.Select]:
    if isinstance(node, _SET_OPERATION):
        return _top_selects(node.left) + _top_selects(node.right)
    if isinstance(node, exp.Subquery):
        return _top_selects(node.this)
    return [node] if isinstance(node, exp.Select) else []


def _packet_tables(packet: dict) -> dict[str, tuple[dict[str, str], frozenset[str]]]:
    """bare table -> ({column: type}, partition columns), the target and every input."""
    found = {}
    target = packet.get("target") or {}
    columns = target.get("columns") or []
    found[bare_table(target.get("table"))] = (
        {str(c["name"]).lower(): str(c.get("type") or "string") for c in columns},
        frozenset(str(c["name"]).lower() for c in columns if c.get("partition")),
    )
    for item in packet.get("inputs") or []:
        found.setdefault(bare_table(item.get("table")), (
            {str(c["name"]).lower(): str(c.get("type") or "string")
             for c in item.get("columns") or []},
            frozenset(str(c).lower() for c in item.get("partition_columns") or []),
        ))
    return found


def _schema(tables: dict) -> dict:
    schema: dict = {}
    for name, (columns, _) in tables.items():
        db, _, table = name.rpartition(".")
        schema.setdefault(db, {})[table] = {column: "string" for column in columns} or {
            "_": "string"}
    return schema


def _tables_read(tree: exp.Expression) -> set[str]:
    ctes = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    return {table_name(table) for table in tree.find_all(exp.Table)
            if table.db or table.name.lower() not in ctes}


def _partitions(item: _Item, root: Scope, tables: dict) -> int:
    """C4; 1 when the item is a full scan it flagged."""
    filtered, unfiltered = set(), set()
    for scope in root.traverse():
        for alias, source in scope.sources.items():
            if not isinstance(source, exp.Table):
                continue
            name = table_name(source)
            columns = tables.get(name, ({}, frozenset()))[1]
            if not columns:
                continue
            (filtered if _filters(scope.expression, alias, columns) else unfiltered).add(name)
    declared = item.data.get("partitions") or []
    named = set()
    for entry in declared:
        name, column = bare_table(entry["table"]), entry["column"].lower()
        named.add(name)
        if name not in filtered | unfiltered and name not in _all_read(root):
            item.fail("C4", f"partitions names {name}, which the query does not read")
        elif column not in tables.get(name, ({}, frozenset()))[1]:
            item.fail("C4", f"partitions names {name}.{column}, which is not a partition column")
    for name in sorted(filtered - named):
        item.fail("C4", f"{name} is filtered on its partition but not named in partitions "
                        "(want and fallback)")
    flagged = bool(item.data.get("full_scan"))
    if unfiltered - filtered and not flagged:
        for name in sorted(unfiltered - filtered):
            item.fail("C4", f"{name} is read without a filter on its partition column; filter "
                            "it, or say why not in full_scan")
        return 0
    if flagged and not unfiltered:
        item.warn("C4", "full_scan is set but every partitioned table is filtered")
        return 0
    return 1 if flagged else 0


def _all_read(root: Scope) -> set[str]:
    return {table_name(source) for scope in root.traverse()
            for source in scope.sources.values() if isinstance(source, exp.Table)}


def _filters(select: exp.Expression, alias: str, columns: frozenset[str]) -> bool:
    if not isinstance(select, exp.Select):
        return False
    conditions = [select.args.get("where")]
    conditions += [join.args.get("on") for join in select.args.get("joins") or []]
    return any(
        column.name.lower() in columns and column.table == alias
        for condition in conditions if condition is not None
        for column in condition.find_all(exp.Column)
    )


def _outputs(item: _Item, root: Scope, sensitive: Sensitive, identifiers: dict) -> None:
    """C5: the base columns whose values a top-level output column shows."""
    reported = set()
    for scope in _top_scopes(root):
        for output in scope.expression.expressions:
            for table, column in _shown(output.unalias(), scope):
                why = sensitive.why(table, column, identifiers)
                if why and (output.alias_or_name, table, column) not in reported:
                    reported.add((output.alias_or_name, table, column))
                    item.fail("C5", f"output column {output.alias_or_name} shows the values of "
                                    f"{table}.{column}, which {why}; count it instead")


def _top_scopes(root: Scope) -> list[Scope]:
    if isinstance(root.expression, _SET_OPERATION):
        return [scope for inner in root.union_scopes for scope in _top_scopes(inner)]
    return [root]


def _shown(node: exp.Expression, scope: Scope, depth: int = 0):
    """``(table, column)`` for every base column whose values ``node`` shows."""
    if depth > 20:
        return
    for column in node.find_all(exp.Column):
        if _hidden(column, node) or _nested(column, node):
            continue
        source = scope.sources.get(column.table)
        if isinstance(source, exp.Table):
            yield table_name(source), column.name.lower()
        elif isinstance(source, Scope):
            for inner in _top_scopes(source):
                found = projection(inner.expression, column.name)
                if found is not None:
                    yield from _shown(found, inner, depth + 1)
    for subquery in node.find_all(exp.Subquery):
        if _hidden(subquery, node):
            continue
        for inner in scope.subquery_scopes:
            if inner.expression is subquery.this:
                for top in _top_scopes(inner):
                    for output in top.expression.expressions:
                        yield from _shown(output.unalias(), top, depth + 1)


def _hidden(node: exp.Expression, root: exp.Expression) -> bool:
    """Inside a count, a comparison or a window's partitioning: no value of it is shown."""
    child, parent = node, node.parent
    while child is not root and parent is not None:
        if isinstance(parent, (exp.Count, exp.CountIf, exp.Predicate)):
            return True
        if isinstance(parent, exp.Window) and child is not parent.this:
            return True
        child, parent = parent, parent.parent
    return False


def _nested(node: exp.Expression, root: exp.Expression) -> bool:
    """Inside a subquery of ``root``: its own scope speaks for it."""
    if node is root:
        return False
    parent = node.parent
    while parent is not None and parent is not root:
        if isinstance(parent, (exp.Subquery, exp.Select)):
            return True
        parent = parent.parent
    return False


def _bounded(item: _Item, root: Scope) -> None:
    """C6: more than one row back needs a LIMIT of at most 50 (51 for a value set)."""
    cap = VALUE_SET_LIMIT if item.data.get("shape") == "value_set" else LIMIT
    outer = root.expression.args.get("limit") if isinstance(root.expression, _SET_OPERATION) \
        else None
    for scope in _top_scopes(root):
        if single_row(scope):
            continue
        limit = scope.expression.args.get("limit") or outer
        value = _limit(limit)
        if value is None:
            item.fail("C6", f"returns one row per group or row without a LIMIT; add LIMIT {cap} "
                            "or less")
            return
        if value > cap:
            item.fail("C6", f"LIMIT {value} is over {cap}")
            return


def _limit(limit) -> int | None:
    if limit is None:
        return None
    value = limit.expression if isinstance(limit, exp.Limit) else limit
    try:
        return int(value.name)
    except (AttributeError, TypeError, ValueError):
        return None


def _lands(item: _Item, root: Scope, packet: dict, documents) -> None:
    """C9: the fixed output columns of a query whose result may become an observation."""
    data = item.data
    lands, shape, table = data["lands"], data.get("shape"), bare_table(data["table"])
    select = root.expression
    if not isinstance(select, exp.Select):
        item.fail("C9", "a query that lands in a slot is one SELECT, not a set operation")
        return
    match = _COLUMN_LANDS.match(lands)
    if match:
        if shape != "value_set":
            item.fail("C9", f"{lands} takes a value_set, not {shape}")
            return
        _value_set(item, root, table, match["column"].lower(), packet, documents)
        return
    if shape != "uniqueness":
        item.fail("C9", f"{lands} takes a uniqueness count, not {shape}")
        return
    if lands == OBSERVED_ROW:
        counted = table
    else:
        counted = bare_table(lands[len(INPUT):])
        inputs = {bare_table(i.get("table")) for i in packet.get("inputs") or []}
        if counted not in inputs:
            item.fail("C9", f"{counted} is not an input of {table} in the packet")
            return
    _uniqueness(item, root, counted)


def _names(item: _Item, select: exp.Select, wanted: tuple[str, ...]) -> bool:
    names = output_names(select)
    if sorted(names) != sorted(wanted):
        item.fail("C9", f"the output columns are {', '.join(names)}; this shape outputs "
                        f"exactly {', '.join(wanted)}")
        return False
    return True


def _uniqueness(item: _Item, root: Scope, counted: str) -> None:
    select = root.expression
    if not _names(item, select, UNIQUENESS):
        return
    if not single_row(root):
        item.fail("C9", "a uniqueness count returns one row")
        return
    forms = {}
    for name in UNIQUENESS:
        form = classify(projection(select, name), root)
        if form is None or form.kind != name:
            said = f"computes {form.kind}" if form is not None else "has none of the forms"
            item.fail("C9", f"{name} {said} that {name} is checked for (a renamed expression "
                            "is not the fixed column)")
            continue
        if form.table != counted:
            item.fail("C9", f"{name} counts {form.table}, not {counted}")
            continue
        forms[name] = form
    if "keys" in forms and "duplicate_keys" in forms and \
            forms["keys"].keys != forms["duplicate_keys"].keys:
        item.fail("C9", f"keys counts ({', '.join(forms['keys'].keys)}) but duplicate_keys "
                        f"({', '.join(forms['duplicate_keys'].keys)}): one set of key columns")


def _value_set(item: _Item, root: Scope, table: str, column: str, packet: dict,
               documents) -> None:
    select = root.expression
    target_columns = {str(c["name"]).lower() for c in (packet.get("target") or {}).get(
        "columns") or []}
    if column not in target_columns:
        item.fail("C9", f"{table} has no column {column}")
        return
    if not _names(item, select, VALUE_SET):
        return
    group = select.args.get("group")
    keys = group.expressions if group is not None else []
    value = projection(select, "value")
    if len(keys) != 1 or not isinstance(value, exp.Column) or not isinstance(keys[0], exp.Column):
        item.fail("C9", "value is the one GROUP BY column")
        return
    base = base_column(value, root)
    if base is None or base != base_column(keys[0], root):
        item.fail("C9", "value is the one GROUP BY column")
        return
    count = projection(select, "cnt")
    if not (isinstance(count, exp.Count) and (isinstance(count.this, exp.Star) or (
            isinstance(count.this, exp.Literal) and not isinstance(count.this, exp.Null)))):
        item.fail("C9", "cnt is COUNT(*) per value")
    if select.args.get("having") is not None:
        item.fail("C9", "no HAVING: a value set lists every value it found")
    if _limit(select.args.get("limit")) != VALUE_SET_LIMIT:
        item.fail("C9", f"a value set ends with LIMIT {VALUE_SET_LIMIT}: a 51st row says the "
                        "list is not complete")
    source_table, source_column = base
    if source_table == table:
        if source_column != column:
            item.fail("C9", f"value is {table}.{source_column}, not the target column {column}")
        return
    if documents is None:
        item.warn("C9", f"value is {source_table}.{source_column}; pass --docs to check it is "
                        f"a source column of {column}")
        return
    document = documents.get(table) or {}
    sources = next((c.get("source_columns") or [] for c in document.get("columns") or []
                    if isinstance(c, dict) and str(c.get("column")).lower() == column), [])
    if f"{source_table}.{source_column}" not in {bare_column(s) for s in sources}:
        item.fail("C9", f"value is {source_table}.{source_column}, which is not a source column "
                        f"of {column} in the document")
