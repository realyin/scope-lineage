"""What one statement of the semantic profile contributes to a packet.

The semantic profile (``describe``'s builder) is the source of every lineage fact here:
a field's physical sources and derivation steps, the statement's rules, its grain and
keys, its inputs and how each is read. This module only re-shapes those facts per target
column and per input table; it derives nothing the profile has not already settled,
except the two time readings check 9 needs (how each input's partitions are read, and
which filters touch a business date).
"""

from __future__ import annotations

import re

from ..render.semantic_text import NULLABLE_LEFT_JOIN_TYPES, aggregate_functions
from .names import bare_column, bare_table, normalize_sql, strip_leading_keyword
from .packet_meaning import (
    PASS_THROUGH_STEPS,
    case_outputs,
    code_expression,
    join_facts,
    literal_outputs,
)

_RULE_KINDS = {"filter": "filter", "having": "filter", "join_condition": "join",
               "case_branch": "case"}
# Stage actions that say how rows are merged or de-duplicated; the profile's rules only
# hold predicates, joins and CASE branches.
_STAGE_RULE_ACTIONS = {"window": "dedup", "distinct": "dedup", "union": "union"}

# Warehouse naming conventions for what one partition of a table holds. A convention,
# not a fact: published as `name_convention` so a reader sees what the check assumed.
_FULL_SUFFIX = re.compile(r"_(df|da|full|snapshot)$")
_INCREMENTAL_SUFFIX = re.compile(r"_(di|hi|inc|incr|delta)$")
_DATE_NAME = re.compile(r"(^|_)(date|dt|day|time|ts|month)$")
_DATE_TYPE = re.compile(r"^(date|timestamp|datetime)")
_DATE_COMMENT = re.compile(r"(date|time|日期|时间)", re.IGNORECASE)


def column_producer(task: str, statement: dict, field: dict) -> dict:
    """How one statement writes one target column.

    Besides the profile's own facts it carries, each only when there is some: the name the
    SQL gave a value a positional write filed under another column (``sql_alias``), the
    physical keys that choose the row of a constant row set it reads (``lookup_keys``),
    the author's comments on the value (``sql_comments``), and for a column whose last
    step is DIRECT, what its chain computes on the way (``computed_by``).
    """
    sources = []
    for source in field.get("sources") or []:
        reference = bare_column(f"{source.get('table')}.{source.get('column')}")
        if reference not in sources:
            sources.append(reference)
    producer = {
        "task": task,
        "statement_id": statement.get("statement_id"),
        "transform": field.get("transform"),
        "role": field.get("structural_role"),
        "expression": field.get("expression"),
        "sources": sources,
        "steps": [text for text in map(step_text, field.get("derivation") or []) if text],
        "case_outputs": case_outputs(code_expression(field)),
    }
    computed = computed_by(field) if str(field.get("transform")) == "DIRECT" else []
    literals, constant_only = literal_outputs(field)
    extra = {
        "computed_by": computed,
        "sql_alias": field.get("sql_alias"),
        "lookup_keys": list(dict.fromkeys(bare_column(key) for key in field.get("lookup_keys") or [])),
        "sql_comments": [str(text) for text in field.get("sql_comments") or []],
        "literal_outputs": literals,
        "constant_only": constant_only,
        _LABEL: field.get("column_label"),
    }
    producer.update({key: value for key, value in extra.items() if value})
    return producer


# The profile's name for a field, kept only while MERGE branches are folded.
_LABEL = "_label"


def step_text(step: dict) -> str | None:
    """A derivation step as words; its expression when no words fit; ``None`` when neither.

    The profile leaves ``text`` empty for an expression its vocabulary cannot word (a
    UDF, ``MD5(...)``); the expression itself is then the fact, as ``describe`` shows it.
    """
    if step.get("text"):
        return str(step["text"])
    return f"表达式 {step['expression']}" if step.get("expression") else None


