"""Which joined inputs a target column's value is read through, and under which constants.

A catalog drafter writing a code set's ``lookup.filter``, the order of a binding's
``code_sets`` and a binding's ``holds`` needs, per target column: the joined inputs the
value is read through and the constant conditions those rows are picked by; the order a
fallback (``COALESCE(d1.x, d2.x, a.c)``) reads them in; and, for a column that holds the
code itself, which of those reads it is the join key of. The lineage already records all
of it in its scope structure -- an output source's ``input_ref_id``, the same id on the
JOIN's ``condition_filters[].fields`` and on its ``join_key_pairs``, and the ``filters``
of the scopes a joined value passes through -- but no layer projects it per column. This
module does, for ``catalog digest --lineage`` only; the lineage contract, the profile and
the packets are unchanged.

What counts, and what does not:

- Only a value that enters its scope through a JOIN (or passes through a joined subtree)
  has conditions; constants on the main side of a query select its rows, not a lookup.
- A condition is a single equality with a **string** literal (``d.kind = 'X'``). Numbers
  (``rn = 1``), ``${…}`` parameters, ``IN`` lists and comparisons are not read.
- A comparison on a partition column is not a condition; the caller says which columns
  are partitions (``is_partition``), so the packet's rule is the only one.
- A join with no such condition only supplements a field and is not published.
- A value whose leaf is not a physical table (an inline ``VALUES`` list, a constant) is
  not published.

The wording is deliberately neutral: a read is "rows of <table> where <column> =
'<literal>'", never "a code set" -- the same shape picks a role, a language or a row
version as often as a dictionary type. The catalog, when given, says which ones are code
sets.

Nothing here reads ``join_relation_detail.right_alias`` (one alias is shared by every JOIN
of one source in a scope) or ``display_expression`` (it lower-cases literals): the input
is identified by ``input_ref_id`` and the literal read from ``condition_filters[]
.expression`` and the scope ``filters``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Optional

from sqlglot import exp

from ..catalog.digest import bare_table
from . import semantic_text
from .glossary_values import (
    CONTEXT_FILTER_EQ,
    VALUE_KIND_LITERAL,
    _comparison,
    _conjuncts,
    _value_kind,
)

#: ``(db.table.column, conjunct SQL) -> is a partition comparison``.
PartitionTest = Callable[[str, str], bool]

ORDER_UNKNOWN = "unknown"

_LEADING_KEYWORD = re.compile(r"^\s*(WHERE|AND|ON|HAVING)\s+", re.IGNORECASE)
_MAX_DEPTH = 64


def column_lookups(
    documents: Iterable[Mapping], *, is_partition: Optional[PartitionTest] = None
) -> dict:
    """``{"tables": {db.table: {column: facts}}}`` over every write statement.

    Every table some statement writes is a key, even with no facts, so a caller can tell
    "written, nothing to add" from "no writing statement". A column's facts are
    ``lookups`` (with ``fallback``) when its value is read through a joined input with
    constant conditions, else ``key_of`` (with ``key_of_order`` when its readers
    disagree) when it is the join key of such reads; columns with neither are absent.
    """
    test = is_partition or (lambda _reference, _conjunct: False)
    tables: dict[str, dict[str, _Column]] = {}
    statements = sorted(_statements(documents), key=lambda item: (item[0], item[1]))
    for task, statement_id, statement in statements:
        target = bare_table(statement.get("target_table"))
        if not target:
            continue
        columns = tables.setdefault(target, {})
        _StatementReader((task, statement_id), statement, test).read(target, columns)
    return {
        "tables": {
            table: {
                name: facts
                for name, column in columns.items()
                if (facts := column.published(columns))
            }
            for table, columns in tables.items()
        }
    }


def partitioned_tables(documents: Iterable[Mapping]) -> dict[str, bool]:
    """``db.table -> is partitioned`` as the lineage's table metadata states it."""
    flags: dict[str, bool] = {}
    for _task, _statement_id, statement in _statements(documents):
        metadata = statement.get("related_metadata") or {}
        for key in ("input_tables", "output_tables"):
            for name, item in (metadata.get(key) or {}).items():
                table = (item or {}).get("table_metadata") or {}
                if table.get("is_partitioned") is not None:
                    flags.setdefault(bare_table(name), bool(table["is_partitioned"]))
    return flags


def _statements(documents: Iterable[Mapping]):
    """``(task, statement id, statement)`` of a task document or a statement document."""
    for document in documents:
        task = str(document.get("task_id") or "")
        lineage = document.get("statement_lineage")
        if isinstance(lineage, Mapping):
            for statement_id, statement in lineage.items():
                yield task, str(statement_id), statement
        elif document.get("scopes"):
            yield task, str(document.get("statement_id") or ""), document


