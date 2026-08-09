"""Column Ref Resolver — a subsystem extracted from a downstream builder.

Plain module-level functions (previously the ColumnRefResolverEngine class). The orchestrating
module imports and calls these; see its wrapper for the public entry point.
"""
from __future__ import annotations
from typing import List
from sqlglot import exp
from sqlglot.errors import OptimizeError
from sqlglot.optimizer.scope import Scope

# UNION / EXCEPT / INTERSECT share a base class in current sqlglot; older builds only expose
# Union. Both shapes answer `.named_selects` and carry branches in `.this` / `.expression`.
_SET_OPERATION = getattr(exp, 'SetOperation', exp.Union)
from .parser import (
    _qualified_table,
    _normalize_table_name,
)
from .scope_types import (
    AMBIGUOUS_SCOPE_ID,
    SourceRef,
    ScopeLineageResult,
    DiagnosticWarning,
)
# Leaf helpers come from `_shared`, never from the orchestrator: importing it back
# formed a cycle that only worked because Python hands out a partially-initialised
# module, making import order load-bearing (ARCH-001).
from ._shared import (
    _find_alias_in_parent,
    _ORIGINALLY_UNQUALIFIED_META,
    _SCOPE_ID_ATTR,
    _inside_nested_query,
    _selected_sources,
    _source_item_from_ast_node,
    _source_ref_binding_key,
    _source_ref_for_source,
    _source_scope_id,
)


def _resolve_column_refs_in_expr(expr: exp.Expression, sg_scope: Scope, result: ScopeLineageResult, schema: dict | None=None) -> List[SourceRef]:
    """Find all exp.Column references in an expression and resolve to SourceRefs.

    Deduplicates by field plus structural SQL input identity.
    """
    seen: set = set()
    sources: list = []
    for col_ref in expr.find_all(exp.Column):
        if _inside_nested_query(col_ref, expr):
            continue
        src = _resolve_column_ref(col_ref, sg_scope, result, schema)
        if src and _source_ref_binding_key(src) not in seen:
            seen.add(_source_ref_binding_key(src))
            sources.append(src)
    return sources


def _resolve_column_ref(col_ref: exp.Column, sg_scope: Scope, result: ScopeLineageResult, schema: dict | None=None) -> SourceRef | None:
    """Resolve a single exp.Column to a SourceRef(scope_id, column_name).

    Decision tree:
      1. Qualified (col_ref.table set): look up in sg_scope.sources
      2. Unqualified: search Scope sources first, then Table sources
      3. Not found: return SourceRef("UNKNOWN", col_name) + warning
    """
    table_alias = (
        ""
        if col_ref.meta.get(_ORIGINALLY_UNQUALIFIED_META)
        else col_ref.table
    )
    col_name = col_ref.name
    struct_ref = _resolve_struct_field_ref(col_ref, sg_scope, result)
    if struct_ref:
        return struct_ref
    if table_alias:
        duplicate_src = _resolve_duplicate_alias_ref(table_alias, col_name, sg_scope, result, schema)
        if duplicate_src is not None:
            return duplicate_src
        src = sg_scope.sources.get(table_alias)
        if isinstance(src, (Scope, exp.Table)):
            return _bound_source_ref(table_alias, src, col_name, sg_scope, result)
        try:
            _sel = sg_scope.selected_sources
        except OptimizeError:
            result.diagnostics.warnings.append(DiagnosticWarning(type='duplicate_alias', scope=getattr(sg_scope, _SCOPE_ID_ATTR, 'UNKNOWN'), msg=f"scope.selected_sources raised OptimizeError while resolving alias '{table_alias}' — likely caused by a duplicate subquery alias in the FROM clause. Column resolution skipped."))
            return SourceRef(scope='UNKNOWN', column=col_name)
        sel_src = _sel.get(table_alias)
        if sel_src:
            (_node, source) = sel_src
            if isinstance(source, (Scope, exp.Table)):
                return _bound_source_ref(
                    table_alias,
                    source,
                    col_name,
                    sg_scope,
                    result,
                )
        parent_binding = _lookup_alias_binding_in_parent_scopes(
            table_alias,
            sg_scope,
        )
        if parent_binding:
            parent_scope, source = parent_binding
            return _bound_source_ref(
                table_alias,
                source,
                col_name,
                parent_scope,
                result,
            )
        result.diagnostics.warnings.append(DiagnosticWarning(type='unresolved_alias', scope=getattr(sg_scope, _SCOPE_ID_ATTR, 'UNKNOWN'), msg=f"Alias '{table_alias}' not found in scope sources"))
        return SourceRef(scope='UNKNOWN', column=col_name)
    else:
        return _resolve_unqualified(col_name, sg_scope, result, schema)


