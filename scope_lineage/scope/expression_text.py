"""Textual SQL-expression operations: reference rewriting and qualifier probes."""
from __future__ import annotations

import re

from .expression_refs import _cached_pattern
from .scope_types import ScopeData
from .sequences import _unique_ordered
from .sql_text_spans import blank_literals_and_comments, sub_in_code

def _unexpanded_bound_aliases_in_expression(scope_data: ScopeData, expression: str | None) -> list[str]:
    expression = blank_literals_and_comments(str(expression or ""))
    if not expression:
        return []
    unresolved_aliases: list[str] = []
    for binding in scope_data.alias_source_bindings or []:
        alias = str(binding.get("alias") or "")
        if not alias or not _qualifier_present(expression, alias):
            continue
        physical_ids = {str(item) for item in binding.get("physical_source_ids") or [] if item}
        physical_id = str(binding.get("physical_source_id") or "")
        if physical_id:
            physical_ids.add(physical_id)
        # "physical_table" is the value the binding builder emits; comparing against
        # "physical" here meant this exemption never fired, so an expression that kept a
        # physical table's own name — already a fully resolved reference — was reported as
        # an unexpanded alias. The `alias in physical_ids` half still holds the line: a
        # local alias such as `FROM ods.source s` that survived expansion is not exempt,
        # because that one really did fail to rewrite.
        # `qualify` names an unaliased table after itself, so `FROM ods.pay` yields
        # references written `pay.uid` while the physical id stays `ods.pay`. Comparing the
        # two directly never matched, and a fully resolved direct physical source was reported
        # as an unexpanded alias (BARE-ALIAS-001). Matching the id's table segment as well
        # still refuses a genuine local alias: `FROM ods.source s` leaves `s`, which is
        # neither the id nor its table name, and an `s.` that survived expansion really did
        # fail to rewrite.
        if binding.get("source_type") == "physical_table" and (
            alias in physical_ids
            or alias in {identifier.rsplit(".", 1)[-1] for identifier in physical_ids}
        ):
            continue
        unresolved_aliases.append(alias)
    return _unique_ordered(unresolved_aliases)


def _qualifier_present(expression: str, qualifier: str) -> bool:
    if f"`{qualifier}`." in expression:
        return True
    return bool(_cached_pattern(rf"(?<![.`\w]){re.escape(qualifier)}\.").search(expression))


# Every substitution below runs on code only (`sub_in_code`): a string literal is data and a
# comment is the author's remark, and rewriting `'see c.v now'` or `/* c.v note */` changed a
# published value or garbled a note (WP4 2.1, 1.13-e). Each step is skipped when its text
# does not occur at all, which is the common case and keeps the scan off long expressions.


def _replace_qualified_ref_with_expression(expression: str, qualifier: str, field: str, replacement: str) -> str:
    replacement_sql = _parenthesize_replacement_expression(replacement)
    expression = _replace_text_in_code(expression, f"`{qualifier}`.`{field}`", replacement_sql)
    expression = _replace_text_in_code(expression, f"`{qualifier}`.{replacement_sql}", replacement_sql)
    if f"{qualifier}.{field}" in expression:
        expression = sub_in_code(
            rf"(?<![.`\w]){re.escape(qualifier)}\.{re.escape(field)}(?![`.\w])",
            replacement_sql,
            expression,
        )
    expression = _replace_text_in_code(expression, f"{qualifier}.{replacement_sql}", replacement_sql)
    return expression


def _replace_text_in_code(expression: str, text: str, replacement: str) -> str:
    if text not in expression:
        return expression
    return sub_in_code(re.escape(text), replacement, expression)


def _replace_unqualified_ref_with_expression(expression: str, field: str, replacement: str) -> str:
    if field not in expression:
        return expression
    replacement_sql = _parenthesize_replacement_expression(replacement)
    expression = sub_in_code(
        rf"(?<![.`\w])`{re.escape(field)}`(?![`.\w])", replacement_sql, expression
    )
    return sub_in_code(
        rf"(?<![.`'\"\w]){re.escape(field)}(?![`.'\"\w])", replacement_sql, expression
    )


def _parenthesize_replacement_expression(expression: str) -> str:
    stripped = expression.strip()
    if re.fullmatch(r"`[^`]+`\.`[^`]+`", stripped):
        return stripped
    if _is_one_parenthesised_unit(stripped):
        return stripped
    return f"({stripped})"


def _is_one_parenthesised_unit(expression: str) -> bool:
    """True when the opening `(` is the one the closing `)` matches.

    First and last character alone also accept `(a + 1) + COALESCE(b, 0)`, and leaving
    that unwrapped turned `c.v * 10` into `(a + 1) + COALESCE(b, 0) * 10` (WP4 1.9).
    Parentheses inside literals and comments are not counted.
    """
    if not (expression.startswith("(") and expression.endswith(")")):
        return False
    code = blank_literals_and_comments(expression)
    depth = 0
    for index, char in enumerate(code):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index == len(code) - 1
    return False


# A regex over text cannot tell a call from a KEYWORD that may be followed by a
# parenthesised expression: `kind IN ('a', 'b')` and `NOT (a AND b)` match `<name>(`
# exactly as `upper(a)` does. Harvesting them made `expression_features.functions`
# carry `in` / `not`, which the catalog then could not place, so an ordinary
# `SUM(CASE WHEN k IN (...) ...)` was published as a UDF black box. `cast`, `case`,
# `if` and `over` were the four this list started as.
#
# Names that are BOTH a keyword and a Spark function -- `filter`, `exists`,
# `transform`, `left`, `right`, `any`, `some` -- are deliberately absent: they are real
# calls worth reporting, and the catalog knows all of them, so neither spelling can be
# mistaken for a UDF.
_SQL_KEYWORDS_BEFORE_PAREN = frozenset({
    "all", "and", "as", "between", "by", "case", "cast", "distinct", "else", "end",
    "escape", "except", "from", "group", "having", "if", "ilike", "in", "intersect",
    "interval", "is", "like", "not", "on", "or", "order", "over", "partition", "rlike",
    "select", "then", "union", "using", "values", "when", "where", "window", "with",
})


# What precedes a type rather than a call: `AS` (CAST / TRY_CAST) or the `::` cast.
_TYPE_POSITION = re.compile(r"(?:\bas|::)\s*$")


def _function_names(expression: str) -> list[str]:
    """The function names an expression calls, lower-case and in order, deduplicated.

    String literals and comments are removed first: a regex has no way to tell `upper(`
    inside a quoted value or a `/* note(x) */` remark from a call, and neither is code.

    A type is written in the same `<name>(` shape -- `CAST(x AS DECIMAL(18, 2))`,
    `x::DECIMAL(18, 2)` -- so a name written where a type goes (after `AS` or `::`) is
    not a call. The position decides, not a list of type names: `char(65)` is a Spark
    function as well as a type, and it stays a call where it is called (WP4 1.13-m).
    """
    names = []
    scanned = blank_literals_and_comments(expression)
    for match in re.finditer(r"\b([a-z_][a-z0-9_]*)\s*\(", scanned):
        name = match.group(1)
        if name in _SQL_KEYWORDS_BEFORE_PAREN:
            continue
        if _TYPE_POSITION.search(scanned, 0, match.start()):
            continue
        if name not in names:
            names.append(name)
    return names
