"""The literals a column's SQL writes out, per producer (B-V1 / V5, packet side).

``literal_outputs`` lists, in SQL spelling, the literals the last computing step of a
producer's chain writes when nothing but pass-throughs follow it: a constant (``''``,
``'web'``, ``NULL``), the fallback of a COALESCE / NVL, the outputs of a CASE / IF.
A literal NULL counts; a NULL a LEFT JOIN brings does not -- that is
``nullable_by_join``'s. A literal only compared in a condition is no output.
``constant_only`` says the producer writes nothing else: every branch ends in a constant.
The checks that read these facts are not here. Every name is synthetic.
"""

from __future__ import annotations

import pytest

from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.semantics.packet import build_packets

SCHEMA = {
    "demo_ods.order_src": ["order_id", "status", "x", "note_id"],
    "demo_ods.note_src": ["note_id", "note"],
    "demo_dwd.order_out": ["order_id", "c"],
}

CODES = ("WITH codes AS (SELECT * FROM VALUES ('k1', '1'), ('k2', '2') AS t(code_key, code_val)) "
         "INSERT OVERWRITE TABLE demo_dwd.order_out SELECT o.order_id, {c} AS c "
         "FROM demo_ods.order_src o LEFT JOIN codes c ON o.status = c.code_val "
         "LEFT JOIN demo_ods.note_src n ON o.note_id = n.note_id")


def _producer(expression: str, sql: str = CODES) -> dict:
    document = to_lineage_dict(parse_scope_lineage(sql.format(c=expression), "t", schema=SCHEMA))
    (packet,) = build_packets([(document, None)])
    column = next(c for c in packet["lineage"]["columns"] if c["column"] == "c")
    (producer,) = column["producers"]
    return producer


@pytest.mark.parametrize(("expression", "outputs", "constant_only"), [
    ("coalesce(c.code_key, '')", ["''"], False),
    ("nvl(o.x, 'none')", ["'none'"], False),
    ("''", ["''"], True),
    ("NULL", ["NULL"], True),
    ("CAST(NULL AS STRING)", ["NULL"], True),
    ("0", ["0"], True),
    ("CASE WHEN o.status = '1' THEN 'A' WHEN o.status = '2' THEN NULL ELSE '' END",
     ["'A'", "NULL", "''"], False),
    ("if(o.x IS NULL, 'Y', o.x)", ["'Y'"], False),
])
def test_the_literals_a_column_writes_are_listed(expression, outputs, constant_only) -> None:
    producer = _producer(expression)
    assert producer["literal_outputs"] == outputs
    assert producer.get("constant_only", False) is constant_only


@pytest.mark.parametrize("expression", [
    # '' only in the condition: the column writes NULL or x, never ''.
    "CASE WHEN o.x = '' THEN o.status ELSE o.x END",
    "o.x",
    # A NULL a LEFT JOIN brings is no literal.
    "n.note",
    "upper(o.x)",
])
def test_a_column_that_writes_no_literal_carries_no_key(expression) -> None:
    producer = _producer(expression)
    assert "literal_outputs" not in producer and "constant_only" not in producer


def test_a_literal_transformed_later_is_no_output() -> None:
    producer = _producer("concat(s.c, '_y')", (
        "INSERT OVERWRITE TABLE demo_dwd.order_out SELECT s.order_id, {c} AS c "
        "FROM (SELECT order_id, 'web' AS c FROM demo_ods.order_src) s"))
    assert "literal_outputs" not in producer


def test_a_literal_handed_on_unchanged_is_an_output() -> None:
    producer = _producer("s.c", (
        "INSERT OVERWRITE TABLE demo_dwd.order_out SELECT s.order_id, {c} AS c "
        "FROM (SELECT order_id, 'web' AS c FROM demo_ods.order_src) s"))
    assert producer["literal_outputs"] == ["'web'"]
    assert producer["constant_only"] is True


def test_union_branches_each_add_their_constant() -> None:
    producer = _producer("'web'", (
        "INSERT OVERWRITE TABLE demo_dwd.order_out SELECT order_id, {c} AS c "
        "FROM demo_ods.order_src UNION ALL SELECT order_id, 'app' AS c FROM demo_ods.order_src"))
    assert producer["literal_outputs"] == ["'web'", "'app'"]
    assert producer["constant_only"] is True


def test_a_branch_that_passes_a_source_on_is_not_constant_only() -> None:
    producer = _producer("'web'", (
        "INSERT OVERWRITE TABLE demo_dwd.order_out SELECT order_id, {c} AS c "
        "FROM demo_ods.order_src UNION ALL SELECT order_id, x AS c FROM demo_ods.order_src"))
    assert producer["literal_outputs"] == ["'web'"]
    assert "constant_only" not in producer


def test_an_inline_values_column_is_no_single_literal() -> None:
    producer = _producer("c.code_key")
    assert "literal_outputs" not in producer and "constant_only" not in producer
