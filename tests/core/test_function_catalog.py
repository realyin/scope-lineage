"""C2: the function catalog knows the Spark builtins, so ``has_udf`` means UDF.

``expression_features.has_udf`` is a contract field, and it was computed against a
hand-written list of 40-odd names. ``HOUR``, ``LAG``, ``RANK``, ``EXPLODE`` and
``GET_JSON_OBJECT`` were all missing, so ordinary Spark SQL was published as a black
box -- one real 52-field task carried 148 "UDF 黑盒" marks and not one of them was a UDF.

Two properties are pinned here: every function name sqlglot's Spark dialect knows is
known to the catalog too, and a name nobody knows is still reported.
"""

from __future__ import annotations

import re

import pytest
from sqlglot.dialects.spark import Spark

from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.semantic_markdown import render_semantic_markdown
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.render.semantic_text import UDF_MARKER
from scope_lineage.scope.expression_text import (
    _SQL_KEYWORDS_BEFORE_PAREN,
    _function_names,
)
from scope_lineage.scope.function_catalog import _KNOWN_SCALAR_FUNCTIONS
from scope_lineage.scope.scope_builder import parse_scope_lineage


SCHEMA = {
    "ods.e": [
        "id",
        "name",
        "amount",
        "event_ts",
        "payload",
        "tags",
        "dt",
    ],
}

# The name shape `_function_names` can ever hand the catalog: a bare identifier
# immediately followed by `(`.
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


def _document(sql: str) -> dict:
    return to_lineage_dict(parse_scope_lineage(sql, "udf_case", schema=SCHEMA))


def _udf_expressions(document: dict) -> list[str]:
    """Every expression the contract calls a UDF, from logic blocks and outputs."""
    found = []
    for scope in (document.get("scopes") or {}).values():
        for item in [*(scope.get("logic_blocks") or []), *(scope.get("outputs") or [])]:
            if (item.get("expression_features") or {}).get("has_udf"):
                found.append(
                    str(item.get("expression") or item.get("raw_expression") or "")
                )
    return found


# ------------------------------------------------------- the sqlglot Spark registry


def test_every_spark_dialect_function_name_is_in_the_catalog() -> None:
    """sqlglot's Spark grammar is the reference list; the catalog must not fall behind."""
    registered = {
        name.lower()
        for name in Spark.Parser.FUNCTIONS
        if _IDENTIFIER.match(name.lower())
    }
    assert registered
    missing = sorted(registered - _KNOWN_SCALAR_FUNCTIONS)
    assert missing == []


@pytest.mark.parametrize(
    "name",
    [
        # The five measured in the real corpus, then the Hive/Spark names sqlglot may
        # not register under their own class.
        "hour", "lag", "rank", "explode", "get_json_object",
        "nvl", "nvl2", "date_format", "from_unixtime", "unix_timestamp",
        "datediff", "date_add", "date_sub", "trunc", "last_day",
        "months_between", "add_months", "regexp_extract", "regexp_replace",
        "json_tuple", "split", "concat_ws", "collect_list", "collect_set",
        "percentile_approx", "named_struct", "map_keys", "posexplode",
        "sha2", "md5", "hash", "crc32", "instr", "locate", "lpad", "rpad",
        "translate", "initcap", "format_number", "round", "bround", "floor",
        "ceil", "pmod", "rand", "uuid", "current_date", "current_timestamp",
        "now", "coalesce", "nullif", "greatest", "least", "size",
        "array_contains", "sort_array", "element_at", "transform", "aggregate",
        "filter", "exists", "to_date", "to_timestamp", "year", "month", "day",
        "dayofmonth", "dayofweek", "weekofyear", "minute", "second", "quarter",
        "decode", "encode", "base64", "unbase64", "reflect", "java_method",
        "lead", "dense_rank", "ntile", "first_value", "last_value",
        "date_trunc", "from_json", "regexp_like",
    ],
)
def test_the_curated_hive_and_spark_builtins_are_known(name: str) -> None:
    assert name in _KNOWN_SCALAR_FUNCTIONS


def test_the_catalog_is_lower_case_so_names_compare_case_insensitively() -> None:
    assert all(name == name.lower() for name in _KNOWN_SCALAR_FUNCTIONS)


# ------------------------------------------------------------------- regression SQL


BUILTIN_SQL = """
INSERT OVERWRITE TABLE mart.t
SELECT
  id,
  HOUR(event_ts)                                            AS event_hour,
  DATE_FORMAT(event_ts, 'yyyyMMdd')                         AS event_day,
  FROM_UNIXTIME(UNIX_TIMESTAMP(event_ts), 'yyyy-MM-dd')     AS event_date,
  DATEDIFF(CURRENT_DATE(), TO_DATE(event_ts))               AS age_days,
  NVL(name, 'UNKNOWN')                                      AS safe_name,
  REGEXP_REPLACE(name, '[0-9]+', '')                        AS letters,
  GET_JSON_OBJECT(payload, '$.channel')                     AS channel,
  CONCAT_WS('|', name, SUBSTR(name, 1, 3))                  AS label,
  ROUND(amount, 2)                                          AS amount_2,
  LPAD(CAST(id AS STRING), 8, '0')                          AS padded_id,
  SIZE(SPLIT(tags, ','))                                    AS tag_count,
  MD5(name)                                                 AS name_hash,
  LAG(amount) OVER (PARTITION BY id ORDER BY event_ts)      AS prev_amount,
  RANK() OVER (PARTITION BY id ORDER BY amount DESC)        AS amount_rank
FROM ods.e
WHERE dt = '20260101' AND INSTR(name, 'x') = 0
"""

