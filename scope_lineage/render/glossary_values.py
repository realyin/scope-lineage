"""Value-domain observations: which constants one statement compares a column against.

WI-2.4, the collecting half of the term / value dictionary. It reads a statement's
contract document together with the ``rules`` and ``fields`` blocks of its semantic
profile, and answers one question per observation: *the SQL wrote this constant beside
this column, here*. It never answers what the constant means -- that is the glossary's
``meaning`` slot, which only a human override or a comment that literally spells the
value out can fill.

Three deliberate restrictions, all in the conservative direction.

1. *A regex pattern stays whole.* ``state RLIKE 'ACTIVE|NEW'`` is recorded as the one
   pattern the author wrote. Splitting the alternation would publish two values the
   statement never compares against, and a regex is not a value list.
2. *A value is only attributed to a physical column when exactly one of the rule's
   fields carries that name.* Two joined tables both holding ``status`` make the
   attribution a guess, so the observation falls back to the scope-level reference and
   is flagged ``logical`` rather than naming a table it cannot prove.
3. *``NULL`` is not published as a value.* It is an absence, not a code. It still counts
   towards a CASE's exhaustiveness, because ``ELSE NULL`` does close the branch set.

This module deliberately imports nothing from ``semantic_profile``: the profile builder
calls *it* (to give every field its ``value_domain``), and the corpus-level aggregator in
``glossary`` calls both.
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping, Sequence

from sqlglot import exp

from . import semantic_text


# What kind of thing stands on the right of the comparison. `literal` and `pattern` reach
# the glossary's `values[]`; the other two are substitutions, and a substitution is not a
# value of the column -- it is the scheduler's or the engine's answer at run time.
#
# WI-2.4b split `pattern` out of `literal`. `col LIKE '%UNIT_OUT_%'` and `col RLIKE 'A|B'`
# name a SHAPE the column's values have, never a value the column holds: listing
# `'%UNIT_OUT_%'` beside `'SA'` as an enumerated value told a reader something the SQL
# never said. The observation is still worth publishing, so it stays in `values[]` under
# its own kind, and every enum-shaped question (closed sets, the `- 取值：` enumeration)
# steps over it.
VALUE_KIND_LITERAL = "literal"
VALUE_KIND_PATTERN = "pattern"
VALUE_KIND_PARAMETERIZED = "parameterized"
VALUE_KIND_FUNCTION = "function"

VALUE_KINDS = (
    VALUE_KIND_LITERAL,
    VALUE_KIND_PATTERN,
    VALUE_KIND_PARAMETERIZED,
    VALUE_KIND_FUNCTION,
)

# The kinds the dictionary publishes as values of the column rather than as parameters.
GLOSSARY_VALUE_KINDS = frozenset({VALUE_KIND_LITERAL, VALUE_KIND_PATTERN})

CONTEXT_FILTER_EQ = "filter_eq"
CONTEXT_FILTER_IN = "filter_in"
CONTEXT_FILTER_NEQ = "filter_neq"
CONTEXT_FILTER_RLIKE = "filter_rlike"
CONTEXT_CASE_CONDITION = "case_condition"
CONTEXT_CASE_THEN = "case_then"
CONTEXT_UNION_CONSTANT = "union_constant"
CONTEXT_CONSTANT_PROJECTION = "constant_projection"
CONTEXT_JOIN_CONDITION = "join_condition"

VALUE_CONTEXTS = (
    CONTEXT_FILTER_EQ,
    CONTEXT_FILTER_IN,
    CONTEXT_FILTER_NEQ,
    CONTEXT_FILTER_RLIKE,
    CONTEXT_CASE_CONDITION,
    CONTEXT_CASE_THEN,
    CONTEXT_UNION_CONSTANT,
    CONTEXT_CONSTANT_PROJECTION,
    CONTEXT_JOIN_CONDITION,
)

# The contexts whose column is an OUTPUT column rather than a read column: a field's
# value domain matches these by target column name, and the physical ones by reference.
OUTPUT_CONTEXTS = frozenset(
    {CONTEXT_CASE_THEN, CONTEXT_UNION_CONSTANT, CONTEXT_CONSTANT_PROJECTION}
)

BASIS_IN_LIST = "in_list"
BASIS_CASE_EXHAUSTIVE = "case_exhaustive"

# WI-9 legacy b. The contexts in which a constant is plausibly a **business code** --
# something a person could be asked to name -- rather than a bound, a batch date or a
# guard. A `<>` , a `RLIKE` or a CASE *condition* pins nothing enumerable: the first
# names what a row is not, the second a shape, and the third is a branch test whose
# value may be a threshold.
ENUMERABLE_CONTEXTS = frozenset(
    {
        CONTEXT_FILTER_EQ,
        CONTEXT_FILTER_IN,
        CONTEXT_CASE_THEN,
        CONTEXT_UNION_CONSTANT,
        CONTEXT_CONSTANT_PROJECTION,
    }
)

# The subset that also proves a bare number is a code. `WHERE n = 0` is as likely a
# threshold or a sentinel as a code, and asking an owner to name every such number is
# how a 待确认 list becomes noise; an IN list, a CASE label and a projected constant are
# each written as one of several alternatives, which is what an enumeration is.
ENUMERABLE_NUMERIC_CONTEXTS = frozenset(
    {CONTEXT_FILTER_IN, CONTEXT_CASE_THEN, CONTEXT_CONSTANT_PROJECTION}
)

COMMENT_SOURCE_COLUMN = "column_comment"
COMMENT_SOURCE_TABLE = "table_comment"
COMMENT_SOURCE_SQL = "sql_comment"

# A one-character code matches almost any sentence by accident ("0" inside "2026"), and
# one wrong candidate costs more than ten missed ones in a layer whose whole promise is
# that it does not guess.
MINIMUM_CANDIDATE_LENGTH = 2

_PREDICATE_RULE_KINDS = frozenset({"filter", "having"})
_ROOT = "ROOT"
_TABLE_COMMENT_KEYS = ("comment", "table_comment", "description")


# ------------------------------------------------------------------ table identity


def table_key(name) -> tuple[str, ...]:
    """The last two dotted segments: what makes ``hive.ods.t`` and ``ods.t`` one table.

    A corpus records the same table under several qualification levels (``ods.t`` in a
    hive-style read, ``catalog.ods.t`` at the iceberg writer). This mirrors the suffix
    rule ``skills/scope-lineage/scripts/query.py`` uses; it is re-implemented here rather
    than imported because a package may not depend on a skill script.
    """
    parts = [part for part in str(name or "").split(".") if part]
    return tuple(parts[-2:])


def same_table(left, right) -> bool:
    """True when one name is a dotted suffix of the other -- i.e. the same table."""
    left, right = str(left), str(right)
    return left == right or left.endswith("." + right) or right.endswith("." + left)


def canonical_name(names) -> str:
    """The most qualified spelling of one table, chosen stably."""
    return max(sorted(str(name) for name in names), key=len)


# ------------------------------------------------------------- statement collection


def statement_observations(
    document: Mapping,
    rules: Sequence[Mapping],
    fields: Sequence[Mapping],
    *,
    task: str | None = None,
    statement_id: str | None = None,
) -> list[dict]:
    """Every constant this statement writes beside a column, one entry per occurrence."""
    context = _context(document, task, statement_id)
    context["sql_aliases"] = _sql_aliases(fields, context["target_table"])
    observations: list[dict] = []
    for rule in rules:
        kind = str(rule.get("kind"))
        if kind in _PREDICATE_RULE_KINDS:
            observations.extend(_predicate_observations(rule, rule.get("expression"), context))
        elif kind == "join_condition":
            for condition in rule.get("extra_conditions") or []:
                observations.extend(
                    _predicate_observations(
                        rule, condition, context, forced=CONTEXT_JOIN_CONDITION
                    )
                )
        elif kind == "case_branch":
            observations.extend(_case_observations(rule, context))
    for field in fields:
        observations.extend(_field_observations(field, context))
    return observations


def _context(document: Mapping, task: str | None, statement_id: str | None) -> dict:
    """The per-statement lookups every observation reads, resolved once."""
    metadata = document.get("related_metadata") or {}
    target = str(document.get("target_table") or "")
    return {
        "task": str(task if task is not None else document.get("task_id") or ""),
        "statement_id": statement_id
        if statement_id is not None
        else document.get("statement_id"),
        "target_table": target,
        "target_columns": {
            str(entry.get("column"))
            for entry in document.get("end_to_end_lineage") or []
        },
        "block_outputs": _block_outputs(document),
        "chains": _chain_steps(document),
        "input_tables": metadata.get("input_tables") or {},
        "output_tables": metadata.get("output_tables") or {},
    }


def _sql_aliases(fields: Sequence[Mapping], target_table: str) -> dict[str, str]:
    """``<target table>.<column> -> the alias the SQL wrote``, for a positional write.

    The profile already decided which of these disagreements is real (WI-B's three
    conditions, the `alias_position_mismatch` ones), so the dictionary reads its answer
    instead of re-deriving it from the contract and risking a second opinion.
    """
    if not target_table:
        return {}
    return {
        f"{target_table}.{field.get('column')}": str(field["sql_alias"])
        for field in fields
        if field.get("sql_alias")
    }


def _chain_steps(document: Mapping) -> dict[str, list[dict]]:
    """``mapping_chain_id -> ordered_steps``: where a chain's steps say what they OUTPUT.

    A profile's ``derivation[]`` restates a chain step for a reader and drops the one key
    this module needs, ``output_field``. WI-2.10 A: a chain legitimately contains steps
    that produce OTHER columns -- the flag a ``SUM(CASE WHEN flag = …)`` reads is part of
    the metric's chain -- so a constant step is attributed by what that step outputs, not
    by what the chain ends at.
    """
    return {
        str(chain.get("mapping_chain_id")): list(chain.get("ordered_steps") or [])
        for chain in document.get("field_mapping_chains") or []
    }


def _block_outputs(document: Mapping) -> dict[str, list[str]]:
    """``logic_block_id -> output_fields``: which column a CASE block actually produces."""
    outputs: dict[str, list[str]] = {}
    for scope in (document.get("scopes") or {}).values():
        for block in scope.get("logic_blocks") or []:
            names = [str(name) for name in block.get("output_fields") or []]
            if names:
                outputs[str(block.get("logic_block_id"))] = names
    return outputs


# ----------------------------------------------------------------------- predicates


def _predicate_observations(
    rule: Mapping, expression, context: dict, *, forced: str | None = None
) -> list[dict]:
    """One filter / HAVING conjunct, or one JOIN extra condition."""
    node = semantic_text.parse_expression(expression)
    parsed = _comparison(node)
    if parsed is None:
        return []
    column, values, kind_context, closes = parsed
    text = semantic_text.expression_text(node)
    closed = _closed_set(values, BASIS_IN_LIST) if closes else None
    return _observations(
        rule,
        column,
        values,
        # The flag travels beside the context because `forced` may overwrite the context
        # (a LIKE inside a JOIN's extra condition is a `join_condition`) while what stands
        # on the right of the operator is unchanged.
        pattern=kind_context == CONTEXT_FILTER_RLIKE,
        context=forced or kind_context,
        expression=text,
        closed_set=closed,
        lookups=context,
        evidence=str(rule.get("rule_id") or rule.get("evidence") or ""),
        comments=rule.get("sql_comments") or [],
    )


def _comparison(node) -> tuple[str, list, str, bool] | None:
    """``(column, value nodes, context, closes the set)`` for one comparison, else None."""
    if isinstance(node, exp.In) and isinstance(node.this, exp.Column):
        return str(node.this.name), list(node.expressions or []), CONTEXT_FILTER_IN, True
    if isinstance(node, (exp.RegexpLike, exp.Like, exp.ILike)):
        if isinstance(node.this, exp.Column):
            return str(node.this.name), [node.expression], CONTEXT_FILTER_RLIKE, False
        return None
    if not isinstance(node, (exp.EQ, exp.NEQ)):
        return None
    sides = (node.this, node.expression)
    for named, value in (sides, sides[::-1]):
        if isinstance(named, exp.Column) and not isinstance(value, exp.Column):
            kind = CONTEXT_FILTER_EQ if isinstance(node, exp.EQ) else CONTEXT_FILTER_NEQ
            return str(named.name), [value], kind, False
    return None


# ---------------------------------------------------------------------- CASE / IF


def _case_observations(rule: Mapping, context: dict) -> list[dict]:
    branches = rule.get("branches")
    if branches is None:
        return []
    observations: list[dict] = []
    for branch in branches:
        observations.extend(
            _predicate_observations(
                rule, branch.get("when"), context, forced=CONTEXT_CASE_CONDITION
            )
        )
    observations.extend(_case_label_observations(rule, branches, context))
    return observations


def _case_label_observations(
    rule: Mapping, branches: Sequence[Mapping], context: dict
) -> list[dict]:
    """The THEN / ELSE constants, attributed to the column the CASE produces.

    WI-C: when the branches are NOT all scalar constants, a *numeric* branch is a
    computation default and not a code. ``CASE WHEN gap > 0 THEN 0 ELSE gap END`` caps a
    number at zero, and filing ``0`` as a candidate code of a DECIMAL amount column
    publishes a fact that is not one. A *string* branch of such a CASE is still a label
    somebody chose, so it is recorded as before -- with no closed set, which is what a
    non-exhaustive CASE already meant. An all-constant CASE is untouched.
    """
    names = context["block_outputs"].get(str(rule.get("evidence")) or "")
    if not names:
        return []
    otherwise = semantic_text.parse_expression(rule.get("else"))
    labels = [semantic_text.parse_expression(branch.get("then")) for branch in branches]
    results = [*labels, otherwise]
    exhaustive = otherwise is not None and all(_is_scalar_constant(node) for node in results)
    closed = _closed_set(results, BASIS_CASE_EXHAUSTIVE) if exhaustive else None
    mixed = any(node is not None and not _is_scalar_constant(node) for node in results)
    column_ref, logical = _output_reference(rule, names[0], context)
    return [
        item
        for node, branch in zip(results, [*branches, None])
        if not (mixed and _is_numeric_literal(node))
        for item in _observation(
            column_ref,
            logical,
            names[0],
            node,
            context=CONTEXT_CASE_THEN,
            expression=_label_expression(branch, node),
            closed_set=closed,
            lookups=context,
            evidence=str(rule.get("rule_id") or rule.get("evidence") or ""),
            comments=rule.get("sql_comments") or [],
        )
    ]


def _is_numeric_literal(node) -> bool:
    """WI-C: a number a branch returns, sign included. ``'0'`` is a string and is not."""
    if isinstance(node, exp.Neg):
        return _is_numeric_literal(node.this)
    return isinstance(node, exp.Literal) and not node.args.get("is_string")


def _label_expression(branch: Mapping | None, node) -> str:
    value = semantic_text.expression_text(node)
    if branch is None:
        return f"ELSE {value}"
    return f"{branch.get('when')} → {value}"


def _output_reference(rule: Mapping, name: str, context: dict) -> tuple[str, bool]:
    """Where a generated column lives: the target table when it reaches it, else a scope."""
    if str(rule.get("scope_id")) == _ROOT and name in context["target_columns"]:
        return f"{context['target_table']}.{name}", False
    return f"{rule.get('scope_id')}.{name}", True


# --------------------------------------------------------------- constant projections


def _field_observations(field: Mapping, context: dict) -> list[dict]:
    """A column whose value is written into the SQL rather than read from a table."""
    steps = [
        step
        for step in field.get("derivation") or []
        if str(step.get("step_type")) == "constant"
    ]
    column = str(field.get("column") or "")
    reference = f"{context['target_table']}.{column}"
    evidence = str(field.get("mapping_chain_id") or reference)
    comments = field.get("sql_comments") or []
    if not steps:
        return _generated_source_observations(field, reference, column, evidence, context)
    chain = context["chains"].get(str(field.get("mapping_chain_id"))) or []
    return [
        item
        for step in steps
        for item in _constant_observation(
            step, chain, context, evidence, comments, (reference, False, column)
        )
    ]


def _constant_observation(
    step: Mapping,
    chain: Sequence[Mapping],
    context: dict,
    evidence: str,
    comments: Sequence,
    fallback: tuple[str, bool, str],
) -> list[dict]:
    """One constant step, filed under the column THAT STEP projects it as (WI-2.10 A).

    A UNION branch writing ``'contract' AS data_source`` beneath a
    ``SUM(CASE WHEN data_source = 'contract' THEN amt END)`` is part of the metric's
    chain, and filing it at the chain's target published ``contract`` as a value of a
    ``decimal`` amount. The step's own ``output_field`` says which column it is. When
    that column reaches the target table unchanged the two are the same column, and the
    target's qualified name is the more useful of the two spellings.
    """
    column_ref, logical, column = _constant_reference(step, chain, context, fallback)
    return _observation(
        column_ref,
        logical,
        column,
        semantic_text.parse_expression(step.get("expression")),
        context=CONTEXT_UNION_CONSTANT if step.get("branch") else CONTEXT_CONSTANT_PROJECTION,
        expression=str(step.get("expression") or ""),
        closed_set=None,
        lookups=context,
        evidence=evidence,
        comments=comments,
    )


def _constant_reference(
    step: Mapping, chain: Sequence[Mapping], context: dict, fallback: tuple[str, bool, str]
) -> tuple[str, bool, str]:
    """``(column_ref, logical, column)`` for the output column of one constant step.

    ``fallback`` is the chain's own target column, used when the contract published no
    step to match -- the pre-WI-2.10 answer, which is right whenever a chain has nothing
    else in it.
    """
    output_field = str(_chain_step(step, chain).get("output_field") or "")
    if not output_field:
        return fallback
    name = output_field.rpartition(".")[2]
    carried = _carried_to_target(output_field, chain, context["target_table"])
    if carried:
        return f"{context['target_table']}.{carried}", False, carried
    return output_field, True, name


def _chain_step(step: Mapping, chain: Sequence[Mapping]) -> Mapping:
    """The chain step a ``derivation[]`` entry restates, matched on its step number."""
    for item in chain:
        if str(item.get("step_no")) == str(step.get("step_no")):
            return item
    return {}


def _carried_to_target(
    output_field: str, chain: Sequence[Mapping], target_table: str
) -> str | None:
    """The target column this constant still IS, or None when a later step consumes it.

    Follows the chain forwards from the constant's own output column: every step that
    reads it must be a pass-through (a plain projection or a UNION arm) for the constant
    to still be what the target column holds. One aggregate, one arithmetic step or one
    CASE reading it breaks the claim, because such a step consumes the value rather than
    emitting it.
    """
    seen: set[str] = set()
    current = str(output_field)
    while current and current not in seen:
        owner, _, name = current.rpartition(".")
        if owner and target_table and same_table(owner, target_table):
            return name
        seen.add(current)
        readers = [
            item
            for item in chain
            if current in [str(field) for field in item.get("input_fields") or []]
            and str(item.get("transform") or "") in PASS_THROUGH_TRANSFORMS
        ]
        if len(readers) != 1:
            return None
        current = str(readers[0].get("output_field") or "")
    return None


def _generated_source_observations(
    field: Mapping, reference: str, column: str, evidence: str, context: dict
) -> list[dict]:
    """The fallback for a field the contract published without a step-by-step chain."""
    return [
        item
        for source in field.get("generated_sources") or []
        if str(source.get("source_type")).upper() == "CONSTANT"
        for item in _observation(
            reference,
            False,
            column,
            semantic_text.parse_expression(source.get("value")),
            context=CONTEXT_CONSTANT_PROJECTION,
            expression=str(source.get("value") or ""),
            closed_set=None,
            lookups=context,
            evidence=evidence,
            comments=field.get("sql_comments") or [],
        )
    ]


# ------------------------------------------------------------------ observation rows


def _observations(
    rule: Mapping, column: str, values: Sequence, *, lookups: dict, **shared
) -> list[dict]:
    column_ref, logical = _attribute(rule, column, lookups)
    return [
        item
        for node in values
        for item in _observation(column_ref, logical, column, node, lookups=lookups, **shared)
    ]


def _observation(
    column_ref: str,
    logical: bool,
    column: str,
    node,
    *,
    context: str,
    expression: str,
    closed_set: dict | None,
    lookups: dict,
    evidence: str,
    comments: Sequence,
    pattern: bool = False,
) -> list[dict]:
    """One published observation, or nothing when the right side is not a constant."""
    kind = _value_kind(node)
    if kind is None or isinstance(node, exp.Null):
        return []
    if pattern and kind == VALUE_KIND_LITERAL:
        # `'${p}%'` stays `parameterized`: the substitution is the bigger fact about it.
        kind = VALUE_KIND_PATTERN
        closed_set = None
    literal = semantic_text.expression_text(node)
    if not _declared_type_admits(column_ref, logical, column, literal, lookups):
        return []
    return [
        {
            "column_ref": column_ref,
            "logical": logical,
            "column": column,
            # WI-2.8 D4: one spelling for one value. The quotes belong to SQL, and the
            # author's own literal is kept beside it for the markdown to show.
            "value": strip_quotes(literal),
            "sql_literal": literal,
            "kind": kind,
            "context": context,
            "expression": expression,
            "evidence": evidence,
            "task": lookups["task"],
            "statement_id": lookups["statement_id"],
            "closed_set": closed_set,
            "sql_alias": lookups.get("sql_aliases", {}).get(column_ref),
            "comments": _comment_pool(column_ref, logical, column, comments, lookups),
        }
    ]


def _declared_type_admits(
    column_ref: str, logical: bool, column: str, literal: str, lookups: dict
) -> bool:
    """WI-2.10 A: the describe-side type guard, applied where the dictionary is built.

    ``'Y'`` is not a value a ``decimal(15,2)`` column holds, and a corpus that publishes
    it there teaches every later reader the same wrong fact. The check needs a declared
    type, so it only speaks for a physical column the metadata describes; a scope-level
    reference names no table and is left alone.
    """
    if logical:
        return True
    table = str(column_ref).rsplit(".", 1)[0]
    detail = _column_detail(_metadata_item(table, lookups), column)
    return type_admits_literal(detail.get("type"), literal)


def _attribute(rule: Mapping, column: str, lookups: dict) -> tuple[str, bool]:
    """``(column_ref, logical)``: a table only when exactly one rule field carries the name."""
    fields = [
        item for item in rule.get("fields") or [] if str(item.get("column")) == column
    ]
    if len(fields) == 1:
        return f"{fields[0].get('table')}.{column}", False
    scoped = [
        item for item in rule.get("scope_fields") or [] if str(item.get("column")) == column
    ]
    if len(scoped) == 1:
        return f"{scoped[0].get('scope')}.{column}", True
    return f"{rule.get('scope_id')}.{column}", True


# ------------------------------------------------------------------- value kinds


def _value_kind(node) -> str | None:
    """What stands on the right, or None when it is not a constant at all."""
    if node is None or isinstance(node, exp.Column):
        return None
    if isinstance(node, exp.Parameter):
        return VALUE_KIND_PARAMETERIZED
    if isinstance(node, exp.Literal):
        return (
            VALUE_KIND_PARAMETERIZED
            if "${" in str(node.this)
            else VALUE_KIND_LITERAL
        )
    if _is_scalar_constant(node):
        return VALUE_KIND_LITERAL
    return VALUE_KIND_FUNCTION


def _is_scalar_constant(node) -> bool:
    if isinstance(node, (exp.Literal, exp.Null, exp.Boolean)):
        return True
    return isinstance(node, exp.Neg) and isinstance(node.this, exp.Literal)


def _closed_set(nodes: Sequence, basis: str) -> dict | None:
    values = [
        strip_quotes(semantic_text.expression_text(node))
        for node in nodes
        if node is not None and _is_scalar_constant(node)
    ]
    if len(values) != len([node for node in nodes if node is not None]):
        return None
    return {"values": values, "basis": basis} if values else None


# ------------------------------------------------------------------- comment pool


def _comment_pool(
    column_ref: str, logical: bool, column: str, sql_comments: Sequence, lookups: dict
) -> list[dict]:
    """Every comment that could describe this value, before the literal-match filter."""
    pool = [
        {
            "text": str(text),
            "source": COMMENT_SOURCE_SQL,
            "evidence": None,
        }
        for text in sql_comments
        if str(text).strip()
    ]
    if logical:
        return pool
    table = column_ref.rsplit(".", 1)[0]
    item = _metadata_item(table, lookups)
    comment = _column_comment(item, column)
    if comment:
        pool.append(
            {
                "text": str(comment),
                "source": COMMENT_SOURCE_COLUMN,
                "evidence": f"column:{table}.{column}",
            }
        )
    table_comment = _table_comment(item)
    if table_comment:
        pool.append(
            {
                "text": str(table_comment),
                "source": COMMENT_SOURCE_TABLE,
                "evidence": f"table:{table}",
            }
        )
    return pool


def _metadata_item(table: str, lookups: dict) -> dict:
    for group in ("input_tables", "output_tables"):
        for name, item in (lookups.get(group) or {}).items():
            if same_table(name, table):
                return item or {}
    return {}


def _column_detail(item: Mapping, column: str) -> Mapping:
    for detail in item.get("column_details") or []:
        if str(detail.get("name")) == column:
            return detail
    return {}


def _column_comment(item: Mapping, column: str) -> str | None:
    return _column_detail(item, column).get("comment")


def _table_comment(item: Mapping) -> str | None:
    table_metadata = item.get("table_metadata") or {}
    for key in _TABLE_COMMENT_KEYS:
        if table_metadata.get(key):
            return str(table_metadata[key])
    return None


# ------------------------------------------------------------- candidate filtering


def strip_quotes(value) -> str:
    return str(value or "").strip().strip("'\"")


def meaning_candidates(value: str, comments: Sequence[Mapping], evidence: str) -> list[dict]:
    """The comments that literally spell this value out, deduped and stably ordered."""
    needle = strip_quotes(value).lower()
    if len(needle) < MINIMUM_CANDIDATE_LENGTH:
        return []
    seen: set = set()
    found: list[dict] = []
    for comment in comments:
        text = str(comment.get("text") or "")
        if needle not in text.lower():
            continue
        entry = {
            "text": text,
            "source": str(comment.get("source")),
            "evidence": comment.get("evidence") or evidence,
        }
        key = (entry["text"], entry["source"], entry["evidence"])
        if key in seen:
            continue
        seen.add(key)
        found.append(entry)
    return sorted(found, key=lambda item: (item["source"], item["text"], item["evidence"]))


def canonical_owner(owner: str, logical: bool, canonical: Mapping) -> str:
    """The corpus's chosen spelling for one value's owner; a scope id is left alone."""
    if logical:
        return owner
    return canonical.get(table_key(owner), owner)


_VALUE_KEYS = (
    "column_ref",
    "logical",
    "column",
    # WI-B: only where a positional write filed these values under a column name the
    # author never wrote. Absent everywhere else, so it never claims a rename.
    "sql_alias",
    "value",
    "sql_literal",
    "kind",
    "observations",
    "task_count",
    "closed_set",
    "meaning_candidates",
    "meaning",
)


# ----------------------------------------------------------------------- values


def aggregate_values(
    observations: Sequence[Mapping], canonical: Mapping | None = None
) -> list[dict]:
    """Group raw observations into one entry per (column, value), stably ordered.

    Shared with the semantic profile, which runs it over one statement's observations to
    give each field its ``value_domain`` even when no corpus glossary was supplied.
    """
    canonical = canonical or {}
    grouped: dict[tuple, list[Mapping]] = {}
    closed: dict[tuple, list[dict]] = {}
    for item in observations:
        if item["kind"] not in GLOSSARY_VALUE_KINDS:
            continue
        owner_key = _owner_key(item, canonical)
        key = (item["column"], owner_key, item["value"], item["kind"])
        grouped.setdefault(key, []).append(item)
        claim = item.get("closed_set")
        if item["kind"] == VALUE_KIND_PATTERN or not claim:
            continue
        if claim not in closed.setdefault((item["column"], owner_key), []):
            closed[(item["column"], owner_key)].append(claim)
    return [
        _value_entry(key, members, closed, canonical)
        for key, members in sorted(grouped.items(), key=lambda pair: _value_sort_key(pair[0]))
    ]


def _owner_key(item: Mapping, canonical: Mapping) -> tuple:
    owner = str(item["column_ref"]).rsplit(".", 1)[0]
    if item.get("logical"):
        return ("scope", owner)
    return table_key(owner)


def _value_sort_key(key: tuple) -> tuple:
    column, owner_key, value, kind = key
    return (column, ".".join(owner_key), value, kind)


def _value_entry(
    key: tuple, members: Sequence[Mapping], closed: Mapping, canonical: Mapping
) -> dict:
    column, owner_key, value, kind = key
    first = members[0]
    owner = canonical_owner(
        str(first["column_ref"]).rsplit(".", 1)[0], bool(first.get("logical")), canonical
    )
    claims = [] if kind == VALUE_KIND_PATTERN else closed.get((column, owner_key)) or []
    entry = {
        "column_ref": f"{owner}.{column}",
        "column": column,
        "value": value,
        "sql_literal": _sql_literal(members),
        "kind": kind,
        "observations": _observation_rows(members),
        "task_count": len({item["task"] for item in members}),
        "closed_set": _agreed_closed_set(claims, value),
        "meaning_candidates": meaning_candidates(
            value,
            [comment for item in members for comment in item.get("comments") or []],
            str(first.get("evidence") or ""),
        ),
        "meaning": None,
    }
    if first.get("logical"):
        entry["logical"] = True
    if first.get("sql_alias"):
        entry["sql_alias"] = str(first["sql_alias"])
    return {key_name: entry[key_name] for key_name in _VALUE_KEYS if key_name in entry}


def _sql_literal(members: Sequence[Mapping]) -> str:
    """The literal the author wrote. One corpus may spell ``0`` and ``'0'``; pick stably."""
    return sorted({str(item.get("sql_literal") or item["value"]) for item in members})[0]


def _observation_rows(members: Sequence[Mapping]) -> list[dict]:
    rows = [
        {
            "task": item["task"],
            "statement_id": item["statement_id"],
            "context": item["context"],
            "evidence": item["evidence"],
            "expression": item["expression"],
        }
        for item in members
    ]
    seen: set = set()
    ordered = []
    for row in sorted(
        rows,
        key=lambda item: (
            item["task"],
            str(item["statement_id"] or ""),
            item["context"],
            item["evidence"],
            item["expression"],
        ),
    ):
        key = tuple(str(value) for value in row.values())
        if key not in seen:
            seen.add(key)
            ordered.append(row)
    return ordered


def _agreed_closed_set(claims: Sequence[Mapping], value: str) -> dict | None:
    """One claim the corpus agrees on, or nothing -- disagreement is not a closed set."""
    if len(claims) != 1:
        return None
    claim = claims[0]
    return dict(claim) if value in (claim.get("values") or []) else None




# ------------------------------------------------- field value domains (describe side)

MEANING_STATUS_CONFIRMED = "confirmed"
MEANING_STATUS_CANDIDATE = "candidate"

VALUE_DOMAIN_KEY = "value_domain"

# WI-2.12. The rule half of the same dictionary. A warehouse's business codes live mostly
# in its WHERE and ON clauses -- `queue_code IN ('01','07')` decides which rows a task is
# about -- and a `value_domain` hangs off an OUTPUT column, so a confirmed meaning could
# not reach the one place it explains the most. This key carries it to the rule.
RULE_VALUE_MEANINGS_KEY = "value_meanings"

# Where a rule's constant is a code somebody can define. A LIKE / RLIKE shape is not one
# (WI-2.4b), and a JOIN key names another column's value rather than a constant.
RULE_VALUE_CONTEXTS = frozenset(
    {CONTEXT_FILTER_EQ, CONTEXT_FILTER_IN, CONTEXT_FILTER_NEQ, CONTEXT_CASE_CONDITION}
)

# What the markdown writes when nobody has said what a value means yet. The same three
# states the glossary's own table uses, so a reader moving between the two documents
# does not have to learn a second vocabulary.
VALUE_DOMAIN_UNCONFIRMED = "待确认"
VALUE_DOMAIN_CANDIDATE_MARK = "?"
VALUE_DOMAIN_PREFIX = "取值："
VALUE_DOMAIN_PATTERN_PREFIX = "匹配模式："
SUMMARY_VALUE_SEPARATOR = "；"
VALUE_DOMAIN_LIMIT = 3

# WI-2.4b. A field whose domain runs to dozens of codes turned the `- 取值：` line into a
# wall nobody reads, and the line is a summary -- `semantic.json` is the record. Twelve
# fits a terminal width and still shows an enum's shape; past that the line says how many
# there are and where the rest live.
VALUE_DOMAIN_LINE_LIMIT = 12
VALUE_DOMAIN_OVERFLOW_NOTE = "，完整见 semantic.json value_domain"

# A field inherits its SOURCE column's observed values only when the value reaches the
# target unchanged. `CASE WHEN pay_status = 'PAID' THEN 'Y' ELSE 'N' END` reads
# `pay_status`, but `'PAID'` is emphatically not a value of `paid_flag` -- that column's
# domain is its own branch labels. The WI-2.4 brief says "match the source physical
# column"; this narrows it to the pass-through transforms, where the claim is true.
#
# WI-2.8 D1. The field-wide transform answers for the chain as a whole, and a chain can
# be DIRECT while one of its sources reaches it through a CASE -- which is how a CASE
# *condition*'s `'N'` ended up published as a value of the `decimal(15,2)` amount column
# the CASE produces. Pass-through is therefore asked of every step: the field's own
# transform and, per source, that source's. One non-pass-through step breaks the claim.
PASS_THROUGH_TRANSFORMS = frozenset({"DIRECT", "UNION"})

# What a pass-through source column may lend its target: the constants the SQL says that
# column EQUALS, plus the shapes a WHERE-level LIKE / RLIKE says its values have (the
# WI-2.4b `pattern` kind, which is never an enumerated value and never closes a set). A
# `<>` names a value the rows do not take, a JOIN key is another column's value, and a
# CASE condition belongs to the column being tested -- none of them is a value the
# target column outputs.
SOURCE_VALUE_CONTEXTS = frozenset(
    {CONTEXT_FILTER_EQ, CONTEXT_FILTER_IN, CONTEXT_FILTER_RLIKE}
)

_VIA_SOURCE = "source"
_VIA_OUTPUT = "output"

# The second half of D1: a type guard. Even a correctly attributed pass-through can
# carry a code observed on a same-named column elsewhere in the corpus, and `'Y'` is not
# a value any amount or date column holds. A quoted literal is only admitted onto these
# types when the text inside the quotes is itself of that type.
NUMERIC_TYPE_PREFIXES = (
    "decimal",
    "numeric",
    "number",
    "int",
    "bigint",
    "smallint",
    "tinyint",
    "long",
    "short",
    "double",
    "float",
    "real",
)
TEMPORAL_TYPE_PREFIXES = ("date", "timestamp", "datetime")

_NUMERIC_TEXT = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")
_TEMPORAL_TEXT = re.compile(
    r"^\d{4}-?\d{2}-?\d{2}([ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?$"
)


def type_admits_literal(declared: object, literal: object) -> bool:
    """False when a declared type says the column cannot hold this QUOTED literal.

    Only a quoted literal is judged: an unquoted ``0`` beside a ``decimal`` is the same
    number written without ceremony, while ``'Y'`` beside one is a value from a different
    column entirely. An undeclared type admits everything -- the layer refuses to guess.
    """
    text = str(literal or "")
    if not text.startswith(("'", '"')):
        return True
    kind = str(declared or "").strip().lower()
    inner = strip_quotes(text)
    if kind.startswith(NUMERIC_TYPE_PREFIXES):
        return bool(_NUMERIC_TEXT.match(inner))
    if kind.startswith(TEMPORAL_TYPE_PREFIXES):
        return bool(_TEMPORAL_TEXT.match(inner))
    return True


#: Where a scope-level output observation is filed. ``cte:c`` is a name inside one
#: statement, not a table, so it cannot be compared to a target table and shares one
#: bucket instead -- see :func:`value_domain_index`.
_LOGICAL_OWNER = ("<scope>",)


def value_domain_index(entries: Sequence[Mapping]) -> dict:
    """Two lookups, both keyed by ``(normalized owner, column)``.

    ``by_column`` is the physical source column a value travels from. ``by_output`` is
    the column a projection *produces*, and its owner is the target table that
    projection writes -- because ``status`` is the most reused column name a warehouse
    has, and a CASE label written into ``mart.orders.status`` says nothing whatever
    about ``mart.tickets.status``. Owners are normalized by :func:`table_key`, so the
    two qualification levels one corpus records (``mart.t`` at a read,
    ``catalog.mart.t`` at the writer) are one owner.

    A scope-level output -- a CASE inside a CTE whose column never reaches a named
    target column -- names no table at all, so it is filed under ``_LOGICAL_OWNER``: it
    keeps speaking to the column it produces in its own statement, which is the only
    place its observations came from.
    """
    index: dict[str, dict] = {"by_column": {}, "by_output": {}}
    for entry in entries:
        owner = str(entry["column_ref"]).rsplit(".", 1)[0]
        logical = bool(entry.get("logical"))
        if not logical:
            key = (table_key(owner), str(entry["column"]))
            index["by_column"].setdefault(key, []).append(entry)
        if any(
            str(item.get("context")) in OUTPUT_CONTEXTS
            for item in entry.get("observations") or []
        ):
            output_key = (
                _LOGICAL_OWNER if logical else table_key(owner),
                str(entry["column"]),
            )
            index["by_output"].setdefault(output_key, []).append(entry)
    return index


def apply_value_domains(
    fields: Sequence[dict], entries: Sequence[Mapping], target_table: object = None
) -> None:
    """Give each field its ``value_domain`` (and, when confirmed, its summary suffix).

    ``target_table`` is the table these fields are written to: the second half of the
    output route's key. Without it only the scope-level observations can match, because
    a value published under some other table's column is not this column's value.
    """
    index = value_domain_index(entries)
    owner = table_key(target_table)
    for field in fields:
        domain = _field_domain(field, index, owner)
        _set_domain(field, domain)
        _apply_summary_suffix(field, domain)


def _set_domain(field: dict, domain: Sequence[dict]) -> None:
    """Write ``value_domain`` in front of ``sources``, keeping every other key in place."""
    splice_before(field, "sources", VALUE_DOMAIN_KEY, list(domain) if domain else None)


def splice_before(entry: dict, anchors: object, key: str, value) -> None:
    """Put ``key`` in front of the first of ``anchors`` present; ``None`` removes it.

    The key order is part of ``semantic-json/1`` and these writers run after the dict was
    assembled, so an entry is spliced in rather than appended -- and rather than this
    module having to know the profile's whole key order. Several anchors because an
    optional key (``sql_comments``) is a fine landmark only when the entry has one.
    """
    entry.pop(key, None)
    if value is None:
        return
    names = (anchors,) if isinstance(anchors, str) else tuple(anchors)
    anchor = next((name for name in names if name in entry), None)
    rebuilt: dict = {}
    for existing, current in entry.items():
        if existing == anchor:
            rebuilt[key] = value
        rebuilt[existing] = current
    rebuilt.setdefault(key, value)
    entry.clear()
    entry.update(rebuilt)


def _field_domain(field: Mapping, index: Mapping, target_owner: tuple) -> list[dict]:
    """One entry per ``(value, kind)``, in the order the values were first observed.

    WI-2.4b. The key used to carry ``column_ref`` as well, so one value that several
    observations produce -- two CASE blocks in two UNION branch scopes both labelling a
    row ``'SA'`` -- was published once per observation and the markdown read
    ``'SA'（待确认）、'SA'（待确认）、'SA'（待确认）``. A field's domain is a set of
    values, not a list of sightings: the sightings belong in ``seen_in``.
    """
    matched = _matched_entries(field, index, target_owner)
    closed = _column_closed_set(matched)
    domain: dict[tuple, dict] = {}
    for entry, _via in matched:
        key = (str(entry["value"]), str(entry["kind"]))
        current = domain.get(key)
        if current is None:
            domain[key] = _domain_entry(entry, closed)
        else:
            _merge_domain_entry(current, _domain_entry(entry, closed))
    return list(domain.values())


def _matched_entries(
    field: Mapping, index: Mapping, target_owner: tuple
) -> list[tuple[Mapping, str]]:
    """Every glossary entry that speaks about THIS column, paired with how it got here.

    Two routes, and the route decides what the entry is allowed to say. ``_VIA_OUTPUT``
    is the column's own projection -- a CASE label, a UNION constant, a constant
    column -- matched by target table *and* output name. ``_VIA_SOURCE`` is a source
    column the value reaches the target from unchanged, and only its ``=`` / ``IN``
    observations travel.
    """
    column = str(field.get("column"))
    matched = [
        (entry, _VIA_SOURCE)
        for source in _pass_through_sources(field)
        for entry in index["by_column"].get(
            (table_key(source.get("table")), str(source.get("column")))
        )
        or []
        if _has_context(entry, SOURCE_VALUE_CONTEXTS)
    ]
    matched.extend(
        (entry, _VIA_OUTPUT)
        for owner in (target_owner, _LOGICAL_OWNER)
        for entry in index["by_output"].get((owner, column)) or []
    )
    return [pair for pair in matched if _type_admits(field, pair[0])]


def _pass_through_sources(field: Mapping) -> list[Mapping]:
    """The sources whose value reaches the target unchanged, checked step by step."""
    if str(field.get("transform") or "") not in PASS_THROUGH_TRANSFORMS:
        return []
    return [
        source
        for source in field.get("sources") or []
        if str(source.get("transform") or "") in PASS_THROUGH_TRANSFORMS
    ]


def _has_context(entry: Mapping, contexts: frozenset) -> bool:
    return any(
        str(item.get("context")) in contexts for item in entry.get("observations") or []
    )


def _type_admits(field: Mapping, entry: Mapping) -> bool:
    """False when the declared type says the column cannot hold this quoted literal."""
    return type_admits_literal(
        field.get("type"), entry.get("sql_literal") or entry.get("value")
    )


def _column_closed_set(matched: Sequence[tuple[Mapping, str]]) -> bool | None:
    """WI-2.8 D3: closed is a claim about the COLUMN, so all of its values share it.

    Two proofs qualify, one per route. The column's own last step is a CASE whose
    branches and ELSE are all constants, so nothing else can come out of it; or a source
    column the value passes through unchanged was pinned by a closed ``IN`` list. A
    per-value verdict left one column reading "0 未证明、1 已证明" out of a single
    three-branch CASE, which answers a question nobody asked.
    """
    for entry, via in matched:
        basis = str((entry.get("closed_set") or {}).get("basis") or "")
        if via == _VIA_OUTPUT and basis == BASIS_CASE_EXHAUSTIVE:
            return True
        if via == _VIA_SOURCE and basis == BASIS_IN_LIST:
            return True
    return None


def _merge_domain_entry(current: dict, other: Mapping) -> None:
    """Fold a second observation of the same value into the entry already published."""
    current["seen_in"].extend(
        item for item in other["seen_in"] if item not in current["seen_in"]
    )
    current["meaning"] = _better_meaning(current["meaning"], other["meaning"])


def _better_meaning(current: dict | None, other: dict | None) -> dict | None:
    """A confirmed meaning beats a candidate; a candidate beats nothing."""
    if current is None:
        return other
    if other is None or current.get("status") == MEANING_STATUS_CONFIRMED:
        return current
    return other if other.get("status") == MEANING_STATUS_CONFIRMED else current


def _domain_entry(entry: Mapping, closed: bool | None = None) -> dict:
    return {
        "value": entry["value"],
        "sql_literal": str(entry.get("sql_literal") or entry["value"]),
        "kind": entry["kind"],
        "seen_in": sorted(
            {str(item.get("evidence")) for item in entry.get("observations") or []}
        ),
        # True when the corpus PROVES the set is closed; null means "not proven", never
        # "proven open" -- an observed set is a floor, not a ceiling. The verdict is the
        # column's (D3), and a match SHAPE is never part of an enumeration.
        "closed_set": True
        if closed and str(entry["kind"]) != VALUE_KIND_PATTERN
        else None,
        "meaning": _domain_meaning(entry),
    }


def _domain_meaning(entry: Mapping) -> dict | None:
    meaning = entry.get("meaning")
    if meaning:
        return {"text": str(meaning.get("text") or ""), "status": MEANING_STATUS_CONFIRMED}
    candidates = entry.get("meaning_candidates") or []
    if candidates:
        return {
            "text": str(candidates[0].get("text") or ""),
            "status": MEANING_STATUS_CANDIDATE,
        }
    return None


# --------------------------------------------------- rule value meanings (WI-2.12)


def apply_rule_value_meanings(
    rules: Sequence[dict], entries: Sequence[Mapping], task: object = None
) -> None:
    """Give each rule the dictionary's reading of the constants it pins a column to.

    One item per ``(column_ref, value)`` the rule compares against, in the order the
    rule writes them, each carrying the meaning the dictionary holds for exactly that
    column and value -- ``null`` while nobody has answered. A rule whose constants the
    dictionary has never seen keeps no key at all, so a profile built without
    ``--glossary`` is byte for byte the document it was before.
    """
    index = value_domain_index(entries)
    scoped = _scope_value_index(entries, task)
    for rule in rules:
        meanings = _merged_rule_meanings(
            _rule_value_meaning(reference, index, scoped)
            for reference in rule_value_references(rule)
        )
        splice_before(rule, "fields", RULE_VALUE_MEANINGS_KEY, meanings or None)


def _scope_value_index(entries: Sequence[Mapping], task: object) -> dict:
    """Scope-level entries by ``(scope owner, column)``, restricted to ONE task.

    A scope id is a name inside one statement: ``cte_a.flag`` in another task is a
    different CTE that happens to share a spelling, and a table name is the only thing
    that makes two columns the same column across a corpus. So the logical bucket
    answers a rule only when this very task is among the observations that filled it.
    """
    index: dict[tuple, list] = {}
    for entry in entries:
        observed = {str(item.get("task")) for item in entry.get("observations") or []}
        if not entry.get("logical") or str(task) not in observed:
            continue
        owner = str(entry["column_ref"]).rsplit(".", 1)[0]
        index.setdefault((owner, str(entry["column"])), []).append(entry)
    return index


def rule_value_references(rule: Mapping) -> list[tuple[str, bool, str]]:
    """``(column_ref, logical, sql literal)`` for every code this rule pins a column to.

    The same attribution the dictionary itself uses (:func:`_attribute`): a table only
    when exactly one of the rule's fields carries the name, a scope reference otherwise.
    Reading it back off the published rule rather than off the contract keeps the two
    halves of the layer answering from one place.
    """
    references: list[tuple[str, bool, str]] = []
    for expression in _rule_condition_expressions(rule):
        parsed = _comparison(semantic_text.parse_expression(expression))
        if parsed is None or parsed[2] not in RULE_VALUE_CONTEXTS:
            continue
        column, values, _context, _closes = parsed
        column_ref, logical = _attribute(rule, column, {})
        references.extend(
            (column_ref, logical, semantic_text.expression_text(node))
            for node in values
            if not isinstance(node, exp.Null)
            and _value_kind(node) in GLOSSARY_VALUE_KINDS
        )
    return references


def _rule_condition_expressions(rule: Mapping) -> list:
    """The conditions of one rule that compare a column against something."""
    kind = str(rule.get("kind"))
    if kind in _PREDICATE_RULE_KINDS:
        return [rule.get("expression")]
    if kind == "join_condition":
        # The key pairs compare two columns; only the extra conditions carry constants.
        return list(rule.get("extra_conditions") or [])
    if kind == "case_branch":
        return [branch.get("when") for branch in rule.get("branches") or []]
    return []


def _rule_value_meaning(
    reference: tuple[str, bool, str], index: Mapping, scoped: Mapping
) -> dict | None:
    """The dictionary entry for one ``(column, value)``, read as a rule item."""
    column_ref, logical, literal = reference
    owner, _, column = str(column_ref).rpartition(".")
    bucket = (
        scoped.get((owner, column))
        if logical
        else index["by_column"].get((table_key(owner), column))
    )
    value = strip_quotes(literal)
    entry = next(
        (item for item in bucket or [] if str(item.get("value")) == value), None
    )
    if entry is None:
        return None
    return {
        "column_ref": column_ref,
        "value": value,
        "sql_literal": literal,
        "meaning": _domain_meaning(entry),
    }


def _merged_rule_meanings(items: Iterable[Mapping | None]) -> list[dict]:
    """One item per ``(column_ref, value)``: a code repeated is one code."""
    merged: dict[tuple, dict] = {}
    for item in items:
        if item is None:
            continue
        key = (item["column_ref"], item["value"])
        current = merged.get(key)
        if current is None:
            merged[key] = dict(item)
        else:
            current["meaning"] = _better_meaning(current["meaning"], item["meaning"])
    return list(merged.values())


def rule_value_meanings(rule: Mapping) -> list[Mapping]:
    """The rule's published items, or an empty list when the key is absent."""
    return list(rule.get(RULE_VALUE_MEANINGS_KEY) or [])