def computed_by(field: dict) -> list[str]:
    """The kinds of computation a field's chain makes, in order, pass-throughs left out.

    The contract's ``transform`` is the last step's: a column that is a SUM two scopes
    down and then projected is DIRECT. An aggregate names its functions.
    """
    kinds: list[str] = []
    for step in field.get("derivation") or []:
        kind = str(step.get("step_type") or "")
        if not kind or kind in PASS_THROUGH_STEPS:
            continue
        if kind == "aggregate":
            names = sorted(aggregate_functions(step.get("expression")))
            kind = f"aggregate({','.join(names)})" if names else kind
        if kind not in kinds:
            kinds.append(kind)
    return kinds


def fold_branches(producers: list[dict]) -> list[dict]:
    """One producer for MERGE branches of one statement that write the same thing.

    A MERGE's UPDATE SET and INSERT branches each write the column; when everything but
    the spelling of the expression (identifier quotes, whitespace, case) is the same,
    they are one fact, and ``branches`` lists the profile's names of the branches folded.
    Branches writing different values (``coalesce(target.c, source.c)`` against
    ``source.c``) stay two producers.
    """
    folded: list[dict] = []
    for producer in producers:
        same = next((kept for kept in folded if _same_content(kept, producer)), None)
        if same is None:
            folded.append(producer)
            continue
        same.setdefault("_folded", [same.get(_LABEL)]).append(producer.get(_LABEL))
    for producer in folded:
        labels = [str(label) for label in producer.pop("_folded", []) if label]
        producer.pop(_LABEL, None)
        if len(labels) > 1:
            producer["branches"] = labels
    return folded


def _same_content(left: dict, right: dict) -> bool:
    ignored = {"expression", _LABEL, "_folded"}
    return (
        {key: value for key, value in left.items() if key not in ignored}
        == {key: value for key, value in right.items() if key not in ignored}
        and _spelling(left.get("expression")) == _spelling(right.get("expression"))
    )


def _spelling(expression) -> str:
    """Quotes and whitespace out, lower case: qualifiers stay, so ``t.c`` is not ``s.c``."""
    return re.sub(r"\s+", "", str(expression or "").replace("`", "")).lower()


def statement_rules(task: str, statement: dict) -> list[dict]:
    """The statement's filters, joins and CASE branches, then its dedup, window and union steps.

    Every rule row a packet has is made here, before the rules are numbered (README 裁决
    12): the notes that name a rule by its number come after. A window in a stage that
    does not dedup -- a ranking nobody filters to ``= 1``, a LEAD -- is a ``window`` row
    (C-P4): the profile's text says what it computes and that nothing keeps one row.
    """
    rules = [_profile_rule(task, statement, rule) for rule in statement.get("rules") or []]
    for stage in statement.get("stages") or []:
        for action in stage.get("actions") or []:
            kind = _STAGE_RULE_ACTIONS.get(str(action.get("type")))
            if kind == "dedup" and action.get("type") == "window" and stage.get("role") != "dedup":
                kind = WINDOW
            if kind:
                rules.append(_stage_rule(task, statement, stage, action, kind))
    return rules


def _profile_rule(task: str, statement: dict, rule: dict) -> dict:
    entry = {
        "kind": _RULE_KINDS.get(str(rule.get("kind")), str(rule.get("kind"))),
        "task": task,
        "statement_id": statement.get("statement_id"),
        "scope": rule.get("scope_id"),
        "expression": rule.get("expression"),
        "partition_filter": bool(rule.get("is_partition_filter")),
        "partition_basis": "lineage",
        "tables": _tables_of(rule.get("fields")),
        "columns": _columns_of(rule.get("fields")),
    }
    if rule.get("join_type"):
        entry["join_type"] = rule["join_type"]
    if rule.get("consumed") is False:
        entry["consumed"] = False
    if rule.get("sql_comments"):
        entry["sql_comments"] = [str(text) for text in rule["sql_comments"]]
    if rule.get("commented_out_sql"):
        # C-P2: SQL switched off beside the condition -- kept, and said to have no effect.
        entry["commented_out_sql"] = [str(text) for text in rule["commented_out_sql"]]
    # Read by the findings and the MERGE block, which name a profile rule or logic block;
    # dropped before the packet is written.
    entry[PROFILE_RULE] = rule.get("rule_id")
    entry[LOGIC_BLOCK] = rule.get("evidence")
    if entry["kind"] == "join":
        entry.update(join_facts(statement, rule))
        # The ON's other conjuncts, read by `mark_partition_filters` and dropped before
        # the packet is written: they are the profile's to publish, not the packet's.
        entry[EXTRA_CONDITIONS] = [str(text) for text in rule.get("extra_conditions") or []]
        if not entry["tables"]:
            # A transitional fallback: an ON whose only equality has more than one column
            # on a side (`IF(COALESCE(a.x, '') = '', a.y, a.x) = d.k`) has no key pair in
            # the lineage, so the rule's `fields` are empty. Name the tables its
            # conditions touch and the right side; once the lineage pairs such an
            # equality, `fields` answers and this never runs.
            entry["tables"] = sorted(
                set(_tables_of(rule.get("extra_condition_fields"))) | set(entry["right_tables"])
            )
    return entry


