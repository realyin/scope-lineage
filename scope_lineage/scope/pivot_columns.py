"""The column set a PIVOT or UNPIVOT produces, read from its AST (audit 1.7).

PIVOT keeps the pivoted relation's columns that neither an aggregate nor the FOR clause
reads -- its implicit grouping columns -- then adds, for each IN value, one column per
aggregate: named by the value alone when there is one aggregate, ``<value>_<alias>`` when
there are several (Spark's naming). Each pivoted column aggregates the rows whose FOR
column holds that value, so it reads the aggregate's columns and the FOR column.

UNPIVOT keeps the relation's columns outside the IN list, then adds the name column --
its values are the IN items' names, written by the statement -- and the value column,
which reads every IN column.

The relation's own column names are an input: without them the grouping columns (and an
UNPIVOT's kept columns) are unknowable and the caller keeps its narrower answer.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlglot import exp

GROUP = "group"
VALUE = "value"
NAME = "name"


@dataclass
class PivotColumn:
    """One output column of a PIVOT / UNPIVOT."""

    name: str
    kind: str  # group | value | name
    # The relation column a kept (group) column passes through.
    relation_column: str | None = None
    # The AST nodes a value column reads (aggregate + FOR column, or the IN columns).
    reads: list[exp.Expression] = field(default_factory=list)
    # The names a name column takes, one per IN item.
    constants: list[str] = field(default_factory=list)
    # A PIVOT value column aggregates; an UNPIVOT value column picks one IN column per row.
    aggregated: bool = False


def pivot_columns(pivot: exp.Pivot, relation_columns: list[str] | None) -> list[PivotColumn] | None:
    """The output columns, in Spark's order, or None when the set is unknowable."""
    if pivot.args.get("unpivot"):
        return _unpivot_columns(pivot, relation_columns)
    return _pivot_columns(pivot, relation_columns)


def _pivot_columns(pivot: exp.Pivot, relation_columns: list[str] | None) -> list[PivotColumn] | None:
    fields = pivot.args.get("fields") or []
    aggregates = list(pivot.expressions)
    if relation_columns is None or len(fields) != 1 or not isinstance(fields[0], exp.In) or not aggregates:
        return None
    values = _in_value_names(fields[0])
    suffixes = _aggregate_suffixes(aggregates)
    if values is None or suffixes is None:
        return None
    read = {
        column.name.lower()
        for node in [*aggregates, fields[0].this]
        for column in node.find_all(exp.Column)
    }
    columns = [
        PivotColumn(name=name.lower(), kind=GROUP, relation_column=name)
        for name in relation_columns
        if name.lower() not in read
    ]
    for value in values:
        for aggregate, suffix in zip(aggregates, suffixes):
            name = f"{value}_{suffix}" if suffix else value
            columns.append(
                PivotColumn(
                    name=name.lower(), kind=VALUE, reads=[aggregate, fields[0].this], aggregated=True
                )
            )
    return columns


def _unpivot_columns(pivot: exp.Pivot, relation_columns: list[str] | None) -> list[PivotColumn] | None:
    fields = pivot.args.get("fields") or []
    value_names = [node.name for node in pivot.expressions if isinstance(node, (exp.Identifier, exp.Column))]
    if relation_columns is None or len(fields) != 1 or not isinstance(fields[0], exp.In):
        return None
    if len(value_names) != 1 or len(value_names) != len(pivot.expressions):
        return None
    name_column = fields[0].this
    items = [item.this if isinstance(item, exp.Alias) else item for item in fields[0].expressions]
    if not isinstance(name_column, (exp.Identifier, exp.Column)) or not all(
        isinstance(item, exp.Column) for item in items
    ):
        return None
    unpivoted = {item.name.lower() for item in items}
    columns = [
        PivotColumn(name=name.lower(), kind=GROUP, relation_column=name)
        for name in relation_columns
        if name.lower() not in unpivoted
    ]
    columns.append(
        PivotColumn(
            name=name_column.name.lower(),
            kind=NAME,
            constants=[
                item.alias if isinstance(item, exp.Alias) else item.name
                for item in fields[0].expressions
            ],
        )
    )
    columns.append(PivotColumn(name=value_names[0].lower(), kind=VALUE, reads=list(items)))
    return columns


def _in_value_names(clause: exp.In) -> list[str] | None:
    names: list[str] = []
    for item in clause.expressions:
        if isinstance(item, exp.Alias):
            names.append(item.alias)
        elif isinstance(item, exp.Literal):
            names.append(str(item.this))
        else:
            return None
    return names or None


def _aggregate_suffixes(aggregates: list[exp.Expression]) -> list[str] | None:
    """``[""]`` for one aggregate; each one's alias for several (unaliased: unknowable)."""
    if len(aggregates) == 1:
        return [""]
    suffixes = [aggregate.alias if isinstance(aggregate, exp.Alias) else "" for aggregate in aggregates]
    return suffixes if all(suffixes) else None