def enum_entries(domain: Sequence[Mapping]) -> list[Mapping]:
    """The values the column actually holds -- everything a pattern is not."""
    return [item for item in domain if str(item.get("kind")) != VALUE_KIND_PATTERN]


def pattern_entries(domain: Sequence[Mapping]) -> list[Mapping]:
    """The shapes the SQL matched the column against (``LIKE`` / ``RLIKE``)."""
    return [item for item in domain if str(item.get("kind")) == VALUE_KIND_PATTERN]


def is_closed_domain(domain: Sequence[Mapping]) -> bool:
    """True when the SQL proved the ENUM closed. A pattern is not part of that claim."""
    entries = enum_entries(domain)
    return bool(entries) and all(item.get("closed_set") for item in entries)


def value_domain_text(
    domain: Sequence[Mapping], limit: int = 0, overflow_note: str = ""
) -> str:
    """``'PAID'（已支付）、'REFUND'（? 退款）、'NEW'（待确认）``, optionally bounded."""
    items = list(domain)
    shown = items[:limit] if limit else items
    rendered = "、".join(_value_text(item) for item in shown)
    if limit and len(items) > limit:
        rendered += f" 等 {len(items)} 个{overflow_note}"
    return rendered


def pattern_domain_text(domain: Sequence[Mapping]) -> str:
    """``'%UNIT_OUT_%'、'A|B'`` -- written bare, because a shape has no 待确认 meaning."""
    return "、".join(_pattern_text(item) for item in pattern_entries(domain))