def _stage_rule(task: str, statement: dict, stage: dict, action: dict, kind: str) -> dict:
    return {
        "kind": kind,
        "task": task,
        "statement_id": statement.get("statement_id"),
        "scope": stage.get("scope_id"),
        "expression": action.get("expression"),
        "partition_filter": False,
        "partition_basis": "lineage",
        "tables": _tables_of(action.get("fields")) or sorted(
            bare_table(table) for table in stage.get("upstream_physical_tables") or []
        ),
        "text": action.get("text"),
        # The action's logic block, which a finding's evidence may name (A-M4), and its
        # intent, which tells a ranking nobody filters; both dropped before writing.
        LOGIC_BLOCK: action.get("evidence"),
        INTENT: action.get("intent"),
    }


def _tables_of(fields) -> list[str]:
    return sorted({bare_table(item.get("table")) for item in fields or [] if item.get("table")})


def _columns_of(fields) -> list[str]:
    columns = []
    for item in fields or []:
        reference = bare_column(f"{item.get('table')}.{item.get('column')}")
        if item.get("table") and reference not in columns:
            columns.append(reference)
    return columns


def statement_keys(task: str, statement: dict) -> dict:
    """The statement's grain and keys, and whether the profile proves them.

    ``proven`` is false on a MERGE whatever its confidence: the profile proves the batch
    the MERGE writes, while a reader of this row asks about the table (A-M1).
    """
    shape = statement.get("output_shape") or {}
    grain = shape.get("grain") or {}
    confidence = shape.get("key_confidence")
    return {
        "task": task,
        "statement_id": statement.get("statement_id"),
        "shape": shape.get("shape"),
        "grain_basis": grain.get("basis"),
        "grain_keys": [str(key.get("name")) for key in grain.get("keys") or []],
        "candidate_keys": list(shape.get("candidate_keys") or []),
        "key_confidence": confidence,
        "proven": confidence == "proven" and not shape.get("merge"),
    }


MERGE_ROW_VALUES = "merge_row_values"


def statement_partition(task: str, statement: dict, table_partitions=()) -> dict:
    """How the statement writes partitions: its PARTITION clause, or a MERGE's rows (A-M6).

    A MERGE has no PARTITION clause, so the lineage names no partition column for it; each
    written row lands in the partition its own values name. ``table_partitions`` are the
    target table's partition columns the metadata states; a MERGE then writes them as
    ``merge_row_values``, with the constants its INSERT writes into them.
    """
    partition = (statement.get("task") or {}).get("partition") or {}
    spec = partition.get("spec") or {}
    entry = {
        "task": task,
        "statement_id": statement.get("statement_id"),
        "columns": list(partition.get("columns") or []),
        "mode": partition.get("mode"),
        "spec": spec,
    }
    dynamic = [name for name, value in spec.items() if value is None]
    fields = statement.get("fields") or []
    merging = (statement.get("output_shape") or {}).get("merge")
    if merging and not entry["columns"] and not entry["mode"] and table_partitions:
        entry["columns"], entry["mode"], dynamic = list(table_partitions), MERGE_ROW_VALUES, list(
            table_partitions)
        # The value an inserted row lands with is the INSERT's; an UPDATE keeps the row.
        fields = [field for field in fields if _NOT_MATCHED.search(str(field.get("column_label")))]
    values = _select_values(fields, dynamic)
    if values:
        entry["select_values"] = values
    return entry


