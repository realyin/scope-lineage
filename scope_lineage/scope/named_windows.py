"""Inline named windows (``OVER w`` + ``WINDOW w AS (...)``) before scopes are built.

A named window's PARTITION BY / ORDER BY / frame sit in the SELECT's ``windows`` arg, not
under the ``OVER w`` that names it. Every resolver downstream reads a window's columns
from the ``exp.Window`` node itself, so ``ROW_NUMBER() OVER w`` was read as a call with
no columns (a CONSTANT) and ``SUM(amt) OVER w`` lost its partition and order columns
(audit 1.6). Rewriting each reference into the full specification once, here, lets every
existing window rule apply unchanged.

Inheritance follows the SQL rule sqlglot parses: a window written as ``(base ...)`` --
in the WINDOW clause or in an OVER -- takes the base's PARTITION BY, and its own ORDER BY
and frame when it writes them, the base's otherwise. ``w2 AS w1`` is ``w1``.
"""
from __future__ import annotations

from sqlglot import exp

# The parts of a window specification, in the order a refinement may replace them.
_SPEC_PARTS = ("partition_by", "order", "spec")


def inline_named_windows(ast: exp.Expression) -> None:
    """Rewrite every ``OVER <name>`` to the named window it refers to (in place)."""
    for select in list(ast.find_all(exp.Select)):
        named = select.args.get("windows")
        if not named:
            continue
        definitions = _resolved_definitions(named)
        unresolved = False
        for window in list(select.find_all(exp.Window)):
            if window.find_ancestor(exp.Select) is not select or _is_definition(window, named):
                continue
            base = _base_name(window)
            if base is None:
                continue
            definition = definitions.get(base)
            if definition is None:
                unresolved = True
                continue
            _apply_definition(window, definition)
        if not unresolved:
            select.set("windows", None)


def _is_definition(window: exp.Window, named: list) -> bool:
    return any(window is item for item in named)


def _base_name(window: exp.Window) -> str | None:
    alias = window.args.get("alias")
    if isinstance(alias, exp.Identifier) and alias.name:
        return alias.name.lower()
    return None


def _resolved_definitions(named: list) -> dict[str, dict[str, exp.Expression | list | None]]:
    """Each named window's own parts, with any base window it builds on merged in."""
    raw = {
        item.this.name.lower(): item
        for item in named
        if isinstance(item, exp.Window) and isinstance(item.this, exp.Identifier)
    }
    resolved: dict[str, dict[str, exp.Expression | list | None]] = {}

    def resolve(name: str, seen: frozenset[str]) -> dict | None:
        if name in resolved:
            return resolved[name]
        window = raw.get(name)
        if window is None or name in seen:
            return None
        parts = {part: window.args.get(part) for part in _SPEC_PARTS}
        base = _base_name(window)
        if base is not None:
            inherited = resolve(base, seen | {name})
            if inherited is None:
                return None
            parts = _merged(inherited, parts)
        resolved[name] = parts
        return parts

    for name in raw:
        resolve(name, frozenset())
    return resolved


def _merged(base: dict, own: dict) -> dict:
    """The base's parts, replaced by every part the refining window writes itself."""
    return {part: own.get(part) or base.get(part) for part in _SPEC_PARTS}


def _apply_definition(window: exp.Window, definition: dict) -> None:
    own = {part: window.args.get(part) for part in _SPEC_PARTS}
    for part, value in _merged(definition, own).items():
        if own.get(part):
            continue
        if isinstance(value, list):
            window.set(part, [item.copy() for item in value])
        elif value is not None:
            window.set(part, value.copy())
    window.set("alias", None)
