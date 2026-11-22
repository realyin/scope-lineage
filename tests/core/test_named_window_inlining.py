"""A named window (`OVER w` + `WINDOW w AS (...)`) reads the columns of its definition.

The window's PARTITION BY and ORDER BY live in the SELECT's WINDOW clause, not under the
`OVER w` that names it, so a resolver that only walks the projection saw a window function
with no columns at all: `ROW_NUMBER() OVER w` became a CONSTANT and `SUM(amt) OVER w`
lost `user_id` and `ts` (audit 1.6). The named windows are inlined into every `OVER` that
names them before scopes are built, including a window defined on top of another one.
"""

from __future__ import annotations

from scope_lineage import parse_scope_lineage, to_dict

SCHEMA = {"ods.events": ["user_id", "ts", "amt", "kind"]}


def _lineage(sql: str) -> dict:
    return to_dict(parse_scope_lineage(sql, "named_window", schema=SCHEMA))


def _physical(lineage: dict, column: str) -> set[str]:
    trace = next(item for item in lineage["end_to_end_lineage"] if item["column"] == column)
    return {source["column"] for source in trace["physical_sources"]}


def _generated_types(lineage: dict, column: str) -> set[str]:
    trace = next(item for item in lineage["end_to_end_lineage"] if item["column"] == column)
    return {source.get("source_type") for source in trace.get("generated_sources") or []}


NAMED = """INSERT INTO dw.ranked
SELECT user_id, ROW_NUMBER() OVER w AS rn, SUM(amt) OVER w AS run_amt
FROM ods.events
WINDOW w AS (PARTITION BY user_id ORDER BY ts)"""

INLINE = """INSERT INTO dw.ranked
SELECT user_id,
       ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY ts) AS rn,
       SUM(amt) OVER (PARTITION BY user_id ORDER BY ts) AS run_amt
FROM ods.events"""


def test_a_named_window_reads_its_partition_and_order_columns():
    lineage = _lineage(NAMED)

    assert _physical(lineage, "rn") == {"user_id", "ts"}
    assert _physical(lineage, "run_amt") == {"user_id", "amt", "ts"}
    assert "CONSTANT" not in _generated_types(lineage, "rn")


def test_the_inline_window_form_is_unchanged():
    """Sentinel: the inline form, which already resolved, is what the named form becomes."""
    inline = _lineage(INLINE)

    assert _physical(inline, "rn") == {"user_id", "ts"}
    assert _physical(inline, "run_amt") == {"user_id", "amt", "ts"}


def test_a_select_without_a_window_clause_keeps_its_text():
    """Sentinel: only a SELECT that has a WINDOW clause is rewritten."""
    sql = "INSERT INTO dw.ranked SELECT user_id, amt FROM ods.events"

    root = _lineage(sql)["scopes"]["ROOT"]
    assert [output["expression"] for output in root["outputs"]] == [
        "`events`.`user_id`",
        "`events`.`amt`",
    ]


def test_a_window_built_on_another_inherits_its_partition():
    sql = """INSERT INTO dw.ranked
SELECT user_id, SUM(amt) OVER w2 AS run_amt
FROM ods.events
WINDOW w1 AS (PARTITION BY user_id), w2 AS (w1 ORDER BY ts)"""

    assert _physical(_lineage(sql), "run_amt") == {"user_id", "amt", "ts"}


def test_an_over_clause_refining_a_named_window_keeps_both_parts():
    sql = """INSERT INTO dw.ranked
SELECT user_id, SUM(amt) OVER (w ORDER BY ts) AS run_amt
FROM ods.events
WINDOW w AS (PARTITION BY kind)"""

    assert _physical(_lineage(sql), "run_amt") == {"kind", "amt", "ts"}


def test_a_window_alias_of_another_window_is_that_window():
    sql = """INSERT INTO dw.ranked
SELECT user_id, ROW_NUMBER() OVER w2 AS rn
FROM ods.events
WINDOW w1 AS (PARTITION BY user_id ORDER BY ts), w2 AS w1"""

    assert _physical(_lineage(sql), "rn") == {"user_id", "ts"}


def test_the_window_logic_block_carries_the_named_specification():
    lineage = _lineage(NAMED)

    blocks = [
        block for block in lineage["scopes"]["ROOT"]["logic_blocks"]
        if block["logic_type"] == "window"
    ]
    rn = next(block for block in blocks if block["output_fields"] == ["rn"])
    spec = rn["window_specification"]
    assert spec["window_function"] == "row_number"
    assert [item["expression_sql"] for item in spec["partition_by"]] != []
    assert spec["order_by"] != []


def test_a_window_name_inside_a_subquery_resolves_against_its_own_select():
    sql = """INSERT INTO dw.ranked
SELECT x.user_id, x.rn
FROM (
  SELECT user_id, ROW_NUMBER() OVER w AS rn
  FROM ods.events
  WINDOW w AS (PARTITION BY user_id ORDER BY ts)
) x"""

    assert _physical(_lineage(sql), "rn") == {"user_id", "ts"}