# ------------------------------------------------------------------ one statement


@dataclass(frozen=True)
class _Condition:
    column: str
    literal: str
    sql: str
    table: Optional[str]  # the physical table the column belongs to, when known


@dataclass
class _Leaf:
    table: str
    column: str
    physical: bool
    joined: bool
    conditions: list = field(default_factory=list)
    rule: Optional[str] = None


@dataclass
class _Read:
    """One joined input a value is read through: ``rows of table where …``."""

    statement: tuple
    rule: str
    table: str
    where: dict
    reads: Optional[str] = None

    def identity(self) -> tuple:
        return (self.statement, self.rule, self.table, tuple(self.where.items()))


@dataclass
class _Column:
    name: str
    lookups: list = field(default_factory=list)
    fallback: list = field(default_factory=list)
    key_of: list = field(default_factory=list)

    def published(self, siblings: Mapping[str, "_Column"]) -> dict:
        if self.lookups:
            facts: dict = {
                "lookups": [
                    {"table": read.table, "where": dict(read.where), "reads": read.reads,
                     "rule": read.rule}
                    for read in self.lookups
                ]
            }
            if self.fallback:
                facts["fallback"] = list(self.fallback)
            return facts
        if not self.key_of:
            return {}
        ordered, known = _key_order(self.key_of, siblings)
        facts = {
            "key_of": [
                {"table": read.table, "where": dict(read.where), "rule": read.rule,
                 "read_by": _readers(read, siblings)}
                for read in ordered
            ]
        }
        if not known:
            facts["key_of_order"] = ORDER_UNKNOWN
        return facts