UDF_SQL = """
INSERT OVERWRITE TABLE mart.t
SELECT id, my_udf(name) AS scored
FROM ods.e
WHERE dt = '20260101'
"""


def test_a_statement_of_spark_builtins_reports_no_udf() -> None:
    document = _document(BUILTIN_SQL)

    assert _udf_expressions(document) == []


def test_the_builtin_statement_carries_no_udf_black_box_line() -> None:
    document = _document(BUILTIN_SQL)

    rendered = render_semantic_markdown(build_semantic_profile(document))

    assert UDF_MARKER not in rendered


def test_a_genuinely_unknown_function_is_still_flagged() -> None:
    document = _document(UDF_SQL)

    flagged = _udf_expressions(document)

    assert flagged
    assert all("my_udf" in expression.lower() for expression in flagged)
    assert UDF_MARKER in render_semantic_markdown(build_semantic_profile(document))


# --------------------------------------------- keywords are not function calls (C2b)


KEYWORD_SCHEMA = {
    "ods.src": [
        "id", "kind", "amt", "t", "s", "u", "tp", "st", "dt",
        "comp", "bal", "x", "ts", "v",
    ],
}

# Five shapes measured on real input, every one of them reported as a UDF black box and
# not one of them calling anything but a builtin. They differ in which keyword sits in
# front of the `(`: `IN`, `NOT`, both at once, an `OR`/`LIKE` chain, and a nested call.
KEYWORD_MEASURES = {
    "in_inside_case": "SUM(CASE WHEN src.kind IN ('a', 'b') THEN src.amt ELSE 0 END)",
    "not_inside_if": (
        "SUM(IF(src.t = 'C' AND NOT (src.s = 'P1' AND src.u = 'S5'), src.amt, 0))"
    ),
    "in_inside_if": "MIN(IF(src.tp = '03' AND src.st IN ('1', '3'), src.dt, NULL))",
    "like_or_chain": (
        "SUM(CASE WHEN src.comp LIKE 'Recv%' OR src.comp = 'AccruPint' THEN src.bal "
        "WHEN src.comp = 'AccruInt' THEN 0 END)"
    ),
    "nested_builtin_call": (
        "SUM(IF(src.x = 'C' "
        "AND SUBSTRING(src.ts, 1, 19) <= '2026-08-14 00:00:00', src.v, 0))"
    ),
}


def _measure_document(measure: str) -> dict:
    sql = (
        "INSERT OVERWRITE TABLE mart.t\n"
        f"SELECT src.id, {measure} AS m\n"
        "FROM ods.src src\n"
        "GROUP BY src.id"
    )
    return to_lineage_dict(parse_scope_lineage(sql, "keyword_case", schema=KEYWORD_SCHEMA))


@pytest.mark.parametrize("measure", KEYWORD_MEASURES.values(), ids=KEYWORD_MEASURES)
def test_a_keyword_before_a_parenthesis_is_not_a_udf(measure: str) -> None:
    assert _udf_expressions(_measure_document(measure)) == []


@pytest.mark.parametrize("measure", KEYWORD_MEASURES.values(), ids=KEYWORD_MEASURES)
def test_a_keyword_before_a_parenthesis_is_not_published_as_a_function(
    measure: str,
) -> None:
    """``expression_features.functions`` is the catalog's input; it must hold calls only."""
    document = _measure_document(measure)

    found = set()
    for scope in (document.get("scopes") or {}).values():
        for item in [*(scope.get("logic_blocks") or []), *(scope.get("outputs") or [])]:
            found.update((item.get("expression_features") or {}).get("functions") or [])

    assert not found & {"in", "not", "and", "or", "when", "then", "else"}


@pytest.mark.parametrize(
    "expression",
    [
        "x in ('a', 'b')",
        "not (a = 1 and b = 2)",
        "a and (b or c)",
        "case when (a) then 1 else (2) end",
        "x between (1) and (2)",
        "y is not null and z in (select k from t)",
    ],
)
def test_a_sql_keyword_is_never_read_as_a_function_name(expression: str) -> None:
    """The scanner is a regex over text, so every keyword that may precede `(` is one it
    would otherwise harvest as a call."""
    assert _function_names(expression) == [
        name for name in _function_names(expression) if name not in _SQL_KEYWORDS_BEFORE_PAREN
    ]
    assert not set(_function_names(expression)) & {
        "in", "not", "and", "or", "when", "then", "else", "between", "is", "select",
    }


def test_a_real_call_beside_a_keyword_is_still_collected() -> None:
    assert _function_names("not (upper(a) in ('x')) and coalesce(b, 0) = 1") == [
        "upper",
        "coalesce",
    ]