def _resolve_struct_field_ref(
    col_ref: exp.Column,
    sg_scope: Scope,
    result: ScopeLineageResult,
) -> SourceRef | None:
    """Resolve ``alias.struct_col.field`` as lineage from ``alias.struct_col``."""
    parts = [p.name if hasattr(p, 'name') else str(p) for p in col_ref.parts or []]
    if len(parts) < 3:
        return None
    source_alias = parts[0]
    base_column = parts[1]
    binding_scope = sg_scope
    source = sg_scope.sources.get(source_alias)
    if not isinstance(source, (Scope, exp.Table)):
        parent_binding = _lookup_alias_binding_in_parent_scopes(
            source_alias,
            sg_scope,
        )
        if parent_binding:
            binding_scope, source = parent_binding
    if not isinstance(source, (Scope, exp.Table)):
        return None
    return _bound_source_ref(
        source_alias,
        source,
        base_column,
        binding_scope,
        result,
    )


def _lookup_source_in_scope_chain(alias: str, sg_scope: Scope) -> Scope | exp.Table | None:
    """Find a source alias in the current scope or an ancestor scope."""
    src = sg_scope.sources.get(alias)
    if isinstance(src, (Scope, exp.Table)):
        return src
    try:
        selected = sg_scope.selected_sources.get(alias)
    except OptimizeError:
        selected = None
    if selected:
        (_node, source) = selected
        if isinstance(source, (Scope, exp.Table)):
            return source
    return _lookup_alias_in_parent_scopes(alias, sg_scope)


def _lookup_alias_in_parent_scopes(table_alias: str, sg_scope: Scope) -> Scope | exp.Table | None:
    """Find a correlated reference alias in ancestor scopes."""
    binding = _lookup_alias_binding_in_parent_scopes(table_alias, sg_scope)
    return binding[1] if binding else None


def _lookup_alias_binding_in_parent_scopes(
    table_alias: str,
    sg_scope: Scope,
) -> tuple[Scope, Scope | exp.Table] | None:
    """Find the ancestor scope that declares a correlated source alias."""
    parent = sg_scope.parent
    while parent is not None:
        src = parent.sources.get(table_alias)
        if isinstance(src, (Scope, exp.Table)):
            return parent, src
        try:
            sel_src = parent.selected_sources.get(table_alias)
        except OptimizeError:
            sel_src = None
        if sel_src:
            (_node, source) = sel_src
            if isinstance(source, (Scope, exp.Table)):
                return parent, source
        parent = parent.parent
    return None


def _bound_source_ref(
    alias: str,
    source: Scope | exp.Table,
    column: str,
    binding_scope: Scope,
    result: ScopeLineageResult,
) -> SourceRef:
    """Build a SourceRef tied to the exact FROM/JOIN input that supplied it."""
    ref = _source_ref_for_source(alias, source, column, result)
    ref.qualifier = alias or None
    ref.binding_scope_id = getattr(binding_scope, _SCOPE_ID_ATTR, None)
    ref.input_ref_id = _input_ref_id_for_source_alias(
        binding_scope,
        alias,
        source,
    )
    return ref


def _input_ref_id_for_source_alias(
    binding_scope: Scope,
    alias: str,
    source: Scope | exp.Table,
) -> str | None:
    """Mirror input_source_refs ordering for an already resolved source object."""
    binding_scope_id = getattr(binding_scope, _SCOPE_ID_ATTR, None)
    if not binding_scope_id:
        return None
    matches = [
        index
        for index, (candidate_alias, candidate_source) in enumerate(
            _iter_select_sources_in_order(binding_scope),
            start=1,
        )
        if candidate_alias == alias and candidate_source is source
    ]
    if len(matches) != 1:
        return None
    return f"input:{binding_scope_id}:{matches[0]:03d}"


