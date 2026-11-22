"""WP4 1.13-l: a type's precision is not a magic number.

`magic_number` warns on an unexplained numeric literal in a column expression. The
literals of `DECIMAL(18, 2)` are the type's precision and scale -- part of the type, not a
value the expression computes with -- yet every `CAST(x AS DECIMAL(18, 2))` was warned
about `18`.
"""

from __future__ import annotations

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {"s.a": ["x", "y"]}


def _magic_messages(projection: str) -> list[str]:
    document = to_lineage_dict(
        parse_scope_lineage(
            f"INSERT OVERWRITE TABLE m.t SELECT {projection} AS d FROM s.a a",
            "magic",
            schema=SCHEMA,
        )
    )
    return [
        warning["msg"]
        for warning in (document.get("diagnostics") or {}).get("warnings") or []
        if warning["type"] == "magic_number"
    ]


@pytest.mark.parametrize(
    "projection",
    [
        "CAST(a.x AS DECIMAL(18, 2))",
        "CAST(a.x AS DECIMAL(38, 10))",
        "CAST(a.x AS VARCHAR(20))",
        "CAST(CAST(a.x AS DECIMAL(20, 4)) AS DECIMAL(18, 2))",
    ],
)
def test_a_type_parameter_is_not_a_magic_number(projection: str) -> None:
    assert _magic_messages(projection) == []


@pytest.mark.parametrize(
    ("projection", "literal"),
    [
        ("a.x * 7", "7"),
        ("CAST(a.x * 7 AS DECIMAL(18, 2))", "7"),
        ("ROUND(CAST(a.x AS DECIMAL(18, 2)), 4)", "4"),
    ],
)
def test_sentinel_a_value_literal_is_still_warned(projection: str, literal: str) -> None:
    messages = _magic_messages(projection)

    assert len(messages) == 1
    assert f"numeric literal {literal} " in messages[0]
