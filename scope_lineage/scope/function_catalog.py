"""SQL function-name catalogs used to classify expressions."""
from __future__ import annotations

import re

from sqlglot import expressions as exp
from sqlglot.dialects.hive import Hive
from sqlglot.dialects.spark import Spark
from sqlglot.dialects.spark2 import Spark2

_AGGREGATE_FUNCTIONS = {
    "avg",
    "collect_list",
    "collect_set",
    "count",
    "count_if",
    "max",
    "min",
    "sum",
}


_CLEANING_FUNCTIONS = {
    "coalesce",
    "nvl",
    "replace",
    "regexp_replace",
    "substr",
    "substring",
    "trim",
}


# The name shape the expression scanner can ever produce: a bare identifier immediately
# followed by `(`. sqlglot also registers multi-word forms (`GROUP_CONCAT`-style aliases
# spelled with spaces, `ARRAY<...>` constructors); those can never be looked up here.
_FUNCTION_NAME_PATTERN = re.compile(r"^[a-z_][a-z0-9_]*$")

# The Hive/Spark builtins this catalog names outright. Most are in sqlglot's
# registries too; naming them here keeps the answer the same whichever supported
# sqlglot version is installed, and covers the ones sqlglot registers under no name
# of their own. Without them, ordinary SQL was published as a UDF black box.
_CURATED_BUILTIN_FUNCTIONS = frozenset({
    "add_months", "aggregate", "array_contains", "ascii", "assert_true", "base64",
    "bin", "bround", "cast", "ceil", "chr", "coalesce", "collect_list", "collect_set",
    "concat_ws", "conv", "crc32", "current_date", "current_timestamp", "current_user",
    "date_add", "date_format", "date_sub", "date_trunc", "datediff", "day",
    "dayofmonth", "dayofweek", "decode", "dense_rank", "element_at", "encode", "exists",
    "explode", "explode_outer", "filter", "find_in_set", "first_value", "floor",
    "format_number", "from_json", "from_unixtime", "get_json_object", "greatest",
    "hash", "hex", "hour", "if", "initcap", "inline", "input_file_name", "instr",
    "java_method", "json_tuple", "lag", "last_day", "last_value", "lead", "least",
    "levenshtein", "locate", "lpad", "map_from_arrays", "map_keys", "map_values", "md5",
    "minute", "monotonically_increasing_id", "month", "months_between", "named_struct",
    "now", "ntile", "nullif", "nvl", "nvl2", "parse_url", "percentile",
    "percentile_approx", "pmod", "posexplode", "posexplode_outer", "printf", "quarter",
    "raise_error", "rand", "rank", "reflect", "regexp_extract", "regexp_like",
    "regexp_replace", "repeat", "reverse", "round", "row_number", "rpad", "second",
    "sentences", "sha2", "shiftleft", "shiftright", "size", "sort_array", "soundex",
    "space", "spark_partition_id", "split", "stack", "str_to_map", "substring_index",
    "to_date", "to_timestamp", "transform", "translate", "trunc", "unbase64", "unhex",
    "unix_timestamp", "uuid", "weekofyear", "xpath_string", "year",
})


def _spark_builtin_function_names() -> frozenset[str]:
    """Every function name sqlglot's Spark/Hive grammars can place.

    ``expression_features.has_udf`` answers "is this name opaque to us". The honest
    reference list is the grammar that parses the SQL, not a hand-written sample of it:
    the sample stopped at 40-odd names, so ``HOUR`` / ``LAG`` / ``RANK`` / ``EXPLODE``
    were all reported as UDFs (one 52-field task carried 148 such marks, none of them a
    UDF). The dialect registries answer for the names Spark spells specially, and the
    ``exp.Func`` classes for the ones every dialect shares.
    """
    names: set[str] = set(_CURATED_BUILTIN_FUNCTIONS)
    for dialect in (Spark, Spark2, Hive):
        names.update(name.lower() for name in dialect.Parser.FUNCTIONS)
    for candidate in vars(exp).values():
        if isinstance(candidate, type) and issubclass(candidate, exp.Func):
            if candidate is not exp.Func:
                names.update(name.lower() for name in candidate.sql_names())
    return frozenset(name for name in names if _FUNCTION_NAME_PATTERN.match(name))


_KNOWN_SCALAR_FUNCTIONS = frozenset({
    *_AGGREGATE_FUNCTIONS,
    *_CLEANING_FUNCTIONS,
    *_spark_builtin_function_names(),
    "left",
    "right",
})


_KNOWN_UDAFS = frozenset({
    "COLLECT_SET", "COLLECT_LIST", "CONCAT_WS", "PERCENTILE",
    "PERCENTILE_APPROX", "HISTOGRAM_NUMERIC", "NVL",
})