_NOT_MATCHED = re.compile(r"merge:not_matched\s")


def _select_values(fields: list[dict], dynamic: list[str]) -> dict[str, list[str]]:
    """The constants a SELECT writes into each dynamic partition column, when only constants.

    ``PARTITION (dt)`` is dynamic whatever the SELECT feeds it, so the spec has no value;
    when the field the SELECT writes to that column reads no source column and is built
    from constants alone (``'${bizdate}' AS dt``, one per UNION branch), those constants
    are the partition values. A column fed from a source keeps no entry.
    """
    fields = {str(field.get("column")): field for field in fields}
    values: dict[str, list[str]] = {}
    for name in dynamic:
        field = fields.get(str(name)) or {}
        generated = field.get("generated_sources") or []
        if field.get("sources") or not generated or any(
                str(item.get("source_type")) != "CONSTANT" for item in generated):
            continue
        values[str(name)] = list(dict.fromkeys(str(item.get("value")) for item in generated))
    return values


# ------------------------------------------------------------------ partition filters

# Names a warehouse gives its date partition column; read only for a table the metadata
# marks partitioned without saying which column is the partition.
_PARTITION_NAMES = frozenset({"dt", "ds", "pt", "p_date"})
_CONSTANT = r"('[^']*'|\d+|\$\{[a-z0-9_.\-]+\})"
_COMPARISON = re.compile(rf"^[a-z0-9_]+(=|<=|>=|<|>){_CONSTANT}$")
_BETWEEN = re.compile(rf"^[a-z0-9_]+between{_CONSTANT}and{_CONSTANT}$")


EXTRA_CONDITIONS = "_extra_conditions"
PROFILE_RULE = "_profile_rule"
LOGIC_BLOCK = "_logic_block"
INTENT = "_intent"
WINDOW = "window"
_QUALIFIED = re.compile(r"^([a-z_][a-z0-9_]*)\.([a-z0-9_]+)((?:=|<=|>=|<|>|between).*)$")


def mark_partition_filters(rules: list[dict], metadata) -> None:
    """Decide per filter conjunct whether it selects partitions, metadata first.

    The lineage's flag is a name rule over a whole WHERE clause, so ``dt = x AND
    status = 0`` marks neither conjunct. Here each conjunct is judged alone: a filter
    whose columns are all partition columns the metadata states (``isPartition``,
    ``PARTITIONED BY``) is a partition filter; failing that, a comparison with a constant
    on a ``dt``/``ds``/``pt``/``p_date`` column of a table the metadata marks partitioned
    is one; with neither, the lineage's flag stands. ``partition_basis`` says which.

    A JOIN's ON reads partitions too (:func:`_join_partition_reads`); what it reads is
    published on the rule as ``partition_reads``, only when there is some.
    """
    for rule in rules:
        if rule["kind"] == "join":
            reads = _join_partition_reads(rule, metadata)
            if reads:
                rule["partition_reads"] = reads
            continue
        if rule["kind"] != "filter" or not rule.get("columns"):
            continue
        decided = [partition_column(ref, rule["expression"], metadata) for ref in rule["columns"]]
        if any(verdict is None for verdict, _ in decided):
            continue
        rule["partition_filter"] = all(verdict for verdict, _ in decided)
        bases = {basis for _, basis in decided}
        rule["partition_basis"] = "metadata" if bases == {"metadata"} else "partition_name"