def displayed_value(item: Mapping) -> str:
    """What a reader sees: the literal the author wrote, quotes and all (WI-2.8 D4)."""
    return str(item.get("sql_literal") or item.get("value") or "")


def _value_text(item: Mapping) -> str:
    meaning = item.get("meaning")
    if not meaning:
        return f"{displayed_value(item)}（{VALUE_DOMAIN_UNCONFIRMED}）"
    return f"{displayed_value(item)}（{_meaning_mark(meaning)}{meaning.get('text')}）"


def _pattern_text(item: Mapping) -> str:
    """A pattern with no meaning stays bare: 「待确认」 would promise a definition that
    nobody is ever going to write, because a match shape is not a business code."""
    meaning = item.get("meaning")
    if not meaning:
        return displayed_value(item)
    return f"{displayed_value(item)}（{_meaning_mark(meaning)}{meaning.get('text')}）"


def meaning_text(meaning: Mapping | None) -> str:
    """``已支付`` when a human confirmed it, ``? 退款`` for a candidate, empty for none."""
    if not meaning:
        return ""
    return f"{_meaning_mark(meaning)}{meaning.get('text')}"


def _meaning_mark(meaning: Mapping) -> str:
    if meaning.get("status") == MEANING_STATUS_CONFIRMED:
        return ""
    return f"{VALUE_DOMAIN_CANDIDATE_MARK} "


