"""Audit 2.2: the scope layer's memo caches are bounded.

PERF-002 put five module-level caches in front of work the resolver repeats within one
parse (compiled patterns, field-reference extraction, two STRUCT-access probes, and the
literal-skipping substitution patterns). They were plain dicts, so a long-lived process
parsing many statements kept every key it ever saw. Each is now an LRU cache with a fixed
size, far above what one statement needs (a few hundred keys on the largest real tasks),
so the gain inside a parse is unchanged and the total stays capped.
"""

from __future__ import annotations

import functools

import pytest

from scope_lineage.scope import expression_refs, passthrough_resolution, scope_facts, sql_text_spans
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.scope.scope_types import SourceRef

CACHES = (
    expression_refs._cached_pattern,
    expression_refs._qualified_field_refs_cached,
    passthrough_resolution._struct_access_cached,
    scope_facts._struct_member_access_cached,
    sql_text_spans._combined,
)


def _cap(cache) -> int:
    return cache.cache_info().maxsize


@pytest.mark.parametrize("cache", CACHES, ids=lambda cache: cache.__name__)
def test_every_parse_cache_has_a_finite_size(cache) -> None:
    assert isinstance(cache, functools._lru_cache_wrapper)
    assert cache.cache_info().maxsize is not None


def test_distinct_inputs_beyond_the_cap_do_not_grow_the_caches() -> None:
    for cache in CACHES:
        cache.cache_clear()
    over = max(_cap(cache) for cache in CACHES) + 50
    for index in range(over):
        name = f"c{index}"
        expression_refs._cached_pattern(rf"`{name}`")
        sql_text_spans.sub_in_code(rf"\b{name}\b", "x", f"{name} + 1")
        expression_refs._qualified_field_refs(f"`a`.`{name}`")
        passthrough_resolution._expression_has_struct_member_access(
            f"`s`.`{name}`.`m`", [SourceRef(scope="cte:s", column=name)]
        )
        scope_facts._has_qualified_struct_member_access(f"`s`.`{name}`.`m`", [("s", name)])

    for cache in CACHES:
        assert cache.cache_info().currsize <= _cap(cache), cache.__name__


def test_consecutive_parses_stay_within_the_caps() -> None:
    for index in range(40):
        columns = [f"k{index}_{n}" for n in range(6)]
        parse_scope_lineage(
            f"WITH c AS (SELECT {', '.join(f'a.{name}' for name in columns)} FROM s.a{index} a) "
            f"INSERT OVERWRITE TABLE m.t SELECT {', '.join(f'c.{name} * 2' for name in columns)} FROM c",
            f"t{index}",
            schema={f"s.a{index}": columns},
        )

    for cache in CACHES:
        assert cache.cache_info().currsize <= _cap(cache), cache.__name__


def test_sentinel_cached_answers_are_unchanged() -> None:
    refs = expression_refs._qualified_field_refs("`a`.`x` + `b`.`y`")
    refs.append(("mutated", "by caller"))

    assert expression_refs._qualified_field_refs("`a`.`x` + `b`.`y`") == [("a", "x"), ("b", "y")]
    assert passthrough_resolution._expression_has_struct_member_access(
        "`s`.`p`.`m`", [SourceRef(scope="cte:s", column="p")]
    ) is True
    assert passthrough_resolution._expression_has_struct_member_access(
        "`s`.`p`.`m`", [SourceRef(scope="s.t", column="p")]
    ) is False
    assert scope_facts._has_qualified_struct_member_access("`s`.`p`.`m`", [("s", "p")]) is True
    assert scope_facts._has_qualified_struct_member_access("`s`.`p`", [("s", "p")]) is False