def _join_partition_reads(rule: dict, metadata) -> list[dict]:
    """The ON conditions that pick partitions of the JOIN's right table.

    ``LEFT JOIN t c ON a.k = c.k AND c.dt = '…'`` reads one partition of ``t`` as surely
    as a WHERE would: the right rows outside it never match. A condition counts when it
    compares a column of the right side, qualified by the name the ON calls it, with a
    constant; the right side is one physical table; the column is a partition column
    (:func:`partition_column`); and the join does not keep every right row -- a RIGHT or
    FULL OUTER join's ON never removes a right row, so it reads them all.
    """
    if rule.get("join_type") in NULLABLE_LEFT_JOIN_TYPES:
        return []
    table = rule.get("right")
    aliases = {str(name).lower() for name in rule.get("right_aliases") or []}
    if not table or rule.get("right_tables") != [table]:
        return []
    reads = []
    for expression in rule.get(EXTRA_CONDITIONS) or []:
        text = re.sub(r"\s+", "", strip_leading_keyword(expression).lower().replace("`", ""))
        match = _QUALIFIED.match(text)
        if not match or match.group(1) not in aliases:
            continue
        text = f"{match.group(2)}{match.group(3)}"
        if not (_COMPARISON.match(text) or _BETWEEN.match(text)):
            continue
        verdict, basis = partition_column(f"{table}.{match.group(2)}", expression, metadata)
        if verdict:
            reads.append({"table": table, "expression": expression, "basis": basis})
    return reads


def drop_private(rules: list[dict]) -> None:
    """Take out what the rules carried for this package only."""
    for rule in rules:
        for key in (EXTRA_CONDITIONS, PROFILE_RULE, LOGIC_BLOCK, INTENT):
            rule.pop(key, None)


def partition_column(reference: str, expression, metadata) -> tuple:
    """``(is a partition column, basis)``; ``(None, "lineage")`` when nothing says."""
    table, column = reference.rsplit(".", 1)
    meta = metadata(table) or {}
    if meta.get("partition_columns"):
        return column in meta["partition_columns"], "metadata"
    text = normalize_sql(expression)
    if (meta.get("partitioned") and column in _PARTITION_NAMES
            and (_COMPARISON.match(text) or _BETWEEN.match(text))):
        return True, "partition_name"
    return None, "lineage"


# ------------------------------------------------------------------ input time facts


def input_time_facts(table: str, rules: list[dict], columns: list[dict]) -> dict:
    """How one input's partitions are read, and its non-partition business-date filters."""
    partition = [r["expression"] for r in rules if r["partition_filter"] and table in r["tables"]]
    partition += [
        read["expression"]
        for rule in rules
        for read in rule.get("partition_reads") or []
        if read["table"] == table
    ]
    by_name = {column["name"]: column for column in columns}
    dated = [
        {"column": name, "expression": rule["expression"], "statement_id": rule["statement_id"]}
        for rule in rules
        if rule["kind"] == "filter" and not rule["partition_filter"] and table in rule["tables"]
        for name in _filter_columns(rule, table)
        if _is_date_column(by_name.get(name) or {"name": name})
    ]
    _mark_date_shapes(dated)
    read = _partition_read(partition)
    convention = _name_convention(table)
    return {
        "partition_read": read,
        "partition_filters": partition,
        "date_filters": dated,
        "name_convention": convention,
        "full_snapshot": read == "equality" and convention == "full",
    }


# The shapes a business-date filter takes. Only a window -- an equality, a lower bound, a
# BETWEEN, or anything not recognised -- selects rows by date; an as-of pair keeps the rows
# valid on one day, an upper bound alone keeps all history up to a day, a NULL check
# looks at no date at all.
DATE_WINDOW = "window"
_FLIP = {"<": ">", "<=": ">=", ">": "<", ">=": "<=", "=": "=", "<>": "<>"}
_SIDE = r"(?P<side>.+?)"
_OPERATOR = r"(?P<op><=|>=|<>|=|<|>)"
_BOUND = re.compile(rf"^{_SIDE}{_OPERATOR}(?P<constant>{_CONSTANT})$")
_BOUND_FLIPPED = re.compile(rf"^(?P<constant>{_CONSTANT}){_OPERATOR}{_SIDE}$")
_NULL_CHECK = re.compile(r"is(not)?null$")
_UPPER, _LOWER = ("<", "<="), (">", ">=")