def _apply_summary_suffix(field: dict, domain: Sequence[Mapping]) -> None:
    """Append the values to the one-sentence summary -- only once one is confirmed.

    A candidate is a comment that happens to contain the value; putting it into the
    sentence a reader stops at would read as a definition, which is exactly the claim
    this layer refuses to make until a human signs it.
    """
    summary = str(field.get("summary") or "")
    marker = SUMMARY_VALUE_SEPARATOR + VALUE_DOMAIN_PREFIX
    if marker in summary:
        summary = summary[: summary.rindex(marker)]
    # The sentence enumerates what the column holds; a match shape is not one of those.
    values = enum_entries(domain)
    confirmed = any(
        (item.get("meaning") or {}).get("status") == MEANING_STATUS_CONFIRMED
        for item in values
    )
    if confirmed:
        summary += marker + value_domain_text(values, VALUE_DOMAIN_LIMIT)
    if summary:
        field["summary"] = summary


def enumerable_code(entry: Mapping) -> bool:
    """Whether one dictionary entry is a **code somebody could be asked to name**.

    WI-9 legacy b. ``values_total`` counts every constant the corpus saw a column
    compared against, which is the right denominator for "how much did we observe" and
    the wrong one for "how much is still unexplained": a batch date, a row limit and a
    ``= 0`` guard are not business vocabulary, and no owner will ever confirm them. Five
    conditions, each a fact of the observation rather than a judgement of the value:

    1. it is filed under a PHYSICAL column -- a scope-level constant belongs to an
       expression inside one statement, not to a column anyone can look up;
    2. it is a literal, never a match shape;
    3. some observation of it is in an :data:`ENUMERABLE_CONTEXTS` context;
    4. it does not read as a date -- ``dt = '20250115'`` is a partition, not a code;
    5. a bare number additionally needs an :data:`ENUMERABLE_NUMERIC_CONTEXTS` context.
    """
    if entry.get("logical") or str(entry.get("kind")) != VALUE_KIND_LITERAL:
        return False
    contexts = {
        str(item.get("context")) for item in entry.get("observations") or []
    }
    if not contexts & ENUMERABLE_CONTEXTS:
        return False
    value = strip_quotes(str(entry.get("value") or ""))
    if not value or _TEMPORAL_TEXT.match(value):
        return False
    if _NUMERIC_TEXT.match(value):
        return bool(contexts & ENUMERABLE_NUMERIC_CONTEXTS)
    return True


