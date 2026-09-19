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
