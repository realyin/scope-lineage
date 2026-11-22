"""The function catalog answers from a frozen name list, not the installed sqlglot.

``has_udf`` asks whether every called name is in ``KNOWN_FUNCTION_NAMES``. The catalog
used to fold in whatever names the installed sqlglot's Spark / Spark2 / Hive registries
held, and those differ between supported versions: 30.0.0 lacks ``try_divide``,
``negative``, ``rint`` and 23 more that 30.17.0 has, and 30.16.0 dropped ``hex_encode``.
So one SQL text got ``has_udf: true`` on one CI leg and ``false`` on another. The
registry names are now a snapshot taken from the pinned version; a test reports what
the installed sqlglot registers beyond it, without changing any output.
"""

from __future__ import annotations

import warnings

from sqlglot.dialects.spark import Spark

from scope_lineage import _function_names_snapshot as snapshot
from scope_lineage import function_catalog
from scope_lineage.scope.task_lineage import parse_task_lineage


def test_the_catalog_does_not_read_the_installed_registry(monkeypatch) -> None:
    monkeypatch.setitem(Spark.Parser.FUNCTIONS, "ZZ_REGISTERED_ONLY_HERE", lambda args: None)

    assert "zz_registered_only_here" not in function_catalog._spark_builtin_function_names()


def test_the_catalog_is_the_curated_list_and_the_snapshot() -> None:
    assert function_catalog._spark_builtin_function_names() == (
        function_catalog._CURATED_BUILTIN_FUNCTIONS | snapshot.REGISTRY_FUNCTION_NAMES
    )


def _has_udf(sql: str) -> list[bool]:
    result = parse_task_lineage(sql, task_name="t", schema={"db.src": ["a", "b"]})
    outputs = result.statement_lineage["stmt:001"]["scopes"]["ROOT"]["outputs"]
    return [output["expression_features"]["has_udf"] for output in outputs]


def test_has_udf_is_the_same_on_every_supported_sqlglot() -> None:
    """Names whose registration differs between 30.0.0 and 30.17.0 answer as on 30.17.0."""
    assert _has_udf(
        "INSERT OVERWRITE TABLE db.tgt SELECT try_divide(a, b) AS c1, negative(a) AS c2, "
        "rint(a) AS c3, hex_encode(a) AS c4 FROM db.src"
    ) == [False, False, False, True]


def test_sentinel_an_ordinary_builtin_and_a_udf() -> None:
    assert _has_udf(
        "INSERT OVERWRITE TABLE db.tgt SELECT abs(a) AS c1, my_udf(a) AS c2 FROM db.src"
    ) == [False, True]


def test_report_names_the_installed_sqlglot_registers_beyond_the_snapshot() -> None:
    """Report only: a new sqlglot's names reach ``has_udf`` by regenerating the snapshot."""
    registered = function_catalog.registry_function_names()
    added = sorted(registered - snapshot.REGISTRY_FUNCTION_NAMES)
    dropped = sorted(snapshot.REGISTRY_FUNCTION_NAMES - registered)
    if added or dropped:
        warnings.warn(
            f"sqlglot registry differs from the function-name snapshot (taken from "
            f"{snapshot.SQLGLOT_VERSION}): {len(added)} new {added[:20]}, "
            f"{len(dropped)} not registered {dropped[:20]}",
            stacklevel=1,
        )
    assert snapshot.REGISTRY_FUNCTION_NAMES  # the snapshot itself is never empty