def enumerable_codes(entries: Sequence[Mapping]) -> set[tuple]:
    """``{(column, value, kind)}`` for the entries :func:`enumerable_code` admits."""
    return {
        (str(entry.get("column")), str(entry.get("value")), str(entry.get("kind")))
        for entry in entries
        if enumerable_code(entry)
    }


def glossary_coverage(
    fields: Sequence[Mapping],
    rules: Sequence[Mapping] = (),
    entries: Sequence[Mapping] = (),
) -> dict[str, int]:
    """How much of this task's code vocabulary the dictionary can already explain.

    WI-2.12. Two halves counted apart and then deduped into one total: the values a
    FIELD holds (``value_domain``) and the codes a RULE pins a column to
    (``value_meanings``). One code is one business question however often it is written,
    so the key is ``(column name, value, kind)`` -- a status pinned in a WHERE and
    carried unchanged into the output column of the same name is one value to confirm,
    not two.

    ``entries`` is the dictionary those values were read from, and it is what carries
    the observation CONTEXT a published ``value_domain`` entry no longer has. It decides
    the WI-9 pair: ``enumerable_*`` is the same union narrowed to the codes
    :func:`enumerable_code` admits, which is the denominator the A2 coverage ratio is
    taken over. Without it the pair is zero rather than absent -- "nothing qualified"
    and "nobody asked" read the same to a counter, and the totals beside it say which.
    """
    codes = enumerable_codes(entries)
    field_items = _field_value_items(fields)
    rule_items = _rule_value_items(rules)
    field_values = _coverage_statuses(field_items)
    rule_values = _coverage_statuses(rule_items)
    merged = dict(field_values)
    for key, status in rule_values.items():
        merged[key] = _stronger_status(merged.get(key), status)
    enumerable = {
        key
        for key, _status, names in [*field_items, *rule_items]
        if key in merged and any((name, key[1], key[2]) in codes for name in names)
    }
    return {
        "values_total": len(merged),
        "confirmed": _status_count(merged, MEANING_STATUS_CONFIRMED),
        "candidate": _status_count(merged, MEANING_STATUS_CANDIDATE),
        "rule_values_total": len(rule_values),
        "rule_values_confirmed": _status_count(rule_values, MEANING_STATUS_CONFIRMED),
        "field_values_total": len(field_values),
        "field_values_confirmed": _status_count(field_values, MEANING_STATUS_CONFIRMED),
        "enumerable_total": len(enumerable),
        "enumerable_confirmed": sum(
            1
            for key in enumerable
            if merged.get(key) == MEANING_STATUS_CONFIRMED
        ),
    }


