"""A statement whose scope build raises is kept, marked, and does not abort the batch.

Migrated from the integration repository, which held the only tests for this. Keeping a failed
statement is deliberate -- the failure stays diagnosable and one bad statement cannot cost a batch
its other results -- but it comes back with empty scopes, so it has to be *distinguishable* from a
success. It once was not: no status field, counted among the successes, and the task index only
recorded whether files existed. `ok=N, error=0` therefore did not mean N valid lineages, and
automation that checked the exit code alone fed empty lineage into the downstream stages
(PARSE-001).

These patch `_build_insert_scope` to inject the failure. There is no SQL that reliably makes a
scope build raise -- if there were, it would be a bug to fix rather than a fixture -- so the
failure is manufactured. Patching Core's own internals from Core's own tests crosses no boundary;
the same tests written in a consuming repository did, which is why they moved here.
"""

from __future__ import annotations

from unittest.mock import patch

import scope_lineage.scope.scope_builder as scope_builder
from scope_lineage import parse_all_scope_lineage, to_lineage_dict


def test_a_failed_statement_is_not_reported_as_a_successful_parse():
    original = scope_builder._build_insert_scope
    scope_builder._build_insert_scope = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        results = parse_all_scope_lineage("INSERT INTO t SELECT a FROM src", "t")
    finally:
        scope_builder._build_insert_scope = original

    assert len(results) == 1, "the failed statement must still be returned, not dropped"
    failed = results[0]
    assert failed.parse_status == "failed"
    assert not failed.scopes, "a failed build yields no scopes -- that is what makes it dangerous"
    # the status must survive into the artifact; consumers read lineage.json, not the dataclass
    assert to_lineage_dict(failed)["parse_status"] == "failed"


def test_a_successful_parse_still_says_so():
    """Without this the status is useless: everything failing looks the same as nothing failing."""
    results = parse_all_scope_lineage("INSERT INTO t SELECT a FROM src", "t")

    assert results[0].parse_status == "ok"


def test_an_error_in_one_insert_does_not_abort_the_others():
    sql = """
    INSERT INTO spark_catalog.dwd.t1 SELECT a.col1 FROM ods.src a;
    INSERT INTO spark_catalog.dwd.t2 SELECT a.col2 FROM ods.src a
    """
    original = scope_builder._build_insert_scope
    call_count = [0]

    def fail_first(tree, task_name, schema=None):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("simulated parse failure")
        return original(tree, task_name, schema)

    with patch.object(scope_builder, "_build_insert_scope", fail_first):
        results = parse_all_scope_lineage(sql, "multi_statement_with_one_failure")

    assert len(results) == 2
    assert any(w.type == "LINEAGE_ERROR" for w in results[0].diagnostics.warnings)
    assert "t1" in results[0].target_table
    assert results[1].scopes.get("ROOT") is not None, "the second statement must be unaffected"