def _resolve_unqualified(col_name: str, sg_scope: Scope, result: ScopeLineageResult, schema: dict | None=None) -> SourceRef:
    """Resolve an unqualified column reference.

    Every selected source is evaluated before choosing one. A source with missing
    schema/output metadata remains possible; it cannot be ignored merely because
    another source is a known match.
    """
    selected = [
        (alias, source)
        for alias, source in _selected_sources(sg_scope).items()
        if isinstance(source, (Scope, exp.Table))
    ]
    viable = [
        (alias, source, _source_column_state(alias, source, col_name, result, schema))
        for alias, source in selected
    ]
    viable = [item for item in viable if item[2] != "absent"]

    candidate_ids = [
        _candidate_source_id(alias, source, result)
        for alias, source, _state in viable
    ]
    unique_viable_ids = {
        candidate_id for candidate_id in candidate_ids if candidate_id
    }

    # Source identity is an occurrence, not only a physical table/scope name. Two
    # aliases of the same table both exposing an unqualified field are still an
    # ambiguous SQL reference. Only this collapsed-identity case needs occurrence
    # coordinates; ordinary ambiguity retains the established stable candidate shape.
    if len(viable) > 1 and len(unique_viable_ids) < len(viable):
        candidate_refs = [
            _source_ref_to_candidate(
                _bound_source_ref(alias, source, col_name, sg_scope, result)
            )
            for alias, source, _state in viable
        ]
        return _ambiguous_ref(
            col_name,
            sg_scope,
            result,
            candidate_refs,
            "viable input occurrences",
        )

    for source in getattr(sg_scope, 'udtf_scopes', []) or []:
        upstream_id = getattr(source, _SCOPE_ID_ATTR, None)
        upstream_sd = result.scopes.get(upstream_id) if upstream_id else None
        if upstream_sd and any((c.name == col_name for c in upstream_sd.columns)):
            candidate_ids.append(upstream_id)

    candidate_ids = sorted(set(item for item in candidate_ids if item))
    if len(candidate_ids) > 1:
        return _ambiguous_ref(
            col_name,
            sg_scope,
            result,
            candidate_ids,
            "viable sources",
        )

    if len(candidate_ids) == 1:
        candidate_id = candidate_ids[0]
        selected_candidate = next(
            (
                (alias, source, state)
                for alias, source, state in viable
                if _candidate_source_id(alias, source, result) == candidate_id
            ),
            None,
        )
        if selected_candidate is not None:
            alias, source, state = selected_candidate
            if state == "unknown" and isinstance(source, exp.Table):
                result.diagnostics.warnings.append(
                    DiagnosticWarning(
                        type='unresolved_unqualified_no_schema',
                        scope=getattr(sg_scope, _SCOPE_ID_ATTR, 'UNKNOWN'),
                        msg=f"Unqualified column '{col_name}' has one viable table source "
                            f"({candidate_id}) but its schema metadata is unavailable",
                    )
                )
            return _bound_source_ref(alias, source, col_name, sg_scope, result)
        return SourceRef(scope=candidate_id, column=col_name)

    # Preserve the existing last-resort scope fallback for scopes whose output cannot
    # be materialized at this build point. Dangling-ref validation decides later whether
    # the field really exists (LINEAGE-001).
    scope_sources = [
        (alias, source) for alias, source in selected if isinstance(source, Scope)
    ]
    if len(scope_sources) == 1:
        (alias, source) = scope_sources[0]
        upstream_id = _source_scope_id(alias, source, result)
        if upstream_id and (not getattr(source, 'is_udtf', False)):
            # Last-resort attribution: with a single scope source, an otherwise unresolvable
            # column usually does come from it. Whether it actually does is settled once, by
            # `_drop_dangling_column_refs`, after every scope is built — checking it here would
            # read a column list that may not be materialized yet, and would miss the
            # schema-expansion exemption (LINEAGE-001).
            return _bound_source_ref(alias, source, col_name, sg_scope, result)
    result.diagnostics.warnings.append(DiagnosticWarning(type='column_not_found', scope=getattr(sg_scope, _SCOPE_ID_ATTR, 'UNKNOWN'), msg=f"Column '{col_name}' not found in any source"))
    return SourceRef(scope='UNKNOWN', column=col_name)


