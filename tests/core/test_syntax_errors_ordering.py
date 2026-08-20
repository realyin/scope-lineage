"""`syntax_errors` must land in the same order in every process.

sqlglot builds one message per entry of `Expression.required_args`, which is a `set`, and
CPython randomises string hashing per process — so a statement missing two required keywords
produced the same two entries in an order that changed from run to run. `syntax_errors` is a
required field of `lineage.json`, and this project treats byte-for-byte determinism as a
contract invariant, so anyone diffing artifacts across runs saw a phantom change
(SYNTAX-ORDER-001).

The existing baseline test cannot catch this: it renders twice inside one process, where the
hash seed is fixed by definition.
"""

from __future__ import annotations

import json
import subprocess
import sys

from scope_lineage.scope.scope_builder import _ordered_syntax_errors, _syntax_status

# Two required keywords missing from one expression — the shape that reaches the set.
# `LIKE` stood here until Core learned to quote keyword-colliding identifiers, which made
# this statement parse; `WHERE` is a clause keyword, which Core never quotes, so the
# half-built TryCast still reaches `required_args` (KEYWORD-IDENT-001).
UNSTABLE_SQL = "INSERT INTO db.t SELECT CAST(WHERE AS DOUBLE) AS c FROM db.s"

_A = {"description": "Required keyword: 'this' missing", "line": 1, "col": 36}
_B = {"description": "Required keyword: 'expression' missing", "line": 1, "col": 36}


def test_either_input_order_gives_the_same_output():
    assert _ordered_syntax_errors([_A, _B]) == _ordered_syntax_errors([_B, _A])


def test_entries_at_one_position_are_ordered_by_description():
    ordered = _ordered_syntax_errors([_A, _B])

    assert [item["description"] for item in ordered] == [
        "Required keyword: 'expression' missing",
        "Required keyword: 'this' missing",
    ]


def test_position_order_is_preserved_across_positions():
    """Sorting must not shuffle errors that are genuinely ordered by where they occur."""
    early = {"description": "zzz later alphabetically", "line": 1, "col": 5}
    late = {"description": "aaa earlier alphabetically", "line": 9, "col": 1}

    ordered = _ordered_syntax_errors([late, early])

    assert [item["col"] for item in ordered] == [5, 1]


def test_an_entry_without_a_position_is_tolerated():
    """The fallback entry carries only a description."""
    bare = {"description": "TokenError: something"}

    ordered = _ordered_syntax_errors([bare, _A])

    assert len(ordered) == 2
    assert bare in ordered


def test_two_hash_seeds_produce_the_same_syntax_errors():
    """The guarantee that matters, and the only one the in-process test cannot give."""
    program = (
        "import json;"
        "from scope_lineage.scope.scope_builder import _syntax_status;"
        f"print(json.dumps(_syntax_status({UNSTABLE_SQL!r})[1]))"
    )
    runs = []
    for seed in ("0", "6"):
        completed = subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            check=True,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
        )
        runs.append(json.loads(completed.stdout))

    assert runs[0] == runs[1]
    # Guard the guard: this SQL must actually be one that produces two entries.
    assert len(runs[0]) >= 2


def test_the_statement_is_still_reported_as_recovered():
    status, errors = _syntax_status(UNSTABLE_SQL)

    assert status == "recovered"
    assert len(errors) >= 2