class _StatementReader:
    def __init__(self, statement_key: tuple, statement: Mapping, is_partition: PartitionTest):
        self.key = statement_key
        self.scopes: Mapping = statement.get("scopes") or {}
        self.is_partition = is_partition
        self.refs = {
            scope_id: {
                str(ref.get("input_ref_id")): ref
                for ref in scope.get("input_source_refs") or []
                if ref.get("input_ref_id")
            }
            for scope_id, scope in self.scopes.items()
        }

    # -------------------------------------------------------------- writer outputs

    def read(self, target: str, columns: dict) -> None:
        for name, scope_id, output in self._written(target):
            column = columns.setdefault(name, _Column(name))
            leaves, visited = self._trace_output(scope_id, output)
            reads = [self._read(leaf) for leaf in leaves]
            lookups = [read for read in reads if read is not None]
            known = {read.identity() for read in column.lookups}
            for read in lookups:
                if read.identity() not in known:
                    column.lookups.append(read)
                    known.add(read.identity())
            if lookups:
                for leaf, read in zip(leaves, reads):
                    reference = f"{bare_table(leaf.table)}.{leaf.column}"
                    if read is None and leaf.physical and reference not in column.fallback:
                        column.fallback.append(reference)
                continue
            known_keys = {read.identity() for read in column.key_of}
            for read in self._key_of(visited):
                if read.identity() not in known_keys:
                    column.key_of.append(read)
                    known_keys.add(read.identity())

    def _written(self, target: str):
        """``(column, scope id, output)`` for each target column a writer scope fills."""
        for scope_id, scope in self.scopes.items():
            if not scope.get("writes_to") and scope_id != "ROOT":
                continue
            taken: set[str] = set()
            for output in scope.get("outputs") or []:
                for reference in output.get("final_target_columns") or []:
                    table, _, column = str(reference).rpartition(".")
                    name = column.lower()
                    if bare_table(table) == target and name not in taken:
                        taken.add(name)
                        yield name, scope_id, output

    # -------------------------------------------------------------- value paths

    def _trace_output(self, scope_id: str, output: Mapping):
        visited: set[tuple[str, str]] = set()
        leaves = self._sources(scope_id, output, False, frozenset(), visited)
        return leaves, visited

    def _trace(self, scope_id: str, name: str, joined: bool, seen: frozenset, visited: set):
        key = (scope_id, str(name).lower())
        if key in seen or len(seen) > _MAX_DEPTH:
            return []
        scope = self.scopes.get(scope_id) or {}
        for output in scope.get("outputs") or []:
            if str(output.get("name")).lower() == key[1]:
                return self._sources(scope_id, output, joined, seen | {key}, visited)
        return []

    def _sources(self, scope_id, output, joined, seen, visited) -> list[_Leaf]:
        leaves: list[_Leaf] = []
        for source in output.get("sources") or []:
            ref_id = str(source.get("input_ref_id") or "")
            column = str(source.get("column") or "")
            if ref_id:
                visited.add((ref_id, column.lower()))
            ref = self.refs.get(scope_id, {}).get(ref_id, {})
            entered = ref.get("position") == "join"
            via = joined or entered
            conditions: list[_Condition] = []
            rule = None
            if entered:
                block = self._join_block(scope_id, ref_id)
                rule = str(block.get("logic_block_id")) if block else None
                conditions = self._join_conditions(block, ref_id) + self._where_on(
                    scope_id, ref_id, str(ref.get("alias") or "")
                )
            inner = source.get("scope")
            if inner in self.scopes:
                below = self._scope_filters(inner) if via else []
                for leaf in self._trace(inner, column, via, seen, visited):
                    leaf.conditions = conditions + below + leaf.conditions
                    leaf.rule = leaf.rule or rule
                    leaves.append(leaf)
            else:
                leaves.append(_Leaf(
                    table=str(inner or ""), column=column,
                    physical=ref.get("source_type") == "physical_table",
                    joined=via, conditions=conditions, rule=rule,
                ))
        return leaves

    def _read(self, leaf: _Leaf) -> Optional[_Read]:
        """The lookup ``leaf`` is read through, or None when it is not one."""
        if not (leaf.physical and leaf.joined and leaf.rule):
            return None
        where = self._where(leaf.conditions, bare_table(leaf.table))
        if not where:
            return None
        return _Read(self.key, leaf.rule, bare_table(leaf.table), where, leaf.column)

    def _where(self, conditions: list[_Condition], table: str) -> dict:
        where: dict[str, str] = {}
        for condition in conditions:
            owner = bare_table(condition.table) if condition.table else table
            if self.is_partition(f"{owner}.{condition.column}", condition.sql):
                continue
            where.setdefault(condition.column, condition.literal)
        return where

    # -------------------------------------------------------------- key of

    def _key_of(self, visited: set) -> list[_Read]:
        """The lookups whose join key (left side) is on this column's value path."""
        found: list[_Read] = []
        for scope_id, scope in self.scopes.items():
            for block in scope.get("logic_blocks") or []:
                detail = block.get("join_relation_detail") or {}
                for pair in detail.get("join_key_pairs") or []:
                    left, right = pair.get("left") or {}, pair.get("right") or {}
                    key = (str(left.get("input_ref_id") or ""), str(left.get("column") or "").lower())
                    if key not in visited or not right.get("input_ref_id"):
                        continue
                    read = self._join_read(scope_id, block, right)
                    if read is not None:
                        found.append(read)
                    break
        return found

    def _join_read(self, scope_id: str, block: Mapping, right: Mapping) -> Optional[_Read]:
        """The rows the JOIN's right side reads, traced from its key column."""
        ref_id = str(right.get("input_ref_id"))
        ref = self.refs.get(scope_id, {}).get(ref_id, {})
        conditions = self._join_conditions(block, ref_id) + self._where_on(
            scope_id, ref_id, str(ref.get("alias") or "")
        )
        inner = str(ref.get("source_id") or right.get("scope") or "")
        column = str(right.get("column") or "")
        if inner in self.scopes:
            below = self._scope_filters(inner)
            leaves = self._trace(inner, column, True, frozenset(), set())
            for leaf in leaves:
                leaf.conditions = conditions + below + leaf.conditions
        else:
            leaves = [_Leaf(inner, column, ref.get("source_type") == "physical_table", True,
                            conditions)]
        for leaf in leaves:
            leaf.rule = str(block.get("logic_block_id"))
            read = self._read(leaf)
            if read is not None:
                read.reads = None
                return read
        return None

    # -------------------------------------------------------------- conditions

    def _join_block(self, scope_id: str, ref_id: str) -> Optional[Mapping]:
        """The JOIN whose right side is ``ref_id``: by its key pairs, else its conditions."""
        blocks = [
            block for block in (self.scopes.get(scope_id) or {}).get("logic_blocks") or []
            if block.get("join_relation_detail")
        ]
        for block in blocks:
            for pair in block["join_relation_detail"].get("join_key_pairs") or []:
                if str((pair.get("right") or {}).get("input_ref_id")) == ref_id:
                    return block
        for block in blocks:
            for condition in block["join_relation_detail"].get("condition_filters") or []:
                if _only_ref(condition.get("fields"), ref_id):
                    return block
        return None

    def _join_conditions(self, block: Optional[Mapping], ref_id: str) -> list[_Condition]:
        if not block:
            return []
        found = []
        for condition in block["join_relation_detail"].get("condition_filters") or []:
            if not _only_ref(condition.get("fields"), ref_id):
                continue
            physical = condition.get("physical_fields") or []
            for parsed in _equalities(condition.get("expression")):
                _qualifier, name, literal, sql = parsed
                table = None
                if len(physical) == 1:
                    name = str(physical[0].get("field") or name)
                    table = physical[0].get("table")
                found.append(_Condition(name, literal, sql, table))
        return found

    def _where_on(self, scope_id: str, ref_id: str, alias: str) -> list[_Condition]:
        """``WHERE d.kind = 'X'`` on the joined alias itself: a condition of that read."""
        if not alias:
            return []
        found = []
        for item in (self.scopes.get(scope_id) or {}).get("filters") or []:
            columns = [c for c in item.get("columns") or [] if c.get("input_ref_id") == ref_id]
            for qualifier, name, literal, sql in _equalities(item.get("expression")):
                if qualifier.lower() != alias.lower():
                    continue
                found.append(_Condition(name, literal, sql, self._column_table(columns, name)))
        return found

    def _scope_filters(self, scope_id: str) -> list[_Condition]:
        """Every string equality in the WHERE of a scope a joined value passes through."""
        found = []
        for item in (self.scopes.get(scope_id) or {}).get("filters") or []:
            columns = list(item.get("columns") or [])
            for _qualifier, name, literal, sql in _equalities(item.get("expression")):
                found.append(_Condition(name, literal, sql, self._column_table(columns, name)))
        return found

    def _column_table(self, columns: list, name: str) -> Optional[str]:
        for column in columns:
            scope = str(column.get("scope") or "")
            if str(column.get("column")).lower() == name.lower() and scope not in self.scopes:
                return scope
        return None


