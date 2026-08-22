"""A quoted column name can be a pattern, and Spark expands it to the columns it matches.

``SELECT \\`(dt)?+.+\\``` is Spark's quoted regex column selection. Read as a literal name it
produces a column no table has, so the projection resolves to nothing and every downstream
reference to that subquery follows it down.
"""

from __future__ import annotations

from scope_lineage import parse_scope_lineage
from scope_lineage.scope.task_lineage import parse_task_lineage

# spark.sql.parser.quotedRegexColumnNames defaults to false, and under false Spark reads a
# backtick-quoted regex as an ordinary column name and fails analysis -- the statements below
# could not run as written. The SET is what makes them real SQL, so it is part of the fixture,
# not scaffolding added to make a test pass.
_ENABLE = "SET spark.sql.parser.quotedRegexColumnNames=true;\n"



SCHEMA = {"ods.s": ["id", "v", "dt"], "mart.t": ["id", "v"]}

REGEX_PROJECTION_SQL = _ENABLE + """
INSERT INTO mart.t
SELECT a.id, a.v FROM (SELECT `(dt)?+.+` FROM ods.s) a
"""


def test_a_quoted_regex_projection_expands_to_the_columns_it_matches() -> None:
    """``(dt)?+.+`` is Spark's idiom for "every column except dt".

    ``(dt)?+`` is possessive: it consumes ``dt`` and will not give it back, leaving ``.+``
    with nothing to match — so the pattern excludes exactly the column it names.
    """
    result = parse_scope_lineage(REGEX_PROJECTION_SQL, "regex_projection", schema=SCHEMA)

    assert [column.name for column in result.scopes["subq:a"].columns] == ["id", "v"]
    assert result.diagnostics.lineage_fact_gaps == []
    assert [
        (column.name, tuple((s.scope, s.column) for s in column.sources))
        for column in result.scopes["ROOT"].columns
    ] == [
        ("id", (("subq:a", "id"),)),
        ("v", (("subq:a", "v"),)),
    ]


def test_the_same_projection_is_complete_at_task_level() -> None:
    result = parse_task_lineage(
        REGEX_PROJECTION_SQL, task_name="regex_projection", schema=SCHEMA
    )

    assert result.diagnostics["lineage_fact_gaps"] == []
    assert result.analysis_status == {"status": "complete", "blocking_reasons": []}


def test_a_regex_projection_without_schema_keeps_its_gap() -> None:
    """Without the source's columns there is nothing to match the pattern against.

    Guessing here would invent column names; the wildcard path reports the same way.
    """
    result = parse_scope_lineage(
        _ENABLE + "INSERT INTO mart.t SELECT a.id FROM (SELECT `(dt)?+.+` FROM ods.undocumented) a",
        "regex_no_schema",
        schema={"mart.t": ["id", "v"]},
    )

    assert result.diagnostics.lineage_fact_gaps != []


def test_the_exclusion_pattern_behaves_the_same_on_every_supported_python() -> None:
    """Possessive quantifiers are 3.11+ syntax; this project supports 3.9.

    Compiling the pattern must not be what decides whether a column is excluded, or the
    same SQL would yield different lineage depending on the interpreter.
    """
    from scope_lineage.scope.scope_resolver import _compiled_column_pattern

    compiled = _compiled_column_pattern("(dt)?+.+")
    assert compiled is not None
    assert [name for name in ("id", "v", "dt") if compiled.fullmatch(name)] == ["id", "v"]

    emulated = _compiled_column_pattern("(?=((?:dt)?))\\1.+")
    assert [name for name in ("id", "v", "dt") if emulated.fullmatch(name)] == ["id", "v"]


def test_a_real_column_whose_name_contains_metacharacters_is_taken_literally() -> None:
    """The schema is consulted first, so an existing column is never read as a pattern."""
    result = parse_scope_lineage(
        "INSERT INTO mart.t SELECT a.`odd.name` AS id FROM (SELECT `odd.name` FROM ods.odd) a",
        "literal_quoted_name",
        schema={"ods.odd": ["odd.name"], "mart.t": ["id", "v"]},
    )

    assert [column.name for column in result.scopes["subq:a"].columns] == ["odd.name"]
