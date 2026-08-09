import re
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


def _replace_aliases(expr: str, alias_map: Dict[str, str]) -> str:
    """Replace table aliases in an expression string with fully-qualified names.

    Handles patterns like ``t1.col`` or ``t1.`` (but not bare ``t1`` without a dot,
    which could be a function name or other identifier).
    Sorts aliases longest-first so that e.g. ``ods_tbl`` is tried before ``ods``.
    """
    if not alias_map:
        return expr
    # Sort by length descending to avoid partial matches
    for alias in sorted(alias_map, key=len, reverse=True):
        # Match alias followed by a dot: t1.  but not part of a longer word
        pattern = r'\b' + re.escape(alias) + r'\.'
        replacement = alias_map[alias] + '.'
        expr = re.sub(pattern, replacement, expr)
    return expr


COLUMN_TYPES = {
    "DIRECT",
    "EXPRESSION",
    "AGGREGATE",
    "WINDOW",
    "CONDITIONAL",
    "CONSTANT",
    "LITERAL_SUBQUERY",
    "LATERAL_VIEW",
}


@dataclass
class ColumnRef:
    table: Optional[str]
    column: str
    expression: Optional[str] = None  # branch-specific expression; set for UNION ALL branches
    cte_expressions: List[str] = field(default_factory=list)  # CTE/subquery expressions (outer→inner order)
    scope_alias_maps: List[Dict[str, str]] = field(default_factory=list)  # per-layer, parallel to cte_expressions

    def lineage_chain(self, outer_expression: str = "", alias_map: Optional[Dict[str, str]] = None) -> str:
        """Human-readable chain: outer_expression -> cte[0] -> cte[1] -> ... (outer→inner).

        When scope_alias_maps are available, each layer uses its own alias map
        so that the same alias name at different SQL scopes resolves correctly.
        Falls back to the flat alias_map when scope_alias_maps is empty.
        Consecutive duplicate segments after alias replacement are collapsed.
        """
        head = self.expression or outer_expression
        parts = [head] + self.cte_expressions if head else list(self.cte_expressions)
        if alias_map and self.scope_alias_maps:
            # Per-layer alias replacement: head uses alias_map, each cte layer uses its scope map
            replaced = [_replace_aliases(parts[0], alias_map)]
            for i, p in enumerate(parts[1:]):
                scope_map = self.scope_alias_maps[i] if i < len(self.scope_alias_maps) else alias_map
                replaced.append(_replace_aliases(p, scope_map))
            parts = replaced
            # Collapse consecutive duplicates after alias replacement
            deduped = [parts[0]] if parts else []
            for p in parts[1:]:
                if p != deduped[-1]:
                    deduped.append(p)
            parts = deduped
        elif alias_map:
            parts = [_replace_aliases(p, alias_map) for p in parts]
            # Collapse consecutive duplicates after alias replacement
            deduped = [parts[0]] if parts else []
            for p in parts[1:]:
                if p != deduped[-1]:
                    deduped.append(p)
            parts = deduped
        return " -> ".join(parts)


@dataclass
class Column:
    name: str
    type: str
    expression: str
    upstream: List[ColumnRef] = field(default_factory=list)


@dataclass
class JoinKey:
    left: ColumnRef
    right: ColumnRef
    expression: str


@dataclass
class Unresolved:
    kind: str
    expression: str
    reason: str
    table: Optional[str] = None
    column: Optional[str] = None


@dataclass
class LineageResult:
    task_name: str
    target_table: str
    columns: List[Column] = field(default_factory=list)
    join_keys: List[JoinKey] = field(default_factory=list)
    unresolved: List[Unresolved] = field(default_factory=list)
    alias_map: Dict[str, str] = field(default_factory=dict)  # alias -> fully-qualified table name

    def to_dict(self) -> dict:
        return asdict(self)