def _only_ref(fields, ref_id: str) -> bool:
    refs = {str(item.get("input_ref_id")) for item in fields or []}
    return refs == {ref_id}


def _equalities(expression) -> list[tuple[str, str, str, str]]:
    """``(qualifier, column, literal, conjunct SQL)`` for each ``column = 'string'`` conjunct.

    The comparison is the glossary's (``_comparison``, ``_value_kind``): a ``${…}``
    parameter is not a literal, and only a quoted string is read.
    """
    text = _LEADING_KEYWORD.sub("", str(expression or ""))
    found = []
    for node in _conjuncts(semantic_text.parse_expression(text)):
        parsed = _comparison(node)
        if parsed is None or parsed[2] != CONTEXT_FILTER_EQ:
            continue
        column, [value], _context, _closes = parsed
        if not (isinstance(value, exp.Literal) and value.is_string):
            continue
        if _value_kind(value) != VALUE_KIND_LITERAL:
            continue
        named = next(side for side in (node.this, node.expression) if isinstance(side, exp.Column))
        # A trailing `/* … */` travels with the conjunct; the partition rule reads bare SQL.
        sql = node.sql(dialect="spark", comments=False)
        found.append((str(named.table or ""), column, str(value.this), sql))
    return found


# ------------------------------------------------------------------ key order


def _readers(read: _Read, siblings: Mapping[str, _Column]) -> list[str]:
    return [
        name for name, column in siblings.items()
        if any(_same_read(read, other) for other in column.lookups)
    ]


def _same_read(key: _Read, value: _Read) -> bool:
    return (key.statement, key.rule, key.table) == (value.statement, value.rule, value.table)


def _key_order(reads: list[_Read], siblings: Mapping[str, _Column]) -> tuple[list[_Read], bool]:
    """``reads`` in the order the columns reading them fall back through them.

    Each sibling whose lookups include two or more of these reads says which comes
    first. When no two siblings contradict each other the reads follow them (ties keep
    the JOIN order); when they do, the JOIN order is kept and the order is unknown.
    """
    before: set[tuple[int, int]] = set()
    for column in siblings.values():
        sequence = [
            index for other in column.lookups
            for index, read in enumerate(reads) if _same_read(read, other)
        ]
        sequence = list(dict.fromkeys(sequence))
        before.update(
            (first, second)
            for position, first in enumerate(sequence)
            for second in sequence[position + 1:]
        )
    if any((second, first) in before for first, second in before):
        return list(reads), False
    placed: list[int] = []
    remaining = list(range(len(reads)))
    while remaining:
        ready = next(
            (
                index for index in remaining
                if not any((other, index) in before for other in remaining if other != index)
            ),
            None,
        )
        if ready is None:  # a longer cycle (A before B before C before A): no order
            return list(reads), False
        placed.append(ready)
        remaining.remove(ready)
    return [reads[index] for index in placed], True