def _resolve_duplicate_alias_ref(table_alias: str, col_name: str, sg_scope: Scope, result: ScopeLineageResult, schema: dict | None=None) -> SourceRef | None:
    """Resolve qualified references when one SELECT reuses the same alias.

    ``sqlglot`` stores sources in a dict. If the same alias appears twice in the
    same FROM/JOIN list, that dict can only keep one binding. For lineage, a
    silent overwrite is worse than an explicit diagnostic, so we inspect the
    SELECT's FROM/JOIN AST in order and disambiguate by known output columns or
    schema metadata.
    """
    candidates = [(alias, source) for (alias, source) in _iter_select_sources_in_order(sg_scope) if alias == table_alias]
    if len(candidates) <= 1:
        return None
    scope_id = getattr(sg_scope, _SCOPE_ID_ATTR, 'UNKNOWN')
    states = [(alias, source, _source_column_state(alias, source, col_name, result, schema)) for (alias, source) in candidates]
    exact = [(alias, source) for (alias, source, state) in states if state == 'present']
    possible = [(alias, source) for (alias, source, state) in states if state == 'unknown']
    selected: tuple[str, Scope | exp.Table] | None = None
    reason = ''
    if len(exact) == 1:
        selected = exact[0]
        reason = 'matched the only source with this output column'
    elif not exact and len(possible) == 1:
        selected = possible[0]
        reason = 'only one duplicate source could still contain the column'
    elif len(exact) > 1:
        selected = exact[0]
        reason = 'multiple duplicate sources expose the column; using the first one'
    result.diagnostics.warnings.append(DiagnosticWarning(type='duplicate_alias', scope=scope_id, msg=f"Alias '{table_alias}' is used {len(candidates)} times in the same SELECT. Column '{col_name}' {('was resolved because it ' + reason if reason else 'could not be disambiguated')}."))
    if selected is None:
        return SourceRef(scope='UNKNOWN', column=col_name)
    (_alias, source) = selected
    return _bound_source_ref(_alias, source, col_name, sg_scope, result)


def _iter_select_sources_in_order(sg_scope: Scope) -> list[tuple[str, Scope | exp.Table]]:
    """Return SELECT FROM/JOIN sources in SQL order, preserving duplicate aliases."""
    expr = sg_scope.expression
    if not isinstance(expr, exp.Select):
        return []
    items: list[tuple[str, Scope | exp.Table]] = []
    from_ = expr.args.get('from_')
    if from_ is not None:
        source = getattr(from_, 'this', None)
        item = _source_item_from_ast_node(source, sg_scope)
        if item:
            items.append(item)
    for join in expr.args.get('joins') or []:
        item = _source_item_from_ast_node(join.this, sg_scope)
        if item:
            items.append(item)
    for source in getattr(sg_scope, 'udtf_scopes', []) or []:
        alias = _find_alias_in_parent(source)
        if alias:
            items.append((alias, source))
    return items


def _source_column_state(alias: str, source: Scope | exp.Table, col_name: str, result: ScopeLineageResult, schema: dict | None) -> str:
    """Return present/absent/unknown for whether source can expose col_name."""
    if isinstance(source, Scope):
        upstream_id = _source_scope_id(alias, source, result)
        upstream_sd = result.scopes.get(upstream_id) if upstream_id else None
        if upstream_sd:
            names = {col.name for col in upstream_sd.columns}
            if col_name in names or '*' in names:
                return 'present'
            if getattr(source, "is_udtf", False):
                # LATERAL VIEW output aliases are declared explicitly. Once materialized,
                # a different name cannot come from this UDTF.
                return 'absent'
            materialized_state = _materialized_star_column_state(
                upstream_id, col_name, result, schema
            )
            if materialized_state != 'unknown':
                return materialized_state
        inner_expr = _query_body(source.expression)
        if inner_expr is not None:
            if col_name in inner_expr.named_selects:
                return 'present'
            if _select_has_star_projection(inner_expr):
                return 'unknown'
            return 'absent'
        return 'unknown'
    fq = _qualified_table(source)
    if schema is not None:
        norm = _normalize_table_name(fq)
        if norm not in schema:
            return 'unknown'
        return 'present' if col_name in schema.get(norm, []) else 'absent'
    return 'unknown'


def _materialized_star_column_state(
    scope_id: str | None,
    col_name: str,
    result: ScopeLineageResult,
    schema: dict | None,
    visited: set[str] | None = None,
) -> str:
    """Return a known column state carried through an already-expanded star chain.

    A physical table with a known schema treats a missing column as absent. Wrapping that
    table in ``SELECT *`` must not erase the same fact and turn it into an ambiguity candidate.
    Missing table metadata remains unknown, while an explicitly qualified downstream reference
    can still use the separate reference-driven materialization path.
    """
    if not scope_id or scope_id not in result.scopes:
        return 'unknown'
    visited = set(visited or ())
    if scope_id in visited:
        return 'unknown'
    visited.add(scope_id)

    scope_data = result.scopes[scope_id]
    names = {column.name for column in scope_data.columns}
    if col_name in names:
        return 'present'
    if any(name == '*' or name.endswith('.*') for name in names):
        return 'unknown'

    states: list[str] = []
    for table in scope_data.star_schema_sources:
        normalized = _normalize_table_name(table)
        if schema is None or normalized not in schema:
            states.append('unknown')
        elif col_name in schema.get(normalized, []):
            states.append('present')
        else:
            states.append('absent')
    for upstream_id in scope_data.star_expanded_from:
        states.append(
            _materialized_star_column_state(
                upstream_id, col_name, result, schema, visited
            )
        )

    if 'present' in states:
        return 'present'
    if states and all(state == 'absent' for state in states):
        return 'absent'
    if not states and names:
        # A materialized scope with concrete outputs and no remaining star provenance is
        # closed. Treating a missing name as unknown makes that scope a false candidate for
        # every unqualified column in a downstream join.
        return 'absent'
    return 'unknown'


