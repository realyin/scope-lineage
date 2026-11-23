"""A neutral synthetic catalog of many tables, written for one test run."""

from __future__ import annotations

import json
from pathlib import Path


def synthetic_catalog(tables: int, concepts: int = 200, domains: int = 10) -> dict:
    """``tables`` tables spread over ``concepts`` concepts related in a ring; each table
    keys its concept and holds a foreign key to the next one."""
    ids = [f"concept:c{n:04d}" for n in range(concepts)]
    common = {"status": "drafted", "source": "test", "evidence": []}
    return {
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
             "domain": f"domain:d{n % domains:02d}", "synonyms": [], "attributes": [],
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
                 *({"column": f"a{m}", "to": "technical"} for m in range(20)),
             ]}
            for n in range(tables)
        ],
    }


def synthetic_semantics(tables: int, directory: Path, every: int = 3) -> None:
    """A minimal table-semantics document, with one open question, for every ``every``-th
    table of ``synthetic_catalog``."""
    directory.mkdir(parents=True, exist_ok=True)
    for n in range(0, tables, every):
        table = f"db.t{n:05d}"
        document = {
            "doc_format": "table-semantics/1",
            "table": table,
            "summary": {
                "what": f"第 {n} 张表。",
                "questions": [{"id": "q1", "text": f"第 {n} 张表的 k 是否唯一？",
                               "about": ["column:k"], "status": "open"}],
            },
            "columns": [{"column": "k", "meaning": "键"}],
            "rules": [],
        }
        (directory / f"{table}.json").write_text(
            json.dumps(document, ensure_ascii=False), encoding="utf-8"
        )
