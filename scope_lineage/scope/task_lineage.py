"""Task-level table-state lineage for ordered Spark SQL statements."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

import sqlglot
from sqlglot import exp

from ..metadata.schema_metadata import DictSchemaProvider
from ._shared import DIALECT, PARSE_OPTS
from .scope_builder import (
    _is_ctas,
    _normalize_directory_insert_sql,
    _qualified_table,
    _statement_category,
    _statement_kind_label,
    _stmt_kind_for_tree,
    _syntax_status,
    parse_scope_lineage,
)


@dataclass
class TaskLineageResult:
    task_id: str
    parse_status: str
    syntax_status: str
    syntax_errors: list[dict] = field(default_factory=list)
    analysis_status: dict = field(default_factory=dict)
    statements: list[dict] = field(default_factory=list)
    table_state_graph: dict = field(default_factory=dict)
    final_table_states: dict[str, str] = field(default_factory=dict)
    statement_lineage: dict[str, object] = field(default_factory=dict)
    end_to_end_lineage: list[dict] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)
    task_dependencies: dict = field(default_factory=dict)


@dataclass
class _State:
    state_id: str
    table: str
    ordinal: int
    known_empty: bool
    value_sources: dict[str, list[dict]]
    row_membership_sources: list[dict] = field(default_factory=list)
    value_condition_sources: dict[str, list[dict]] = field(default_factory=dict)
    columns_known: bool = True
    missing_reasons: list[str] = field(default_factory=list)


class _StateBuilder:
    def __init__(self, schema: Mapping[str, Iterable[str]] | None):
        self.schema_provider = DictSchemaProvider(schema)
        self.states: dict[str, _State] = {}
        self.current_by_table: dict[str, _State] = {}
        self.nodes: list[dict] = []
        self.edges: list[dict] = []

    def current(self, table: str) -> _State:
        current = self.current_by_table.get(table)
        if current is not None:
            return current
        columns = self.schema_provider.get_columns(table)
        state_id = _state_id(table, 0)
        value_sources = {
            column: [_prior_state_source(state_id, table, column)]
            for column in (columns or [])
        }
        current = _State(
            state_id=state_id,
            table=table,
            ordinal=0,
            known_empty=False,
            value_sources=value_sources,
            columns_known=columns is not None,
            missing_reasons=(
                []
                if columns is not None
                else ["schema_missing_for_state_passthrough"]
            ),
        )
        self._add(current, producer_statement_id=None)
        return current

    def transition(
        self,
        previous: _State | None,
        *,
        table: str,
        statement_id: str,
        effect: str,
        known_empty: bool,
        value_sources: dict[str, list[dict]],
        row_membership_sources: list[dict] | None = None,
        value_condition_sources: dict[str, list[dict]] | None = None,
        columns_known: bool = True,
        missing_reasons: list[str] | None = None,
    ) -> _State:
        ordinal = (previous.ordinal + 1) if previous is not None else 1
        state = _State(
            state_id=_state_id(table, ordinal),
            table=table,
            ordinal=ordinal,
            known_empty=known_empty,
            value_sources=value_sources,
            row_membership_sources=list(row_membership_sources or []),
            value_condition_sources={
                key: list(value)
                for key, value in (value_condition_sources or {}).items()
            },
            columns_known=columns_known,
            missing_reasons=list(missing_reasons or []),
        )
        self._add(state, producer_statement_id=statement_id)
        if previous is not None:
            self.edges.append({
                "from": previous.state_id,
                "to": state.state_id,
                "statement_id": statement_id,
                "effect": effect,
            })
        return state

    def _add(self, state: _State, producer_statement_id: str | None) -> None:
        self.states[state.state_id] = state
        self.current_by_table[state.table] = state
        self.nodes.append({
            "state_id": state.state_id,
            "table": state.table,
            "ordinal": state.ordinal,
            "known_empty": state.known_empty,
            "columns_known": state.columns_known,
            "producer_statement_id": producer_statement_id,
        })

    def graph(self) -> dict:
        return {
            "nodes": list(self.nodes),
            "edges": list(self.edges),
            "nodes_by_id": {
                item["state_id"]: dict(item)
                for item in self.nodes
            },
        }

    def end_to_end(self) -> list[dict]:
        items: list[dict] = []
        for table in sorted(self.current_by_table):
            state = self.current_by_table[table]
            for column, sources in state.value_sources.items():
                items.append({
                    "target_state": state.state_id,
                    "table": table,
                    "column": column,
                    "value_sources": _dedupe_dicts(sources),
                    "row_membership_sources": _dedupe_dicts(
                        state.row_membership_sources
                    ),
                    "value_condition_sources": _dedupe_dicts(
                        state.value_condition_sources.get(column, [])
                    ),
                    "trace_complete": state.columns_known,
                    "missing_reasons": list(state.missing_reasons),
                })
        return items


def parse_task_lineage(
    sql: str,
    task_name: str,
    schema: Mapping[str, Iterable[str]] | None = None,
    target_metadata=None,
    task_dependencies: dict | None = None,
) -> TaskLineageResult:
    """Parse an ordered SQL script into table-state and statement lineage."""
    normalized = _normalize_directory_insert_sql(sql)
    trees = sqlglot.parse(normalized, dialect=DIALECT, **PARSE_OPTS)
    syntax_status, syntax_errors = _syntax_status(sql)
    state_builder = _StateBuilder(schema)
    statements: list[dict] = []
    statement_lineage: dict[str, object] = {}
    warnings: list[dict] = []
    gaps: list[dict] = []
    parse_failed = False
    unsupported_data_changes = 0

    for statement_index, tree in enumerate(trees):
        statement_id = f"stmt:{statement_index + 1:03d}"
        if tree is None:
            statements.append({
                "statement_id": statement_id,
                "statement_index": statement_index,
                "stmt_kind": "EMPTY",
                "category": "empty_statement",
                "model_status": "ignored",
                "normalized_sql": "",
            })
            continue
        statement = _statement_record(statement_id, statement_index, tree)
        try:
            if _is_projection_write(tree):
                _apply_projection_write(
                    statement,
                    tree,
                    task_name,
                    schema,
                    target_metadata,
                    state_builder,
                    statement_lineage,
                    gaps,
                )
            elif isinstance(tree, exp.Delete):
                _apply_delete(statement, tree, state_builder, gaps)
            elif isinstance(tree, exp.TruncateTable):
                _apply_truncate(statement, tree, state_builder)
            elif isinstance(tree, exp.Update):
                _apply_update(statement, tree, state_builder, gaps)
            elif statement["category"] in {
                "control_statement",
                "empty_statement",
            }:
                statement["model_status"] = "ignored"
            else:
                unsupported_data_changes += 1
                warnings.append({
                    "statement_id": statement_id,
                    "type": "unsupported_statement",
                    "scope": "TASK",
                    "msg": (
                        f"{statement['stmt_kind']} is not modeled by task lineage"
                    ),
                })
        except Exception as exc:
            parse_failed = True
            statement["model_status"] = "failed"
            warnings.append({
                "statement_id": statement_id,
                "type": "LINEAGE_ERROR",
                "scope": "TASK",
                "msg": f"{type(exc).__name__}: {exc}",
            })
        statements.append(statement)

    gaps.extend(_statement_fact_gaps(statement_lineage))
    partial = bool(
        syntax_status != "strict_ok"
        or unsupported_data_changes
        or gaps
        or any(item["model_status"] == "failed" for item in statements)
    )
    analysis_status = {
        "status": "partial" if partial else "complete",
        "blocking_reasons": _analysis_blocking_reasons(
            syntax_status,
            unsupported_data_changes,
            gaps,
            statements,
        ),
    }
    result = TaskLineageResult(
        task_id=task_name,
        parse_status="failed" if parse_failed else "ok",
        syntax_status=syntax_status,
        syntax_errors=syntax_errors,
        analysis_status=analysis_status,
        statements=statements,
        table_state_graph=state_builder.graph(),
        final_table_states={
            table: state.state_id
            for table, state in sorted(state_builder.current_by_table.items())
        },
        statement_lineage=statement_lineage,
        end_to_end_lineage=state_builder.end_to_end(),
        diagnostics={
            "warnings": warnings,
            "lineage_fact_gaps": gaps,
            "metadata_coverage": _metadata_coverage(
                state_builder,
                statement_lineage,
                statements,
                schema,
            ),
            "stats": {
                "statement_count": len(statements),
                "modeled_statement_count": sum(
                    item["model_status"] == "modeled" for item in statements
                ),
                "ignored_statement_count": sum(
                    item["model_status"] == "ignored" for item in statements
                ),
                "failed_statement_count": sum(
                    item["model_status"] == "failed" for item in statements
                ),
            },
        },
        task_dependencies=dict(task_dependencies or {}),
    )
    return result


def _statement_record(
    statement_id: str,
    statement_index: int,
    tree: exp.Expression,
) -> dict:
    if _is_projection_write(tree):
        kind = _stmt_kind_for_tree(tree)
        category = (
            "conditional_write"
            if kind == "MERGE"
            else "projection_write"
        )
    else:
        kind = _statement_kind_label(tree)
        category = _statement_category(kind)
    return {
        "statement_id": statement_id,
        "statement_index": statement_index,
        "stmt_kind": kind,
        "category": category,
        "model_status": (
            "ignored"
            if category in {"control_statement", "empty_statement"}
            else "unsupported"
        ),
        "normalized_sql": tree.sql(dialect=DIALECT),
    }


def _is_projection_write(tree: exp.Expression) -> bool:
    return bool(
        isinstance(tree, (exp.Insert, exp.Merge))
        or _is_ctas(tree)
        or tree.find(exp.Insert) is not None
        or tree.find(exp.Merge) is not None
    )


def _apply_projection_write(
    statement: dict,
    tree: exp.Expression,
    task_name: str,
    schema,
    target_metadata,
    states: _StateBuilder,
    statement_lineage: dict[str, object],
    gaps: list[dict],
) -> None:
    from ..contract.lineage import to_lineage_dict

    result = parse_scope_lineage(
        tree.sql(dialect=DIALECT),
        task_name=f"{task_name}#{statement['statement_index']}",
        schema=dict(schema or {}),
        target_metadata=target_metadata,
    )
    statement_id = statement["statement_id"]
    statement["model_status"] = "modeled"
    statement["target_table"] = result.target_table
    statement["target_field_binding"] = _target_binding_observation(
        result.target_field_binding,
        metadata_requested=target_metadata is not None,
    )
    previous = None if result.stmt_kind == "CTAS" else states.current(
        result.target_table
    )
    written_values = _write_value_sources(result)
    state_missing_reasons = _projection_state_missing_reasons(
        result,
        written_values,
    )
    if "projection_wildcard_unexpanded" in state_missing_reasons:
        gaps.append({
            "gap_type": "projection_wildcard_unexpanded",
            "statement_id": statement_id,
            "target_table": result.target_table,
            "root_impact": True,
            "needed_fact": "source schema for wildcard expansion",
        })
    effect = _write_effect(result)
    if (
        effect in {"APPEND", "MERGE", "REPLACE_PARTITION"}
        and previous is not None
        and not previous.columns_known
    ):
        state_missing_reasons = list(dict.fromkeys([
            *state_missing_reasons,
            *previous.missing_reasons,
        ]))
    merge_conditions = (
        _merge_condition_sources(tree, target_table=result.target_table)
        if isinstance(tree, exp.Merge)
        else []
    )
    if effect in {"APPEND", "REPLACE_PARTITION"} and previous is not None:
        value_sources = _merge_value_sources(
            _prior_values_for_written_columns(previous, written_values),
            written_values,
        )
    elif effect == "MERGE" and previous is not None:
        value_sources = _merge_value_sources(
            _prior_values_for_written_columns(previous, written_values),
            written_values,
        )
    else:
        value_sources = written_values
    columns_known = not state_missing_reasons and (
        bool(value_sources)
        or (previous.columns_known if previous is not None else False)
    )
    row_membership_sources = (
        list(previous.row_membership_sources)
        if effect in {"APPEND", "MERGE", "REPLACE_PARTITION"}
        and previous is not None
        else []
    )
    if effect == "MERGE":
        row_membership_sources = _dedupe_dicts([
            *row_membership_sources,
            *merge_conditions,
        ])
    value_condition_sources = (
        {
            column: list(sources)
            for column, sources in previous.value_condition_sources.items()
        }
        if effect in {"APPEND", "MERGE", "REPLACE_PARTITION"}
        and previous is not None
        else {}
    )
    if effect == "MERGE":
        for column in written_values:
            value_condition_sources[column] = _dedupe_dicts([
                *value_condition_sources.get(column, []),
                *merge_conditions,
            ])
    state = states.transition(
        previous,
        table=result.target_table,
        statement_id=statement_id,
        effect=effect,
        known_empty=False,
        value_sources=value_sources,
        row_membership_sources=row_membership_sources,
        value_condition_sources=value_condition_sources,
        columns_known=columns_known,
        missing_reasons=state_missing_reasons,
    )
    statement["input_states"] = (
        [previous.state_id] if previous is not None else []
    )
    statement["output_state"] = state.state_id
    statement["effect"] = {
        "rowset_effect": {
            "operation": effect,
            **(
                {"membership_sources": merge_conditions}
                if effect == "MERGE"
                else {}
            ),
        },
        "column_effect": {"value_mode": "WRITE_PROJECTION"},
    }
    statement_lineage[statement_id] = to_lineage_dict(result)


def _apply_delete(
    statement: dict,
    tree: exp.Delete,
    states: _StateBuilder,
    gaps: list[dict],
) -> None:
    table = _table_name(tree.this)
    previous = states.current(table)
    where = tree.args.get("where")
    predicate = where.this if isinstance(where, exp.Where) else None
    membership_sources = _expression_field_sources(predicate, target_table=table)
    deletes_all_rows = predicate is None
    all_membership = _dedupe_dicts([
        *previous.row_membership_sources,
        *membership_sources,
    ])
    state = states.transition(
        previous,
        table=table,
        statement_id=statement["statement_id"],
        effect="RESET" if deletes_all_rows else "ANTI_FILTER",
        known_empty=deletes_all_rows or previous.known_empty,
        value_sources=(
            _empty_column_values(previous)
            if deletes_all_rows
            else {
                column: list(sources)
                for column, sources in previous.value_sources.items()
            }
        ),
        row_membership_sources=all_membership,
        value_condition_sources=previous.value_condition_sources,
        columns_known=previous.columns_known,
        missing_reasons=previous.missing_reasons,
    )
    statement.update({
        "model_status": "modeled",
        "target_table": table,
        "input_states": [previous.state_id],
        "output_state": state.state_id,
        "effect": {
            "rowset_effect": {
                "operation": (
                    "DELETE_ALL_ROWS"
                    if deletes_all_rows
                    else "DELETE_MATCHED_ROWS"
                ),
                "predicate_expression": (
                    predicate.sql(dialect=DIALECT) if predicate is not None else None
                ),
                "membership_sources": membership_sources,
            },
            "column_effect": {
                "value_mode": (
                    "NO_SURVIVING_ROWS"
                    if deletes_all_rows
                    else "PASSTHROUGH_SURVIVING_ROWS"
                ),
                "value_changed_columns": [],
                "row_membership_affected_columns": ["*"],
            },
        },
    })
    if not previous.columns_known:
        gaps.append(_schema_passthrough_gap(statement, table))


def _apply_truncate(
    statement: dict,
    tree: exp.TruncateTable,
    states: _StateBuilder,
) -> None:
    tables = list(tree.args.get("expressions") or [])
    table = _table_name(tables[0]) if tables else ""
    previous = states.current(table)
    partition = tree.args.get("partition")
    partition_only = isinstance(partition, exp.Partition)
    membership_sources = _expression_field_sources(
        partition if partition_only else None,
        target_table=table,
    )
    state = states.transition(
        previous,
        table=table,
        statement_id=statement["statement_id"],
        effect="RESET_PARTITION" if partition_only else "RESET",
        known_empty=previous.known_empty if partition_only else True,
        value_sources=(
            {
                column: list(sources)
                for column, sources in previous.value_sources.items()
            }
            if partition_only
            else _empty_column_values(previous)
        ),
        row_membership_sources=_dedupe_dicts([
            *previous.row_membership_sources,
            *membership_sources,
        ]),
        value_condition_sources=previous.value_condition_sources,
        columns_known=previous.columns_known,
        missing_reasons=previous.missing_reasons,
    )
    statement.update({
        "model_status": "modeled",
        "target_table": table,
        "input_states": [previous.state_id],
        "output_state": state.state_id,
        "effect": {
            "rowset_effect": {
                "operation": (
                    "RESET_PARTITION" if partition_only else "RESET_ALL_ROWS"
                ),
                "partition_expression": (
                    partition.sql(dialect=DIALECT) if partition_only else None
                ),
                "membership_sources": membership_sources,
            },
            "column_effect": {
                "schema_preserved": True,
                "value_mode": (
                    "PASSTHROUGH_UNAFFECTED_PARTITIONS"
                    if partition_only
                    else "NO_SURVIVING_ROWS"
                ),
                "row_membership_affected_columns": ["*"],
            },
        },
    })


def _apply_update(
    statement: dict,
    tree: exp.Update,
    states: _StateBuilder,
    gaps: list[dict],
) -> None:
    table = _table_name(tree.this)
    previous = states.current(table)
    where = tree.args.get("where")
    predicate = where.this if isinstance(where, exp.Where) else None
    condition_sources = _expression_field_sources(predicate, target_table=table)
    changed: list[str] = []
    assignments: list[dict] = []
    value_sources = {
        column: list(sources)
        for column, sources in previous.value_sources.items()
    }
    value_conditions = {
        column: list(sources)
        for column, sources in previous.value_condition_sources.items()
    }
    for assignment in tree.expressions:
        if not isinstance(assignment, exp.EQ) or not isinstance(
            assignment.this, exp.Column
        ):
            continue
        column = assignment.this.name
        changed.append(column)
        expression_sources = _expression_field_sources(
            assignment.expression,
            target_table=table,
        )
        value_sources[column] = _dedupe_dicts([
            *value_sources.get(
                column,
                [_prior_state_source(previous.state_id, table, column)],
            ),
            *[
                {
                    "source_kind": "physical_field",
                    **source,
                    "transform": "EXPRESSION",
                }
                for source in expression_sources
            ],
        ])
        value_conditions[column] = _dedupe_dicts([
            *value_conditions.get(column, []),
            *condition_sources,
        ])
        assignments.append({
            "column": column,
            "expression": assignment.expression.sql(dialect=DIALECT),
            "value_sources": expression_sources,
        })
    state = states.transition(
        previous,
        table=table,
        statement_id=statement["statement_id"],
        effect="CONDITIONAL_UPDATE",
        known_empty=previous.known_empty,
        value_sources=value_sources,
        row_membership_sources=previous.row_membership_sources,
        value_condition_sources=value_conditions,
        columns_known=previous.columns_known,
        missing_reasons=previous.missing_reasons,
    )
    statement.update({
        "model_status": "modeled",
        "target_table": table,
        "input_states": [previous.state_id],
        "output_state": state.state_id,
        "effect": {
            "rowset_effect": {"operation": "PRESERVE_ROWS"},
            "column_effect": {
                "value_mode": "CONDITIONAL_ASSIGNMENT",
                "value_changed_columns": changed,
                "value_passthrough_columns": [
                    column
                    for column in previous.value_sources
                    if column not in set(changed)
                ],
            },
            "predicate_expression": (
                predicate.sql(dialect=DIALECT) if predicate is not None else None
            ),
            "condition_sources": condition_sources,
            "assignments": assignments,
        },
    })
    if not previous.columns_known:
        gaps.append(_schema_passthrough_gap(statement, table))


def _write_effect(result) -> str:
    if result.stmt_kind == "INSERT":
        return "APPEND"
    if (
        result.stmt_kind == "INSERT_OVERWRITE"
        and result.target_partition_mode != "none"
    ):
        return "REPLACE_PARTITION"
    if result.stmt_kind in {"INSERT_OVERWRITE", "CTAS"}:
        return "REPLACE"
    if result.stmt_kind == "MERGE":
        return "MERGE"
    return "WRITE"


def _target_binding_observation(
    binding: dict,
    *,
    metadata_requested: bool,
) -> dict:
    if not binding:
        return {
            "status": "absent",
            "reason_code": (
                "target_table_not_found"
                if metadata_requested
                else "metadata_not_provided"
            ),
        }
    issues = list(binding.get("issues") or [])
    reason_code = None
    if binding.get("status") == "fallback":
        reason_code = _binding_reason_code(issues)
    return {
        **dict(binding),
        **({"reason_code": reason_code} if reason_code else {}),
    }


def _binding_reason_code(issues: list[str]) -> str:
    if any(item.startswith("target_metadata_invalid:") for item in issues):
        return "metadata_unusable"
    if any(item.startswith("projection_target_count_mismatch:") for item in issues):
        return "column_count_mismatch"
    if any(item.startswith("insert_partition_not_in_target_metadata:") for item in issues):
        return "partition_alignment_mismatch"
    if "target_column_names_not_unique" in issues:
        return "ddl_schema_conflict"
    return "binding_not_applicable"


def _write_value_sources(result) -> dict[str, list[dict]]:
    from .end_to_end import build_end_to_end_lineage

    values: dict[str, list[dict]] = {}
    for item in build_end_to_end_lineage(result):
        sources = [
            {
                "source_kind": "physical_field",
                "table": source["table"],
                "column": source["column"],
                "transform": source.get("transform", item.get("transform", "DIRECT")),
            }
            for source in item.get("physical_sources", [])
        ]
        for generated in item.get("generated_sources", []):
            sources.append({
                "source_kind": "generated",
                **dict(generated),
            })
        values[item["column"]] = _dedupe_dicts(sources)
    return values


def _projection_state_missing_reasons(
    result,
    written_values: dict[str, list[dict]],
) -> list[str]:
    if "*" in written_values or any(
        source.get("column") == "*"
        for sources in written_values.values()
        for source in sources
    ):
        return ["projection_wildcard_unexpanded"]
    if any(
        gap.get("root_impact")
        for gap in result.diagnostics.lineage_fact_gaps
        if isinstance(gap, dict)
    ):
        return ["projection_lineage_fact_gap"]
    if not written_values:
        return ["projection_has_no_resolved_target_fields"]
    return []


def _prior_values_for_written_columns(
    previous: _State,
    written: dict[str, list[dict]],
) -> dict[str, list[dict]]:
    result = {
        column: list(sources)
        for column, sources in previous.value_sources.items()
    }
    for column in written:
        result.setdefault(
            column,
            [_prior_state_source(previous.state_id, previous.table, column)],
        )
    return result


def _merge_value_sources(*mappings) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for mapping in mappings:
        for column, sources in mapping.items():
            result[column] = _dedupe_dicts([
                *result.get(column, []),
                *sources,
            ])
    return result


def _empty_column_values(previous: _State) -> dict[str, list[dict]]:
    return {column: [] for column in previous.value_sources}


def _expression_field_sources(
    expression: exp.Expression | None,
    *,
    target_table: str,
    aliases: Mapping[str, str] | None = None,
) -> list[dict]:
    if expression is None:
        return []
    sources: list[dict] = []
    for column in expression.find_all(exp.Column):
        select = column.find_ancestor(exp.Select)
        if select is None:
            table = (
                (aliases or {}).get(column.table.lower(), column.table)
                if column.table
                else target_table
            )
        else:
            direct_tables = [
                item
                for item in select.find_all(exp.Table)
                if item.find_ancestor(exp.Select) is select
            ]
            aliases = {
                (item.alias_or_name or "").lower(): _table_name(item)
                for item in direct_tables
            }
            if column.table:
                table = aliases.get(column.table.lower(), column.table)
            elif len(direct_tables) == 1:
                table = _table_name(direct_tables[0])
            else:
                table = "UNKNOWN"
        sources.append({"table": table, "column": column.name})
    return _dedupe_dicts(sources)


def _merge_condition_sources(
    tree: exp.Merge,
    *,
    target_table: str,
) -> list[dict]:
    aliases: dict[str, str] = {}
    target = tree.this
    if isinstance(target, exp.Table):
        aliases[(target.alias_or_name or target.name).lower()] = target_table
    using = tree.args.get("using")
    if isinstance(using, exp.Table):
        aliases[(using.alias_or_name or using.name).lower()] = _table_name(using)
    elif isinstance(using, exp.Expression):
        physical_tables = [
            _table_name(table)
            for table in using.find_all(exp.Table)
        ]
        aliases[(using.alias_or_name or "source").lower()] = (
            physical_tables[0]
            if len(set(physical_tables)) == 1
            else "UNKNOWN"
        )
    expressions = [tree.args.get("on")]
    whens = tree.args.get("whens")
    if whens is not None:
        expressions.extend(
            when.args.get("condition")
            for when in getattr(whens, "expressions", [])
        )
    sources: list[dict] = []
    for expression in expressions:
        sources.extend(
            _expression_field_sources(
                expression,
                target_table=target_table,
                aliases=aliases,
            )
        )
    return _dedupe_dicts(sources)


def _table_name(table: exp.Expression | None) -> str:
    return _qualified_table(table) if isinstance(table, exp.Table) else ""


def _state_id(table: str, ordinal: int) -> str:
    return f"state:{table}:{ordinal:03d}"


def _prior_state_source(state_id: str, table: str, column: str) -> dict:
    return {
        "source_kind": "prior_table_state",
        "state_id": state_id,
        "table": table,
        "column": column,
    }


def _schema_passthrough_gap(statement: dict, table: str) -> dict:
    return {
        "gap_type": "schema_missing_for_state_passthrough",
        "statement_id": statement["statement_id"],
        "target_table": table,
        "root_impact": True,
        "needed_fact": "target table columns",
    }


def _analysis_blocking_reasons(
    syntax_status: str,
    unsupported_data_changes: int,
    gaps: list[dict],
    statements: list[dict],
) -> list[str]:
    reasons: list[str] = []
    if syntax_status != "strict_ok":
        reasons.append("syntax_recovered")
    if unsupported_data_changes:
        reasons.append("unsupported_data_change")
    if gaps:
        reasons.append("lineage_fact_gap")
    if any(item["model_status"] == "failed" for item in statements):
        reasons.append("statement_failed")
    return reasons


def _statement_fact_gaps(statement_lineage: Mapping[str, object]) -> list[dict]:
    result: list[dict] = []
    for statement_id, lineage in statement_lineage.items():
        if not isinstance(lineage, dict):
            continue
        diagnostics = lineage.get("diagnostics") or {}
        for gap in diagnostics.get("lineage_fact_gaps") or []:
            if isinstance(gap, dict):
                result.append({"statement_id": statement_id, **dict(gap)})
    return result


def _metadata_coverage(
    states: _StateBuilder,
    statement_lineage: dict[str, object],
    statements: list[dict],
    schema,
) -> dict:
    referenced: set[str] = set(states.current_by_table)
    for lineage in statement_lineage.values():
        referenced.update(lineage.get("source_tables") or [])
        target = lineage.get("target_table")
        if target:
            referenced.add(target)
    for statement in statements:
        effect = statement.get("effect") or {}
        rowset = effect.get("rowset_effect") or {}
        for source in rowset.get("membership_sources") or []:
            table = source.get("table")
            if table and table != "UNKNOWN":
                referenced.add(table)
    covered = sorted(
        table
        for table in referenced
        if states.schema_provider.get_columns(table) is not None
    )
    missing = sorted(set(referenced) - set(covered))
    return {
        "referenced_table_count": len(referenced),
        "covered_table_count": len(covered),
        "missing_table_count": len(missing),
        "covered_tables": covered,
        "missing_tables": missing,
        "schema_source_count": getattr(schema, "metadata_source_count", 0)
        if schema is not None
        else 0,
        "metadata_conflicts": [
            dict(item)
            for item in getattr(schema, "metadata_conflicts", [])
            if item.get("table") in referenced
        ],
    }


def _dedupe_dicts(items: Iterable[dict]) -> list[dict]:
    result: list[dict] = []
    seen: set[tuple] = set()
    for item in items:
        key = tuple(sorted((key, repr(value)) for key, value in item.items()))
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(item))
    return result
