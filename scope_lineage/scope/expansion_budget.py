"""Budgeted expression expansion (PERF-001): bounded, composable, never damaged."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

# Expansion budget for `expanded_expression`. Inlining an upstream field's expanded text copies
# it once per reference, and each additional scope layer multiplies again; a moderately sized
# statement expanded to a string and a lineage.json three orders of magnitude larger (PERF-001).
#
# The budget bounds the copy by DECLINING a substitution, not by cutting text. What is left
# behind is the original `a.field` reference — still valid SQL, and itself the pointer to the
# upstream output that holds the rest of the logic. Because upstream expressions are bounded
# first, downstream ones inline small text, so the multiplication collapses at every layer
# instead of only at the top.
EXPANSION_MAX_CHARS = 262_144       # 256 KiB per materialized expression
EXPANSION_MAX_SUBSTITUTIONS = 2_000  # guards reference count, which chars alone does not

#: The flag an operator raises the substitution guard with, quoted in the gap this guard
#: produces. Named here, beside the number it moves, so the two cannot drift apart.
EXPANSION_LIMIT_FLAG = "--expansion-limit"

#: Which guard an operator can move, and with what. ``max_chars`` is the materialized
#: size ceiling and has no flag: raising it would hand back the multiplicative blow-up
#: the budget exists to prevent, while the untouched reference already points at the rest.
EXPANSION_GUARD_FLAGS = {"max_substitutions": EXPANSION_LIMIT_FLAG}


def expansion_limit_fact(guard: str | None, limit: int | None) -> dict | None:
    """The guard that stopped an expansion and the number it stopped at, or nothing.

    One shape for every place that publishes it -- the output, its mapping chain and the
    gap's evidence -- so a consumer learns to read it once.
    """
    if not guard or limit is None:
        return None
    return {"guard": str(guard), "limit": int(limit)}

#: The trailing note a guarded expression carries, so a consumer reading the text alone
#: cannot mistake a capped expansion for the whole logic (Q2). A SQL block comment: the
#: published expression stays parseable, exactly as the untouched `a.field` reference it
#: sits beside does.
EXPANSION_TRUNCATION_MARKER = "/* expansion truncated at {guard}={limit} */"


def expansion_truncation_marker(guard: str, limit: int) -> str:
    """The marker for one guard and the number it stopped at."""
    return EXPANSION_TRUNCATION_MARKER.format(guard=guard, limit=int(limit))


def truncated_expansion(expression: str, guard: str, limit: int) -> str:
    """``expression`` published with its truncation marker, still within the ceiling.

    Only ``max_chars`` is a size, so only it can require cutting text; the marker is then
    made room for rather than added on top, and the published string stays inside the
    limit the guard declared. ``max_substitutions`` counts references, so its number says
    nothing about length and the text is marked as it stands.
    """
    marker = expansion_truncation_marker(guard, limit)
    text = str(expression or "")
    if guard == "max_chars":
        room = max(int(limit) - len(marker) - 1, 0)
        if len(text) > room:
            text = text[:room].rstrip()
    return f"{text} {marker}" if text else marker


def expansion_sources_are_resolved(resolution: dict | None) -> bool:
    """Whether the walk finished the source set that the text ran out of room for.

    The two facts are independent: the budget caps the *concatenated text*, while the
    source sets are unioned from each upstream output whether or not its text was inlined
    (see ``_restore_facts_behind_unexpanded_refs``). When the sources are complete, a
    tripped guard is a publishing limit — a warning — not a missing lineage fact.
    """
    resolution = resolution or {}
    if str(resolution.get("status") or "") != "resolved":
        return False
    if [reason for reason in resolution.get("missing_reasons") or [] if reason]:
        return False
    return bool(
        resolution.get("physical_source_fields")
        or resolution.get("generated_sources")
        or resolution.get("rowset_sources")
    )

#: One run's substitution allowance, or None for the module default. A ContextVar rather
#: than a rebound constant: the budget is constructed several layers below the caller
#: that chose the number, and a process-wide assignment would outlive the parse that set
#: it -- an in-process second call would silently inherit the first one's policy.
_ACTIVE_MAX_SUBSTITUTIONS: ContextVar = ContextVar(
    "scope_lineage_expansion_max_substitutions", default=None
)


@contextmanager
def expansion_limit(max_substitutions: int | None):
    """Run the block with ``max_substitutions`` as every budget's allowance.

    ``None`` changes nothing, so a caller that was not asked for a limit is the caller it
    always was. The value is restored on the way out, including on an exception.
    """
    if max_substitutions is None:
        yield
        return
    if int(max_substitutions) < 1:
        raise ValueError(
            f"expansion limit must be a positive number of substitutions, got "
            f"{max_substitutions!r}"
        )
    token = _ACTIVE_MAX_SUBSTITUTIONS.set(int(max_substitutions))
    try:
        yield
    finally:
        _ACTIVE_MAX_SUBSTITUTIONS.reset(token)


def active_max_substitutions() -> int:
    """This run's substitution allowance: the caller's, else the module's."""
    active = _ACTIVE_MAX_SUBSTITUTIONS.get()
    return EXPANSION_MAX_SUBSTITUTIONS if active is None else active

class ExpansionBudget:
    """One expression's expansion allowance, and the record of what it had to decline.

    Shared by every inlining site so a single expression cannot exceed the limit by being
    grown from several places, and so the reason is reported the same way everywhere.
    """

    __slots__ = ("max_chars", "max_substitutions", "substitutions", "stop_reason",
                 "stop_limit", "skipped_refs")

    def __init__(self, max_chars: int | None = None,
                 max_substitutions: int | None = None) -> None:
        # Read at construction, not as a default argument: the limits are module-level policy
        # and tests raise them to prove the case under test actually blows up without them.
        self.max_chars = EXPANSION_MAX_CHARS if max_chars is None else max_chars
        self.max_substitutions = (
            active_max_substitutions() if max_substitutions is None else max_substitutions
        )
        self.substitutions = 0
        self.stop_reason: str | None = None
        # The number the run actually stopped at, so a diagnostic can quote it rather
        # than the reader having to know which constant `stop_reason` refers to.
        self.stop_limit: int | None = None
        self.skipped_refs: list[dict] = []

    @property
    def status(self) -> str:
        return "bounded" if self.stop_reason else "full"

    def _decline(self, reason: str, ref: str, scope_id: str | None, field: str | None) -> None:
        if not self.stop_reason:
            self.stop_reason = reason
            self.stop_limit = (
                self.max_chars if reason == "max_chars" else self.max_substitutions
            )
        entry = {"ref": ref, "reason": reason}
        if scope_id:
            entry["scope_id"] = scope_id
        if field:
            entry["field"] = field
        if entry not in self.skipped_refs:
            self.skipped_refs.append(entry)

    def substitute(self, expression: str, replacement: str, apply, *,
                   ref: str, scope_id: str | None = None, field: str | None = None) -> str:
        """Apply `apply(expression, replacement)` unless it would break the budget.

        Declining is checked twice: once cheaply on the replacement itself (a single upstream
        expression already at the limit can never be inlined), and once on the actual result,
        because one reference can occur many times.
        """
        if not replacement:
            return expression
        if self.substitutions >= self.max_substitutions:
            self._decline("max_substitutions", ref, scope_id, field)
            return expression
        if len(replacement) > self.max_chars:
            self._decline("max_chars", ref, scope_id, field)
            return expression
        expanded = apply(expression, replacement)
        if len(expanded) > self.max_chars:
            self._decline("max_chars", ref, scope_id, field)
            return expression
        if expanded != expression:
            self.substitutions += 1
        return expanded