def _mark_date_shapes(dated: list[dict]) -> None:
    """Give each date filter its ``shape``: ``as_of``, ``upper_bound``, ``null_check``, ``window``.

    ``X <= C`` (or ``<``) with ``Y > C`` (or ``>=``) on another column, in the same
    statement, with the same constant, is an as-of pair: both are ``as_of``. An upper bound
    left alone is ``upper_bound``; ``IS [NOT] NULL`` is ``null_check``; anything else --
    ``=``, ``>=``, ``>``, BETWEEN, a shape not recognised -- is a ``window``.
    """
    bounds = [_bound(item["expression"]) for item in dated]
    for item, bound in zip(dated, bounds):
        if bound is None:
            null = _NULL_CHECK.search(normalize_sql(item["expression"]))
            item["shape"] = "null_check" if null else DATE_WINDOW
            continue
        side, operator, constant = bound
        upper = operator in _UPPER
        if upper or operator in _LOWER:
            wanted = _LOWER if upper else _UPPER
            paired = any(
                other is not None and other[1] in wanted and other[2] == constant
                and other[0] != side and peer["statement_id"] == item["statement_id"]
                for peer, other in zip(dated, bounds)
            )
            if paired:
                item["shape"] = "as_of"
                continue
        item["shape"] = "upper_bound" if upper else DATE_WINDOW


def _bound(expression) -> tuple | None:
    """``(side, operator, constant)`` of ``side <op> constant``, constant-first flipped."""
    text = normalize_sql(expression)
    match = _BOUND.match(text)
    if match:
        return match["side"], match["op"], match["constant"]
    match = _BOUND_FLIPPED.match(text)
    if match:
        return match["side"], _FLIP[match["op"]], match["constant"]
    return None


def _filter_columns(rule: dict, table: str) -> list[str]:
    prefix = f"{table}."
    return [ref[len(prefix):] for ref in rule.get("columns") or [] if ref.startswith(prefix)]


def _partition_read(expressions: list[str]) -> str:
    """``none``, ``equality``, ``multi_equality`` (C-P7) or ``range``.

    Every filter an equality: ``equality``, as before. Every filter an equality or an IN
    list of literals, the literals together more than one value: ``multi_equality`` --
    several fixed partitions, not a range (``dt IN ('20250101', '20260101')``). An IN
    list of one value is an equality; anything else (a bound, BETWEEN, a subquery) is
    ``range``.
    """
    if not expressions:
        return "none"
    if all(_is_equality(text) for text in expressions):
        return "equality"
    values = [partition_values(text) for text in expressions]
    if any(found is None for found in values):
        return "range"
    return "multi_equality" if len({v for found in values for v in found}) > 1 else "equality"


def _is_equality(expression: str) -> bool:
    text = normalize_sql(expression)
    return text.count("=") == 1 and not any(op in text for op in ("<", ">", "in(", "between"))


_LITERAL = r"'[^']*'|\d+"
_IN_LIST = re.compile(rf"^[^=<>()]+in\(((?:{_LITERAL})(?:,(?:{_LITERAL}))*)\)$")
_EQUALS = re.compile(rf"^[^=<>()]+=({_LITERAL})$")


def partition_values(expression: str) -> list[str] | None:
    """The literals an equality or a literal IN list fixes its column to; ``None`` otherwise."""
    if not (_IN_LIST.match(normalize_sql(expression)) or _EQUALS.match(normalize_sql(expression))):
        return None
    # The literals as written: the normalised text is lower-cased.
    written = re.split(r"=|\bin\s*\(", strip_leading_keyword(expression), maxsplit=1,
                       flags=re.IGNORECASE)[-1]
    return re.findall(_LITERAL, written)


def _name_convention(table: str) -> str:
    name = table.rsplit(".", 1)[-1]
    if _FULL_SUFFIX.search(name):
        return "full"
    if _INCREMENTAL_SUFFIX.search(name):
        return "incremental"
    return "unknown"


def _is_date_column(column: dict) -> bool:
    return bool(
        _DATE_TYPE.match(str(column.get("type") or "").lower())
        or _DATE_NAME.search(str(column.get("name") or "").lower())
        or _DATE_COMMENT.search(str(column.get("comment") or ""))
    )
