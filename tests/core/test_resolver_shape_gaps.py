"""Three resolver shapes that lost a source they could name (WP3m, WP3n, WP3o).

* 3m: ``info.addr.city`` with two FROM sources. sqlglot leaves the three parts
  unrewritten, and ``addr`` was taken for a table alias; the struct column ``info`` is
  looked up in the sources instead -- bound when one source has it, AMBIGUOUS when more
  do (1.13-h).
* 3n: ``LATERAL VIEW JSON_TUPLE(...) t`` / ``STACK(n, ...) t`` without column aliases.
  Spark names the outputs ``c0..`` and ``col0..``; INLINE without a schema stays a gap
  (1.13-i).
* 3o: an AMBIGUOUS reference was handed to the input-table collector as a table named
  ``AMBIGUOUS``; every candidate is a table the statement reads (1.13-k).

Every name here is synthetic.
"""

from __future__ import annotations

from scope_lineage.contract import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage


def _document(sql: str, schema: dict) -> dict:
    return to_lineage_dict(parse_scope_lineage(sql, "t", schema=schema))


def _column(document: dict, name: str) -> dict:
    return next(c for c in document["scopes"]["ROOT"]["columns"] if c["name"] == name)


def _sources(column: dict) -> set[tuple[str, str]]:
    return {(source["scope"], source["column"]) for source in column["sources"]}


# ------------------------------------------------------------------ 3m


STRUCT_SQL = (
    "INSERT OVERWRITE TABLE m.t SELECT info.addr.city AS c "
    "FROM s.u JOIN s.v ON s.u.id = s.v.id"
)


def test_a_three_part_struct_access_binds_to_the_one_source_with_the_struct() -> None:
    document = _document(STRUCT_SQL, {"s.u": ["info", "id"], "s.v": ["id"]})

    assert _sources(_column(document, "c")) == {("s.u", "info")}
    assert not [
        w for w in document["diagnostics"].get("warnings", []) if w["type"] == "unresolved_alias"
    ]


def test_a_three_part_struct_access_two_sources_could_supply_is_ambiguous() -> None:
    document = _document(STRUCT_SQL, {"s.u": ["info", "id"], "s.v": ["info", "id"]})

    [source] = _column(document, "c")["sources"]
    assert source["scope"] == "AMBIGUOUS"
    assert {(c["scope"], c["column"]) for c in source["candidates"]} == {
        ("s.u", "info"), ("s.v", "info"),
    }


def test_a_three_part_access_through_a_real_alias_is_unchanged() -> None:
    document = _document(
        "INSERT OVERWRITE TABLE m.t SELECT u.info.addr AS c FROM s.u u JOIN s.v v ON u.id = v.id",
        {"s.u": ["info", "id"], "s.v": ["info", "id"]},
    )

    assert _sources(_column(document, "c")) == {("s.u", "info")}


# ------------------------------------------------------------------ 3n

UDTF_SCHEMA = {"s.a": ["id", "js", "c1", "c2", "arr"]}


def _udtf(document: dict) -> dict[str, set[tuple[str, str]]]:
    return {c["name"]: _sources(c) for c in document["scopes"]["udtf:t"]["columns"]}


def test_json_tuple_without_aliases_names_its_outputs_c0_onward() -> None:
    document = _document(
        "INSERT OVERWRITE TABLE m.t SELECT a.id, t.c0, t.c1 FROM s.a a "
        "LATERAL VIEW JSON_TUPLE(a.js, 'k1', 'k2') t",
        UDTF_SCHEMA,
    )

    assert _sources(_column(document, "c0")) == {("udtf:t", "c0")}
    assert _udtf(document) == {"c0": {("s.a", "js")}, "c1": {("s.a", "js")}}


def test_stack_without_aliases_names_its_outputs_col0_onward() -> None:
    document = _document(
        "INSERT OVERWRITE TABLE m.t SELECT a.id, t.col0, t.col1 FROM s.a a "
        "LATERAL VIEW STACK(2, 'x', a.c1, 'y', a.c2) t",
        UDTF_SCHEMA,
    )

    assert _sources(_column(document, "col1")) == {("udtf:t", "col1")}
    udtf = _udtf(document)
    assert set(udtf) == {"col0", "col1"}
    assert ("s.a", "c1") in udtf["col1"]


def test_inline_without_a_schema_is_still_a_gap() -> None:
    document = _document(
        "INSERT OVERWRITE TABLE m.t SELECT a.id, t.f FROM s.a a LATERAL VIEW INLINE(a.arr) t",
        UDTF_SCHEMA,
    )

    assert _sources(_column(document, "f")) == {("UNKNOWN", "f")}


# ------------------------------------------------------------------ 3o


def test_an_ambiguous_reference_keeps_every_candidate_table_as_an_input() -> None:
    document = _document(
        "INSERT OVERWRITE TABLE m.t SELECT v FROM s.a a CROSS JOIN s.b b",
        {"s.a": ["v", "p"], "s.b": ["v", "q"]},
    )

    inputs = document["related_metadata"]["input_tables"]
    assert set(inputs) == {"s.a", "s.b"}
    for table in ("s.a", "s.b"):
        used = {c["name"]: c["used"] for c in inputs[table]["declared_columns"]}
        assert used["v"] is True
