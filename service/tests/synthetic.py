"""A neutral synthetic catalog of many tables, written for one test run."""

from __future__ import annotations

import json
from pathlib import Path


def synthetic_catalog(
    tables: int, concepts: int = 200, domains: int = 10, *, measures: int = 0,
    lineage: bool = False,
) -> dict:
    """``tables`` tables spread over ``concepts`` concepts related in a ring; each table
    keys its concept and holds a foreign key to the next one.

    With ``measures``, each concept has that many measure attributes, every table binds a
    column to each and leaves one column unmapped in every fifth table; with ``lineage``,
    the document carries lineage evidence proving the key of every other table."""
    ids = [f"concept:c{n:04d}" for n in range(concepts)]
    common = {"status": "drafted", "source": "test", "evidence": []}
    document = {
        "doc_format": "ontology-json/3",
        "catalog": {"name": "synthetic"},
        "counts": {"concepts": concepts, "representations": tables},
        "domains": [
            {"id": f"domain:d{n:02d}", "name": f"域 {n}", **common} for n in range(domains)
        ],
        "identifiers": [
            {"id": f"id:c{n:04d}", "name": f"标识 {n}", "identifies": ids[n], "scope": "global",
             "spellings": [], **common}
            for n in range(concepts)
        ],
        "code_sets": [],
        "concepts": [
            {"id": ids[n], "name": f"概念 {n}", "kind": "entity",
             "domain": f"domain:d{n % domains:02d}", "synonyms": [],
             "attributes": [
                 {"id": f"attr:c{n:04d}.m{m}", "name": f"度量 {m}", "category": "measure",
                  **common}
                 for m in range(measures)
             ],
             "identifiers": [f"id:c{n:04d}"], "definition": f"第 {n} 个概念。", **common}
            for n in range(concepts)
        ],
        "relations": [
            {"id": f"rel:r{n:04d}", "kind": "association", "from": ids[n],
             "to": ids[(n + 1) % concepts], "name": "links",
             "cardinality": {"from": "0..*", "to": "1"}, **common}
            for n in range(concepts)
        ],
        "constraints": [], "metrics": [], "terms": [],
        "representations": [
            {"table": f"db.t{n:05d}", "concept": ids[n % concepts], "kind": "core",
             "time": "snapshot", "table_status": "active", "scope": [], **common,
             "grain": {"identifiers": [f"id:c{n % concepts:04d}"], "source": "declared"},
             "bindings": [
                 {"column": "k", "to": "identifier", "ref": f"id:c{n % concepts:04d}"},
                 {"column": "fk", "to": "foreign_identifier",
                  "ref": f"id:c{(n + 1) % concepts:04d}"},
                 *({"column": f"m{m}", "to": "attribute",
                    "ref": f"attr:c{n % concepts:04d}.m{m}"} for m in range(measures)),
                 *([{"column": "u0", "to": "unmapped"}] if measures and n % 5 == 0 else []),
                 *({"column": f"a{m}", "to": "technical"} for m in range(20)),
             ]}
            for n in range(tables)
        ],
    }
    if lineage:
        document["evidence"] = {
            "inputs": {"lineage": {"tasks": tables}},
            "representations": {
                f"db.t{n:05d}": {"grain_proof": {"confidence": "proven", "keys": ["k"]}}
                for n in range(0, tables, 2)
            },
        }
    return document


def synthetic_semantics(
    tables: int, directory: Path, every: int = 3, *, measures: int = 0
) -> None:
    """A minimal table-semantics document, with one open question, for every ``every``-th
    table of ``synthetic_catalog``. With ``measures``, it also describes the measure
    columns (a unit on the first only), says whether a row is unique and lists watch
    items, one of them a conflict in every other document."""
    directory.mkdir(parents=True, exist_ok=True)
    for n in range(0, tables, every):
        table = f"db.t{n:05d}"
        summary: dict = {
            "what": f"第 {n} 张表。",
            "questions": [{"id": "q1", "text": f"第 {n} 张表的 k 是否唯一？",
                           "about": ["column:k"], "status": "open"}],
        }
        columns = [{"column": "k", "meaning": "键"}]
        if measures:
            summary["row"] = {"unique": ("yes", "no", "unknown")[n // every % 3]}
            summary["watch"] = [{"kind": "risk", "text": "注意"}] + (
                [{"kind": "conflict", "text": "矛盾"}] if n % 2 == 0 else []
            )
            columns += [
                {"column": f"m{m}", "meaning": "度量", "category": "measure",
                 **({"unit": "元"} if m == 0 else {})}
                for m in range(measures)
            ]
        document = {
            "doc_format": "table-semantics/1",
            "table": table,
            "summary": summary,
            "columns": columns,
            "rules": [],
        }
        (directory / f"{table}.json").write_text(
            json.dumps(document, ensure_ascii=False), encoding="utf-8"
        )