def _field_value_items(fields: Sequence[Mapping]) -> list[tuple[tuple, object, list]]:
    """``(key, status, the column names the dictionary may hold this value under)``.

    A field publishes its domain under its own OUTPUT name, and the dictionary files an
    observation under the column the SQL compared -- the same code, two names, whenever
    a pass-through renames it. Both are offered, so a renamed code is not silently
    dropped from the enumerable count.
    """
    return [
        (
            (str(field.get("column")), str(item.get("value")), str(item.get("kind"))),
            (item.get("meaning") or {}).get("status"),
            _dictionary_names(field),
        )
        for field in fields
        for item in field.get(VALUE_DOMAIN_KEY) or []
    ]


def _dictionary_names(field: Mapping) -> list[str]:
    names = [str(field.get("column"))]
    names.extend(
        str(source.get("column"))
        for source in _pass_through_sources(field)
        if source.get("column")
    )
    return names


def _rule_value_items(rules: Sequence[Mapping]) -> list[tuple[tuple, object, list]]:
    """A rule's codes, keyed by the bare column name the field side also uses."""
    return [
        (
            (
                str(item.get("column_ref")).rpartition(".")[2],
                str(item.get("value")),
                VALUE_KIND_LITERAL,
            ),
            (item.get("meaning") or {}).get("status"),
            [str(item.get("column_ref")).rpartition(".")[2]],
        )
        for rule in rules
        for item in rule_value_meanings(rule)
    ]


def _coverage_statuses(items: Sequence[tuple]) -> dict[tuple, object]:
    counted: dict[tuple, object] = {}
    for key, status, *_rest in items:
        counted[key] = _stronger_status(counted.get(key), status)
    return counted


def _stronger_status(current: object, other: object) -> object:
    """Confirmed beats candidate beats nothing -- the same order ``_better_meaning`` uses."""
    ranked = (MEANING_STATUS_CONFIRMED, MEANING_STATUS_CANDIDATE)
    for status in ranked:
        if status in (current, other):
            return status
    return current or other


def _status_count(statuses: Mapping[tuple, object], status: str) -> int:
    return sum(1 for item in statuses.values() if item == status)