def _candidate_source_id(
    alias: str,
    source: Scope | exp.Table,
    result: ScopeLineageResult,
) -> str | None:
    if isinstance(source, Scope):
        return _source_scope_id(alias, source, result)
    return _qualified_table(source)


def _query_body(expression):
    """The projection-bearing query body, unwrapping a subquery's parentheses.

    A derived-table source is not always a SELECT: `(select ... union all select ...) a` is a
    set operation. Its output names come from the branches, so callers must be able to ask
    the same two questions (named_selects / has a star) of either shape.
    """
    if isinstance(expression, exp.Subquery):
        expression = expression.this
    return expression if isinstance(expression, (exp.Select, _SET_OPERATION)) else None



def _source_ref_to_candidate(ref: SourceRef) -> dict[str, str]:
    return {
        "scope": ref.scope,
        "column": ref.column,
        **({"qualifier": ref.qualifier} if ref.qualifier else {}),
        **(
            {"binding_scope_id": ref.binding_scope_id}
            if ref.binding_scope_id
            else {}
        ),
        **({"input_ref_id": ref.input_ref_id} if ref.input_ref_id else {}),
    }


def _ambiguous_ref(col_name, sg_scope, result, candidate_scopes, kind: str) -> SourceRef:
    """Report an unqualified column that several sources could equally supply.

    Returning the first candidate made the recorded source depend on join order rather than on
    the query: swap the two sides of a JOIN and the "physical source" changed, while the field
    still claimed `status=resolved` and `trace_complete=true`. That is a guess published as a
    fact, and downstream modeling consumes it as one (LINEAGE-002).

    The candidates are kept — this is narrower than UNKNOWN, which would throw away the fact
    that we know exactly which sources are in play, only not which one SQL means.
    """
    # Sorted, not in traversal order: the candidate set must not change when the two sides of
    # a JOIN are swapped, or the artifact still varies with something the query does not mean.
    candidates_by_key: dict[tuple[str, str, str, str, str], dict[str, str]] = {}
    for value in candidate_scopes:
        candidate = (
            dict(value)
            if isinstance(value, dict)
            else {"scope": str(value or ""), "column": col_name}
        )
        if not candidate.get("scope"):
            continue
        candidate.setdefault("column", col_name)
        key = (
            str(candidate.get("scope") or ""),
            str(candidate.get("column") or ""),
            str(candidate.get("binding_scope_id") or ""),
            str(candidate.get("input_ref_id") or ""),
            str(candidate.get("qualifier") or ""),
        )
        candidates_by_key[key] = candidate
    candidates = [candidates_by_key[key] for key in sorted(candidates_by_key)]
    result.diagnostics.warnings.append(DiagnosticWarning(
        type='ambiguous_unqualified',
        scope=getattr(sg_scope, _SCOPE_ID_ATTR, 'UNKNOWN'),
        msg=f"Unqualified column '{col_name}' found in multiple {kind} "
            f"({', '.join(str(c['scope']) for c in candidates)}); left ambiguous rather than "
            f"attributed to one",
    ))
    return SourceRef(scope=AMBIGUOUS_SCOPE_ID, column=col_name, candidates=candidates)

def _select_has_star_projection(select) -> bool:
    """Return True if a SELECT (or any branch of a set operation) projects a star."""
    if isinstance(select, _SET_OPERATION):
        return any(
            _select_has_star_projection(branch)
            for branch in (select.this, select.expression)
            if branch is not None
        )
    if not isinstance(select, exp.Select):
        return False
    for projection in select.selects:
        inner = projection.this if isinstance(projection, exp.Alias) else projection
        if isinstance(inner, exp.Star):
            return True
        if isinstance(inner, exp.Column) and isinstance(inner.this, exp.Star):
            return True
    return False
